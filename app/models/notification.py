import datetime

from sqlalchemy import Column, String, BigInteger, DateTime, Text, JSON

from app.db.base_class import Base


class Notification(Base):
    """An in-app notification. Every push the backend sends is also stored here."""
    __tablename__ = "user_notifications"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, index=True, nullable=False)
    notification_type = Column(String(30), default="system")
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False, default="")
    booking_ref = Column(String(40), nullable=True)
    data = Column(JSON, nullable=True)
    push_status = Column(String(15), default="pending")  # sent | failed | no_token
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
