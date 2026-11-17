from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.freelancer import Freelancer
from freelance_api.dependencies import get_current_freelancer
from freelance_api.models import FreelancerSetting
from freelance_api.schemas import (
    ApiResponse,
    FreelancerSettingsResponse,
    PrivacyPreferences,
    NotificationPreferences,
    SecurityPreferences,
    UpdatePrivacyPreferencesRequest,
    UpdateNotificationPreferencesRequest,
    UpdateSecurityPreferencesRequest,
)

router = APIRouter(tags=["Freelancer Settings & Preferences"])

async def _get_or_create_settings(db: AsyncSession, freelancer_id: int) -> FreelancerSetting:
    stmt = select(FreelancerSetting).where(FreelancerSetting.freelancer_id == freelancer_id)
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()
    if not setting:
        setting = FreelancerSetting(
            freelancer_id=freelancer_id,
            privacy_preferences={
                "show_profile_in_directory": True,
                "allow_marketing_contact": True,
                "share_activity_status": True,
            },
            notification_preferences={
                "push_notifications": True,
                "email_notifications": True,
                "sms_notifications": True,
                "referral_alerts": True,
                "payout_alerts": True,
            },
            security_preferences={
                "two_factor_enabled": False,
                "login_alerts": True,
            }
        )
        db.add(setting)
        await db.commit()
        await db.refresh(setting)
    return setting

@router.get("/freelancer/settings", response_model=ApiResponse[FreelancerSettingsResponse])
async def get_settings(
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Load saved user preferences."""
    setting = await _get_or_create_settings(db, current_freelancer.id)
    return ApiResponse(
        success=True,
        message="Settings retrieved successfully",
        data=FreelancerSettingsResponse(
            privacy=PrivacyPreferences(**(setting.privacy_preferences or {})),
            notifications=NotificationPreferences(**(setting.notification_preferences or {})),
            security=SecurityPreferences(**(setting.security_preferences or {}))
        )
    )


@router.patch("/freelancer/settings/privacy", response_model=ApiResponse[PrivacyPreferences])
async def update_privacy(
    req: UpdatePrivacyPreferencesRequest,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Save privacy settings."""
    setting = await _get_or_create_settings(db, current_freelancer.id)
    current_priv = dict(setting.privacy_preferences or {})
    for k, v in req.model_dump(exclude_unset=True).items():
        current_priv[k] = v

    setting.privacy_preferences = current_priv
    await db.commit()
    await db.refresh(setting)

    return ApiResponse(
        success=True,
        message="Privacy preferences updated successfully",
        data=PrivacyPreferences(**setting.privacy_preferences)
    )


@router.patch("/freelancer/settings/notifications", response_model=ApiResponse[NotificationPreferences])
async def update_notifications(
    req: UpdateNotificationPreferencesRequest,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Save notification choices."""
    setting = await _get_or_create_settings(db, current_freelancer.id)
    current_notif = dict(setting.notification_preferences or {})
    for k, v in req.model_dump(exclude_unset=True).items():
        current_notif[k] = v

    setting.notification_preferences = current_notif
    await db.commit()
    await db.refresh(setting)

    return ApiResponse(
        success=True,
        message="Notification preferences updated successfully",
        data=NotificationPreferences(**setting.notification_preferences)
    )


@router.patch("/freelancer/settings/security", response_model=ApiResponse[SecurityPreferences])
async def update_security(
    req: UpdateSecurityPreferencesRequest,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Update supported security options."""
    setting = await _get_or_create_settings(db, current_freelancer.id)
    current_sec = dict(setting.security_preferences or {})
    for k, v in req.model_dump(exclude_unset=True).items():
        current_sec[k] = v

    setting.security_preferences = current_sec
    await db.commit()
    await db.refresh(setting)

    return ApiResponse(
        success=True,
        message="Security preferences updated successfully",
        data=SecurityPreferences(**setting.security_preferences)
    )

