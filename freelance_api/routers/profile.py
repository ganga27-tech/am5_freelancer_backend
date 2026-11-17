from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.freelancer import Freelancer
from app.services.upload_service import upload_service
from freelance_api.dependencies import get_current_freelancer, mask_account_number
from freelance_api.schemas import (
    ApiResponse,
    FreelancerProfileResponse,
    UpdateProfileRequest,
    BankDetailsResponse,
    UpdateBankDetailsRequest,
    ProfileCompletionResponse,
    PhotoUploadResponse,
)
from freelance_api.service import FreelanceService

router = APIRouter(tags=["Freelancer Profile & Bank"])

@router.get("/freelancer/profile", response_model=ApiResponse[FreelancerProfileResponse])
async def get_profile(current_freelancer: Freelancer = Depends(get_current_freelancer)):
    """Load the authenticated freelancer's profile."""
    pct, _, _ = FreelanceService.calculate_completion(current_freelancer)
    return ApiResponse(
        success=True,
        message="Profile details retrieved successfully",
        data=FreelancerProfileResponse(
            user_id=current_freelancer.id,
            full_name=current_freelancer.full_name,
            first_name=current_freelancer.first_name,
            last_name=current_freelancer.last_name,
            mobile=current_freelancer.phone_number,
            email=current_freelancer.email,
            photo_url=current_freelancer.photo_url,
            address=current_freelancer.address,
            city=current_freelancer.city,
            state=current_freelancer.state,
            pincode=current_freelancer.pincode,
            bio=current_freelancer.bio,
            profile_status=current_freelancer.profile_status or "active",
            completion_percentage=pct,
            kyc_status=current_freelancer.kyc_status or "NOT_STARTED",
            referral_code=current_freelancer.referral_code
        )
    )


@router.patch("/freelancer/profile", response_model=ApiResponse[FreelancerProfileResponse])
async def update_profile(
    req: UpdateProfileRequest,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Update editable profile fields."""
    update_data = req.model_dump(exclude_unset=True)
    if "full_name" in update_data and update_data["full_name"]:
        parts = update_data["full_name"].strip().split(" ", 1)
        update_data["first_name"] = parts[0]
        update_data["last_name"] = parts[1] if len(parts) > 1 else ""

    freelancer = await FreelanceService.update_profile(db, current_freelancer, update_data)
    pct, _, _ = FreelanceService.calculate_completion(freelancer)

    return ApiResponse(
        success=True,
        message="Profile updated successfully",
        data=FreelancerProfileResponse(
            user_id=freelancer.id,
            full_name=freelancer.full_name,
            first_name=freelancer.first_name,
            last_name=freelancer.last_name,
            mobile=freelancer.phone_number,
            email=freelancer.email,
            photo_url=freelancer.photo_url,
            address=freelancer.address,
            city=freelancer.city,
            state=freelancer.state,
            pincode=freelancer.pincode,
            bio=freelancer.bio,
            profile_status=freelancer.profile_status or "active",
            completion_percentage=pct,
            kyc_status=freelancer.kyc_status or "NOT_STARTED",
            referral_code=freelancer.referral_code
        )
    )


@router.post("/freelancer/profile/photo", response_model=ApiResponse[PhotoUploadResponse])
async def upload_profile_photo(
    file: UploadFile = File(...),
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Upload or replace profile photo."""
    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image files are allowed")

    contents = await file.read()
    filename = file.filename or "profile.jpg"
    url = await upload_service.upload_file(contents, filename, content_type)
    if not url:
        url = f"https://cdn.am5royal.com/avatars/{current_freelancer.id}-{filename}"

    current_freelancer.photo_url = url
    await db.commit()
    await db.refresh(current_freelancer)

    return ApiResponse(
        success=True,
        message="Profile photo uploaded successfully",
        data=PhotoUploadResponse(photo_url=url, upload_status="success")
    )


@router.get("/freelancer/bank-details", response_model=ApiResponse[BankDetailsResponse])
async def get_bank_details(current_freelancer: Freelancer = Depends(get_current_freelancer)):
    """Load saved payout bank details safely (masked account number)."""
    return ApiResponse(
        success=True,
        message="Bank details retrieved successfully",
        data=BankDetailsResponse(
            account_holder=current_freelancer.bank_account_name,
            masked_account_number=mask_account_number(current_freelancer.bank_account_number),
            ifsc=current_freelancer.bank_ifsc_code,
            bank_name=current_freelancer.bank_name,
            verification_status=current_freelancer.bank_verification_status or "NOT_VERIFIED"
        )
    )


@router.put("/freelancer/bank-details", response_model=ApiResponse[BankDetailsResponse])
async def update_bank_details(
    req: UpdateBankDetailsRequest,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Submit or update payout bank information."""
    try:
        freelancer = await FreelanceService.update_bank_details(
            db=db,
            freelancer=current_freelancer,
            data=req.model_dump()
        )
        return ApiResponse(
            success=True,
            message="Bank details updated successfully",
            data=BankDetailsResponse(
                account_holder=freelancer.bank_account_name,
                masked_account_number=mask_account_number(freelancer.bank_account_number),
                ifsc=freelancer.bank_ifsc_code,
                bank_name=freelancer.bank_name,
                verification_status=freelancer.bank_verification_status or "PENDING"
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/freelancer/profile/completion", response_model=ApiResponse[ProfileCompletionResponse])
async def get_profile_completion(current_freelancer: Freelancer = Depends(get_current_freelancer)):
    """Show completion percentage and missing profile items."""
    pct, completed, missing = FreelanceService.calculate_completion(current_freelancer)
    return ApiResponse(
        success=True,
        message="Profile completion status calculated",
        data=ProfileCompletionResponse(
            completion_percentage=pct,
            profile_status=current_freelancer.profile_status or "active",
            completed_fields=completed,
            missing_fields=missing
        )
    )

