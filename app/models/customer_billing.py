import datetime

from sqlalchemy import (
    Column, String, Integer, Boolean, ForeignKey, Numeric, DateTime, Text, BigInteger, UniqueConstraint,
)

from app.db.base_class import Base


class CustomerWallet(Base):
    """Cashback wallet. One per customer; created on first use."""
    __tablename__ = "customer_wallets"

    id = Column(BigInteger, primary_key=True, index=True)
    customer_id = Column(BigInteger, ForeignKey("customers.id"), unique=True, index=True, nullable=False)
    balance = Column(Numeric(10, 2), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CustomerWalletTransaction(Base):
    __tablename__ = "customer_wallet_transactions"
    # `reference` makes credits/debits idempotent (e.g. "feedback:<booking id>").
    __table_args__ = (UniqueConstraint("wallet_id", "reference", name="uq_wallet_tx_reference"),)

    id = Column(BigInteger, primary_key=True, index=True)
    wallet_id = Column(BigInteger, ForeignKey("customer_wallets.id"), index=True, nullable=False)
    transaction_type = Column(String(10), nullable=False)  # credit | debit
    amount = Column(Numeric(10, 2), nullable=False)
    description = Column(String, nullable=True)
    booking_id = Column(BigInteger, nullable=True)
    reference = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class BookingFeedback(Base):
    __tablename__ = "booking_feedback"

    id = Column(BigInteger, primary_key=True, index=True)
    booking_id = Column(BigInteger, ForeignKey("bookings.id"), unique=True, nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"), index=True, nullable=False)
    vendor_id = Column(BigInteger, nullable=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    cashback_amount = Column(Numeric(10, 2), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Coupon(Base):
    """Managed directly in SQL for now (see scripts/coupons.sql). Codes are stored upper-case."""
    __tablename__ = "coupons"

    id = Column(BigInteger, primary_key=True, index=True)
    code = Column(String(40), unique=True, index=True, nullable=False)
    title = Column(String, nullable=True)
    discount_type = Column(String(10), nullable=False)  # percent | flat
    value = Column(Numeric(10, 2), nullable=False)
    max_discount = Column(Numeric(10, 2), nullable=True)  # cap for percent coupons
    min_order_amount = Column(Numeric(10, 2), nullable=False, default=0)
    valid_from = Column(DateTime, nullable=True)
    valid_to = Column(DateTime, nullable=True)
    usage_limit = Column(Integer, nullable=True)           # total redemptions, NULL = unlimited
    per_customer_limit = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"

    id = Column(BigInteger, primary_key=True, index=True)
    coupon_id = Column(BigInteger, ForeignKey("coupons.id"), index=True, nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"), index=True, nullable=False)
    booking_id = Column(BigInteger, ForeignKey("bookings.id"), index=True, nullable=False)
    discount_amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String(10), nullable=False, default="applied")  # applied | reversed
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class BookingPayment(Base):
    """COD payment record: what the coupon and wallet covered, and the cash still due."""
    __tablename__ = "booking_payments"

    id = Column(BigInteger, primary_key=True, index=True)
    booking_id = Column(BigInteger, ForeignKey("bookings.id"), index=True, nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"), index=True, nullable=False)
    subtotal_amount = Column(Numeric(10, 2), nullable=False)
    discount_amount = Column(Numeric(10, 2), nullable=False, default=0)
    wallet_amount = Column(Numeric(10, 2), nullable=False, default=0)
    amount_due = Column(Numeric(10, 2), nullable=False)  # cash to pay at the visit
    coupon_code = Column(String(40), nullable=True)
    method = Column(String(10), nullable=False, default="COD")
    status = Column(String(12), nullable=False, default="pending")  # pending | captured | cancelled
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(BigInteger, primary_key=True, index=True)
    invoice_number = Column(String(30), unique=True, index=True, nullable=True)
    booking_id = Column(BigInteger, ForeignKey("bookings.id"), unique=True, nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id"), index=True, nullable=False)
    vendor_id = Column(BigInteger, nullable=True)
    service_name = Column(String, nullable=True)
    subtotal_amount = Column(Numeric(10, 2), nullable=False)
    discount_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    status = Column(String(10), nullable=False, default="issued")
    issued_at = Column(DateTime, default=datetime.datetime.utcnow)
