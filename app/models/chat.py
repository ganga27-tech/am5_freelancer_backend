import datetime

from sqlalchemy import Column, String, BigInteger, Integer, DateTime, Text, ForeignKey

from app.db.base_class import Base


class ChatThread(Base):
    """One conversation per booking, between its customer and its vendor."""
    __tablename__ = "chat_threads"

    id = Column(BigInteger, primary_key=True, index=True)
    booking_id = Column(BigInteger, ForeignKey("bookings.id"), unique=True, nullable=False)
    customer_id = Column(BigInteger, index=True, nullable=False)
    vendor_id = Column(BigInteger, index=True, nullable=False)
    last_message_at = Column(DateTime, nullable=True, index=True)
    last_message_preview = Column(String(120), nullable=True)
    customer_unread = Column(Integer, default=0, nullable=False)
    vendor_unread = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(BigInteger, primary_key=True, index=True)
    thread_id = Column(BigInteger, ForeignKey("chat_threads.id"), index=True, nullable=False)
    sender_type = Column(String(10), nullable=False)  # customer | vendor
    sender_user_id = Column(BigInteger, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    read_at = Column(DateTime, nullable=True)
