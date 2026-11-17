import datetime

from sqlalchemy import Column, String, BigInteger, DateTime, ForeignKey

from app.db.base_class import Base


class BookingCall(Base):
    """A masked phone call between a booking's customer and vendor, placed through Smartflo."""
    __tablename__ = "booking_calls"

    id = Column(BigInteger, primary_key=True, index=True)
    booking_id = Column(BigInteger, ForeignKey("bookings.id"), index=True, nullable=False)
    initiator_user_id = Column(BigInteger, nullable=False)
    callee_user_id = Column(BigInteger, nullable=False)
    status = Column(String(15), default="ringing")  # ringing | answered | ended | failed
    provider_ref = Column(String(100), nullable=True)
    error_message = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    answered_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    end_reason = Column(String(30), nullable=True)
