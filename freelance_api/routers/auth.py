from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.freelancer import Freelancer
from freelance_api.dependencies import get_current_freelancer
from freelance_api.schemas import (
    ApiResponse,
    LoginRequest,
    RegisterRequest,
    ForgotPasswordRequest,
    VerifyOtpRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    AuthTokenResponse,
    RegistrationResponse,
    ChallengeResponse,
    OtpVerificationResponse,
)
from freelance_api.service import FreelanceService

router = APIRouter(tags=["Freelancer Authentication"])

@router.post("/login", response_model=ApiResponse[AuthTokenResponse])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Allow login using registered mobile number OR email and password."""
    try:
        freelancer, token = await FreelanceService.login(db, req.identifier, req.password)
        return ApiResponse(
            success=True,
            message="Login successful",
            data=AuthTokenResponse(
                access_token=token,
                token_type="bearer",
                user={
                    "user_id": freelancer.id,
                    "full_name": freelancer.full_name,
                    "mobile": freelancer.phone_number,
                    "email": freelancer.email,
                    "profile_status": freelancer.profile_status or "active"
                }
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred during login")


@router.post("/register", response_model=ApiResponse[RegistrationResponse], status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new freelancer account."""
    try:
        freelancer = await FreelanceService.register(
            db=db,
            full_name=req.full_name,
            mobile_number=req.mobile_number,
            email=req.email,
            password=req.password
        )
        return ApiResponse(
            success=True,
            message="Account registered successfully",
            data=RegistrationResponse(
                user_id=freelancer.id,
                registration_status="completed",
                verification_required=False,
                next_step="login"
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Registration failed: {str(e)}")


@router.post("/forgot-password", response_model=ApiResponse[ChallengeResponse])
async def forgot_password(req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Start recovery using registered mobile number or email."""
    try:
        challenge_id, expiry = await FreelanceService.request_password_reset(db, req.identifier)
        return ApiResponse(
            success=True,
            message="If an account exists, a verification code has been dispatched",
            data=ChallengeResponse(
                challenge_id=challenge_id,
                expiry_seconds=expiry,
                message="Verification code sent to registered contact"
            )
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process request")


@router.post("/verify-otp", response_model=ApiResponse[OtpVerificationResponse])
async def verify_otp(req: VerifyOtpRequest):
    """Verify registration or password-recovery OTP."""
    try:
        reset_token = await FreelanceService.verify_otp(req.challenge_id, req.otp, req.purpose)
        return ApiResponse(
            success=True,
            message="OTP verified successfully",
            data=OtpVerificationResponse(
                verified=True,
                reset_token=reset_token,
                message="Verification successful. You may now reset your password."
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/reset-password", response_model=ApiResponse[dict])
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Set a new password after successful recovery verification."""
    try:
        await FreelanceService.reset_password(db, req.reset_token, req.new_password)
        return ApiResponse(
            success=True,
            message="Password reset successfully. You can now log in with your new password.",
            data={"status": "success"}
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/change-password", response_model=ApiResponse[dict])
async def change_password(
    req: ChangePasswordRequest,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Change password while logged in."""
    try:
        await FreelanceService.change_password(db, current_freelancer, req.current_password, req.new_password)
        return ApiResponse(
            success=True,
            message="Password updated successfully",
            data={"status": "success"}
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

