import firebase_admin
from firebase_admin import messaging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user_location import User

async def _store_notification(user_id: int, title: str, body: str, data: dict, push_status: str) -> None:
    """Keep a copy for the in-app notification list. Uses its own session and never raises."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.notification import Notification
        data = data or {}
        async with AsyncSessionLocal() as session:
            session.add(Notification(
                user_id=user_id,
                notification_type=str(data.get("type") or "system")[:30],
                title=(title or "")[:200],
                body=body or "",
                booking_ref=(str(data["booking_id"])[:40] if data.get("booking_id") else None),
                data=data or None,
                push_status=push_status,
            ))
            await session.commit()
    except Exception as e:
        print(f"Could not store notification for user {user_id}: {e}")


async def send_push_notification(user_id: int, db: AsyncSession, title: str, body: str, data: dict = None):
    """
    Sends a push notification to a specific user's registered FCM token.
    """
    user_query = await db.execute(select(User).where(User.id == user_id))
    user = user_query.scalar_one_or_none()
    
    fcm_token = user.fcm_token if user else None
    
    # Fallback to DeviceInstallation if User.fcm_token is not set
    if not fcm_token and user_id:
        from app.models.device import DeviceInstallation
        device_query = await db.execute(
            select(DeviceInstallation)
            .where(DeviceInstallation.user_id == user_id, DeviceInstallation.fcm_token.is_not(None))
            .order_by(DeviceInstallation.last_active_at.desc())
        )
        device = device_query.scalars().first()
        if device:
            fcm_token = device.fcm_token

    if not fcm_token:
        print(f"No FCM token found for user {user_id}")
        await _store_notification(user_id, title, body, data, "no_token")
        return False
        
    try:
        # 2. Construct the message
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data if data else {},
            token=fcm_token,
        )
        
        # 3. Send the message
        response = messaging.send(message)
        print(f"Successfully sent push notification to user {user_id}. Message ID: {response}")
        await _store_notification(user_id, title, body, data, "sent")
        return True
    except Exception as e:
        print(f"Failed to send push notification to user {user_id}: {e}")
        await _store_notification(user_id, title, body, data, "failed")
        return False

async def send_user_push_notification(user_id: int, title: str, body: str, data: dict = None):
    """
    Helper to send push notification using a fresh DB session (ideal for background tasks).
    """
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        return await send_push_notification(user_id, session, title, body, data)

