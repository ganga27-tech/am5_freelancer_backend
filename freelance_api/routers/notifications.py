from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func, update, delete
from datetime import datetime

from app.db.session import get_db
from app.models.freelancer import Freelancer
from freelance_api.dependencies import get_current_freelancer
from freelance_api.models import FreelancerNotification, FreelancerDeviceToken
from freelance_api.schemas import (
    ApiResponse,
    PaginatedData,
    NotificationItemResponse,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
)

router = APIRouter(tags=["Freelancer Notifications"])

@router.get("/freelancer/notifications", response_model=ApiResponse[PaginatedData[NotificationItemResponse]])
async def list_notifications(
    status_filter: Optional[str] = Query("all", alias="status", description="all, read, unread"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Return notifications for authenticated freelancer only (pagination & status filter)."""
    conditions = [FreelancerNotification.freelancer_id == current_freelancer.id]

    if status_filter == "read":
        conditions.append(FreelancerNotification.is_read.is_(True))
    elif status_filter == "unread":
        conditions.append(FreelancerNotification.is_read.is_(False))

    count_stmt = select(func.count(FreelancerNotification.id)).where(and_(*conditions))
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0

    unread_stmt = select(func.count(FreelancerNotification.id)).where(
        and_(
            FreelancerNotification.freelancer_id == current_freelancer.id,
            FreelancerNotification.is_read.is_(False)
        )
    )
    unread_res = await db.execute(unread_stmt)
    unread_count = unread_res.scalar() or 0

    stmt = (
        select(FreelancerNotification)
        .where(and_(*conditions))
        .order_by(desc(FreelancerNotification.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()

    items = [
        NotificationItemResponse(
            notificationId=r.notification_id,
            title=r.title,
            body=r.body,
            type=r.type,
            referenceId=r.reference_id,
            deepLink=r.deep_link,
            isRead=r.is_read,
            createdAt=r.created_at.isoformat() + "Z"
        )
        for r in rows
    ]

    return ApiResponse(
        success=True,
        message="Notifications retrieved",
        data=PaginatedData(
            items=items,
            page=page,
            limit=limit,
            total=total,
            hasMore=(page * limit) < total,
            unreadCount=unread_count
        )
    )


@router.get("/freelancer/notifications/unread-count", response_model=ApiResponse[dict])
async def get_unread_count(
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Return unread notification count for authenticated freelancer."""
    stmt = select(func.count(FreelancerNotification.id)).where(
        and_(
            FreelancerNotification.freelancer_id == current_freelancer.id,
            FreelancerNotification.is_read.is_(False)
        )
    )
    res = await db.execute(stmt)
    count = res.scalar() or 0

    return ApiResponse(
        success=True,
        message="Unread count retrieved",
        data={"unreadCount": count}
    )


@router.patch("/freelancer/notifications/{notificationId}/read", response_model=ApiResponse[dict])
async def mark_notification_read(
    notificationId: str,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Mark one notification as read only if it belongs to authenticated freelancer."""
    stmt = select(FreelancerNotification).where(
        and_(
            FreelancerNotification.notification_id == notificationId,
            FreelancerNotification.freelancer_id == current_freelancer.id
        )
    )
    res = await db.execute(stmt)
    notif = res.scalar_one_or_none()

    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    now = datetime.utcnow()
    notif.is_read = True
    notif.read_at = now
    await db.commit()

    return ApiResponse(
        success=True,
        message="Notification marked as read",
        data={
            "notificationId": notif.notification_id,
            "isRead": True,
            "readAt": now.isoformat() + "Z"
        }
    )


@router.patch("/freelancer/notifications/read-all", response_model=ApiResponse[dict])
async def mark_all_notifications_read(
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Mark all notifications as read for authenticated freelancer."""
    now = datetime.utcnow()
    stmt = (
        update(FreelancerNotification)
        .where(
            and_(
                FreelancerNotification.freelancer_id == current_freelancer.id,
                FreelancerNotification.is_read.is_(False)
            )
        )
        .values(is_read=True, read_at=now)
    )
    result = await db.execute(stmt)
    await db.commit()

    return ApiResponse(
        success=True,
        message="All notifications marked as read",
        data={"updatedCount": result.rowcount}
    )


@router.post("/freelancer/notifications/devices", response_model=ApiResponse[DeviceRegisterResponse], status_code=status.HTTP_201_CREATED)
async def register_device(
    req: DeviceRegisterRequest,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Register or update push token for push notifications."""
    device_id = f"dev_{current_freelancer.id}_{req.platform.lower()}"

    # Upsert token
    stmt = select(FreelancerDeviceToken).where(
        and_(
            FreelancerDeviceToken.freelancer_id == current_freelancer.id,
            FreelancerDeviceToken.device_id == device_id
        )
    )
    res = await db.execute(stmt)
    token_entry = res.scalar_one_or_none()

    if token_entry:
        token_entry.device_token = req.deviceToken
        token_entry.app_version = req.appVersion
        token_entry.updated_at = datetime.utcnow()
    else:
        token_entry = FreelancerDeviceToken(
            freelancer_id=current_freelancer.id,
            device_id=device_id,
            platform=req.platform.lower().strip(),
            device_token=req.deviceToken,
            app_version=req.appVersion
        )
        db.add(token_entry)

    await db.commit()

    return ApiResponse(
        success=True,
        message="Device push token registered",
        data=DeviceRegisterResponse(
            status="registered",
            device_id=device_id
        )
    )


@router.delete("/freelancer/notifications/devices/{deviceId}", response_model=ApiResponse[dict])
async def unregister_device(
    deviceId: str,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Remove push token on logout or uninstall."""
    stmt = delete(FreelancerDeviceToken).where(
        and_(
            FreelancerDeviceToken.freelancer_id == current_freelancer.id,
            FreelancerDeviceToken.device_id == deviceId
        )
    )
    await db.execute(stmt)
    await db.commit()

    return ApiResponse(
        success=True,
        message="Device token removed successfully",
        data={"deviceId": deviceId, "status": "removed"}
    )

