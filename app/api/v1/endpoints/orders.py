from typing import List, Optional
import uuid
import datetime
from datetime import date, time, timezone, datetime, timedelta
import random
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func, delete, update, bindparam
from sqlalchemy.exc import IntegrityError

from app.db.session import get_db
from app.models.orders import Order as OrderModel, OrderItem as OrderItemModel, BookingLocationPing
from app.models.vendor import Vendor, VendorService
from app.models.subscriptions import VendorSubscription, SubscriptionPlan, VendorWallet, WalletTransaction
from app.models.user_location import Customer, Address as AddressModel
from app.models.catalog import Package as PackageModel, ServiceSubcategory as SubcategoryModel
from app.schemas.orders import OrderCreate, CalculationRequest, CalculationResponse
from app.dependencies.auth import get_current_customer, get_current_vendor
from app.core.rate_limit import limiter
from app.core.geo import estimate_route
from app.models.customer_billing import BookingFeedback, BookingPayment
from app.services import customer_wallet_service as wallets
from app.services.booking_assignment_service import (
    area_from_address,
    build_initial_assignment_meta,
    close_pending_offers,
    get_pending_offer,
    notify_vendor_new_booking,
    notify_customer_vendor_accepted,
    handle_vendor_decline_or_timeout,
    open_offer,
    process_pending_booking_timeouts,
)
from app.services import vendor_lead_service as leads
from app.models.booking_offer import BookingOffer, VendorLeadHistory
from app.dependencies.auth import get_current_admin

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))
# Statuses from which a customer may still cancel or reschedule.
CHANGEABLE_STATUSES = ("PENDING", "new", "ACCEPTED")
MAX_RESCHEDULES = 2

def _to_ist(dt: datetime) -> datetime:
    """Slots are shown in IST. Aware datetimes are converted; naive ones are taken as IST already."""
    return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)

def _now_ist() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST)

async def _vendor_unit_price(db: AsyncSession, vendor_id: int, subcategory_id: int) -> Optional[float]:
    """The vendor's own price for a service, as shown to the customer (discounted price wins)."""
    res = await db.execute(
        select(VendorService)
        .where(
            VendorService.vendor_id == vendor_id,
            VendorService.sub_category_id == subcategory_id,
            VendorService.is_active == True,
        )
        .order_by(VendorService.id)
    )
    row = res.scalars().first()
    if not row:
        return None
    price = float(row.discounted_price or row.price or 0)
    return price if price > 0 else None

@router.get("/", response_model=List[dict])
@limiter.limit("30/minute")
async def get_my_orders(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
    status: Optional[str] = Query(None, description="Filter by booking status (case-insensitive)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    """
    Order history for the logged-in customer, newest first.
    """
    query = select(OrderModel).where(OrderModel.customer_id == current_customer.id)
    if status and status.strip():
        query = query.where(func.upper(OrderModel.status) == status.strip().upper())
    query = query.order_by(OrderModel.created_at.desc(), OrderModel.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    orders = result.scalars().all()

    return [
        {
            "orderId": o.booking_reference or f"HYD{str(o.id).zfill(5)}",
            "invoice": None,
            "razorPayOrderId": None,
            "orderdate": o.created_at.strftime("%Y-%m-%d") if o.created_at else None,
            "ordertime": o.created_at.strftime("%I:%M %p") if o.created_at else None,
            "serviceDate": o.booking_date.strftime("%Y-%m-%d") if o.booking_date else None,
            "serviceTime": o.booking_time.strftime("%I:%M %p") if o.booking_time else None,
            "status": o.status,
            "customer_name": o.customer_name or current_customer.full_name,
            "email": o.customer_email or current_customer.email,
            "contactNumber": o.customer_phone or current_customer.phone,
            "totalAmount": float(o.total_amount or 0.0),
            "finalAmount": float(o.final_amount or 0.0),
            "service_name": o.service_name,
            "service_category": o.service_category,
            "vendor_id": o.vendor_id,
            "vendor_name": o.vendor_name,
            "service_address": o.service_address,
            "material_option": o.material_option,
            "special_instructions": o.special_instructions,
            "cancellation_reason": o.cancellation_reason,
            "cancelled_at": o.cancelled_at.isoformat() if o.cancelled_at else None,
            "reschedule_count": o.reschedule_count or 0,
        }
        for o in orders
    ]

@router.post("/", response_model=dict)
@limiter.limit("5/minute")
async def create_order(
    request: Request,
    order_in: OrderCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """
    Create a new booking (Matches PDF Page 44).
    """
    # 1. Fetch Address details
    address_res = await db.execute(
        select(AddressModel).where(
            AddressModel.id == order_in.address_id,
            AddressModel.customer_id == current_customer.id
        )
    )
    address = address_res.scalar_one_or_none()
    if not address:
        raise HTTPException(status_code=400, detail="Invalid address_id or address does not belong to customer")

    # Format the full text address
    address_parts = [address.address_line1]
    if address.address_line2:
        address_parts.append(address.address_line2)
    if address.city:
        address_parts.append(address.city)
    if address.state:
        address_parts.append(address.state)
    if address.pincode:
        address_parts.append(address.pincode)
    service_address = ", ".join(address_parts)

    # 2. Get and validate all packages/subcategories to extract all subcategory_ids
    if not order_in.items:
        raise HTTPException(status_code=400, detail="Order items cannot be empty")

    subcategory_ids = set()
    first_item = order_in.items[0]
    package = None
    subcategory = None

    for idx, item in enumerate(order_in.items):
        if item.package_id:
            package_res = await db.execute(select(PackageModel).where(PackageModel.id == item.package_id))
            item_package = package_res.scalar_one_or_none()
            if not item_package:
                raise HTTPException(status_code=400, detail=f"Package not found for ID {item.package_id}")
            subcategory_ids.add(item_package.subcategory_id)
            if idx == 0:
                package = item_package
                subcat_res = await db.execute(select(SubcategoryModel).where(SubcategoryModel.id == package.subcategory_id))
                subcategory = subcat_res.scalar_one_or_none()
        elif item.subcategory_id:
            subcat_res = await db.execute(select(SubcategoryModel).where(SubcategoryModel.id == item.subcategory_id))
            item_subcategory = subcat_res.scalar_one_or_none()
            if not item_subcategory:
                raise HTTPException(status_code=400, detail=f"Subcategory not found for ID {item.subcategory_id}")
            subcategory_ids.add(item_subcategory.id)
            if idx == 0:
                subcategory = item_subcategory
        else:
            raise HTTPException(status_code=400, detail="Either package_id or subcategory_id must be provided for order items")

    # 3. Validate the schedule. Slots are in IST, so store IST date/time
    #    (the app sends UTC, which would otherwise shift the slot by 5h30m).
    scheduled_ist = _to_ist(order_in.scheduled_at)
    if scheduled_ist <= _now_ist():
        raise HTTPException(status_code=400, detail="Scheduled time must be in the future")
    booking_date = scheduled_ist.date()
    booking_time = scheduled_ist.time().replace(tzinfo=None)

    if order_in.vendor_profile_id is None:
        raise HTTPException(status_code=400, detail="vendor_profile_id is required")

    # 5. Fetch and Validate Vendor details (current schema uses vendors table)
    vendor_profile_id = order_in.vendor_profile_id
    vendor_name = "Default Vendor"
    vendor_phone = "9999999999"
    vendor_email = "vendor@example.com"
    resolved_vendor_id = None

    if vendor_profile_id is not None:
        vendor_res = await db.execute(
            select(Vendor).where(Vendor.id == vendor_profile_id)
        )
        vendor_obj = vendor_res.scalar_one_or_none()
        if not vendor_obj:
            raise HTTPException(
                status_code=400,
                detail=f"Vendor not found for ID {vendor_profile_id}",
            )
        # Only active members with leads left take bookings.
        vendor_sub = await leads.get_active_subscription(db, vendor_obj.id)
        if vendor_obj.status != "active" or not leads.has_leads(vendor_sub):
            raise HTTPException(
                status_code=400,
                detail="This professional is not taking bookings right now. Please choose another professional.",
            )

        resolved_vendor_id = vendor_obj.id
        vendor_name = vendor_obj.business_name or "Vendor"
        vendor_phone = vendor_obj.mobile or vendor_phone
        vendor_email = vendor_obj.email or vendor_email

        services_res = await db.execute(
            select(VendorService.sub_category_id).where(
                VendorService.vendor_id == vendor_obj.id,
                VendorService.is_active == True,
            )
        )
        provided_subcats = {row[0] for row in services_res.fetchall() if row[0]}
        missing_subcats = subcategory_ids - provided_subcats
        if missing_subcats and provided_subcats:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Selected vendor does not provide the requested services "
                    f"(missing subcategory IDs: {list(missing_subcats)})"
                ),
            )
    else:
        vendor_res = await db.execute(select(Vendor).where(Vendor.id == 1))
        vendor_obj = vendor_res.scalar_one_or_none()
        if vendor_obj:
            resolved_vendor_id = vendor_obj.id
            vendor_profile_id = vendor_obj.id
            vendor_name = vendor_obj.business_name or vendor_name
            vendor_phone = vendor_obj.mobile or vendor_phone
            vendor_email = vendor_obj.email or vendor_email
        else:
            vendor_profile_id = 1

    # 5b. Price on the server. The vendor's own price (or the package price) wins;
    #     the client's unit_price is only used when the server has no price at all.
    total_amount = 0.0
    order_items = []
    for item in order_in.items:
        unit_price = None
        if item.package_id:
            pkg_res = await db.execute(select(PackageModel.price).where(PackageModel.id == item.package_id))
            pkg_price = pkg_res.scalar_one_or_none()
            if pkg_price:
                unit_price = float(pkg_price)
        elif item.subcategory_id and resolved_vendor_id:
            unit_price = await _vendor_unit_price(db, resolved_vendor_id, item.subcategory_id)
        if unit_price is None:
            unit_price = item.unit_price
        total_amount += item.quantity * unit_price
        order_items.append(
            OrderItemModel(
                package_id=item.package_id,
                quantity=item.quantity,
                price=unit_price,
            )
        )

    # 6. Create Order
    new_order = OrderModel(
        customer_id=current_customer.id,
        vendor_id=resolved_vendor_id,
        vendor_profile_id=vendor_profile_id,
        booking_reference=f"HYD{uuid.uuid4().hex[:6].upper()}",
        status="PENDING",
        service_id=subcategory.id if subcategory else None,
        service_subcategory_id=subcategory.id if subcategory else None,
        service_category_id=subcategory.category_id if subcategory else None,
        booking_date=booking_date,
        booking_time=booking_time,
        service_address=service_address,
        latitude=address.latitude,
        longitude=address.longitude,
        total_amount=total_amount,
        final_amount=total_amount,
        customer_name=current_customer.full_name,
        customer_phone=current_customer.phone,
        customer_email=current_customer.email,
        vendor_name=vendor_name,
        vendor_phone=vendor_phone,
        vendor_email=vendor_email,
        service_name=package.name if package else (subcategory.name if subcategory else "General Service"),
        duration_minutes=package.duration_minutes if package else 60,
        special_instructions=order_in.special_instructions,
        material_option=order_in.material_option,
        vendor_notes=build_initial_assignment_meta(order_in.catalog_service_id),
    )

    db.add(new_order)
    await db.flush() # Get generated order ID

    # Associate and add items
    for item in order_items:
        item.order_id = new_order.id
        db.add(item)

    offer = await open_offer(db, new_order, vendor_obj)
    await db.commit()
    await db.refresh(new_order)

    # Push + SMS + WhatsApp to the vendor; they have 1 hour to accept.
    await notify_vendor_new_booking(vendor_obj, new_order, offer.expires_at, background_tasks)

    return {"message": "Order created successfully", "orderId": new_order.booking_reference, "status": "PENDING"}

class RejectBookingRequest(BaseModel):
    reason: Optional[str] = None


# Statuses where the vendor has accepted and may see the customer's contact details.
CONTACT_VISIBLE_STATUSES = ("ACCEPTED", "CONFIRMED", "IN_PROGRESS", "COMPLETED")


def _customer_details(order: OrderModel) -> dict:
    """Full customer details once accepted; name and area only before that."""
    if str(order.status or "").upper() in CONTACT_VISIBLE_STATUSES:
        return {
            "name": order.customer_name,
            "phone": order.customer_phone,
            "address": order.service_address,
            "latitude": float(order.latitude) if order.latitude is not None else None,
            "longitude": float(order.longitude) if order.longitude is not None else None,
            "details_visible": True,
        }
    return {
        "name": order.customer_name,
        "phone": None,
        "address": None,
        "area": area_from_address(order.service_address),
        "details_visible": False,
    }


@router.get("/vendor/offers/{order_id}")
async def get_booking_offer(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor),
):
    """
    What the vendor sees when they open the booking alert: service, time, area,
    price and how long they have to accept. Phone and address appear only after accepting.
    """
    order = (await db.execute(
        select(OrderModel).where(OrderModel.booking_reference == order_id)
    )).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Booking not found")
    offer = (await db.execute(
        select(BookingOffer)
        .where(BookingOffer.booking_id == order.id, BookingOffer.vendor_id == current_vendor.id)
        .order_by(BookingOffer.offered_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if not offer and order.vendor_id != current_vendor.id:
        raise HTTPException(status_code=404, detail="Booking not found")

    sub = await leads.get_active_subscription(db, current_vendor.id)
    still_yours = order.vendor_id == current_vendor.id
    can_respond = bool(
        still_yours and offer and offer.outcome == "pending"
        and offer.expires_at > datetime.utcnow() and order.status in ("PENDING", "new")
    )
    return {
        "orderId": order.booking_reference,
        "status": order.status if still_yours else "REASSIGNED",
        "offer_status": offer.outcome if offer else None,  # pending | accepted | declined | expired | cancelled
        "offered_at": _iso_utc(offer.offered_at) if offer else None,
        "expires_at": _iso_utc(offer.expires_at) if offer else None,
        "can_respond": can_respond,
        "service_name": order.service_name,
        "booking_date": order.booking_date.isoformat() if order.booking_date else None,
        "booking_time": order.booking_time.strftime("%I:%M %p") if order.booking_time else None,
        "total_amount": float(order.total_amount or 0),
        "material_option": order.material_option,
        "special_instructions": order.special_instructions,
        "customer": _customer_details(order) if still_yours else {"name": None, "details_visible": False},
        "leads_left": leads.leads_left(sub),  # null = unlimited
    }


@router.get("/vendor/leads")
async def get_my_leads(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor),
):
    """The vendor's lead balance on their current plan, plus recent lead history."""
    sub = await leads.get_active_subscription(db, current_vendor.id)
    plan = await leads.get_plan(db, sub) if sub else None
    rows = (await db.execute(
        select(VendorLeadHistory, OrderModel.booking_reference)
        .outerjoin(OrderModel, OrderModel.id == VendorLeadHistory.booking_id)
        .where(VendorLeadHistory.vendor_id == current_vendor.id)
        .order_by(VendorLeadHistory.created_at.desc(), VendorLeadHistory.id.desc())
        .limit(limit)
    )).all()
    unlimited = bool(sub and (sub.leads_total or 0) < 0)
    return {
        "has_active_plan": sub is not None,
        "plan_name": plan.name if plan else None,
        "plan_end_date": _iso_utc(sub.end_date) if sub else None,
        "unlimited": unlimited,
        "leads_total": None if unlimited or not sub else sub.leads_total,
        "leads_used": sub.leads_used if sub else 0,
        "leads_left": leads.leads_left(sub),  # null = unlimited
        "missed_uncharged": sub.missed_uncharged if sub else 0,
        "misses_per_lead": leads.MISSES_PER_LEAD,
        "history": [
            {
                "event": h.event,  # accepted | missed | missed_pair | missed_pair_no_balance
                "leads_charged": h.leads_charged,
                "leads_left": h.leads_left,
                "booking_reference": ref,
                "created_at": _iso_utc(h.created_at),
            }
            for h, ref in rows
        ],
    }


@router.put("/{order_id}/accept")
@limiter.limit("10/minute")
async def accept_booking(
    request: Request,
    order_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor),
):
    """
    Vendor accepts a pending booking within the time limit. Costs 1 lead.
    After this the vendor sees the customer's phone and address.
    """
    # Lock the booking so the timeout job can't move it while we accept.
    result = await db.execute(
        select(OrderModel).where(OrderModel.booking_reference == order_id).with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.vendor_id != current_vendor.id:
        raise HTTPException(status_code=403, detail="This booking is not assigned to you")
    if order.status not in ("PENDING", "new"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot accept booking with status {order.status}",
        )

    now = datetime.utcnow()
    offer = await get_pending_offer(db, order.id, current_vendor.id, lock=True)
    if offer and offer.expires_at <= now:
        # Time is up: pass it on now instead of waiting for the next timeout run.
        await handle_vendor_decline_or_timeout(
            db, order, declined_vendor_id=current_vendor.id,
            reason="Vendor did not accept within the time limit",
            background_tasks=background_tasks, is_timeout=True,
        )
        raise HTTPException(status_code=410, detail="The time to accept this booking has passed")

    try:
        _, left = await leads.charge_accept(db, current_vendor.id, order.id)
    except leads.NoLeadsLeft:
        await db.rollback()
        raise HTTPException(
            status_code=402,
            detail={
                "code": "NO_LEADS_LEFT",
                "message": "You have no leads left. Renew or upgrade your plan to accept bookings.",
            },
        )

    if offer:
        offer.outcome = "accepted"
        offer.responded_at = now
    order.status = "ACCEPTED"
    order.accepted_at = now
    order.confirmed_at = now
    order.vendor_name = current_vendor.business_name or order.vendor_name
    order.vendor_phone = current_vendor.mobile or order.vendor_phone
    await db.commit()
    await db.refresh(order)

    await notify_customer_vendor_accepted(
        db,
        order,
        current_vendor,
        background_tasks=background_tasks,
    )

    return {
        "message": "Booking accepted successfully",
        "orderId": order.booking_reference,
        "status": order.status,
        "leads_left": left,  # null = unlimited
        "customer": _customer_details(order),
    }


@router.put("/{order_id}/reject")
@limiter.limit("10/minute")
async def reject_booking(
    request: Request,
    order_id: str,
    body: RejectBookingRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor),
):
    """
    Vendor rejects a pending booking. Counts as a miss (every 2 misses cost
    1 lead). System reassigns to the next nearest eligible vendor with
    price <= booked amount, or marks unassigned.
    """
    result = await db.execute(
        select(OrderModel).where(OrderModel.booking_reference == order_id).with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.vendor_id != current_vendor.id:
        raise HTTPException(status_code=403, detail="This booking is not assigned to you")
    if order.status not in ("PENDING", "new"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject booking with status {order.status}",
        )

    outcome = await handle_vendor_decline_or_timeout(
        db,
        order,
        declined_vendor_id=current_vendor.id,
        reason=body.reason,
        background_tasks=background_tasks,
    )
    return outcome


@router.post("/process-pending-timeouts")
@limiter.limit("5/minute")
async def run_pending_booking_timeouts(
    request: Request,
    background_tasks: BackgroundTasks,
    current_admin=Depends(get_current_admin),
):
    """
    Admin-only manual run of the timeout job (it also runs every minute on its own):
    reassign bookings vendors did not accept in time.
    """
    processed = await process_pending_booking_timeouts(background_tasks)
    return {"processed": processed, "message": f"Processed {processed} timed-out bookings"}

@router.put("/{order_id}/cancel")
@limiter.limit("3/minute")
async def cancel_order(
    request: Request,
    order_id: str,
    reason: Optional[str] = Query(None, description="Reason for cancellation"),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer)
):
    """
    Cancel an existing order (Matches PDF Page 64).
    """
    query = select(OrderModel).where(
        OrderModel.booking_reference == order_id,
        OrderModel.customer_id == current_customer.id
    )
    result = await db.execute(query)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in CHANGEABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"A booking that is {str(order.status).lower()} cannot be cancelled",
        )

    order.status = "CANCELLED"
    order.cancellation_reason = (reason or "").strip() or "Cancelled by customer"
    order.cancelled_at = datetime.utcnow()
    order.cancelled_by = "customer"
    await close_pending_offers(db, order.id, "cancelled", "Customer cancelled the booking")
    await db.execute(delete(BookingLocationPing).where(BookingLocationPing.booking_id == order.id))
    await wallets.reverse_booking_payment(db, order)  # refund wallet money, release the coupon

    await db.commit()
    return {"message": "Your Order cancelled successfully"}

class RescheduleRequest(BaseModel):
    scheduled_at: datetime

@router.put("/{order_id}/reschedule")
@limiter.limit("3/minute")
async def reschedule_order(
    request: Request,
    order_id: str,
    body: Optional[RescheduleRequest] = None,
    scheduled_at: Optional[datetime] = Query(None, description="New date and time (ISO 8601)"),
    new_date: Optional[date] = Query(None, description="Legacy: new date"),
    new_time: Optional[time] = Query(None, description="Legacy: new time"),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer)
):
    """
    Reschedule a booking. Send scheduled_at (JSON body or query), or the legacy new_date + new_time.
    """
    target = body.scheduled_at if body else scheduled_at
    if target is not None:
        target_ist = _to_ist(target)
    elif new_date and new_time:
        target_ist = datetime.combine(new_date, new_time).replace(tzinfo=IST)
    else:
        raise HTTPException(status_code=422, detail="Provide scheduled_at (or new_date and new_time)")

    result = await db.execute(
        select(OrderModel).where(
            OrderModel.booking_reference == order_id,
            OrderModel.customer_id == current_customer.id
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in CHANGEABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"A booking that is {str(order.status).lower()} cannot be rescheduled",
        )
    if (order.reschedule_count or 0) >= MAX_RESCHEDULES:
        raise HTTPException(
            status_code=400,
            detail=f"This booking has already been rescheduled {MAX_RESCHEDULES} times",
        )
    if target_ist <= _now_ist():
        raise HTTPException(status_code=400, detail="New time must be in the future")

    order.booking_date = target_ist.date()
    order.booking_time = target_ist.time().replace(tzinfo=None)
    order.reschedule_count = (order.reschedule_count or 0) + 1

    await db.commit()
    return {
        "message": "Order rescheduled successfully",
        "orderId": order.booking_reference,
        "serviceDate": order.booking_date.strftime("%Y-%m-%d"),
        "serviceTime": order.booking_time.strftime("%I:%M %p"),
        "reschedule_count": order.reschedule_count,
    }

# --- Live tracking ----------------------------------------------------------
TRACKABLE_STATUSES = ("ACCEPTED", "IN_PROGRESS")
PING_FRESH_SECONDS = 180

def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None

async def _customer_booking(db: AsyncSession, order_id: str, customer: Customer) -> OrderModel:
    res = await db.execute(
        select(OrderModel).where(
            OrderModel.booking_reference == order_id,
            OrderModel.customer_id == customer.id,
        )
    )
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

async def _latest_ping(db: AsyncSession, booking_id: int) -> Optional[BookingLocationPing]:
    res = await db.execute(
        select(BookingLocationPing)
        .where(BookingLocationPing.booking_id == booking_id)
        .order_by(BookingLocationPing.recorded_at.desc(), BookingLocationPing.id.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()

@router.get("/{order_id}/tracking")
@limiter.limit("60/minute")
async def get_booking_tracking(
    request: Request,
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Booking status plus the vendor's live status, for the customer's tracking screen."""
    order = await _customer_booking(db, order_id, current_customer)
    status_upper = str(order.status or "").upper()
    trackable = status_upper in TRACKABLE_STATUSES
    ping = await _latest_ping(db, order.id) if trackable else None

    dest_lat = float(order.latitude) if order.latitude is not None else None
    dest_lng = float(order.longitude) if order.longitude is not None else None

    fresh = bool(
        ping and ping.recorded_at
        and (datetime.utcnow() - ping.recorded_at).total_seconds() <= PING_FRESH_SECONDS
    )
    if status_upper == "IN_PROGRESS":
        tracking_status = "arrived"
    elif status_upper == "ACCEPTED":
        tracking_status = "en_route" if fresh else "not_started"
    elif status_upper == "COMPLETED":
        tracking_status = "ended"
    elif status_upper in ("CANCELLED", "REJECTED"):
        tracking_status = "cancelled"
    else:
        tracking_status = "not_started"
    is_live = status_upper == "ACCEPTED" and fresh

    route = None
    if ping and dest_lat is not None and dest_lng is not None and status_upper == "ACCEPTED":
        route = estimate_route(float(ping.latitude), float(ping.longitude), dest_lat, dest_lng)

    return {
        "booking_id": order.booking_reference,
        "booking_code": order.booking_reference,
        "booking_status": status_upper.lower(),
        "tracking_status": tracking_status,
        "is_live": is_live,
        "destination_latitude": dest_lat,
        "destination_longitude": dest_lng,
        "destination_label": order.service_address,
        "professional_latitude": float(ping.latitude) if ping else None,
        "professional_longitude": float(ping.longitude) if ping else None,
        "professional_heading": ping.heading if ping else None,
        "professional_speed_kmh": ping.speed_kmh if ping else None,
        "last_ping_at": _iso_utc(ping.recorded_at) if ping else None,
        "distance_km": route["distance_km"] if route else None,
        "eta_minutes": route["eta_minutes"] if route else None,
        "bearing_degrees": route["bearing_degrees"] if route else None,
        "started_at": _iso_utc(order.started_at.replace(tzinfo=None)) if order.started_at else None,
        "arrived_at": None,
        "ended_at": _iso_utc(
            (order.completed_at or order.cancelled_at).replace(tzinfo=None)
        ) if (order.completed_at or order.cancelled_at) else None,
    }

@router.get("/{order_id}/location-pings")
@limiter.limit("60/minute")
async def list_location_pings(
    request: Request,
    order_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Vendor's recent location trail, oldest first. Empty unless the booking is active."""
    order = await _customer_booking(db, order_id, current_customer)
    if str(order.status or "").upper() not in TRACKABLE_STATUSES:
        return []
    res = await db.execute(
        select(BookingLocationPing)
        .where(BookingLocationPing.booking_id == order.id)
        .order_by(BookingLocationPing.recorded_at.desc(), BookingLocationPing.id.desc())
        .limit(limit)
    )
    pings = list(reversed(res.scalars().all()))
    return [
        {
            "id": str(p.id),
            "latitude": float(p.latitude),
            "longitude": float(p.longitude),
            "accuracy_m": p.accuracy_m,
            "heading": p.heading,
            "speed_kmh": p.speed_kmh,
            "recorded_at": _iso_utc(p.recorded_at),
            "source": p.source or "gps",
        }
        for p in pings
    ]

class LocationPingRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    accuracy_m: Optional[float] = Field(None, ge=0)
    heading: Optional[float] = Field(None, ge=0, le=360)
    speed_kmh: Optional[float] = Field(None, ge=0, le=300)
    source: Literal["gps", "network", "manual"] = "gps"

@router.post("/{order_id}/location-ping")
@limiter.limit("30/minute")
async def post_location_ping(
    request: Request,
    order_id: str,
    ping_in: LocationPingRequest,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor),
):
    """Vendor app reports its position while travelling to / working on an accepted booking."""
    res = await db.execute(select(OrderModel).where(OrderModel.booking_reference == order_id))
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.vendor_id != current_vendor.id:
        raise HTTPException(status_code=403, detail="This booking is not assigned to you")
    if str(order.status or "").upper() not in TRACKABLE_STATUSES:
        raise HTTPException(status_code=400, detail="Location can only be shared for an accepted booking")

    db.add(BookingLocationPing(booking_id=order.id, vendor_id=current_vendor.id, **ping_in.model_dump()))
    await db.commit()
    return {"message": "Location recorded"}

FEEDBACK_CASHBACK = 5  # rupees, fixed

class FeedbackRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    text: Optional[str] = Field(None, max_length=1000)

@router.post("/{order_id}/feedback")
@limiter.limit("10/minute")
async def add_booking_feedback(
    request: Request,
    order_id: str,
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Rating and comment for a completed booking. Credits a fixed cashback to the wallet, once."""
    order = await _customer_booking(db, order_id, current_customer)
    if str(order.status or "").upper() != "COMPLETED":
        raise HTTPException(status_code=400, detail="Feedback can only be given for a completed booking")

    already = await db.execute(select(BookingFeedback.id).where(BookingFeedback.booking_id == order.id))
    if already.first():
        raise HTTPException(status_code=409, detail="Feedback was already submitted for this booking")

    feedback = BookingFeedback(
        booking_id=order.id, customer_id=current_customer.id, vendor_id=order.vendor_id,
        rating=body.rating, comment=(body.text or "").strip() or None,
        cashback_amount=FEEDBACK_CASHBACK,
    )
    db.add(feedback)
    try:
        await db.flush()
    except IntegrityError:  # two submissions raced; the unique booking_id wins
        await db.rollback()
        raise HTTPException(status_code=409, detail="Feedback was already submitted for this booking")

    if order.vendor_id:
        vendor = (await db.execute(
            select(Vendor).where(Vendor.id == order.vendor_id).with_for_update()
        )).scalar_one_or_none()
        if vendor:
            count = int(vendor.total_reviews or 0)
            avg = float(vendor.avg_rating or 0)
            vendor.avg_rating = round((avg * count + body.rating) / (count + 1), 2)
            vendor.total_reviews = count + 1

    await wallets.credit(
        db, current_customer.id, FEEDBACK_CASHBACK, "Cashback for your feedback",
        booking_id=order.id, reference=f"feedback:{order.id}",
    )
    await db.commit()
    return {
        "message": "Thanks for your feedback",
        "feedback_id": feedback.id,
        "rating": body.rating,
        "cashback_amount": FEEDBACK_CASHBACK,
    }

class PriceEstimateRequest(BaseModel):
    vendor_id: int
    service_id: int  # sub-category id, as used by the booking flow
    quantity: int = Field(1, ge=1, le=20)
    material_option: Optional[Literal["with", "without"]] = None
    coupon_code: Optional[str] = None

@router.post("/price-estimate")
@limiter.limit("30/minute")
async def price_estimate(
    request: Request,
    est_in: PriceEstimateRequest,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """
    Server-side price for a vendor + service. Uses the same price as POST /orders/,
    so the amount shown before booking is the amount that is charged.
    """
    vendor = await db.get(Vendor, est_in.vendor_id)
    if not vendor or vendor.status != "active":
        raise HTTPException(status_code=404, detail="Vendor not found")
    unit_price = await _vendor_unit_price(db, vendor.id, est_in.service_id)
    if unit_price is None:
        raise HTTPException(status_code=404, detail="This vendor has no price for the selected service")

    subtotal = round(unit_price * est_in.quantity, 2)
    coupon_code = (est_in.coupon_code or "").strip() or None
    return {
        "vendor_id": vendor.id,
        "service_id": est_in.service_id,
        "quantity": est_in.quantity,
        "unit_price": unit_price,
        "subtotal": subtotal,
        "discount": 0.0,
        "total_amount": subtotal,
        "currency": "INR",
        "material_option": est_in.material_option,
        "coupon_applied": False,
        "coupon_message": "Coupons are not available yet" if coupon_code else None,
    }

@router.post("/order/calculation", response_model=CalculationResponse)
@limiter.limit("15/minute")
async def calculate_order_amount(
    request: Request,
    calc_in: CalculationRequest,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer)
):
    """
    Calculate order pricing details, taxes, discounts, and royalty metrics (Matches external calculations endpoint).
    """
    # Calculate sum of package amounts
    package_amount = 0.0
    for pkg in calc_in.packages:
        qty = int(pkg.quantity)
        amt = float(pkg.packageAmount)
        package_amount += amt * qty

    # Fixed pricing constants based on the analyzed schema
    platform_charge = 0.0
    platform_charge_paid = 15.0
    visiting_charge = 0.0
    visiting_charge_paid = 0.0

    # Calculate tax components
    gst_on_charges = round(platform_charge_paid * 0.18, 2)
    # package amount is tax inclusive (18%)
    included_gst = round(package_amount - (package_amount / 1.18), 2)
    # GST in output represents platform charge + its GST
    gst = platform_charge_paid + gst_on_charges

    # Calculate discounts
    royal_discount = round(0.05 * package_amount + 0.06 * platform_charge_paid, 2)
    maximum_discount = round(0.035 * package_amount - 0.009 * platform_charge_paid, 2)

    # Calculate Revenue
    royal_revenue = round(0.125 * package_amount - 0.017 * platform_charge_paid, 2)

    # Calculate total payable amount (rounded to nearest integer)
    total_amount = round(package_amount - royal_discount + gst)

    # Resolve customer ID from authenticated token
    visit_id_prefix = f"HYDCX{str(current_customer.id).zfill(5)}"
    referral_count = 0

    # Generate a deterministic or randomized 4-digit code (e.g. 0313)
    rand_seq = random.randint(100, 9999)
    visit_id = f"{visit_id_prefix}OCV{rand_seq:04d}"

    return CalculationResponse(
        packageAmount=package_amount,
        platformCharge=platform_charge,
        platformChargePaid=platform_charge_paid,
        visitingCharge=visiting_charge,
        visitingChargePaid=visiting_charge_paid,
        GST=gst,
        gstOnCharges=gst_on_charges,
        includedGST=included_gst,
        totalAmount=total_amount,
        memberSaving=0,
        maximumDiscount=maximum_discount,
        influencerDiscount=0.0,
        Am5RoyalDiscount=royal_discount,
        Am5ROYALRevenue=royal_revenue,
        referralCount=referral_count,
        visitId=visit_id
    )

def _parse_ids(input_str: Optional[str]) -> List[int]:
    if not input_str:
        return []
    input_str = input_str.strip()
    if not input_str:
        return []
    if input_str.startswith('[') and input_str.endswith(']'):
        try:
            val = json.loads(input_str)
            if isinstance(val, list):
                return [int(x) for x in val]
            return [int(val)]
        except Exception:
            pass
    # Comma-separated fallback
    parts = input_str.split(',')
    res = []
    for p in parts:
        p = p.strip()
        if p.isdigit():
            res.append(int(p))
    return res

@router.get("/availableServiceProviderSlots", response_model=List[str])
@limiter.limit("30/minute")
async def get_available_service_provider_slots(
    request: Request,
    professionId: Optional[int] = Query(None),
    serviceIds: Optional[str] = Query(None),
    packageIds: Optional[str] = Query(None),
    addressId: Optional[str] = Query(None),
    serviceDate: Optional[str] = Query(None),
    customerId: Optional[str] = Query(None),
    vendor_id: Optional[int] = Query(None, description="Only this vendor's availability"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get available service provider slots for a given date, profession, services, and address.
    """
    # Parse lists of IDs
    service_id_list = _parse_ids(serviceIds)
    package_id_list = _parse_ids(packageIds)

    # 1. Parse serviceDate (default to today in IST timezone)
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(timezone.utc).astimezone(ist)

    target_date = now_ist.date()
    if serviceDate:
        try:
            target_date = datetime.strptime(serviceDate.strip(), "%Y-%m-%d").date()
        except Exception:
            pass

    # 2. Eligible vendors offering the requested subcategories/category
    #    (vendors -> vendor_services -> sub_categories).
    where_clauses = [
        "UPPER(v.status) IN ('APPROVED', 'ACTIVE')",
        "vs.is_active = True",
    ]
    query_params = {}
    if vendor_id:
        where_clauses.append("v.id = :vendor_id")
        query_params["vendor_id"] = vendor_id

    if service_id_list:
        where_clauses.append("vs.sub_category_id IN :service_ids")
        query_params["service_ids"] = service_id_list
    elif professionId:
        where_clauses.append("sub.main_category_id = :profession_id")
        query_params["profession_id"] = int(professionId)

    vendors_stmt = text(f"""
        SELECT DISTINCT v.id AS vendor_id
        FROM vendors v
        JOIN vendor_services vs ON vs.vendor_id = v.id
        JOIN sub_categories sub ON sub.id = vs.sub_category_id
        WHERE {" AND ".join(where_clauses)}
    """)
    if service_id_list:
        vendors_stmt = vendors_stmt.bindparams(bindparam("service_ids", expanding=True))

    # Each optional query runs in a savepoint so a failure cannot abort the whole transaction.
    try:
        async with db.begin_nested():
            eligible_vendors = (await db.execute(vendors_stmt, query_params)).fetchall()
    except Exception:
        eligible_vendors = []

    available_slots = set()
    default_slots = ["08:30-11:30", "11:30-14:30", "14:30-17:30"]

    def _slot_bounds(slot: str):
        start, end = slot.split('-')
        return (
            datetime.strptime(start.strip(), "%H:%M").time(),
            datetime.strptime(end.strip(), "%H:%M").time(),
        )

    # Gather available slots across all matched vendors
    for vendor in eligible_vendors:
        # vendor_availability holds the vendor's working windows (day_of_week: 0 = Monday)
        try:
            async with db.begin_nested():
                win_res = await db.execute(
                    text("""
                        SELECT start_time, end_time, is_available FROM vendor_availability
                        WHERE vendor_id = :vendor_id AND day_of_week = :dow
                    """),
                    {"vendor_id": vendor.vendor_id, "dow": target_date.weekday()},
                )
                windows = win_res.fetchall()
        except Exception:
            windows = []

        open_windows = [
            (w.start_time, w.end_time)
            for w in windows
            if w.is_available and w.start_time and w.end_time
        ]
        if windows and not open_windows:
            continue  # vendor marked this day as unavailable

        if open_windows:
            vendor_slots = [
                slot for slot in default_slots
                if any(ws <= _slot_bounds(slot)[0] and _slot_bounds(slot)[1] <= we for ws, we in open_windows)
            ]
        else:
            vendor_slots = default_slots  # no schedule set: assume the standard slots

        # Filter out booked/blocked slots
        for slot in vendor_slots:
            try:
                async with db.begin_nested():
                    booking_res = await db.execute(
                        text("""
                            SELECT booked_count, held_count, total_capacity, status
                            FROM booking_vendor_availability
                            WHERE vendor_id = :vendor_id AND date = :date AND time_slot = :slot
                        """),
                        {"vendor_id": vendor.vendor_id, "date": target_date, "slot": slot}
                    )
                    booking_info = booking_res.fetchone()
                    if booking_info:
                        booked, held, capacity, status = booking_info
                        if status == 'BLOCKED' or (booked + held) >= capacity:
                            continue  # No capacity left

                    hold_res = await db.execute(
                        text("""
                            SELECT COUNT(*) FROM slot_hold
                            WHERE vendor_id = :vendor_id AND date = :date AND time_slot = :slot
                              AND status = 'HELD' AND expires_at > :now
                        """),
                        {"vendor_id": vendor.vendor_id, "date": target_date, "slot": slot, "now": datetime.now(timezone.utc)}
                    )
                    active_holds = hold_res.scalar()
                    if active_holds > 0:
                        total_cap = booking_info[2] if booking_info else 1
                        booked_cnt = booking_info[0] if booking_info else 0
                        if (booked_cnt + active_holds) >= total_cap:
                            continue

                available_slots.add(slot)
            except Exception:
                available_slots.add(slot)

    # 4. Final filter of slots (e.g. filter out past slots if date is today)
    final_slots = list(available_slots if (available_slots or eligible_vendors) else default_slots)

    if target_date == now_ist.date():
        filtered_slots = []
        for slot in final_slots:
            parts = slot.split('-')
            if len(parts) == 2:
                try:
                    slot_start_time = datetime.strptime(parts[0].strip(), "%H:%M").time()
                    slot_dt = datetime.combine(target_date, slot_start_time).replace(tzinfo=ist)

                    # Buffer: min_advance_hours (or fallback to 2 hours)
                    min_buffer_hours = 2.0
                    if slot_dt > now_ist + timedelta(hours=min_buffer_hours):
                        filtered_slots.append(slot)
                except Exception:
                    filtered_slots.append(slot)
            else:
                filtered_slots.append(slot)
        final_slots = filtered_slots

    # Sort slots chronologically
    try:
        final_slots = sorted(list(final_slots), key=lambda s: s.split('-')[0])
    except Exception:
        pass

    return final_slots
from pydantic import BaseModel
from typing import Optional
from app.models.subscriptions import VendorWallet, WalletTransaction, VendorSubscription, SubscriptionPlan
from app.dependencies.auth import get_current_vendor

class GenerateOtpRequest(BaseModel):
    order_id: str

class OtpResponse(BaseModel):
    start_otp: str
    end_otp: str

class StartServiceRequest(BaseModel):
    order_id: str
    start_otp: str

class CompleteServiceRequest(BaseModel):
    order_id: str
    end_otp: str

def generate_random_otp() -> str:
    return str(random.randint(100000, 999999))

@router.post("/generate-otps", response_model=OtpResponse)
async def generate_otps(
    request: GenerateOtpRequest,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer)
):
    # Only customer can generate OTPs for their order
    query = select(OrderModel).where(
        OrderModel.booking_reference == request.order_id,
        OrderModel.customer_id == current_customer.id
    )
    res = await db.execute(query)
    order = res.scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if not order.start_otp or not order.end_otp:
        order.start_otp = generate_random_otp()
        order.end_otp = generate_random_otp()
        await db.commit()
        
    return OtpResponse(start_otp=order.start_otp, end_otp=order.end_otp)
@router.post("/start")
async def start_service(
    request: StartServiceRequest,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor)
):
    query = select(OrderModel).where(OrderModel.booking_reference == request.order_id)
    res = await db.execute(query)
    order = res.scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.vendor_id != current_vendor.id:
        raise HTTPException(status_code=403, detail="This booking is not assigned to you")
    if order.status not in ("ACCEPTED", "CONFIRMED"):
        raise HTTPException(status_code=400, detail=f"Cannot start service from status {order.status}")
        
    if order.start_otp != request.start_otp:
        raise HTTPException(status_code=400, detail="Invalid Start OTP")
        
    order.status = "IN_PROGRESS"
    order.started_at = datetime.utcnow()  # column is timestamp without time zone
    await db.commit()
    
    return {"message": "Service started successfully"}

@router.post("/complete")
async def complete_service(
    request: CompleteServiceRequest,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor)
):
    query = select(OrderModel).where(OrderModel.booking_reference == request.order_id)
    res = await db.execute(query)
    order = res.scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.vendor_id != current_vendor.id:
        raise HTTPException(status_code=403, detail="This booking is not assigned to you")
    if order.status != "IN_PROGRESS":
        raise HTTPException(status_code=400, detail=f"Cannot complete service from status {order.status}")

    if order.end_otp != request.end_otp:
        raise HTTPException(status_code=400, detail="Invalid End OTP")

    # Members pay per lead when they accept, so nothing is charged here.
    order.status = "COMPLETED"
    order.completed_at = datetime.utcnow()  # column is timestamp without time zone
    await db.execute(delete(BookingLocationPing).where(BookingLocationPing.booking_id == order.id))
    await db.execute(
        update(BookingPayment)
        .where(BookingPayment.booking_id == order.id, BookingPayment.status == "pending")
        .values(status="captured")
    )
    await db.commit()
    
    return {
        "message": "Service completed successfully",
        "commission_deducted": 0.0,  # kept for older vendor app builds
    }

class VendorOrderResponse(BaseModel):
    id: int
    booking_reference: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    service_address: Optional[str] = None
    service_name: Optional[str] = None
    booking_date: Optional[date] = None
    booking_time: Optional[time] = None
    status: str
    total_amount: Optional[float] = None
    start_otp: Optional[str] = None
    end_otp: Optional[str] = None

    class Config:
        from_attributes = True

@router.get("/vendor/me", response_model=List[VendorOrderResponse])
async def get_vendor_orders(
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor)
):
    query_str = """
        SELECT 
            b.id,
            COALESCE(b.booking_reference, 'HYD' || LPAD(b.id::text, 5, '0')) as booking_reference,
            c.full_name as customer_name,
            c.phone as customer_phone,
            b.booking_address as service_address,
            COALESCE(b.service_name, sub.name, 'General Service') as service_name,
            COALESCE(b.booking_date, DATE(b.scheduled_date)) as booking_date,
            COALESCE(b.booking_time, b.scheduled_date::time) as booking_time,
            b.booking_status as status,
            b.total_amount,
            b.start_otp,
            b.end_otp
        FROM bookings b
        LEFT JOIN customers c ON b.customer_id = c.id
        LEFT JOIN vendor_services vs ON b.vendor_service_id = vs.id
        LEFT JOIN sub_categories sub ON vs.sub_category_id = sub.id
        WHERE b.vendor_id = :vendor_id
    """
    
    where_clauses = []
    if status_filter == "upcoming":
        where_clauses.append("b.booking_status IN ('new', 'ACCEPTED', 'PENDING')")
    elif status_filter == "ongoing":
        where_clauses.append("b.booking_status = 'IN_PROGRESS'")
    elif status_filter == "completed":
        where_clauses.append("b.booking_status = 'COMPLETED'")
        
    if where_clauses:
        query_str += " AND " + " AND ".join(where_clauses)
        
    query_str += " ORDER BY b.created_at DESC"
    
    res = await db.execute(text(query_str), {"vendor_id": current_vendor.id})
    orders = res.fetchall()
    
    result = []
    for o in orders:
        # Phone and address only after the vendor accepts.
        visible = str(o.status or "").upper() in CONTACT_VISIBLE_STATUSES
        result.append({
            "id": o.id,
            "booking_reference": o.booking_reference,
            "customer_name": o.customer_name,
            "customer_phone": o.customer_phone if visible else None,
            "service_address": o.service_address if visible else area_from_address(o.service_address),
            "service_name": o.service_name,
            "booking_date": o.booking_date,
            "booking_time": o.booking_time,
            "status": o.status or 'pending',
            "total_amount": float(o.total_amount) if o.total_amount else 0.0,
            # The customer reads these codes out to the vendor; never send them to the vendor.
            "start_otp": None,
            "end_otp": None,
        })
        
    return result
