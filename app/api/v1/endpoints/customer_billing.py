"""Customer wallet, coupons, COD payments and invoices (mounted at the API root)."""
import datetime as dt
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.db.session import get_db
from app.dependencies.auth import get_current_customer
from app.models.customer_billing import (
    BookingPayment, Coupon, CouponRedemption, CustomerWalletTransaction, Invoice,
)
from app.models.orders import Order as OrderModel
from app.models.user_location import Customer
from app.services import customer_wallet_service as wallets
from app.services.customer_wallet_service import money

router = APIRouter()

# Statuses a booking can still be paid for.
PAYABLE_STATUSES = ("PENDING", "new", "ACCEPTED")


def _iso(value: Optional[dt.datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


# ---------------------------------------------------------------- wallet (38)

@router.get("/wallet")
@limiter.limit("60/minute")
async def get_wallet(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Cashback balance and history, newest first."""
    wallet = await wallets.get_wallet(db, current_customer.id)
    await db.commit()  # persists a wallet created on first view
    res = await db.execute(
        select(CustomerWalletTransaction)
        .where(CustomerWalletTransaction.wallet_id == wallet.id)
        .order_by(CustomerWalletTransaction.created_at.desc(), CustomerWalletTransaction.id.desc())
        .offset(skip).limit(limit)
    )
    return {
        "id": str(wallet.id),
        "balance": float(money(wallet.balance)),
        "currency": "INR",
        "status": "active",
        "transactions": [
            {
                "id": str(t.id),
                "type": t.transaction_type,
                "amount": float(t.amount),
                "description": t.description,
                "booking_id": t.booking_id,
                "created_at": _iso(t.created_at),
            }
            for t in res.scalars().all()
        ],
    }


# -------------------------------------------------------------- coupons (36)

class CouponError(Exception):
    pass


async def evaluate_coupon(
    db: AsyncSession, customer_id: int, code: str, amount: Decimal, lock: bool = False,
):
    """Return (coupon, discount) or raise CouponError with a user-facing message."""
    code_n = (code or "").strip().upper()
    if not code_n:
        raise CouponError("Enter a coupon code")
    query = select(Coupon).where(Coupon.code == code_n)
    if lock:
        query = query.with_for_update()
    coupon = (await db.execute(query)).scalar_one_or_none()
    if not coupon or not coupon.is_active:
        raise CouponError("This coupon is not valid")

    now = dt.datetime.utcnow()
    if coupon.valid_from and now < coupon.valid_from:
        raise CouponError("This coupon is not active yet")
    if coupon.valid_to and now > coupon.valid_to:
        raise CouponError("This coupon has expired")
    if amount < money(coupon.min_order_amount):
        raise CouponError(f"Minimum order amount for this coupon is ₹{money(coupon.min_order_amount)}")

    if coupon.usage_limit is not None:
        used = (await db.execute(
            select(func.count(CouponRedemption.id)).where(
                CouponRedemption.coupon_id == coupon.id, CouponRedemption.status == "applied")
        )).scalar() or 0
        if used >= coupon.usage_limit:
            raise CouponError("This coupon has reached its usage limit")
    mine = (await db.execute(
        select(func.count(CouponRedemption.id)).where(
            CouponRedemption.coupon_id == coupon.id,
            CouponRedemption.customer_id == customer_id,
            CouponRedemption.status == "applied")
    )).scalar() or 0
    if mine >= (coupon.per_customer_limit or 1):
        raise CouponError("You have already used this coupon")

    if coupon.discount_type == "percent":
        discount = amount * money(coupon.value) / Decimal(100)
        if coupon.max_discount is not None:
            discount = min(discount, money(coupon.max_discount))
    else:
        discount = money(coupon.value)
    discount = money(min(discount, amount))
    if discount <= 0:
        raise CouponError("This coupon gives no discount on this order")
    return coupon, discount


class CouponValidateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=40)
    order_amount: float = Field(..., gt=0)


@router.post("/coupons/validate")
@limiter.limit("20/minute")
async def validate_coupon(
    request: Request,
    body: CouponValidateRequest,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Check a coupon against an amount. Does not use the coupon up."""
    amount = money(body.order_amount)
    code = body.code.strip().upper()
    try:
        coupon, discount = await evaluate_coupon(db, current_customer.id, code, amount)
    except CouponError as exc:
        return {
            "valid": False, "code": code, "title": "", "discount_amount": 0.0,
            "payable_amount": float(amount), "message": str(exc),
        }
    return {
        "valid": True,
        "code": coupon.code,
        "title": coupon.title or coupon.code,
        "discount_amount": float(discount),
        "payable_amount": float(amount - discount),
        "message": f"You save ₹{discount}",
    }


# ------------------------------------------------------------- payments (35, 37)

class PaymentCreateRequest(BaseModel):
    booking_id: str  # the booking reference returned by POST /orders/
    coupon_code: Optional[str] = Field(None, max_length=40)
    use_wallet_amount: float = Field(0, ge=0)


def _payment_json(payment: BookingPayment, booking_ref: str) -> dict:
    return {
        "id": str(payment.id),
        "booking_id": booking_ref,
        "amount": float(payment.amount_due),
        "currency": "INR",
        "method": payment.method,
        "provider": "am5",
        "provider_order_id": None,
        "client_secret": None,
        "status": payment.status,
        "gateway_amount": 0.0,
        "wallet_amount": float(payment.wallet_amount),
        "discount_amount": float(payment.discount_amount),
        "coupon_code": payment.coupon_code,
    }


async def _own_booking(
    db: AsyncSession, reference: str, customer: Customer, lock: bool = False,
) -> OrderModel:
    query = select(OrderModel).where(
        OrderModel.booking_reference == reference, OrderModel.customer_id == customer.id)
    if lock:
        # Serialises double-taps: a second request waits, then sees the first payment.
        query = query.with_for_update()
    res = await db.execute(query)
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Booking not found")
    return order


@router.post("/payments")
@limiter.limit("10/minute")
async def create_payment(
    request: Request,
    body: PaymentCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """
    Settle a booking: apply a coupon and/or wallet money, and record the cash due at the visit.
    COD only. All amounts are computed here from the booking, never taken from the client.
    Calling it again for the same booking returns the existing payment.
    """
    order = await _own_booking(db, body.booking_id, current_customer, lock=True)

    existing = (await db.execute(
        select(BookingPayment).where(
            BookingPayment.booking_id == order.id, BookingPayment.status != "cancelled")
    )).scalars().first()
    if existing:
        return _payment_json(existing, order.booking_reference)

    if order.status not in PAYABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"A booking that is {str(order.status).lower()} cannot be paid for",
        )

    subtotal = money(order.total_amount)
    if subtotal <= 0:
        raise HTTPException(status_code=400, detail="This booking has no amount to pay")

    coupon, discount = None, Decimal("0.00")
    code = (body.coupon_code or "").strip()
    if code:
        try:
            coupon, discount = await evaluate_coupon(db, current_customer.id, code, subtotal, lock=True)
        except CouponError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    payable = subtotal - discount
    wallet_amount = money(body.use_wallet_amount)
    if wallet_amount > payable:
        raise HTTPException(status_code=400, detail="Wallet amount is more than the amount payable")

    payment = BookingPayment(
        booking_id=order.id, customer_id=current_customer.id,
        subtotal_amount=subtotal, discount_amount=discount, wallet_amount=wallet_amount,
        amount_due=payable - wallet_amount, coupon_code=coupon.code if coupon else None,
        method="COD", status="pending",
    )
    db.add(payment)
    await db.flush()

    if wallet_amount > 0:
        try:
            await wallets.debit(
                db, current_customer.id, wallet_amount, "Used for booking",
                booking_id=order.id, reference=f"payment:{payment.id}",
            )
        except wallets.InsufficientBalance:
            await db.rollback()
            raise HTTPException(status_code=400, detail="Insufficient wallet balance")
    if coupon:
        db.add(CouponRedemption(
            coupon_id=coupon.id, customer_id=current_customer.id,
            booking_id=order.id, discount_amount=discount,
        ))
    order.final_amount = payable  # the booking's charge after the coupon
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Payment could not be completed, please retry")
    await db.refresh(payment)
    return _payment_json(payment, order.booking_reference)


@router.post("/payments/{payment_id}/confirm")
@limiter.limit("20/minute")
async def confirm_payment(
    request: Request,
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """
    Current state of a payment. Cash is collected at the visit, so there is nothing for the
    customer to verify: the payment becomes `captured` when the booking is completed.
    (An online gateway would verify its payment token here.)
    """
    payment = await db.get(BookingPayment, payment_id)
    if not payment or payment.customer_id != current_customer.id:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status == "cancelled":
        raise HTTPException(status_code=400, detail="This payment was cancelled")
    order = await db.get(OrderModel, payment.booking_id)
    return _payment_json(payment, order.booking_reference if order else "")


# -------------------------------------------------------------- invoices (34)

def _invoice_json(inv: Invoice, booking_ref: str) -> dict:
    return {
        "id": str(inv.id),
        "invoice_number": inv.invoice_number,
        "booking_id": booking_ref,
        "service_name": inv.service_name,
        "subtotal_amount": float(inv.subtotal_amount),
        "discount_amount": float(inv.discount_amount),
        "total_amount": float(inv.total_amount),
        "currency": inv.currency,
        "status": inv.status,
        "issued_at": _iso(inv.issued_at),
        "pdf_url": None,  # PDFs are not generated yet
    }


async def ensure_invoices(db: AsyncSession, customer_id: int) -> None:
    """Issue an invoice, once, for every completed booking that has none. Numbers never change."""
    missing = (await db.execute(
        select(OrderModel)
        .outerjoin(Invoice, Invoice.booking_id == OrderModel.id)
        .where(
            OrderModel.customer_id == customer_id,
            func.upper(OrderModel.status) == "COMPLETED",
            Invoice.id.is_(None),
        )
    )).scalars().all()
    if not missing:
        return
    discounts = {
        p.booking_id: money(p.discount_amount)
        for p in (await db.execute(
            select(BookingPayment).where(
                BookingPayment.booking_id.in_([o.id for o in missing]),
                BookingPayment.status != "cancelled")
        )).scalars().all()
    }
    for order in missing:
        subtotal = money(order.total_amount)
        discount = discounts.get(order.id, Decimal("0.00"))
        invoice = Invoice(
            booking_id=order.id, customer_id=customer_id, vendor_id=order.vendor_id,
            service_name=order.service_name, subtotal_amount=subtotal,
            discount_amount=discount, total_amount=subtotal - discount,
            issued_at=order.completed_at.replace(tzinfo=None) if order.completed_at else dt.datetime.utcnow(),
        )
        try:
            async with db.begin_nested():
                db.add(invoice)
                await db.flush()
                invoice.invoice_number = f"INV-{invoice.issued_at.year}-{invoice.id:06d}"
        except IntegrityError:
            continue  # another request issued it first
    await db.commit()


@router.get("/invoices")
@limiter.limit("30/minute")
async def list_invoices(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """The customer's invoices, newest first."""
    await ensure_invoices(db, current_customer.id)
    rows = (await db.execute(
        select(Invoice, OrderModel.booking_reference)
        .join(OrderModel, OrderModel.id == Invoice.booking_id)
        .where(Invoice.customer_id == current_customer.id)
        .order_by(Invoice.issued_at.desc(), Invoice.id.desc())
        .offset(skip).limit(limit)
    )).all()
    return [_invoice_json(inv, ref) for inv, ref in rows]


@router.get("/invoices/{invoice_id}")
@limiter.limit("30/minute")
async def get_invoice(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    await ensure_invoices(db, current_customer.id)
    row = (await db.execute(
        select(Invoice, OrderModel.booking_reference)
        .join(OrderModel, OrderModel.id == Invoice.booking_id)
        .where(Invoice.id == invoice_id, Invoice.customer_id == current_customer.id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _invoice_json(*row)
