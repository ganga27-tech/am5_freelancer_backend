import datetime

from sqlalchemy import Column, String, Integer, BigInteger, DateTime, ForeignKey, Index

from app.db.base_class import Base


class BookingOffer(Base):
    """One booking offered to one vendor. A booking gets a new row each time it moves to another vendor."""
    __tablename__ = "booking_offers"
    __table_args__ = (
        Index("ix_booking_offers_outcome_expires", "outcome", "expires_at"),
    )

    id = Column(BigInteger, primary_key=True, index=True)
    booking_id = Column(BigInteger, ForeignKey("bookings.id"), index=True, nullable=False)
    vendor_id = Column(BigInteger, ForeignKey("vendors.id"), index=True, nullable=False)
    subscription_id = Column(BigInteger, ForeignKey("vendor_subscriptions.id"), nullable=True)
    offered_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    responded_at = Column(DateTime, nullable=True)
    outcome = Column(String(15), default="pending", nullable=False)  # pending | accepted | declined | expired | cancelled
    reason = Column(String(300), nullable=True)


class VendorLeadHistory(Base):
    """Every change to a vendor's lead count, and every missed booking."""
    __tablename__ = "vendor_lead_history"

    id = Column(BigInteger, primary_key=True, index=True)
    vendor_id = Column(BigInteger, ForeignKey("vendors.id"), index=True, nullable=False)
    subscription_id = Column(BigInteger, ForeignKey("vendor_subscriptions.id"), nullable=True)
    booking_id = Column(BigInteger, ForeignKey("bookings.id"), nullable=True)
    # accepted | missed | missed_pair | missed_pair_no_balance
    event = Column(String(30), nullable=False)
    leads_charged = Column(Integer, default=0, nullable=False)
    leads_left = Column(Integer, nullable=True)  # after this event; None = unlimited plan
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
