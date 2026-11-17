"""Customer cashback wallet. Every balance change goes through credit()/debit(),
which write the transaction and update the balance together under a row lock."""
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer_billing import (
    CustomerWallet, CustomerWalletTransaction, BookingPayment, CouponRedemption,
)

TWOPLACES = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


class InsufficientBalance(Exception):
    pass


async def get_wallet(db: AsyncSession, customer_id: int, lock: bool = False) -> CustomerWallet:
    query = select(CustomerWallet).where(CustomerWallet.customer_id == customer_id)
    if lock:
        query = query.with_for_update()
    wallet = (await db.execute(query)).scalar_one_or_none()
    if wallet is None:
        wallet = CustomerWallet(customer_id=customer_id, balance=0)
        db.add(wallet)
        await db.flush()
    return wallet


async def _already_recorded(db: AsyncSession, wallet_id: int, reference: Optional[str]) -> bool:
    if not reference:
        return False
    res = await db.execute(
        select(CustomerWalletTransaction.id).where(
            CustomerWalletTransaction.wallet_id == wallet_id,
            CustomerWalletTransaction.reference == reference,
        )
    )
    return res.first() is not None


async def credit(
    db: AsyncSession, customer_id: int, amount, description: str,
    booking_id: Optional[int] = None, reference: Optional[str] = None,
) -> bool:
    """Add money. Returns False (and does nothing) if `reference` was already used."""
    amount = money(amount)
    if amount <= 0:
        raise ValueError("Amount must be positive")
    wallet = await get_wallet(db, customer_id, lock=True)
    if await _already_recorded(db, wallet.id, reference):
        return False
    wallet.balance = money(wallet.balance) + amount
    db.add(CustomerWalletTransaction(
        wallet_id=wallet.id, transaction_type="credit", amount=amount,
        description=description, booking_id=booking_id, reference=reference,
    ))
    await db.flush()
    return True


async def debit(
    db: AsyncSession, customer_id: int, amount, description: str,
    booking_id: Optional[int] = None, reference: Optional[str] = None,
) -> bool:
    amount = money(amount)
    if amount <= 0:
        raise ValueError("Amount must be positive")
    wallet = await get_wallet(db, customer_id, lock=True)
    if await _already_recorded(db, wallet.id, reference):
        return False
    if money(wallet.balance) < amount:
        raise InsufficientBalance()
    wallet.balance = money(wallet.balance) - amount
    db.add(CustomerWalletTransaction(
        wallet_id=wallet.id, transaction_type="debit", amount=amount,
        description=description, booking_id=booking_id, reference=reference,
    ))
    await db.flush()
    return True


async def reverse_booking_payment(db: AsyncSession, order) -> None:
    """Undo a pending payment when its booking is cancelled: refund wallet money,
    release the coupon, mark the payment cancelled. The caller commits."""
    res = await db.execute(
        select(BookingPayment).where(BookingPayment.booking_id == order.id, BookingPayment.status == "pending")
    )
    for payment in res.scalars().all():
        if money(payment.wallet_amount) > 0:
            await credit(
                db, payment.customer_id, payment.wallet_amount,
                "Refund for cancelled booking", booking_id=order.id,
                reference=f"payment-refund:{payment.id}",
            )
        payment.status = "cancelled"
    await db.execute(
        update(CouponRedemption)
        .where(CouponRedemption.booking_id == order.id, CouponRedemption.status == "applied")
        .values(status="reversed")
    )
