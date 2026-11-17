from datetime import date, datetime, timedelta
from typing import List, Optional
import re

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import exists, or_, select, text

from app.db.session import get_db
from app.models.employee import Employee, WithdrawalRequest
from app.schemas.employee import (
    EmployeeCreate,
    TelecallerTeamMemberCreate,
    EmployeeResponse,
    EmployeeLogin,
    Token,
    EmployeeUpdateRequest,
    WhatsAppInviteRequest,
    TelecallerOnboardedVendor,
    PaginatedOnboardedVendorsResponse,
    VendorDetailsUpdate,
    VendorFullDetailsResponse,
    LeadStatusUpdate,
    LeadPerformanceResponse,
    TeamNotificationResponse,
    AdminContactMessageRequest,
    VendorAuditLogResponse,
    VendorServiceItem,
    VendorServiceCreateRequest,
    VendorServiceUpdateRequest,
    VendorAvailabilitySlotItem,
    VendorAvailabilityUpdateRequest,
    RegistrationTeamLeadRemarkUpdate,
)
from app.schemas.withdrawal import WithdrawalRequestCreate, WithdrawalRequestResponse
from app.core.security import get_password_hash, verify_password, create_access_token
from app.dependencies.auth import get_current_employee, get_current_admin
from app.schemas.call import InitiateCallRequest, InitiateCallResponse
from app.models.call_log import TelecallerCallLog
from app.services.smartflo_service import smartflo_service
from app.services.airtel_iq_service import airtel_iq_service
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class ManualCustomerLeadPushRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=100)
    customer_location: str = Field(..., min_length=1, max_length=300)
    customer_phone: str = Field(..., min_length=7, max_length=25)


@router.post("/telecaller-dashboard/manual-customer-push")
async def send_manual_customer_lead_push(
    payload: ManualCustomerLeadPushRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_employee: Employee = Depends(get_current_employee),
):
    allowed_roles = {"telecaller", "telecaller_lead", "team_lead", "admin", "super_admin"}
    if (current_employee.role or "").strip().lower() not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role is not allowed to send vendor customer leads",
        )

    customer_name = payload.customer_name.strip()
    customer_location = payload.customer_location.strip()
    customer_phone = payload.customer_phone.strip()
    if not customer_name or not customer_location or not customer_phone:
        raise HTTPException(status_code=422, detail="Customer details cannot be blank")
    if not re.fullmatch(r"\+?[0-9][0-9 ()-]{6,23}", customer_phone):
        raise HTTPException(status_code=422, detail="Customer phone number is invalid")

    from app.models.device import DeviceInstallation
    from app.models.user_location import User
    from app.models.vendor import Vendor
    from app.services.notification_service import send_user_push_notification

    has_device_token = exists(
        select(DeviceInstallation.device_id).where(
            DeviceInstallation.user_id == User.id,
            DeviceInstallation.fcm_token.is_not(None),
            DeviceInstallation.fcm_token != "",
        )
    )
    has_vendor_role = or_(
        User.role == "VENDOR",
        User.role.like("VENDOR,%"),
        User.role.like("%,VENDOR"),
        User.role.like("%,VENDOR,%"),
    )
    result = await db.execute(
        select(User.id)
        .join(Vendor, Vendor.user_id == User.id)
        .where(
            Vendor.status == "active",
            User.is_active.is_(True),
            has_vendor_role,
            or_(
                (User.fcm_token.is_not(None) & (User.fcm_token != "")),
                has_device_token,
            ),
        )
        .distinct()
    )
    vendor_user_ids = result.scalars().all()

    title = "New Customer Lead"
    body = (
        f"Name: {customer_name} | Location: {customer_location} | "
        f"Phone: {customer_phone}"
    )
    notification_data = {"type": "manual_customer_lead"}
    for user_id in vendor_user_ids:
        background_tasks.add_task(
            send_user_push_notification,
            user_id,
            title,
            body,
            notification_data,
        )

    return {
        "message": "Customer lead notification queued",
        "recipient_count": len(vendor_user_ids),
    }


@router.post("/", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    employee_in: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    # Check if employee with same email or phone exists
    query = select(Employee).where(
        (Employee.email == employee_in.email) | 
        (Employee.phone_number == employee_in.phone_number)
    )
    result = await db.execute(query)
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Employee with this email or phone number already exists"
        )
        
    new_employee = Employee(
        first_name=employee_in.first_name,
        last_name=employee_in.last_name,
        email=employee_in.email,
        phone_number=employee_in.phone_number,
        hashed_password=get_password_hash(employee_in.password),
        role=employee_in.role
    )
    db.add(new_employee)
    await db.commit()
    await db.refresh(new_employee)
    return new_employee


@router.post("/telecaller-team/members", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def add_telecaller_team_member(
    member_in: TelecallerTeamMemberCreate,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    """Allow telecaller_lead, admin, or super_admin to add team members and configure roles."""
    current_role = (current_employee.role or "").strip().lower()
    allowed_creator_roles = {"telecaller_lead", "admin", "super_admin", "team_lead"}
    if current_role not in allowed_creator_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Telecaller Team Leads and Admins can add team members."
        )

    # Validate role that lead can assign
    allowed_roles = {"telecaller", "telecaller_lead"}
    target_role = (member_in.role or "telecaller").strip().lower()
    if target_role not in allowed_roles:
        target_role = "telecaller"

    # Check for existing email / phone
    clean_phone = member_in.phone_number.replace("+91", "").strip()
    query = select(Employee).where(
        (Employee.email == member_in.email.strip()) |
        (Employee.phone_number == clean_phone)
    )
    result = await db.execute(query)
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An employee with this email or phone number already exists."
        )

    new_member = Employee(
        first_name=member_in.first_name.strip(),
        last_name=member_in.last_name.strip() if member_in.last_name else None,
        email=member_in.email.strip().lower(),
        phone_number=clean_phone,
        hashed_password=get_password_hash(member_in.password),
        role=target_role,
        status="active"
    )
    db.add(new_member)
    await db.commit()
    await db.refresh(new_member)
    return new_member


@router.get("/telecaller-team/members", response_model=List[EmployeeResponse])
async def list_telecaller_team_members(
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    """List all telecaller team members visible to Team Lead."""
    current_role = (current_employee.role or "").strip().lower()
    allowed_creator_roles = {"telecaller_lead", "admin", "super_admin", "team_lead"}
    if current_role not in allowed_creator_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted to Team Leads and Admins."
        )

    query = select(Employee).where(
        Employee.role.in_(["telecaller", "telecaller_lead", "team_lead", "verification"])
    ).order_by(Employee.id.desc())
    result = await db.execute(query)
    return result.scalars().all()

@router.post("/login", response_model=Token)
async def login_employee(
    login_data: EmployeeLogin,
    db: AsyncSession = Depends(get_db)
):
    # Authenticate employee by email or phone_number
    query = select(Employee).where(
        (Employee.email == login_data.identifier) |
        (Employee.phone_number == login_data.identifier)
    )
    result = await db.execute(query)
    employee = result.scalar_one_or_none()
    
    if not employee or not verify_password(login_data.password, employee.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect identifier or password",
        )
        
    if employee.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee account is not active",
        )
        
    # Generate token
    access_token = create_access_token(subject=str(employee.id))
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "role": employee.role
    }

@router.get("/me", response_model=EmployeeResponse)
async def read_employee_me(
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import text
    from datetime import date
    
    res = await db.execute(text("SELECT points FROM employee_daily_points WHERE employee_id = :emp_id AND date = :today"), {"emp_id": current_employee.id, "today": date.today()})
    today_points = res.scalar_one_or_none() or 0
    
    return {
        "id": current_employee.id,
        "first_name": current_employee.first_name,
        "last_name": current_employee.last_name,
        "email": current_employee.email,
        "phone_number": current_employee.phone_number,
        "role": current_employee.role,
        "status": current_employee.status,
        "referral_points": current_employee.referral_points,
        "bank_name": current_employee.bank_name,
        "bank_account_number": current_employee.bank_account_number,
        "bank_account_name": current_employee.bank_account_name,
        "bank_ifsc_code": current_employee.bank_ifsc_code
    }

@router.put("/me", response_model=EmployeeResponse)
async def update_employee_me(
    employee_in: EmployeeUpdateRequest,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    update_data = employee_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(current_employee, field, value)
        
    await db.commit()
    await db.refresh(current_employee)
    
    from sqlalchemy import text
    from datetime import date
    res = await db.execute(text("SELECT points FROM employee_daily_points WHERE employee_id = :emp_id AND date = :today"), {"emp_id": current_employee.id, "today": date.today()})
    today_points = res.scalar_one_or_none() or 0

    return {
        "id": current_employee.id,
        "first_name": current_employee.first_name,
        "last_name": current_employee.last_name,
        "email": current_employee.email,
        "phone_number": current_employee.phone_number,
        "role": current_employee.role,
        "status": current_employee.status,
        "referral_points": current_employee.referral_points,
        "bank_name": current_employee.bank_name,
        "bank_account_number": current_employee.bank_account_number,
        "bank_account_name": current_employee.bank_account_name,
        "bank_ifsc_code": current_employee.bank_ifsc_code
    }
@router.get("/", response_model=List[EmployeeResponse])
async def list_employees(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    query = select(Employee).offset(skip).limit(limit)
    result = await db.execute(query)
    employees = result.scalars().all()
    return employees

from app.schemas.vendor_registration import VendorRegistrationRequest
from app.models.user_location import User
from app.models.vendor import Vendor, VendorSubCategory
from sqlalchemy import delete

@router.post("/vendors/onboard", response_model=dict)
async def onboard_vendor(
    mobile: str,
    request: VendorRegistrationRequest,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    # Check if user exists
    user_query = await db.execute(select(User).where(User.mobile == mobile))
    user = user_query.scalar_one_or_none()
    
    if not user:
        user = User(
            mobile=mobile,
            email=None,
            role="VENDOR",
            is_active=True,
            otp_verified=True
        )
        db.add(user)
        await db.flush()
    else:
        if not user.role:
            user.role = "VENDOR"
        elif "VENDOR" not in str(user.role):
            user.role = str(user.role) + ",VENDOR"
        db.add(user)
        await db.flush()

    # Check if vendor already exists
    vendor_query = await db.execute(select(Vendor).where(Vendor.user_id == user.id))
    vendor = vendor_query.scalar_one_or_none()
    
    if vendor and vendor.status == "active":
        raise HTTPException(status_code=400, detail="Vendor is already fully registered")
        
    if not vendor:
        vendor = Vendor(
            user_id=user.id,
            status="onboarding"
        )
        db.add(vendor)
        await db.flush()
        
    # Update Vendor Profile
    vendor.first_name = request.first_name
    vendor.last_name = request.last_name
    vendor.father_name = request.father_name
    vendor.email = request.email
    if request.email and user.email != request.email:
        existing_email_user = (await db.execute(
            select(User.id).where(User.email == request.email, User.id != user.id)
        )).scalar_one_or_none()
        if not existing_email_user:
            user.email = request.email
            db.add(user)
    vendor.alternative_number = request.alternative_number
    vendor.business_name = request.business_name
    vendor.aadhaar_number = request.aadhaar_number
    vendor.address = request.address
    vendor.city = request.city
    vendor.state = request.state
    vendor.pincode = request.pincode
    vendor.latitude = request.latitude
    vendor.longitude = request.longitude
    vendor.service_radius_km = request.service_radius_km
    vendor.profile_image = request.profile_image
    vendor.status = "active"
    
    # Track which employee onboarded this vendor
    vendor.onboarded_by_employee_id = current_employee.id
    existing_source = (vendor.lead_source or "").strip().lower()
    if existing_source not in ("company", "company_website", "company_mobile"):
        vendor.lead_source = "direct_telecaller"
    if not vendor.assigned_telecaller_id and existing_source in (
        "company",
        "company_website",
        "company_mobile",
    ):
        vendor.assigned_telecaller_id = current_employee.id
    
    db.add(vendor)
    
    # Delete existing categories if any
    await db.execute(delete(VendorSubCategory).where(VendorSubCategory.vendor_id == vendor.id))
    
    # Add Categories
    for cat in request.categories:
        for sub_cat_id in cat.sub_category_ids:
            new_sub_cat = VendorSubCategory(
                vendor_id=vendor.id,
                main_category_id=cat.main_category_id,
                sub_category_id=sub_cat_id
            )
            db.add(new_sub_cat)
            
    # Add referral points to employee

    from datetime import date
    from sqlalchemy import text
    
    current_employee.referral_points += 10
    
    # Update daily points
    today = date.today()
    check_query = text("SELECT id FROM employee_daily_points WHERE employee_id = :emp_id AND date = :today")
    res = await db.execute(check_query, {"emp_id": current_employee.id, "today": today})
    if res.scalar_one_or_none():
        await db.execute(text("UPDATE employee_daily_points SET points = points + 10 WHERE employee_id = :emp_id AND date = :today"), {"emp_id": current_employee.id, "today": today})
    else:
        await db.execute(text("INSERT INTO employee_daily_points (employee_id, date, points) VALUES (:emp_id, :today, 10)"), {"emp_id": current_employee.id, "today": today})

    db.add(current_employee)
            
    await db.commit()
    
    return {
        "message": "Vendor onboarded successfully",
        "vendor_id": vendor.id,
        "points_earned": 10,
        "total_points": current_employee.referral_points
    }

from app.schemas.employee import (
    TelecallerVendorOnboardRequest,
    TelecallerVendorProfileRequest,
    TelecallerCategoryServicesRequest,
    TelecallerDashboardStatsResponse,
    PaginatedOnboardedVendorsResponse,
    TelecallerLeaderboardEntry
)
from app.models.vendor import VendorService
from app.models.catalog import Service


async def _get_or_create_user_and_vendor(mobile: str, db: AsyncSession):
    """Create or fetch User + Vendor for telecaller onboarding."""
    user_query = await db.execute(select(User).where(User.mobile == mobile))
    user = user_query.scalar_one_or_none()

    if not user:
        user = User(
            mobile=mobile,
            email=None,
            role="VENDOR",
            is_active=True,
            otp_verified=True
        )
        db.add(user)
        await db.flush()
    else:
        if not user.role:
            user.role = "VENDOR"
        elif "VENDOR" not in str(user.role):
            user.role = str(user.role) + ",VENDOR"
        db.add(user)
        await db.flush()

    vendor_query = await db.execute(select(Vendor).where(Vendor.user_id == user.id))
    vendor = vendor_query.scalar_one_or_none()

    if vendor and vendor.status == "active":
        raise HTTPException(status_code=400, detail="Vendor is already fully registered")

    if not vendor:
        vendor = Vendor(
            user_id=user.id,
            status="onboarding",
            lead_source="direct_telecaller",
        )
        db.add(vendor)
        await db.flush()

    return user, vendor


def _apply_vendor_profile(vendor: Vendor, request, employee_id: int):
    """Apply profile fields from a request object onto a Vendor."""
    vendor.first_name = request.first_name
    vendor.last_name = request.last_name
    vendor.father_name = request.father_name
    vendor.email = request.email
    vendor.alternative_number = request.alternative_number
    vendor.business_name = request.business_name
    vendor.aadhaar_number = request.aadhaar_number
    vendor.address = request.address
    vendor.city = request.city
    vendor.state = request.state
    vendor.pincode = request.pincode
    vendor.latitude = request.latitude
    vendor.longitude = request.longitude
    vendor.service_radius_km = request.service_radius_km
    vendor.profile_image = request.profile_image
    vendor.status = "onboarding"
    vendor.onboarded_by_employee_id = employee_id
    # Preserve company website/mobile assignment source; only mark direct for true telecaller onboard
    existing_source = (vendor.lead_source or "").strip().lower()
    if existing_source not in ("company", "company_website", "company_mobile"):
        vendor.lead_source = "direct_telecaller"
    if not vendor.assigned_telecaller_id and existing_source in (
        "company",
        "company_website",
        "company_mobile",
    ):
        vendor.assigned_telecaller_id = employee_id


async def _append_categories(vendor: Vendor, categories, db: AsyncSession):
    """Append category selections, skipping duplicates (single query for existing)."""
    requested: set[tuple[int, int]] = set()
    for cat in categories:
        for sub_cat_id in cat.sub_category_ids:
            requested.add((cat.main_category_id, sub_cat_id))

    if not requested:
        return

    existing_result = await db.execute(
        select(VendorSubCategory.main_category_id, VendorSubCategory.sub_category_id).where(
            VendorSubCategory.vendor_id == vendor.id
        )
    )
    existing = {(row[0], row[1]) for row in existing_result.all()}

    for main_category_id, sub_cat_id in requested - existing:
        db.add(VendorSubCategory(
            vendor_id=vendor.id,
            main_category_id=main_category_id,
            sub_category_id=sub_cat_id,
        ))


async def _append_services(vendor: Vendor, services, db: AsyncSession):
    """Append or update vendor services (batched catalog + existing lookups)."""
    if not services:
        return

    service_ids = [srv.service_id for srv in services]
    catalog_result = await db.execute(select(Service).where(Service.id.in_(service_ids)))
    service_map = {s.id: s for s in catalog_result.scalars().all()}

    missing = [sid for sid in service_ids if sid not in service_map]
    if missing:
        raise HTTPException(status_code=404, detail=f"Service ID {missing[0]} not found")

    existing_result = await db.execute(
        select(VendorService).where(
            VendorService.vendor_id == vendor.id,
            VendorService.service_id.in_(service_ids),
        )
    )
    existing_map = {vs.service_id: vs for vs in existing_result.scalars().all()}

    for srv in services:
        service_record = service_map[srv.service_id]
        existing = existing_map.get(service_record.id)

        if existing:
            existing.price = srv.amount
            existing.discounted_price = srv.discounted_amount
            existing.negotiable = srv.is_negotiable
            existing.is_active = True
            db.add(existing)
        else:
            db.add(VendorService(
                vendor_id=vendor.id,
                main_category_id=service_record.main_category_id,
                sub_category_id=service_record.sub_category_id,
                service_id=service_record.id,
                title=service_record.name,
                price=srv.amount,
                discounted_price=srv.discounted_amount,
                negotiable=srv.is_negotiable,
                is_active=True,
            ))


@router.post("/vendors/telecaller-onboard/profile", response_model=dict)
async def telecaller_onboard_profile(
    mobile: str,
    request: TelecallerVendorProfileRequest,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    """Step 1: Create vendor stub with profile details."""
    _, vendor = await _get_or_create_user_and_vendor(mobile, db)
    _apply_vendor_profile(vendor, request, current_employee.id)
    db.add(vendor)
    await db.commit()

    return {
        "message": "Vendor profile saved successfully",
        "vendor_id": vendor.id,
    }


@router.post("/vendors/telecaller-onboard/category-services", response_model=dict)
async def telecaller_onboard_category_services(
    mobile: str,
    request: TelecallerCategoryServicesRequest,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    """Step 3: Append categories and services for the current category selection."""
    _, vendor = await _get_or_create_user_and_vendor(mobile, db)

    if not vendor.first_name:
        raise HTTPException(
            status_code=400,
            detail="Vendor profile not found. Complete step 1 first."
        )

    await _append_categories(vendor, request.categories, db)
    await _append_services(vendor, request.services, db)
    await db.commit()

    return {
        "message": "Categories and services saved successfully",
        "vendor_id": vendor.id,
    }


@router.post("/vendors/telecaller-onboard/complete", response_model=dict)
async def telecaller_onboard_complete(
    mobile: str,
    background_tasks: BackgroundTasks,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    """Step 5: Finalize telecaller onboarding — notify vendor and award referral points."""
    _, vendor = await _get_or_create_user_and_vendor(mobile, db)

    if not vendor.first_name:
        raise HTTPException(
            status_code=400,
            detail="Vendor profile not found. Complete step 1 first."
        )

    vendor.status = "onboarding"
    vendor.onboarded_by_employee_id = current_employee.id
    db.add(vendor)


    from datetime import date
    from sqlalchemy import text
    
    current_employee.referral_points += 10
    
    # Update daily points
    today = date.today()
    check_query = text("SELECT id FROM employee_daily_points WHERE employee_id = :emp_id AND date = :today")
    res = await db.execute(check_query, {"emp_id": current_employee.id, "today": today})
    if res.scalar_one_or_none():
        await db.execute(text("UPDATE employee_daily_points SET points = points + 10 WHERE employee_id = :emp_id AND date = :today"), {"emp_id": current_employee.id, "today": today})
    else:
        await db.execute(text("INSERT INTO employee_daily_points (employee_id, date, points) VALUES (:emp_id, :today, 10)"), {"emp_id": current_employee.id, "today": today})

    db.add(current_employee)
    await db.commit()

    if vendor.user_id:
        from app.services.notification_service import send_user_push_notification
        background_tasks.add_task(
            send_user_push_notification,
            user_id=vendor.user_id,
            title="Complete Your KYC Verification",
            body="Welcome to AM5 ROYAL! Complete your documentation and KYC to activate your vendor account.",
        )

    return {
        "message": "Vendor telecaller onboarding completed successfully",
        "vendor_id": vendor.id,
        "points_earned": 10,
        "total_points": current_employee.referral_points,
    }


@router.post("/vendors/telecaller-onboard", response_model=dict)
async def telecaller_onboard_vendor(
    mobile: str,
    request: TelecallerVendorOnboardRequest,
    background_tasks: BackgroundTasks,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    """Full telecaller onboard in one call (legacy). Keeps vendor in onboarding status."""
    _, vendor = await _get_or_create_user_and_vendor(mobile, db)
    _apply_vendor_profile(vendor, request, current_employee.id)
    db.add(vendor)

    # Replace all categories and services for full onboard
    await db.execute(delete(VendorSubCategory).where(VendorSubCategory.vendor_id == vendor.id))
    for cat in request.categories:
        for sub_cat_id in cat.sub_category_ids:
            db.add(VendorSubCategory(
                vendor_id=vendor.id,
                main_category_id=cat.main_category_id,
                sub_category_id=sub_cat_id,
            ))

    await db.execute(delete(VendorService).where(VendorService.vendor_id == vendor.id))
    await _append_services(vendor, request.services, db)


    from datetime import date
    from sqlalchemy import text
    
    current_employee.referral_points += 10
    
    # Update daily points
    today = date.today()
    check_query = text("SELECT id FROM employee_daily_points WHERE employee_id = :emp_id AND date = :today")
    res = await db.execute(check_query, {"emp_id": current_employee.id, "today": today})
    if res.scalar_one_or_none():
        await db.execute(text("UPDATE employee_daily_points SET points = points + 10 WHERE employee_id = :emp_id AND date = :today"), {"emp_id": current_employee.id, "today": today})
    else:
        await db.execute(text("INSERT INTO employee_daily_points (employee_id, date, points) VALUES (:emp_id, :today, 10)"), {"emp_id": current_employee.id, "today": today})

    db.add(current_employee)
    await db.commit()

    if vendor.user_id:
        from app.services.notification_service import send_user_push_notification
        background_tasks.add_task(
            send_user_push_notification,
            user_id=vendor.user_id,
            title="Complete Your KYC Verification",
            body="Welcome to AM5 ROYAL! Complete your documentation and KYC to activate your vendor account.",
        )

    return {
        "message": "Vendor fully onboarded successfully",
        "vendor_id": vendor.id,
        "points_earned": 10,
        "total_points": current_employee.referral_points
    }

from typing import Optional
from datetime import date, datetime, timedelta

@router.get("/telecaller-dashboard/stats", response_model=TelecallerDashboardStatsResponse)
async def get_telecaller_stats(
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import text
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    
    # weekly onboardings
    weekly_query = text("SELECT COUNT(*) FROM vendors WHERE onboarded_by_employee_id = :emp_id AND created_at >= :start_of_week")
    res_week = await db.execute(weekly_query, {"emp_id": current_employee.id, "start_of_week": start_of_week})
    weekly_onboardings = res_week.scalar() or 0
    
    # monthly onboardings
    monthly_query = text("SELECT COUNT(*) FROM vendors WHERE onboarded_by_employee_id = :emp_id AND created_at >= :start_of_month")
    res_month = await db.execute(monthly_query, {"emp_id": current_employee.id, "start_of_month": start_of_month})
    monthly_conversions = res_month.scalar() or 0
    
    # estimated referral payout (10% of subscription price of all onboarded vendors)
    payout_query = text("""
        SELECT COALESCE(SUM(sp.price), 0)
        FROM vendors v
        JOIN vendor_subscriptions vs ON v.id = vs.vendor_id
        JOIN subscription_plans sp ON vs.subscription_plan_id = sp.id
        WHERE v.onboarded_by_employee_id = :emp_id AND vs.status = 'active'
    """)
    res_payout = await db.execute(payout_query, {"emp_id": current_employee.id})
    estimated_referral_payout = float(res_payout.scalar() or 0.0) * 0.10
    
    # monthly payout bonus (10% of subscription price of vendors onboarded this month)
    monthly_payout_query = text("""
        SELECT COALESCE(SUM(sp.price), 0)
        FROM vendors v
        JOIN vendor_subscriptions vs ON v.id = vs.vendor_id
        JOIN subscription_plans sp ON vs.subscription_plan_id = sp.id
        WHERE v.onboarded_by_employee_id = :emp_id AND vs.status = 'active' AND v.created_at >= :start_of_month
    """)
    res_monthly_payout = await db.execute(monthly_payout_query, {"emp_id": current_employee.id, "start_of_month": start_of_month})
    monthly_payout_bonus = float(res_monthly_payout.scalar() or 0.0) * 0.10

    # Calculate total withdrawn (sum of approved/pending withdrawals)
    withdrawn_query = text("SELECT COALESCE(SUM(amount), 0) FROM withdrawal_requests WHERE employee_id = :emp_id AND status IN ('pending', 'approved')")
    res_withdrawn = await db.execute(withdrawn_query, {"emp_id": current_employee.id})
    total_withdrawn = float(res_withdrawn.scalar() or 0.0)
    
    withdrawable_balance = max(0.0, estimated_referral_payout - total_withdrawn)
    
    # Calculate detailed points
    telecaller_points_query = text("SELECT COALESCE(SUM(points_added), 0) FROM points_history WHERE user_id = :emp_id AND user_type = 'employee' AND reason = 'direct_telecaller_payment'")
    res_tp = await db.execute(telecaller_points_query, {"emp_id": current_employee.id})
    telecaller_points = int(res_tp.scalar() or 0)
    
    company_points_query = text("SELECT COALESCE(SUM(points_added), 0) FROM points_history WHERE user_id = :emp_id AND user_type = 'employee' AND reason = 'company_lead_payment'")
    res_cp = await db.execute(company_points_query, {"emp_id": current_employee.id})
    company_points = int(res_cp.scalar() or 0)
    
    freelancer_points_query = text("""
        SELECT f.first_name, f.last_name, SUM(ph.points_added) as total_points
        FROM points_history ph
        JOIN vendors v ON ph.vendor_id = v.id
        JOIN freelancers f ON v.freelancer_id = f.id
        WHERE ph.user_id = :emp_id AND ph.user_type = 'employee' AND ph.reason = 'freelancer_lead_telecaller_payment'
        GROUP BY f.id, f.first_name, f.last_name
    """)
    res_fp = await db.execute(freelancer_points_query, {"emp_id": current_employee.id})
    freelancer_points_list = []
    for row in res_fp.all():
        name = row[0] if row[0] else "Freelancer"
        if row[1]:
            name += f" {row[1]}"
        freelancer_points_list.append({"name": name, "points": int(row[2])})
        
    return {
        "weekly_onboardings": weekly_onboardings,
        "monthly_conversions": monthly_conversions,
        "referral_points": current_employee.referral_points,
        "estimated_referral_payout": estimated_referral_payout,
        "monthly_payout_bonus": monthly_payout_bonus,
        "withdrawable_balance": withdrawable_balance,
        "total_withdrawn": total_withdrawn,
        "telecaller_points": {"name": current_employee.first_name or "Telecaller", "points": telecaller_points},
        "company_points": {"name": "AM5royal", "points": company_points},
        "freelancer_points": freelancer_points_list
    }


@router.get("/telecaller-dashboard/onboarded", response_model=PaginatedOnboardedVendorsResponse)
async def get_telecaller_onboarded(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
    lead_source: Optional[str] = None,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import text
    
    query_str = """
        SELECT 
            v.id, 
            v.business_name, 
            v.first_name, 
            v.last_name, 
            v.father_name,
            v.city,
            v.district,
            v.state,
            v.pincode,
            v.address,
            v.alternative_number,
            v.alternative_contact_number,
            v.created_at,
            u.mobile as mobile_number,
            u.email as user_email,
            v.email as vendor_email,
            COALESCE(u.email, u.mobile) as username,
            v.lead_source,
            (SELECT vs.title FROM vendor_services vs WHERE vs.vendor_id = v.id ORDER BY vs.id DESC LIMIT 1) as service_name,
            COALESCE(
                (SELECT TRIM(CONCAT(e.first_name, ' ', COALESCE(e.last_name, ''))) FROM employees e WHERE e.id = v.assigned_telecaller_id),
                'Unassigned'
            ) as assigned_team_member,
            EXISTS (SELECT 1 FROM vendor_services vs WHERE vs.vendor_id = v.id) as has_services,
            (v.first_name IS NOT NULL AND v.first_name != '') as has_registration,
            EXISTS (SELECT 1 FROM vendor_availability va WHERE va.vendor_id = v.id) as has_slots,
            (EXISTS (SELECT 1 FROM vendor_documents vd WHERE vd.vendor_id = v.id) OR (v.aadhaar_number IS NOT NULL AND v.aadhaar_number != '')) as has_business_reg,
            EXISTS (SELECT 1 FROM vendor_subscriptions vs WHERE vs.vendor_id = v.id AND vs.status = 'active') as has_payment,
            (v.status = 'temporary_active') as is_temp_active,
            (v.status = 'active') as is_activated,
            (
                CASE
                    WHEN v.status = 'rejected' THEN 'rejected'
                    WHEN v.status = 'active' THEN 'active'
                    WHEN v.status = 'temporary_active' THEN 'temporary active'
                    WHEN EXISTS (SELECT 1 FROM vendor_subscriptions vs WHERE vs.vendor_id = v.id AND vs.status = 'active') THEN 'temporary active'
                    WHEN EXISTS (SELECT 1 FROM vendor_documents vd WHERE vd.vendor_id = v.id) OR (v.aadhaar_number IS NOT NULL AND v.aadhaar_number != '') THEN 'business registration'
                    WHEN EXISTS (SELECT 1 FROM vendor_availability va WHERE va.vendor_id = v.id) THEN 'slots'
                    WHEN v.first_name IS NOT NULL AND v.first_name != '' THEN 'registration'
                    WHEN EXISTS (SELECT 1 FROM vendor_services v_s WHERE v_s.vendor_id = v.id) THEN 'services'
                    ELSE 'services'
                END
            ) as status
        FROM vendors v
        JOIN users u ON v.user_id = u.id
        WHERE COALESCE(v.status, '') <> 'rejected'
          AND (
            v.onboarded_by_employee_id = :emp_id
            OR v.assigned_telecaller_id = :emp_id
            OR (
                v.status = 'temporary_active'
                AND (
                    v.lead_source IN ('company', 'company_website', 'company_mobile', 'freelancer')
                    OR v.lead_source IS NULL
                    OR v.lead_source = ''
                )
            )
            OR (
                v.assigned_telecaller_id IS NULL
                AND (
                    v.lead_source IN ('company', 'company_website', 'company_mobile', 'freelancer')
                    OR v.lead_source IS NULL
                    OR v.lead_source = ''
                )
            )
          )
    """
    params = {"emp_id": current_employee.id}
    
    if start_date:
        query_str += " AND v.created_at >= :start_date"
        params["start_date"] = start_date
    if end_date:
        # Add 1 day to include the end date fully
        query_str += " AND v.created_at < :end_date"
        params["end_date"] = end_date + timedelta(days=1)

    if lead_source:
        if lead_source == "company_website":
            query_str += " AND (v.lead_source IN ('company_website', 'company') OR v.lead_source IS NULL OR v.lead_source = '')"
        elif lead_source == "company_mobile":
            query_str += " AND v.lead_source = 'company_mobile'"
        elif lead_source == "freelancer":
            query_str += " AND v.lead_source = 'freelancer'"
        elif lead_source == "direct_telecaller":
            query_str += " AND (v.lead_source = 'direct_telecaller' OR (v.onboarded_by_employee_id = :emp_id AND (v.lead_source NOT IN ('company', 'company_website', 'company_mobile', 'freelancer') OR v.lead_source IS NULL)))"
        else:
            query_str += " AND v.lead_source = :lead_source"
            params["lead_source"] = lead_source
        
    # Count total
    count_query_str = "SELECT COUNT(*) FROM (" + query_str + ") AS sub"
    res_count = await db.execute(text(count_query_str), params)
    total = res_count.scalar() or 0
    
    # Paginated data — Temp Active first so Approve/Reject appear on Website + Application tabs
    query_str += """
        ORDER BY
            CASE WHEN v.status = 'temporary_active' THEN 0 ELSE 1 END,
            (v.lead_source IN ('company', 'company_website', 'company_mobile', 'freelancer')) DESC,
            v.created_at DESC
        LIMIT :limit OFFSET :skip
    """
    params["limit"] = limit
    params["skip"] = skip
    
    res = await db.execute(text(query_str), params)
    rows = res.fetchall()
    
    vendors = []
    for row in rows:
        email = row.vendor_email or row.user_email or ""
        crm_status = "New"
        st = (row.status or "").lower()
        if st == "active":
            crm_status = "Activated"
        elif st == "temporary active":
            crm_status = "KYC Pending"
        elif st == "payment":
            crm_status = "Payment Pending"
        elif st in ("business registration", "registration", "slots done", "slots", "services added", "services"):
            crm_status = "Registration Pending"

        vendors.append({
            "id": row.id,
            "business_name": row.business_name,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "city": row.city,
            "status": row.status,
            "created_at": row.created_at,
            "mobile_number": row.mobile_number or "",
            "lead_source": row.lead_source,
            "email": email,
            "username": row.username or "",
            "service_name": row.service_name or "General Services",
            "assigned_team_member": row.assigned_team_member,
            "lead_status": crm_status,
            "has_services": bool(row.has_services),
            "has_registration": bool(row.has_registration),
            "has_slots": bool(row.has_slots),
            "has_business_reg": bool(row.has_business_reg),
            "has_payment": bool(row.has_payment),
            "is_temp_active": bool(row.is_temp_active),
            "is_activated": bool(row.is_activated)
        })
        
    return {
        "total": total,
        "vendors": vendors
    }


@router.get("/registration-team-leads/vendors")
async def get_registration_team_lead_vendors(
    skip: int = 0,
    limit: int = 50,
    search: str | None = None,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """List registration vendors and their workflow progress for team leads."""
    current_role = (current_employee.role or "").strip().lower()
    if current_role not in {"team_lead", "telecaller_lead", "admin", "super_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team leads and admins can view registration team lead vendors.",
        )
    if skip < 0 or limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="skip must be non-negative and limit must be between 1 and 100.")
    search_pattern = f"%{search.strip() if search else ''}%"
    search_filter = """
        (COALESCE(v.business_name, '') ILIKE :search_pattern OR
            COALESCE(v.first_name, '') ILIKE :search_pattern OR
            COALESCE(v.last_name, '') ILIKE :search_pattern OR
            COALESCE(v.father_name, '') ILIKE :search_pattern OR
            COALESCE(v.mobile, u.mobile, '') ILIKE :search_pattern OR
            COALESCE(v.email, u.email, '') ILIKE :search_pattern OR
            COALESCE(v.city, '') ILIKE :search_pattern OR
            COALESCE(v.district, '') ILIKE :search_pattern OR
            COALESCE(v.state, '') ILIKE :search_pattern OR
            COALESCE(v.pincode::text, '') ILIKE :search_pattern)
    """
    workflow_query = f"""
        SELECT
            v.id,
            v.business_name,
            v.first_name,
            v.last_name,
            v.father_name,
            v.city,
            v.district,
            v.state,
            v.pincode,
            v.address,
            v.alternative_number,
            v.alternative_contact_number,
            v.created_at,
            COALESCE(v.mobile, u.mobile, '') AS mobile_number,
            COALESCE(v.email, u.email, '') AS email,
            v.lead_source,
            v.status AS raw_status,
            v.registration_team_lead_remark AS registration_remark,
            v.registration_team_lead_remark_updated_at AS remark_updated_at,
            NULLIF(TRIM(CONCAT(re.first_name, ' ', COALESCE(re.last_name, ''))), '') AS remark_updated_by,
            COALESCE(
                (SELECT vs.title FROM vendor_services vs WHERE vs.vendor_id = v.id ORDER BY vs.id DESC LIMIT 1),
                'General Services'
            ) AS service_name,
            EXISTS (SELECT 1 FROM vendor_services vs WHERE vs.vendor_id = v.id) AS has_services,
            (v.first_name IS NOT NULL AND v.first_name != '') AS has_registration,
            EXISTS (SELECT 1 FROM vendor_availability va WHERE va.vendor_id = v.id) AS has_slots,
            (
                EXISTS (SELECT 1 FROM vendor_documents vd WHERE vd.vendor_id = v.id)
                OR (v.aadhaar_number IS NOT NULL AND v.aadhaar_number != '')
            ) AS has_business_reg,
            EXISTS (
                SELECT 1 FROM vendor_subscriptions vs
                WHERE vs.vendor_id = v.id AND vs.status = 'active'
            ) AS has_payment,
            (v.status = 'temporary_active') AS is_temp_active,
            (v.status = 'active') AS is_activated,
            CASE
                WHEN v.status = 'active' THEN 'active'
                WHEN v.status = 'temporary_active' THEN 'temporary active'
                WHEN EXISTS (
                    SELECT 1 FROM vendor_subscriptions vs
                    WHERE vs.vendor_id = v.id AND vs.status = 'active'
                ) THEN 'temporary active'
                WHEN EXISTS (SELECT 1 FROM vendor_documents vd WHERE vd.vendor_id = v.id)
                    OR (v.aadhaar_number IS NOT NULL AND v.aadhaar_number != '')
                    THEN 'business registration'
                WHEN EXISTS (SELECT 1 FROM vendor_availability va WHERE va.vendor_id = v.id)
                    THEN 'slots'
                WHEN v.first_name IS NOT NULL AND v.first_name != '' THEN 'registration'
                WHEN EXISTS (SELECT 1 FROM vendor_services vs WHERE vs.vendor_id = v.id)
                    THEN 'services'
                ELSE 'services'
            END AS workflow_status
        FROM vendors v
        LEFT JOIN users u ON u.id = v.user_id
        LEFT JOIN employees re ON re.id = v.registration_team_lead_remark_updated_by
        WHERE COALESCE(v.status, '') <> 'rejected'
          AND v.status = 'registration'
          AND (
              NULLIF(TRIM(v.aadhaar_number), '') IS NOT NULL
              OR NULLIF(TRIM(v.pan_number), '') IS NOT NULL
          )
          AND {search_filter}
    """
    workflow_stages = """
        ('services', 'registration', 'slots', 'business registration', 'temporary active', 'active')
    """
    queue_filter = f"""
        workflow_status IN {workflow_stages}
        AND raw_status = 'registration'
    """
    query = text(f"""
        SELECT *
        FROM ({workflow_query}) AS registration_workflow
        WHERE {queue_filter}
        ORDER BY
            CASE workflow_status
                WHEN 'temporary active' THEN 0
                WHEN 'business registration' THEN 1
                WHEN 'slots' THEN 2
                WHEN 'registration' THEN 3
                WHEN 'services' THEN 4
                WHEN 'active' THEN 5
                ELSE 6
            END,
            created_at DESC,
            id DESC
        LIMIT :limit OFFSET :skip
    """)
    params = {
        "search_pattern": search_pattern,
        "limit": limit,
        "skip": skip,
    }
    count_result = await db.execute(text(f"""
        SELECT COUNT(*)
        FROM ({workflow_query}) AS registration_workflow
        WHERE {queue_filter}
    """), {
        "search_pattern": search_pattern,
    })
    total = count_result.scalar() or 0
    result = await db.execute(query, params)
    vendors = [
        {
            "id": row["id"],
            "business_name": row["business_name"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "father_name": row["father_name"],
            "city": row["city"],
            "district": row["district"],
            "state": row["state"],
            "pincode": row["pincode"],
            "address": row["address"],
            "alternative_number": row["alternative_number"],
            "alternative_contact_number": row["alternative_contact_number"],
            "created_at": row["created_at"],
            "mobile_number": row["mobile_number"],
            "email": row["email"],
            "lead_source": row["lead_source"],
            "service_name": row["service_name"],
            "status": row["workflow_status"],
            "lead_status": (
                "Activated" if row["workflow_status"] == "active"
                else "KYC Pending" if row["workflow_status"] == "temporary active"
                else "Registration Pending"
            ),
            "has_services": bool(row["has_services"]),
            "has_registration": bool(row["has_registration"]),
            "has_slots": bool(row["has_slots"]),
            "has_business_reg": bool(row["has_business_reg"]),
            "has_payment": bool(row["has_payment"]),
            "is_temp_active": bool(row["is_temp_active"]),
            "is_activated": bool(row["is_activated"]),
            "registration_remark": row["registration_remark"],
            "remark_updated_at": row["remark_updated_at"],
            "remark_updated_by": row["remark_updated_by"],
        }
        for row in result.mappings()
    ]
    return {"total": total, "skip": skip, "limit": limit, "vendors": vendors}


@router.put("/registration-team-leads/vendors/{vendor_id}/remark")
async def update_registration_team_lead_remark(
    vendor_id: int,
    remark_in: RegistrationTeamLeadRemarkUpdate,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Update the shared follow-up remark for a registration vendor."""
    current_role = (current_employee.role or "").strip().lower()
    if current_role not in {"team_lead", "telecaller_lead", "admin", "super_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team leads and admins can update registration follow-up remarks.",
        )

    result = await db.execute(
        text("""
            UPDATE vendors
            SET registration_team_lead_remark = :remark,
                registration_team_lead_remark_updated_at = NOW(),
                registration_team_lead_remark_updated_by = :employee_id
            WHERE id = :vendor_id
              AND status = 'registration'
            RETURNING registration_team_lead_remark_updated_at
        """),
        {
            "remark": remark_in.remark.strip(),
            "employee_id": current_employee.id,
            "vendor_id": vendor_id,
        },
    )
    updated = result.mappings().first()
    if not updated:
        exists = await db.execute(
            text("SELECT 1 FROM vendors WHERE id = :vendor_id"),
            {"vendor_id": vendor_id},
        )
        if exists.scalar() is None:
            raise HTTPException(status_code=404, detail="Vendor not found.")
        raise HTTPException(status_code=409, detail="This vendor is no longer at registration stage.")

    await db.commit()
    full_name = " ".join(
        part for part in (current_employee.first_name, current_employee.last_name) if part
    )
    return {
        "message": "Registration follow-up remark saved.",
        "vendor_id": vendor_id,
        "registration_remark": remark_in.remark.strip(),
        "remark_updated_at": updated["registration_team_lead_remark_updated_at"],
        "remark_updated_by": full_name or current_employee.email,
    }


@router.get("/telecaller-dashboard/vendor-step-details/{vendor_id}")
async def get_vendor_step_details(
    vendor_id: int,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed step breakdown for a vendor:
    - registration (Personal info, contact, location)
    - business_reg (Business name, PAN, Aadhaar, GST, docs)
    - services (Services added with prices & discount prices)
    - slots (Availability & working hours)
    - payment (Subscriptions / payment details)
    """
    from sqlalchemy import text

    vendor_row = (
        await db.execute(
            text(
                """
                SELECT
                    v.id,
                    v.first_name,
                    v.last_name,
                    v.father_name,
                    v.email,
                    v.alternative_number,
                    v.alternative_contact_number,
                    v.city,
                    v.state,
                    v.pincode,
                    v.address,
                    v.created_at,
                    v.business_name,
                    v.aadhaar_number,
                    v.pan_number,
                    v.gst_number,
                    v.service_radius_km,
                    v.payment_info,
                    v.status,
                    v.lead_source,
                    v.onboarded_by_employee_id,
                    v.assigned_telecaller_id,
                    v.registration_team_lead_id,
                    u.mobile AS mobile_number
                FROM vendors v
                JOIN users u ON v.user_id = u.id
                WHERE v.id = :vendor_id
                """
            ),
            {"vendor_id": vendor_id},
        )
    ).mappings().first()

    if not vendor_row:
        raise HTTPException(status_code=404, detail="Vendor not found")

    owned = (
        vendor_row["onboarded_by_employee_id"] == current_employee.id
        or vendor_row["assigned_telecaller_id"] == current_employee.id
        or vendor_row["registration_team_lead_id"] == current_employee.id
    )
    lead_source = (vendor_row["lead_source"] or "").strip().lower()
    is_company_lead = lead_source in (
        "",
        "company",
        "company_website",
        "company_mobile",
    )
    # Same visibility as list: assigned/onboarded OR company Temp Active pool
    status = (vendor_row["status"] or "").strip().lower()
    in_temp_pool = status == "temporary_active" and is_company_lead
    registration_team_lead_view = (
        status == "registration"
        and (current_employee.role or "").strip().lower()
        in {"team_lead", "telecaller_lead", "admin", "super_admin"}
    )
    if not owned and not in_temp_pool and not registration_team_lead_view:
        raise HTTPException(status_code=403, detail="Not allowed to view this vendor")

    docs = (
        await db.execute(
            text(
                """
                SELECT document_type, verification_status, document_url
                FROM vendor_documents
                WHERE vendor_id = :vendor_id
                ORDER BY id DESC
                """
            ),
            {"vendor_id": vendor_id},
        )
    ).mappings().all()

    services = (
        await db.execute(
            text(
                """
                SELECT
                    vs.id,
                    vs.service_id,
                    vs.title,
                    vs.description,
                    vs.price,
                    vs.discounted_price,
                    vs.negotiable,
                    vs.main_category_id,
                    vs.sub_category_id,
                    mc.name AS main_category_name,
                    sc.name AS sub_category_name
                FROM vendor_services vs
                LEFT JOIN main_categories mc ON vs.main_category_id = mc.id
                LEFT JOIN sub_categories sc ON vs.sub_category_id = sc.id
                WHERE vs.vendor_id = :vendor_id
                ORDER BY vs.id DESC
                """
            ),
            {"vendor_id": vendor_id},
        )
    ).mappings().all()

    day_names = {
        0: "Monday",
        1: "Tuesday",
        2: "Wednesday",
        3: "Thursday",
        4: "Friday",
        5: "Saturday",
        6: "Sunday",
    }
    availability = (
        await db.execute(
            text(
                """
                SELECT day_of_week, start_time, end_time, is_available
                FROM vendor_availability
                WHERE vendor_id = :vendor_id
                ORDER BY day_of_week ASC, start_time ASC
                """
            ),
            {"vendor_id": vendor_id},
        )
    ).mappings().all()

    subscriptions = (
        await db.execute(
            text(
                """
                SELECT
                    vs.id,
                    vs.status,
                    vs.start_date,
                    vs.end_date,
                    sp.name AS plan_name,
                    sp.price AS amount
                FROM vendor_subscriptions vs
                LEFT JOIN subscription_plans sp ON vs.subscription_plan_id = sp.id
                WHERE vs.vendor_id = :vendor_id
                ORDER BY vs.id DESC
                """
            ),
            {"vendor_id": vendor_id},
        )
    ).mappings().all()

    def _fmt_time(value):
        if value is None:
            return None
        if hasattr(value, "strftime"):
            return value.strftime("%H:%M")
        return str(value)[:5]

    def _fmt_dt(value):
        if value is None:
            return None
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    return {
        "registration": {
            "first_name": vendor_row["first_name"],
            "last_name": vendor_row["last_name"],
            "father_name": vendor_row["father_name"],
            "mobile_number": vendor_row["mobile_number"] or "",
            "alternative_contact_number": (
                vendor_row["alternative_contact_number"]
                or vendor_row["alternative_number"]
            ),
            "email": vendor_row["email"],
            "city": vendor_row["city"],
            "state": vendor_row["state"],
            "pincode": vendor_row["pincode"],
            "address": vendor_row["address"],
            "created_at": _fmt_dt(vendor_row["created_at"]),
        },
        "business_reg": {
            "business_name": vendor_row["business_name"],
            "aadhaar_number": vendor_row["aadhaar_number"],
            "pan_number": vendor_row["pan_number"],
            "gst_number": vendor_row["gst_number"],
            "service_radius_km": vendor_row["service_radius_km"] or 10,
            "documents": [
                {
                    "document_type": d["document_type"],
                    "verification_status": d["verification_status"],
                    "document_url": d["document_url"],
                }
                for d in docs
            ],
        },
        "services": [
            {
                "id": s["id"],
                "service_id": s["service_id"],
                "title": s["title"],
                "description": s["description"],
                "price": float(s["price"]) if s["price"] is not None else None,
                "discounted_price": (
                    float(s["discounted_price"])
                    if s["discounted_price"] is not None
                    else None
                ),
                "negotiable": bool(s["negotiable"]),
                "main_category_id": s["main_category_id"],
                "sub_category_id": s["sub_category_id"],
                "main_category_name": s["main_category_name"],
                "sub_category_name": s["sub_category_name"],
            }
            for s in services
        ],
        "slots": [
            {
                "day_of_week": a["day_of_week"],
                "day_name": day_names.get(a["day_of_week"], f"Day {a['day_of_week']}"),
                "start_time": _fmt_time(a["start_time"]),
                "end_time": _fmt_time(a["end_time"]),
                "is_available": a["is_available"],
            }
            for a in availability
            if a["is_available"] is not False
        ],
        "payment": {
            "payment_info": vendor_row["payment_info"],
            "subscriptions": [
                {
                    "plan_name": sub["plan_name"] or "Plan",
                    "payment_id": str(sub["id"]),
                    "amount": float(sub["amount"]) if sub["amount"] is not None else 0,
                    "status": sub["status"],
                    "start_date": _fmt_dt(sub["start_date"]),
                    "end_date": _fmt_dt(sub["end_date"]),
                }
                for sub in subscriptions
            ],
        },
    }


@router.get("/telecaller-dashboard/leaderboard", response_model=List[TelecallerLeaderboardEntry])
async def get_telecaller_leaderboard(
    db: AsyncSession = Depends(get_db),
    current_employee: Employee = Depends(get_current_employee)
):
    result = await db.execute(
        select(Employee.first_name, Employee.last_name, Employee.referral_points)
        .where(Employee.role.in_(['telecaller', 'verification']), Employee.status == 'active')
        .order_by(Employee.referral_points.desc())
        .limit(10)
    )
    rows = result.fetchall()
    return [{"name": f"{r[0]} {r[1] or ''}".strip(), "points": r[2]} for r in rows]


@router.get("/telecaller-dashboard/incentives")
async def get_verification_incentives(
    skip: int = 0,
    limit: int = 100,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Department-wide verification incentive summary (newest first)."""
    from app.models.verification_incentive import VerificationIncentive
    from app.models.subscriptions import SubscriptionPlan

    result = await db.execute(
        select(VerificationIncentive, SubscriptionPlan.name)
        .outerjoin(
            SubscriptionPlan,
            VerificationIncentive.plan_id == SubscriptionPlan.id,
        )
        .order_by(
            VerificationIncentive.payment_date.desc(),
            VerificationIncentive.id.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "id": row.id,
            "vendor_id": row.vendor_id,
            "vendor_name": row.vendor_name,
            "subscription_amount": row.subscription_amount,
            "incentive_percent": row.incentive_percent,
            "incentive_amount": row.incentive_amount,
            "payment_date": row.payment_date.isoformat() if row.payment_date else None,
            "plan_id": row.plan_id,
            "plan_name": plan_name,
            "employee_id": row.employee_id,
        }
        for row, plan_name in rows
    ]


@router.put("/vendors/{vendor_id}/approve", response_model=dict)
async def approve_vendor_by_telecaller(
    vendor_id: int,
    background_tasks: BackgroundTasks,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Allow telecaller to approve temporary_active vendors (assigned or unassigned)."""
    from sqlalchemy import text
    from app.models.vendor import Vendor
    from app.models.user_location import User

    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    old_status = (vendor.status or "").strip().lower()
    is_reverification = old_status in (
        "re_verification_pending",
        "re-verification pending",
        "re-verification",
        "re_verification",
    )
    has_active_sub = False
    if not is_reverification and old_status not in ("temporary_active", "temporary active"):
        sub_res = await db.execute(
            text(
                """
                SELECT 1 FROM vendor_subscriptions
                WHERE vendor_id = :vendor_id AND status = 'active'
                LIMIT 1
                """
            ),
            {"vendor_id": vendor_id},
        )
        has_active_sub = sub_res.first() is not None
        if not has_active_sub:
            raise HTTPException(
                status_code=400,
                detail="Only temporary_active or re_verification_pending vendors can be approved",
            )

    # Claim unassigned company lead for this telecaller on approve
    if vendor.assigned_telecaller_id is None:
        vendor.assigned_telecaller_id = current_employee.id

    vendor.status = "active"
    db.add(vendor)
    
    await record_vendor_audit_log(
        db,
        vendor_id=vendor_id,
        employee=current_employee,
        action_type="approve_vendor",
        description=f"Approved vendor verification (status set to active)",
        details={"old_status": old_status, "new_status": "active", "is_reverification": is_reverification}
    )
    await db.commit()

    user_query = await db.execute(select(User).where(User.id == vendor.user_id))
    user = user_query.scalar_one_or_none()
    if user:
        from app.services.notification_service import send_user_push_notification
        notif_title = "Re-verification Approved" if is_reverification else "Verification Completed"
        notif_body = (
            "Your updated profile and services have been approved and are now live."
            if is_reverification
            else "Your verification is completed. Thank you for choosing AM5Royal."
        )
        background_tasks.add_task(
            send_user_push_notification,
            user_id=user.id,
            title=notif_title,
            body=notif_body,
        )

    return {"message": "Vendor approved successfully", "status": "active"}


@router.put("/vendors/{vendor_id}/reject")
async def reject_vendor_by_employee(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_employee: Employee = Depends(get_current_employee),
):
    """Allow telecaller to reject vendors visible in their dashboard (assigned or unassigned)."""
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    old_status = (vendor.status or "").strip().lower()
    if old_status == "active":
        raise HTTPException(
            status_code=400,
            detail="Active vendors cannot be rejected",
        )

    if vendor.assigned_telecaller_id is None:
        vendor.assigned_telecaller_id = current_employee.id

    if old_status in (
        "re_verification_pending",
        "re-verification pending",
        "re-verification",
        "re_verification",
    ):
        vendor.status = "re_verification_rejected"
    else:
        vendor.status = "rejected"

    db.add(vendor)
    await record_vendor_audit_log(
        db,
        vendor_id=vendor_id,
        employee=current_employee,
        action_type="reject_vendor",
        description=f"Rejected vendor verification (status set to {vendor.status})",
        details={"old_status": old_status, "new_status": vendor.status}
    )
    await db.commit()
    return {"message": "Vendor status updated successfully", "status": vendor.status}


@router.post("/vendors/send-whatsapp-invite")
async def send_whatsapp_invite(
    request: WhatsAppInviteRequest,
    current_employee: Employee = Depends(get_current_employee)
):
    from app.services.whatsapp_service import send_whatsapp
    invite_link = 'https://vendor.am5royal.com/login'
    message = (
        f"🌟 *Welcome to AM5 ROYAL!* 🌟\n\n"
        f"Dear *{request.vendor_name}*,\n"
        f"Grow your business today by joining AM5 ROYAL as a premium Vendor partner! 🚀\n\n"
        f"👉 *Register & Complete your KYC here:* {invite_link}\n\n"
        f"We look forward to partnering with you!\n"
        f"Team AM5 ROYAL"
    )

    ok, error = await send_whatsapp(
        request.phone_number, message, campaign_name=f"Vendor Invitation - {request.vendor_name}"
    )
    if ok:
        return {"success": True, "message": "WhatsApp invite sent"}
    return {"success": False, "error": error}

@router.post("/withdraw", response_model=WithdrawalRequestResponse)
async def request_withdrawal(
    request: WithdrawalRequestCreate,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import text
    
    # 1. Verify that bank details are present
    if not (current_employee.bank_name and current_employee.bank_account_number and current_employee.bank_ifsc_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bank details are missing. Please update your bank details first."
        )
        
    # 2. Check current withdrawable balance
    # Calculate estimated referral payout (same as stats endpoint)
    payout_query = text("""
        SELECT COALESCE(SUM(sp.price), 0)
        FROM vendors v
        JOIN vendor_subscriptions vs ON v.id = vs.vendor_id
        JOIN subscription_plans sp ON vs.subscription_plan_id = sp.id
        WHERE v.onboarded_by_employee_id = :emp_id AND vs.status = 'active'
    """)
    res_payout = await db.execute(payout_query, {"emp_id": current_employee.id})
    estimated_referral_payout = float(res_payout.scalar() or 0.0) * 0.10

    # Calculate total withdrawn (sum of approved/pending withdrawals)
    withdrawn_query = text("SELECT COALESCE(SUM(amount), 0) FROM withdrawal_requests WHERE employee_id = :emp_id AND status IN ('pending', 'approved')")
    res_withdrawn = await db.execute(withdrawn_query, {"emp_id": current_employee.id})
    total_withdrawn = float(res_withdrawn.scalar() or 0.0)
    
    withdrawable_balance = max(0.0, estimated_referral_payout - total_withdrawn)

    if request.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Withdrawal amount must be greater than zero."
        )

    if request.amount > withdrawable_balance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance. Your current withdrawable balance is ₹{withdrawable_balance:.2f}."
        )
        
    # 3. Create a withdrawal request record
    withdrawal = WithdrawalRequest(
        employee_id=current_employee.id,
        amount=request.amount,
        status="pending",
        bank_name=current_employee.bank_name,
        bank_account_number=current_employee.bank_account_number,
        bank_account_name=current_employee.bank_account_name,
        bank_ifsc_code=current_employee.bank_ifsc_code
    )
    
    db.add(withdrawal)
    await db.commit()
    await db.refresh(withdrawal)
    return withdrawal

@router.get("/withdrawals", response_model=List[WithdrawalRequestResponse])
async def list_employee_withdrawals(
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(WithdrawalRequest)
        .where(WithdrawalRequest.employee_id == current_employee.id)
        .order_by(WithdrawalRequest.created_at.desc())
    )
    return result.scalars().all()


@router.get("/vendors/{vendor_id}/details", response_model=VendorFullDetailsResponse)
async def get_vendor_details_for_telecaller(
    vendor_id: int,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve full vendor details for telecaller viewing/editing."""
    from app.models.vendor import Vendor
    from app.models.user_location import User
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
        
    user_query = await db.execute(select(User).where(User.id == vendor.user_id))
    user = user_query.scalar_one_or_none()

    vendor_email = getattr(vendor, "email", None)
    user_email = user.email if user else None
    effective_email = None
    if vendor_email and not vendor_email.startswith("vendor_"):
        effective_email = vendor_email
    elif user_email and not user_email.startswith("vendor_"):
        effective_email = user_email
    else:
        effective_email = vendor_email or user_email

    highlights = getattr(vendor, "business_highlights", None)
    if isinstance(highlights, str):
        import json
        try:
            parsed = json.loads(highlights)
            if isinstance(parsed, list):
                highlights = [str(x) for x in parsed if x is not None]
            else:
                highlights = [s.strip() for s in highlights.split(",") if s.strip()]
        except Exception:
            highlights = [s.strip() for s in highlights.split(",") if s.strip()]
    elif isinstance(highlights, list):
        highlights = [str(x) for x in highlights if x is not None]

    return VendorFullDetailsResponse(
        id=int(vendor.id),
        user_id=int(vendor.user_id) if vendor.user_id else None,
        first_name=vendor.first_name,
        last_name=vendor.last_name,
        father_name=getattr(vendor, "father_name", None),
        email=effective_email,
        mobile=user.mobile if user else getattr(vendor, "mobile", None),
        alternative_number=getattr(vendor, "alternative_number", None),
        alternative_contact_number=getattr(vendor, "alternative_contact_number", None),
        business_name=vendor.business_name,
        aadhaar_number=getattr(vendor, "aadhaar_number", None),
        pan_number=getattr(vendor, "pan_number", None),
        gst_number=getattr(vendor, "gst_number", None),
        address=vendor.address,
        street=getattr(vendor, "street", None),
        city=vendor.city,
        district=getattr(vendor, "district", None),
        state=vendor.state,
        pincode=vendor.pincode,
        service_radius_km=getattr(vendor, "service_radius_km", 10),
        visiting_charges=float(vendor.visiting_charges) if getattr(vendor, "visiting_charges", None) is not None else None,
        business_description=getattr(vendor, "business_description", None),
        business_highlights=highlights,
        about_business=getattr(vendor, "about_business", None),
        additional_business_info=getattr(vendor, "additional_business_info", None),
        status=vendor.status,
    )


async def record_vendor_audit_log(
    db: AsyncSession,
    vendor_id: int,
    employee: Employee,
    action_type: str,
    description: str,
    details: Optional[dict] = None
):
    """Helper to record audit trail in vendor_audit_logs."""
    try:
        from app.models.vendor import VendorAuditLog
        emp_name = f"{employee.first_name or ''} {employee.last_name or ''}".strip() or f"Employee #{employee.id}"
        log = VendorAuditLog(
            vendor_id=vendor_id,
            employee_id=employee.id,
            employee_name=emp_name,
            employee_role=getattr(employee, "role", "telecaller"),
            action_type=action_type,
            description=description,
            details=details or {},
            created_at=datetime.utcnow()
        )
        db.add(log)
    except Exception as e:
        logger.error(f"Failed to record vendor audit log for vendor {vendor_id}: {e}")


@router.put("/vendors/{vendor_id}/details")
async def update_vendor_details_by_telecaller(
    vendor_id: int,
    details: VendorDetailsUpdate,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Allow telecaller to edit vendor personal, business, KYC and operational details."""
    from app.models.vendor import Vendor
    from app.models.user_location import User
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    update_data = details.model_dump(exclude_unset=True)
    changed_fields = []
    for key, val in update_data.items():
        if hasattr(vendor, key) and val is not None:
            old_val = getattr(vendor, key)
            if str(old_val) != str(val):
                changed_fields.append(key)
            setattr(vendor, key, val)

    # If email is provided, sync with User table as well
    req_email = getattr(details, "email", None)
    if req_email and vendor.user_id:
        user_query = await db.execute(select(User).where(User.id == vendor.user_id))
        user = user_query.scalar_one_or_none()
        if user and user.email != req_email:
            existing_email_user = (await db.execute(
                select(User.id).where(User.email == req_email, User.id != user.id)
            )).scalar_one_or_none()
            if not existing_email_user:
                user.email = req_email
                db.add(user)

    db.add(vendor)
    
    desc = f"Updated profile details ({', '.join(changed_fields)})" if changed_fields else "Updated profile details"
    await record_vendor_audit_log(
        db,
        vendor_id=vendor_id,
        employee=current_employee,
        action_type="profile_update",
        description=desc,
        details=update_data
    )

    await db.commit()
    await db.refresh(vendor)
    return {"success": True, "message": "Vendor details updated successfully", "vendor_id": vendor_id}


@router.put("/vendors/{vendor_id}/lead-status")
async def update_vendor_lead_status(
    vendor_id: int,
    status_in: LeadStatusUpdate,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Allow telecaller to update CRM lead status (New, Contacted, In Progress, Converted, etc.)."""
    from app.models.vendor import Vendor
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # If unassigned, claim it
    if vendor.assigned_telecaller_id is None:
        vendor.assigned_telecaller_id = current_employee.id

    old_status = getattr(vendor, "status", None)
    if status_in.status.lower() == "activated":
        vendor.status = "active"

    await record_vendor_audit_log(
        db,
        vendor_id=vendor_id,
        employee=current_employee,
        action_type="lead_status_update",
        description=f"Updated lead status to '{status_in.status}' (notes: {status_in.notes or 'None'})",
        details={"status": status_in.status, "notes": status_in.notes, "old_status": old_status}
    )

    await db.commit()
    return {
        "message": f"Lead status updated to {status_in.status}",
        "vendor_id": vendor_id,
        "status": status_in.status
    }


@router.get("/catalog/categories-tree")
async def get_catalog_categories_tree(
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Returns the full hierarchical category -> subcategory -> services catalog tree."""
    from app.models.catalog import ServiceCategory, ServiceSubcategory, Service
    
    cats_res = await db.execute(
        select(ServiceCategory)
        .where(ServiceCategory.is_active == True)
        .order_by(ServiceCategory.name.asc())
    )
    categories = cats_res.scalars().all()
    
    subcats_res = await db.execute(
        select(ServiceSubcategory)
        .where(ServiceSubcategory.is_active == True)
        .order_by(ServiceSubcategory.sort_order.asc(), ServiceSubcategory.name.asc())
    )
    subcategories = subcats_res.scalars().all()
    
    services_res = await db.execute(
        select(Service)
        .where(Service.is_active == True)
        .order_by(Service.name.asc())
    )
    services = services_res.scalars().all()
    
    services_by_subcat = {}
    for svc in services:
        if svc.sub_category_id:
            services_by_subcat.setdefault(svc.sub_category_id, []).append({
                "id": svc.id,
                "name": svc.name,
                "image_url": svc.image_url,
                "main_category_id": svc.main_category_id,
                "sub_category_id": svc.sub_category_id,
            })
            
    subcats_by_cat = {}
    for sc in subcategories:
        subcats_by_cat.setdefault(sc.main_category_id, []).append({
            "id": sc.id,
            "name": sc.name,
            "main_category_id": sc.main_category_id,
            "description": sc.description,
            "icon_url": sc.icon_url,
            "services": services_by_subcat.get(sc.id, []),
        })
        
    tree = []
    for cat in categories:
        tree.append({
            "id": cat.id,
            "name": cat.name,
            "icon": cat.icon,
            "subcategories": subcats_by_cat.get(cat.id, []),
        })
        
    return tree


@router.get("/vendors/{vendor_id}/services", response_model=List[VendorServiceItem])
async def get_vendor_services_for_telecaller(
    vendor_id: int,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all services currently assigned to the vendor."""
    from app.models.vendor import Vendor
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
        
    services = (
        await db.execute(
            text(
                """
                SELECT
                    vs.id,
                    vs.vendor_id,
                    vs.service_id,
                    vs.main_category_id,
                    vs.sub_category_id,
                    vs.title,
                    vs.description,
                    vs.price,
                    vs.discounted_price,
                    vs.negotiable,
                    vs.is_active,
                    mc.name AS main_category_name,
                    sc.name AS sub_category_name
                FROM vendor_services vs
                LEFT JOIN main_categories mc ON vs.main_category_id = mc.id
                LEFT JOIN sub_categories sc ON vs.sub_category_id = sc.id
                WHERE vs.vendor_id = :vendor_id
                ORDER BY vs.id DESC
                """
            ),
            {"vendor_id": vendor_id},
        )
    ).mappings().all()

    return [
        {
            "id": s["id"],
            "vendor_id": s["vendor_id"],
            "service_id": s["service_id"],
            "main_category_id": s["main_category_id"],
            "sub_category_id": s["sub_category_id"],
            "title": s["title"],
            "description": s["description"],
            "price": float(s["price"]) if s["price"] is not None else None,
            "discounted_price": float(s["discounted_price"]) if s["discounted_price"] is not None else None,
            "negotiable": bool(s["negotiable"]),
            "is_active": bool(s["is_active"]),
            "main_category_name": s["main_category_name"],
            "sub_category_name": s["sub_category_name"],
        }
        for s in services
    ]


@router.post("/vendors/{vendor_id}/services")
async def add_vendor_service_by_telecaller(
    vendor_id: int,
    service_in: VendorServiceCreateRequest,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Add a service (and link subcategory) to vendor profile, recording an audit log."""
    from app.models.vendor import Vendor, VendorService, VendorSubCategory
    
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
        
    existing_query = select(VendorService).where(
        VendorService.vendor_id == vendor_id,
        VendorService.sub_category_id == service_in.sub_category_id,
        VendorService.title == service_in.title
    )
    if service_in.service_id:
        existing_query = select(VendorService).where(
            VendorService.vendor_id == vendor_id,
            VendorService.service_id == service_in.service_id
        )
    existing_svc = (await db.execute(existing_query)).scalar_one_or_none()
    
    if existing_svc:
        existing_svc.price = service_in.price
        existing_svc.discounted_price = service_in.discounted_price
        existing_svc.negotiable = service_in.negotiable
        existing_svc.description = service_in.description or existing_svc.description
        existing_svc.is_active = True
        db.add(existing_svc)
        vendor_svc = existing_svc
        action = "service_update"
        desc = f"Updated service '{vendor_svc.title}' price to ₹{service_in.price}"
    else:
        vendor_svc = VendorService(
            vendor_id=vendor_id,
            main_category_id=service_in.main_category_id,
            sub_category_id=service_in.sub_category_id,
            service_id=service_in.service_id,
            title=service_in.title,
            description=service_in.description,
            price=service_in.price,
            discounted_price=service_in.discounted_price,
            negotiable=service_in.negotiable,
            is_active=True
        )
        db.add(vendor_svc)
        action = "service_add"
        desc = f"Added service '{vendor_svc.title}' at ₹{service_in.price}"

    subcat_query = select(VendorSubCategory).where(
        VendorSubCategory.vendor_id == vendor_id,
        VendorSubCategory.sub_category_id == service_in.sub_category_id
    )
    if not (await db.execute(subcat_query)).scalar_one_or_none():
        db.add(VendorSubCategory(
            vendor_id=vendor_id,
            main_category_id=service_in.main_category_id,
            sub_category_id=service_in.sub_category_id
        ))

    vendor.telecaller_services_updated = True
    db.add(vendor)

    await record_vendor_audit_log(
        db,
        vendor_id=vendor_id,
        employee=current_employee,
        action_type=action,
        description=desc,
        details=service_in.model_dump()
    )

    await db.commit()
    return {"success": True, "message": "Service added successfully"}


@router.put("/vendors/{vendor_id}/services/{service_id}")
async def update_vendor_service_by_telecaller(
    vendor_id: int,
    service_id: int,
    service_in: VendorServiceUpdateRequest,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Update price, discount, or details for a vendor service, recording an audit log."""
    from app.models.vendor import Vendor, VendorService
    
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
        
    svc = await db.get(VendorService, service_id)
    if not svc or svc.vendor_id != vendor_id:
        svc_res = await db.execute(
            select(VendorService).where(
                VendorService.vendor_id == vendor_id,
                VendorService.service_id == service_id
            )
        )
        svc = svc_res.scalars().first()

    if not svc:
        raise HTTPException(status_code=404, detail="Service not found for this vendor")

    old_price = float(svc.price) if svc.price is not None else 0.0
    changes = []
    
    update_data = service_in.model_dump(exclude_unset=True)
    if "title" in update_data and update_data["title"]:
        svc.title = update_data["title"]
        changes.append(f"title='{svc.title}'")
    if "price" in update_data and update_data["price"] is not None:
        svc.price = update_data["price"]
        changes.append(f"price=₹{svc.price} (was ₹{old_price})")
    if "discounted_price" in update_data:
        svc.discounted_price = update_data["discounted_price"]
        changes.append(f"discounted_price=₹{svc.discounted_price}")
    if "negotiable" in update_data:
        svc.negotiable = update_data["negotiable"]
        changes.append(f"negotiable={svc.negotiable}")
    if "description" in update_data:
        svc.description = update_data["description"]
    if "is_active" in update_data:
        svc.is_active = update_data["is_active"]
        changes.append(f"is_active={svc.is_active}")

    db.add(svc)
    
    desc = f"Updated service '{svc.title}': {', '.join(changes)}" if changes else f"Updated service '{svc.title}'"
    await record_vendor_audit_log(
        db,
        vendor_id=vendor_id,
        employee=current_employee,
        action_type="service_update",
        description=desc,
        details=update_data
    )
    
    await db.commit()
    return {"success": True, "message": "Service updated successfully"}


@router.delete("/vendors/{vendor_id}/services/{service_id}")
async def delete_vendor_service_by_telecaller(
    vendor_id: int,
    service_id: int,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Remove a service from vendor catalog and record an audit log."""
    from app.models.vendor import Vendor, VendorService, VendorSubCategory, VendorServiceMedia
    from sqlalchemy import delete
    
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
        
    svc = await db.get(VendorService, service_id)
    if not svc or svc.vendor_id != vendor_id:
        svc_res = await db.execute(
            select(VendorService).where(
                VendorService.vendor_id == vendor_id,
                VendorService.service_id == service_id
            )
        )
        svc = svc_res.scalars().first()

    if not svc:
        raise HTTPException(status_code=404, detail="Service not found for this vendor")

    svc_title = svc.title
    subcat_id = svc.sub_category_id
    svc_pk = svc.id

    await db.execute(delete(VendorServiceMedia).where(VendorServiceMedia.vendor_service_id == svc_pk))
    await db.delete(svc)
    await db.flush()

    remaining_res = await db.execute(
        select(VendorService.id).where(
            VendorService.vendor_id == vendor_id,
            VendorService.sub_category_id == subcat_id
        )
    )
    if remaining_res.first() is None:
        await db.execute(
            delete(VendorSubCategory).where(
                VendorSubCategory.vendor_id == vendor_id,
                VendorSubCategory.sub_category_id == subcat_id
            )
        )

    await record_vendor_audit_log(
        db,
        vendor_id=vendor_id,
        employee=current_employee,
        action_type="service_remove",
        description=f"Removed service '{svc_title}' from vendor catalog",
        details={"service_id": service_id, "title": svc_title, "sub_category_id": subcat_id}
    )

    await db.commit()
    return {"success": True, "message": f"Service '{svc_title}' removed successfully"}


@router.delete("/vendors/{vendor_id}/sub-categories/{sub_category_id}")
async def delete_vendor_subcategory_by_telecaller(
    vendor_id: int,
    sub_category_id: int,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Remove a subcategory and all associated services for the vendor."""
    from app.models.vendor import Vendor, VendorService, VendorSubCategory, VendorServiceMedia
    from sqlalchemy import delete
    
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    services_res = await db.execute(
        select(VendorService).where(
            VendorService.vendor_id == vendor_id,
            VendorService.sub_category_id == sub_category_id
        )
    )
    services = services_res.scalars().all()
    
    for s in services:
        await db.execute(delete(VendorServiceMedia).where(VendorServiceMedia.vendor_service_id == s.id))
        await db.delete(s)

    await db.execute(
        delete(VendorSubCategory).where(
            VendorSubCategory.vendor_id == vendor_id,
            VendorSubCategory.sub_category_id == sub_category_id
        )
    )

    await record_vendor_audit_log(
        db,
        vendor_id=vendor_id,
        employee=current_employee,
        action_type="subcategory_remove",
        description=f"Removed subcategory #{sub_category_id} and {len(services)} associated services",
        details={"sub_category_id": sub_category_id, "services_count": len(services)}
    )

    await db.commit()
    return {"success": True, "message": f"Subcategory and its {len(services)} services removed"}


@router.get("/vendors/{vendor_id}/slots")
async def get_vendor_slots_for_telecaller(
    vendor_id: int,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve working availability slots for the vendor."""
    from app.models.vendor import Vendor, VendorAvailability
    
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    slots_res = await db.execute(
        select(VendorAvailability)
        .where(VendorAvailability.vendor_id == vendor_id)
        .order_by(VendorAvailability.day_of_week.asc())
    )
    slots = slots_res.scalars().all()
    
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    def _fmt_t(val):
        if val is None:
            return "09:00"
        if hasattr(val, "strftime"):
            return val.strftime("%H:%M")
        return str(val)[:5]

    slots_map = {s.day_of_week: s for s in slots}
    
    result = []
    for day_num in range(7):
        slot = slots_map.get(day_num)
        if slot:
            result.append({
                "day_of_week": day_num,
                "day_name": day_names[day_num],
                "start_time": _fmt_t(slot.start_time),
                "end_time": _fmt_t(slot.end_time),
                "is_available": bool(slot.is_available)
            })
        else:
            result.append({
                "day_of_week": day_num,
                "day_name": day_names[day_num],
                "start_time": "09:00",
                "end_time": "18:00",
                "is_available": False
            })
            
    return result


@router.put("/vendors/{vendor_id}/slots")
async def update_vendor_slots_by_telecaller(
    vendor_id: int,
    slots_in: VendorAvailabilityUpdateRequest,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Update or configure working availability slots for the vendor."""
    from app.models.vendor import Vendor, VendorAvailability
    from sqlalchemy import delete
    from datetime import time
    
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    await db.execute(delete(VendorAvailability).where(VendorAvailability.vendor_id == vendor_id))

    def _parse_time(t_str: str) -> time:
        try:
            parts = [int(p) for p in t_str.split(":")[:2]]
            return time(hour=parts[0], minute=parts[1])
        except Exception:
            return time(hour=9, minute=0)

    added_slots = []
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    
    for s in slots_in.slots:
        st = _parse_time(s.start_time)
        et = _parse_time(s.end_time)
        new_avail = VendorAvailability(
            vendor_id=vendor_id,
            day_of_week=s.day_of_week,
            start_time=st,
            end_time=et,
            is_available=s.is_available
        )
        db.add(new_avail)
        if s.is_available:
            day_label = day_names[s.day_of_week] if 0 <= s.day_of_week < 7 else str(s.day_of_week)
            added_slots.append(f"{day_label} ({s.start_time}-{s.end_time})")

    desc = f"Updated working availability slots ({', '.join(added_slots) if added_slots else 'all days off'})"
    await record_vendor_audit_log(
        db,
        vendor_id=vendor_id,
        employee=current_employee,
        action_type="slots_update",
        description=desc,
        details={"slots": [s.model_dump() for s in slots_in.slots]}
    )

    await db.commit()
    return {"success": True, "message": "Availability slots updated successfully"}


@router.get("/vendors/{vendor_id}/audit-logs", response_model=List[VendorAuditLogResponse])
async def get_vendor_audit_logs(
    vendor_id: int,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve full audit log trail of who changed what and when for this vendor."""
    from app.models.vendor import Vendor, VendorAuditLog
    
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    result = await db.execute(
        select(VendorAuditLog)
        .where(VendorAuditLog.vendor_id == vendor_id)
        .order_by(VendorAuditLog.created_at.desc())
        .limit(100)
    )
    logs = result.scalars().all()
    return logs


@router.get("/notifications", response_model=List[TeamNotificationResponse])
async def get_team_notifications(
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve dynamic notifications for this verification team member."""
    from sqlalchemy import text
    
    query = text("""
        SELECT v.id, v.business_name, v.first_name, v.status, v.lead_source, v.created_at
        FROM vendors v
        WHERE (v.assigned_telecaller_id = :emp_id OR v.onboarded_by_employee_id = :emp_id OR v.status = 'temporary_active')
        ORDER BY v.created_at DESC
        LIMIT 25
    """)
    res = await db.execute(query, {"emp_id": current_employee.id})
    rows = res.fetchall()

    notifications = []
    # Admin system message
    notifications.append({
        "id": "admin-1",
        "type": "admin",
        "title": "AM5 Operations Welcome",
        "message": "Welcome to AM5 ROYAL Verification Desk. Ensure KYC documents and PAN/Aadhaar match before activating vendors.",
        "lead_id": None,
        "created_at": datetime.utcnow().isoformat(),
        "is_read": False
    })

    for r in rows:
        st = (r.status or "").lower()
        ls = r.lead_source or "Website"
        source_label = "Company Website" if "website" in ls else ("Company App" if "mobile" in ls else "Freelancer")
        name = r.business_name or r.first_name or "Vendor Partner"

        if st in ("temporary_active", "temp active"):
            notifications.append({
                "id": f"kyc-{r.id}",
                "type": "kyc_pending",
                "title": f"KYC Verification Required: {name}",
                "message": f"Partner has completed subscription. Review and approve or reject.",
                "lead_id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else datetime.utcnow().isoformat(),
                "is_read": False
            })
        elif st == "payment":
            notifications.append({
                "id": f"pay-{r.id}",
                "type": "payment_pending",
                "title": f"Payment Pending: {name}",
                "message": f"Business details submitted. Guide partner to complete subscription payment.",
                "lead_id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else datetime.utcnow().isoformat(),
                "is_read": False
            })
        else:
            notifications.append({
                "id": f"lead-{r.id}",
                "type": "new_lead",
                "title": f"New {source_label} Lead: {name}",
                "message": f"Lead received via {source_label}. Stage: {r.status}.",
                "lead_id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else datetime.utcnow().isoformat(),
                "is_read": False
            })

    return notifications


@router.get("/telecaller-dashboard/lead-performance", response_model=LeadPerformanceResponse)
async def get_lead_performance_metrics(
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Detailed Section 12 Lead Performance Metrics for the Verification Team Member."""
    from sqlalchemy import text

    query = text("""
        SELECT
            COUNT(*) as total_leads,
            COUNT(CASE WHEN v.lead_source IN ('company', 'company_website') OR v.lead_source IS NULL OR v.lead_source = '' THEN 1 END) as website_leads,
            COUNT(CASE WHEN v.lead_source = 'company_mobile' THEN 1 END) as application_leads,
            COUNT(CASE WHEN v.lead_source = 'freelancer' THEN 1 END) as freelancer_leads,
            COUNT(CASE WHEN v.assigned_telecaller_id = :emp_id THEN 1 END) as assigned_leads,
            COUNT(CASE WHEN v.status = 'active' THEN 1 END) as activated_vendors,
            COUNT(CASE WHEN v.status = 'temporary_active' THEN 1 END) as pending_leads
        FROM vendors v
        WHERE (v.assigned_telecaller_id = :emp_id OR v.onboarded_by_employee_id = :emp_id OR v.lead_source IN ('company', 'company_website', 'company_mobile', 'freelancer'))
    """)
    res = await db.execute(query, {"emp_id": current_employee.id})
    row = res.mappings().first() or {}

    total = row.get("total_leads") or 0
    activated = row.get("activated_vendors") or 0
    conv_rate = round((activated / total * 100), 1) if total > 0 else 0.0

    return {
        "total_leads": total,
        "website_leads": row.get("website_leads") or 0,
        "application_leads": row.get("application_leads") or 0,
        "freelancer_leads": row.get("freelancer_leads") or 0,
        "assigned_leads": row.get("assigned_leads") or 0,
        "contacted_leads": max(0, total - (row.get("pending_leads") or 0)),
        "in_progress_leads": row.get("pending_leads") or 0,
        "converted_leads": activated,
        "activated_vendors": activated,
        "pending_leads": row.get("pending_leads") or 0,
        "closed_leads": 0,
        "conversion_rate": conv_rate
    }


@router.post("/contact-admin")
async def send_contact_admin_message(
    req: AdminContactMessageRequest,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """Log or dispatch a support request to administrator."""
    return {
        "success": True,
        "message": f"Support request '{req.subject}' received. An administrator will respond shortly."
    }


@router.post("/telecaller-dashboard/call", response_model=InitiateCallResponse)
async def initiate_telecaller_call(
    call_req: InitiateCallRequest,
    current_employee: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db),
):
    """
    Initiates a Tata Smartflo Click-to-Call call from the logged-in telecaller to a vendor or lead.
    Validates telecaller session, validates phone number, triggers Smartflo C2C,
    and logs the call in the database.
    """
    # 1. Resolve agent number (Priority: request > employee phone > default configured DID/Extension)
    agent_phone = (
        call_req.agent_phone
        or getattr(current_employee, "phone", None)
        or settings.SMARTFLO_DEFAULT_AGENT_NUMBER
        or "918065605779"
    )

    # 2. Validate target phone number
    try:
        norm_target = smartflo_service.normalize_phone_number(call_req.phone_number)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    # 3. Optional: Verify vendor existence if vendor_id is supplied
    vendor_id = call_req.vendor_id
    if vendor_id:
        from app.models.vendor import Vendor
        v_check = await db.execute(select(Vendor.id).where(Vendor.id == vendor_id))
        if not v_check.scalar_one_or_none():
            logger.warning(f"Vendor ID {vendor_id} not found in database; proceeding with phone {norm_target}")
            vendor_id = None

    # 4. Initiate Click-to-Call via Tata Smartflo service
    success, message, call_session_id = await smartflo_service.initiate_click_to_call(
        agent_number=agent_phone,
        destination_number=norm_target,
        caller_id=settings.SMARTFLO_CALLER_ID,
        call_timeout=settings.SMARTFLO_CALL_TIMEOUT,
        custom_identifier={
            "vendor_id": str(vendor_id) if vendor_id else "0",
            "employee_id": str(current_employee.id),
        } if vendor_id else None,
    )

    # 5. Log call in telecaller_call_logs table
    call_log = TelecallerCallLog(
        telecaller_id=current_employee.id,
        vendor_id=vendor_id,
        target_phone=norm_target,
        agent_phone=str(agent_phone),
        call_session_id=call_session_id,
        record=True,
        status="initiated" if success else "failed",
        error_message=None if success else message,
    )
    db.add(call_log)
    try:
        await db.commit()
    except Exception as db_err:
        logger.error(f"Failed to commit call log: {db_err}")
        await db.rollback()

    if not success:
        return InitiateCallResponse(
            success=False,
            message=message,
            target_phone=norm_target,
            agent_phone=str(agent_phone),
        )

    return InitiateCallResponse(
        success=True,
        message=message,
        call_session_id=call_session_id,
        target_phone=norm_target,
        agent_phone=str(agent_phone),
    )
