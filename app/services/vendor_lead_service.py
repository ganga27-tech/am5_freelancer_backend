"""
Vendor leads.

Each active subscription carries leads from its plan (free_leads; -1 = unlimited).
- Accepting a booking costs 1 lead.
- Every 2 declined or ignored bookings cost 1 lead. With no leads left, the
  miss is only recorded (the balance never goes negative).
"""
from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking_offer import VendorLeadHistory
from app.models.subscriptions import SubscriptionPlan, VendorSubscription

MISSES_PER_LEAD = 2


class NoLeadsLeft(Exception):
    pass


def has_leads_condition():
    """SQL condition: the subscription row still has leads (or is unlimited)."""
    return or_(
        VendorSubscription.leads_total < 0,
        VendorSubscription.leads_used < VendorSubscription.leads_total,
    )


def active_subscription_condition():
    """SQL condition: subscription status is 'active'. end_date is not checked."""
    return VendorSubscription.status == "active"


def eligible_vendor_ids_subquery():
    """Vendor ids with an active subscription that still has leads."""
    return (
        select(VendorSubscription.vendor_id)
        .where(active_subscription_condition(), has_leads_condition())
    )


def leads_left(sub: Optional[VendorSubscription]) -> Optional[int]:
    """Leads remaining. None means unlimited."""
    if sub is None:
        return 0
    total = sub.leads_total if sub.leads_total is not None else 0
    if total < 0:
        return None
    return max(total - (sub.leads_used or 0), 0)


def has_leads(sub: Optional[VendorSubscription]) -> bool:
    left = leads_left(sub)
    return left is None or left > 0


async def get_active_subscription(
    db: AsyncSession, vendor_id: int, lock: bool = False
) -> Optional[VendorSubscription]:
    query = (
        select(VendorSubscription)
        .where(VendorSubscription.vendor_id == vendor_id, active_subscription_condition())
        .order_by(VendorSubscription.end_date.desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def get_plan(db: AsyncSession, sub: VendorSubscription) -> Optional[SubscriptionPlan]:
    return await db.get(SubscriptionPlan, sub.subscription_plan_id)


async def charge_accept(db: AsyncSession, vendor_id: int, booking_id: int) -> Tuple[VendorSubscription, Optional[int]]:
    """
    Take 1 lead for an accepted booking. Locks the subscription row so two
    accepts can't both use the last lead. Raises NoLeadsLeft. Caller commits.
    """
    sub = await get_active_subscription(db, vendor_id, lock=True)
    if sub is None or not has_leads(sub):
        raise NoLeadsLeft()
    if leads_left(sub) is not None:
        sub.leads_used = (sub.leads_used or 0) + 1
    left = leads_left(sub)
    db.add(VendorLeadHistory(
        vendor_id=vendor_id, subscription_id=sub.id, booking_id=booking_id,
        event="accepted", leads_charged=1 if left is not None else 0, leads_left=left,
    ))
    return sub, left


async def record_miss(db: AsyncSession, vendor_id: int, booking_id: int) -> None:
    """
    Record a declined or ignored booking. Every 2nd miss costs 1 lead, or is
    only recorded when no leads are left. Caller commits.
    """
    sub = await get_active_subscription(db, vendor_id, lock=True)
    if sub is None:
        db.add(VendorLeadHistory(vendor_id=vendor_id, booking_id=booking_id, event="missed", leads_left=0))
        return

    sub.missed_uncharged = (sub.missed_uncharged or 0) + 1
    db.add(VendorLeadHistory(
        vendor_id=vendor_id, subscription_id=sub.id, booking_id=booking_id,
        event="missed", leads_left=leads_left(sub),
    ))
    if sub.missed_uncharged < MISSES_PER_LEAD:
        return

    sub.missed_uncharged = 0
    left = leads_left(sub)
    if left is None:
        # Unlimited plan: nothing to take, just record the pair.
        db.add(VendorLeadHistory(
            vendor_id=vendor_id, subscription_id=sub.id, booking_id=booking_id,
            event="missed_pair", leads_charged=0, leads_left=None,
        ))
    elif left > 0:
        sub.leads_used = (sub.leads_used or 0) + 1
        db.add(VendorLeadHistory(
            vendor_id=vendor_id, subscription_id=sub.id, booking_id=booking_id,
            event="missed_pair", leads_charged=1, leads_left=leads_left(sub),
        ))
    else:
        db.add(VendorLeadHistory(
            vendor_id=vendor_id, subscription_id=sub.id, booking_id=booking_id,
            event="missed_pair_no_balance", leads_charged=0, leads_left=0,
        ))
