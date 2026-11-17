"""
Booking vendor assignment.

A booking is offered to one active member vendor at a time. The vendor gets a
push notification, SMS and WhatsApp message and has ACCEPT_TIMEOUT_MINUTES to
accept. If they decline or don't answer, the booking moves to the next nearest
eligible vendor. Only vendors with status 'active', an active subscription and
leads left are offered bookings.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.geo import haversine_km, SEARCH_RADII_KM
from app.models.booking_offer import BookingOffer
from app.models.orders import Order
from app.models.subscriptions import VendorSubscription
from app.models.user_location import Customer
from app.models.vendor import Vendor, VendorService
from app.services import vendor_lead_service as leads
from app.services.notification_service import send_user_push_notification
from app.services.otp_service import otp_service
from app.services.whatsapp_service import send_whatsapp

logger = logging.getLogger(__name__)

VENDOR_ASSIGNMENT_META_KEY = "vendor_assignment"
ACCEPT_TIMEOUT_MINUTES = settings.BOOKING_ACCEPT_TIMEOUT_MINUTES
AWAITING_STATUSES = ("PENDING", "new")


# ------------------------------------------------------------------ helpers

def _parse_assignment_meta(vendor_notes: Optional[str]) -> Dict[str, Any]:
    if not vendor_notes:
        return {}
    try:
        data = json.loads(vendor_notes)
        if isinstance(data, dict):
            return data.get(VENDOR_ASSIGNMENT_META_KEY, {})
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def _serialize_assignment_meta(meta_data: Dict[str, Any]) -> str:
    return json.dumps({VENDOR_ASSIGNMENT_META_KEY: meta_data})


def build_initial_assignment_meta(catalog_service_id: Optional[int] = None) -> str:
    return _serialize_assignment_meta(
        {
            "declined_vendor_ids": [],
            "assigned_at": datetime.utcnow().isoformat(),
            "catalog_service_id": catalog_service_id,
        }
    )


def area_from_address(address: Optional[str]) -> str:
    """The locality part of an address (drops the house/street line) for vendors who haven't accepted yet."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) <= 1:
        return ""
    return ", ".join(parts[-3:]) if len(parts) > 3 else ", ".join(parts[1:])


async def _run(background_tasks, fn, *args) -> None:
    if background_tasks is not None:
        background_tasks.add_task(fn, *args)
        return
    try:
        await fn(*args)
    except Exception as e:  # an alert failing must never break assignment
        logger.error("Alert %s failed: %s", getattr(fn, "__name__", fn), e)


async def _customer_user_id(db: AsyncSession, order: Order) -> Optional[int]:
    if not order.customer_id:
        return None
    customer = await db.get(Customer, order.customer_id)
    return customer.user_id if customer else None


# ------------------------------------------------------------------- alerts

async def notify_vendor_new_booking(
    vendor: Vendor,
    order: Order,
    expires_at: datetime,
    background_tasks=None,
) -> None:
    """Push + SMS + WhatsApp to the vendor: new booking, accept or decline."""
    booking_id = order.booking_reference or ""
    service = order.service_name or "a service"
    when = f"{order.booking_date} {order.booking_time.strftime('%I:%M %p') if order.booking_time else ''}".strip()
    area = area_from_address(order.service_address)
    hours = ACCEPT_TIMEOUT_MINUTES // 60
    window = f"{hours} hour{'s' if hours != 1 else ''}" if ACCEPT_TIMEOUT_MINUTES % 60 == 0 else f"{ACCEPT_TIMEOUT_MINUTES} minutes"

    if vendor.user_id:
        await _run(
            background_tasks,
            send_user_push_notification,
            vendor.user_id,
            "New Booking Received",
            f"{order.customer_name or 'A customer'} booked {service} for {when}"
            f"{' in ' + area if area else ''}. Accept or decline within {window}.",
            {
                "type": "new_booking",
                "order_id": booking_id,
                "expires_at": expires_at.isoformat() + "Z",
            },
        )
    else:
        logger.warning("Vendor %s has no user_id; skipping booking push", vendor.id)

    if vendor.mobile:
        await _run(
            background_tasks,
            otp_service.send_vendor_new_booking_sms,
            vendor.mobile,
            order.customer_name or "Customer",
            booking_id,
        )
        message = (
            f"*New booking on AM5 ROYAL* 🔔\n\n"
            f"Booking ID: *{booking_id}*\n"
            f"Customer: {order.customer_name or 'Customer'}\n"
            f"Service: {service}\n"
            f"Date & time: {when}\n"
            + (f"Area: {area}\n" if area else "")
            + f"\nOpen the AM5 ROYAL vendor app to *accept or decline* within {window}. "
            f"After that the booking goes to another vendor."
        )
        await _run(background_tasks, send_whatsapp, vendor.mobile, message, f"New booking {booking_id}")


async def _push_customer(db, order, background_tasks, title, body, kind) -> None:
    user_id = await _customer_user_id(db, order)
    if not user_id:
        return
    await _run(
        background_tasks,
        send_user_push_notification,
        user_id, title, body,
        {"type": kind, "order_id": order.booking_reference or str(order.id)},
    )


async def notify_customer_vendor_accepted(db: AsyncSession, order: Order, vendor: Vendor, background_tasks=None) -> None:
    vendor_name = order.vendor_name or vendor.business_name or "Vendor"
    await _push_customer(
        db, order, background_tasks, "Vendor Assigned",
        f"{vendor_name} has accepted your booking for {order.service_name or 'your service'}. "
        "You can call them from the booking page.",
        "booking_accepted",
    )


async def notify_customer_reassignment(db: AsyncSession, order: Order, vendor_name: str, background_tasks=None) -> None:
    await _push_customer(
        db, order, background_tasks, "Vendor Updated",
        f"Your booking was passed to {vendor_name}. They will confirm shortly.",
        "booking_reassigned",
    )


async def notify_customer_no_vendor(db: AsyncSession, order: Order, background_tasks=None) -> None:
    await _push_customer(
        db, order, background_tasks, "Booking Update",
        "We could not find an available vendor for your booking right now. Our team will contact you shortly.",
        "booking_unassigned",
    )


# --------------------------------------------------------------- matching

async def _offered_vendor_ids(db: AsyncSession, order: Order) -> List[int]:
    rows = await db.execute(select(BookingOffer.vendor_id).where(BookingOffer.booking_id == order.id))
    ids = {r[0] for r in rows}
    ids.update(_parse_assignment_meta(order.vendor_notes).get("declined_vendor_ids") or [])
    if order.vendor_id:
        ids.add(order.vendor_id)
    return list(ids)


async def find_next_vendor_for_order(
    db: AsyncSession,
    order: Order,
    excluded_vendor_ids: List[int],
) -> Optional[Tuple[Vendor, VendorService]]:
    """
    Nearest eligible vendor: status 'active', active subscription with leads
    left, offers the service at or below the booked price, and not offered
    this booking before.
    """
    meta = _parse_assignment_meta(order.vendor_notes)
    max_price = float(order.final_amount or order.total_amount or 0)
    subcategory_id = order.service_subcategory_id
    category_id = order.service_category_id
    catalog_service_id = meta.get("catalog_service_id")

    if not subcategory_id and not catalog_service_id:
        return None

    query = (
        select(VendorService, Vendor)
        .join(Vendor, Vendor.id == VendorService.vendor_id)
        .where(VendorService.is_active == True)
        .where(Vendor.status == "active")
        .where(Vendor.id.in_(leads.eligible_vendor_ids_subquery()))
    )
    if subcategory_id:
        query = query.where(VendorService.sub_category_id == subcategory_id)
    if category_id:
        query = query.where(VendorService.main_category_id == category_id)
    if catalog_service_id:
        query = query.where(VendorService.service_id == catalog_service_id)
    if excluded_vendor_ids:
        query = query.where(Vendor.id.notin_(list(set(excluded_vendor_ids))))
    if max_price > 0:
        # Customer keeps the price they booked at.
        query = query.where(func.coalesce(VendorService.discounted_price, VendorService.price) <= max_price)

    rows = (await db.execute(query)).all()
    if not rows:
        return None

    customer_lat = float(order.latitude) if order.latitude is not None else None
    customer_lon = float(order.longitude) if order.longitude is not None else None

    candidates: List[Tuple[Vendor, VendorService, float]] = []
    for vs, vendor in rows:
        distance_km = 9999.0
        if None not in (customer_lat, customer_lon, vendor.latitude, vendor.longitude):
            distance_km = haversine_km(customer_lat, customer_lon, float(vendor.latitude), float(vendor.longitude))
            if distance_km > max(SEARCH_RADII_KM) or distance_km > (vendor.service_radius_km or 10):
                continue
        candidates.append((vendor, vs, distance_km))

    if not candidates:
        if customer_lat is None or customer_lon is None:
            vs, vendor = rows[0]
            return vendor, vs
        return None

    candidates.sort(key=lambda item: (item[2], -float(item[0].avg_rating or 0)))
    vendor, vs, _ = candidates[0]
    return vendor, vs


# ----------------------------------------------------------------- offers

async def open_offer(db: AsyncSession, order: Order, vendor: Vendor) -> BookingOffer:
    """Give the booking to this vendor and start their timer. Caller commits, then alerts."""
    now = datetime.utcnow()
    sub = await leads.get_active_subscription(db, vendor.id)
    offer = BookingOffer(
        booking_id=order.id,
        vendor_id=vendor.id,
        subscription_id=sub.id if sub else None,
        offered_at=now,
        expires_at=now + timedelta(minutes=ACCEPT_TIMEOUT_MINUTES),
        outcome="pending",
    )
    db.add(offer)

    meta = _parse_assignment_meta(order.vendor_notes)
    meta["assigned_at"] = now.isoformat()
    order.vendor_notes = _serialize_assignment_meta(meta)
    order.vendor_id = vendor.id
    order.vendor_profile_id = vendor.id
    order.vendor_name = vendor.business_name or "Vendor"
    order.vendor_phone = vendor.mobile
    order.vendor_email = vendor.email
    order.status = "PENDING"
    order.accepted_at = None
    db.add(order)
    await db.flush()
    return offer


async def get_pending_offer(db: AsyncSession, booking_id: int, vendor_id: int, lock: bool = False) -> Optional[BookingOffer]:
    query = (
        select(BookingOffer)
        .where(
            BookingOffer.booking_id == booking_id,
            BookingOffer.vendor_id == vendor_id,
            BookingOffer.outcome == "pending",
        )
        .order_by(BookingOffer.offered_at.desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def close_pending_offers(db: AsyncSession, booking_id: int, outcome: str, reason: Optional[str] = None) -> None:
    """Close any open offer on a booking (e.g. the customer cancelled). Caller commits."""
    rows = await db.execute(
        select(BookingOffer).where(BookingOffer.booking_id == booking_id, BookingOffer.outcome == "pending")
    )
    for offer in rows.scalars():
        offer.outcome = outcome
        offer.responded_at = datetime.utcnow()
        offer.reason = reason


async def handle_vendor_decline_or_timeout(
    db: AsyncSession,
    order: Order,
    declined_vendor_id: int,
    reason: Optional[str] = None,
    background_tasks=None,
    is_timeout: bool = False,
) -> Dict[str, Any]:
    """
    Close the vendor's offer, count the miss against their leads, and pass the
    booking to the next vendor (or mark it UNASSIGNED). Expects the order row to
    be locked by the caller. Commits.
    """
    if order.status not in AWAITING_STATUSES:
        return {"reassigned": False, "message": "Order is not awaiting vendor acceptance"}

    now = datetime.utcnow()
    offer = await get_pending_offer(db, order.id, declined_vendor_id, lock=True)
    if offer:
        offer.outcome = "expired" if is_timeout else "declined"
        offer.responded_at = now
        offer.reason = (reason or "")[:300] or None

    meta = _parse_assignment_meta(order.vendor_notes)
    declined = list(meta.get("declined_vendor_ids") or [])
    if declined_vendor_id and declined_vendor_id not in declined:
        declined.append(declined_vendor_id)
    meta["declined_vendor_ids"] = declined
    order.vendor_notes = _serialize_assignment_meta(meta)
    order.rejection_reason = reason or (
        "Vendor did not accept within time limit" if is_timeout else "Vendor rejected the booking"
    )
    order.rejected_at = now

    if declined_vendor_id:
        await leads.record_miss(db, declined_vendor_id, order.id)

    excluded = await _offered_vendor_ids(db, order)
    next_match = await find_next_vendor_for_order(db, order, excluded)
    if next_match:
        vendor, _ = next_match
        new_offer = await open_offer(db, order, vendor)
        await db.commit()
        await notify_vendor_new_booking(vendor, order, new_offer.expires_at, background_tasks)
        await notify_customer_reassignment(db, order, vendor.business_name or "Vendor", background_tasks)
        return {
            "reassigned": True,
            "new_vendor_id": vendor.id,
            "new_vendor_name": vendor.business_name,
            "message": "Booking reassigned to another nearby vendor",
        }

    order.status = "UNASSIGNED"
    db.add(order)
    await db.commit()
    await notify_customer_no_vendor(db, order, background_tasks)
    return {"reassigned": False, "message": "No eligible vendor found. Customer has been notified."}


async def process_pending_booking_timeouts(background_tasks=None) -> int:
    """Move bookings whose vendor didn't respond within ACCEPT_TIMEOUT_MINUTES to the next vendor."""
    from app.db.session import AsyncSessionLocal

    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        expired = await session.execute(
            select(BookingOffer.booking_id, BookingOffer.vendor_id)
            .where(BookingOffer.outcome == "pending", BookingOffer.expires_at <= now)
        )
        due = list(expired.all())

        # Bookings created before booking_offers existed: use the assigned_at in vendor_notes.
        legacy = await session.execute(
            select(Order).where(
                Order.status.in_(AWAITING_STATUSES),
                Order.vendor_id.isnot(None),
                ~exists().where(BookingOffer.booking_id == Order.id),
            )
        )
        cutoff = now - timedelta(minutes=ACCEPT_TIMEOUT_MINUTES)
        for order in legacy.scalars():
            assigned_at = _parse_assignment_meta(order.vendor_notes).get("assigned_at")
            try:
                if assigned_at and datetime.fromisoformat(assigned_at) <= cutoff:
                    due.append((order.id, order.vendor_id))
            except ValueError:
                continue

    processed = 0
    for booking_id, vendor_id in due:
        async with AsyncSessionLocal() as session:
            # skip_locked: if the vendor is accepting right now, leave this booking alone.
            order = (await session.execute(
                select(Order).where(Order.id == booking_id).with_for_update(skip_locked=True)
            )).scalar_one_or_none()
            if order is None:
                continue  # locked by an accept in progress; try again next run
            if order.status not in AWAITING_STATUSES:
                # Booking was cancelled or accepted: just close the stale offer.
                await close_pending_offers(session, booking_id, "expired", "Booking no longer waiting")
                await session.commit()
                continue
            if order.vendor_id != vendor_id:
                # Booking already moved to someone else: close this vendor's leftover offer.
                stale = await get_pending_offer(session, booking_id, vendor_id, lock=True)
                if stale:
                    stale.outcome = "expired"
                    stale.responded_at = now
                    await session.commit()
                continue
            try:
                await handle_vendor_decline_or_timeout(
                    session, order,
                    declined_vendor_id=vendor_id,
                    reason=f"Vendor did not accept within {ACCEPT_TIMEOUT_MINUTES} minutes",
                    background_tasks=background_tasks,
                    is_timeout=True,
                )
                processed += 1
            except Exception as e:
                await session.rollback()
                logger.error("Timeout reassignment failed for booking %s: %s", booking_id, e)

    if processed:
        logger.info("Processed %d timed-out pending bookings for reassignment", processed)
    return processed
