"""In-app notifications (/notifications) and masked booking calls via Airtel IQ (/calls)."""
import datetime as dt
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.db.session import get_db
from app.dependencies.auth import get_current_customer, get_current_vendor
from app.models.booking_call import BookingCall
from app.models.notification import Notification
from app.models.orders import Order
from app.models.user_location import Customer
from app.models.vendor import Vendor
from app.services.airtel_iq_service import airtel_iq_service

logger = logging.getLogger(__name__)
router = APIRouter()

CALLABLE_STATUSES = ("ACCEPTED", "CONFIRMED", "IN_PROGRESS")
# A call still counts as in progress this long after it was placed.
ACTIVE_CALL_WINDOW = dt.timedelta(minutes=10)
END_REASONS = {"hangup", "declined", "missed", "failed", "cancelled"}


def _iso(value: Optional[dt.datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


# ------------------------------------------------------------- notifications

def _notification_json(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "notification_type": n.notification_type or "system",
        "title": n.title,
        "body": n.body or "",
        "booking_id": n.booking_ref,
        "data": n.data,
        "push_status": n.push_status or "pending",
        "read_at": _iso(n.read_at),
        "created_at": _iso(n.created_at),
    }


@router.get("/notifications")
@limiter.limit("60/minute")
async def list_notifications(
    request: Request,
    unread_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """The customer's notifications, newest first. An empty list when there are none."""
    query = select(Notification).where(Notification.user_id == current_customer.user_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = (await db.execute(
        query.order_by(Notification.created_at.desc(), Notification.id.desc()).offset(skip).limit(limit)
    )).scalars().all()
    return [_notification_json(n) for n in rows]


@router.get("/notifications/unread-count")
@limiter.limit("120/minute")
async def unread_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    count = (await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == current_customer.user_id, Notification.read_at.is_(None))
    )).scalar() or 0
    return {"unread_count": int(count)}


@router.put("/notifications/read-all")
@limiter.limit("30/minute")
async def mark_all_read(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    result = await db.execute(update(Notification).where(
        Notification.user_id == current_customer.user_id, Notification.read_at.is_(None),
    ).values(read_at=dt.datetime.utcnow()))
    await db.commit()
    return {"updated": result.rowcount or 0}


@router.put("/notifications/{notification_id}/read")
@limiter.limit("60/minute")
async def mark_read(
    request: Request,
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    n = (await db.execute(select(Notification).where(
        Notification.id == notification_id, Notification.user_id == current_customer.user_id,
    ))).scalar_one_or_none()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.read_at is None:
        n.read_at = dt.datetime.utcnow()
        await db.commit()
    return _notification_json(n)


# --------------------------------------------------------------------- calls

class CallStart(BaseModel):
    booking_id: str = Field(..., min_length=1, max_length=40)  # booking reference


class CallEnd(BaseModel):
    reason: str = Field("hangup", max_length=30)


def _call_json(c: BookingCall, order: Order) -> dict:
    return {
        "id": str(c.id),
        "booking_id": order.booking_reference,
        "status": c.status,
        "room_id": "",
        "provider": "airtel",
        "initiator_user_id": str(c.initiator_user_id),
        "callee_user_id": str(c.callee_user_id),
        "started_at": _iso(c.answered_at or c.created_at),
        "ended_at": _iso(c.ended_at),
        "end_reason": c.end_reason,
    }


async def _own_call(db: AsyncSession, call_id: int, customer: Customer, lock: bool = False):
    query = (select(BookingCall, Order).join(Order, Order.id == BookingCall.booking_id)
             .where(BookingCall.id == call_id, BookingCall.initiator_user_id == customer.user_id))
    if lock:
        query = query.with_for_update(of=BookingCall)
    row = (await db.execute(query)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    return row


@router.post("/calls", status_code=201)
@limiter.limit("5/minute")
async def start_call(
    request: Request,
    body: CallStart,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """
    Call the professional on one of your bookings. Airtel rings your phone first, then
    connects the professional, so neither side sees the other's number.
    """
    order = (await db.execute(select(Order).where(
        Order.booking_reference == body.booking_id.strip(), Order.customer_id == current_customer.id,
    ))).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Booking not found")
    if not order.vendor_id or str(order.status or "").upper() not in CALLABLE_STATUSES:
        raise HTTPException(status_code=400, detail="You can call once a professional has accepted your booking")
    if not current_customer.phone:
        raise HTTPException(status_code=400, detail="Add a phone number to your profile to place calls")

    vendor = await db.get(Vendor, order.vendor_id)
    if not vendor or not vendor.mobile or not vendor.user_id:
        raise HTTPException(status_code=400, detail="The professional can't be reached by phone right now")

    recent = (await db.execute(select(BookingCall.id).where(
        BookingCall.booking_id == order.id,
        BookingCall.initiator_user_id == current_customer.user_id,
        BookingCall.status.in_(("ringing", "answered")),
        BookingCall.created_at > dt.datetime.utcnow() - ACTIVE_CALL_WINDOW,
    ))).first()
    if recent:
        raise HTTPException(status_code=409, detail="A call is already in progress for this booking")

    call = BookingCall(booking_id=order.id, initiator_user_id=current_customer.user_id,
                       callee_user_id=vendor.user_id, status="ringing")
    db.add(call)
    await db.flush()

    # Not recorded: neither party has agreed to recording.
    success, message, ref_id = await airtel_iq_service.initiate_click_to_call(
        agent_number=current_customer.phone,
        target_number=vendor.mobile,
        record=False,
    )
    if not success and (message or "").startswith("Invalid"):
        await db.rollback()  # nothing was dialled; don't keep a failed record
        if "agent" in message:
            raise HTTPException(status_code=400, detail="Your phone number is not valid for calls. Please update your profile.")
        raise HTTPException(status_code=400, detail="The professional can't be reached by phone right now")
    if not success:
        call.status = "failed"
        call.end_reason = "failed"
        call.ended_at = dt.datetime.utcnow()
        call.error_message = (message or "")[:300]
        await db.commit()
        logger.warning("Booking call %s failed: %s", call.id, message)
        raise HTTPException(status_code=502, detail="Could not place the call. Please try again.")
    call.provider_ref = ref_id
    await db.commit()
    await db.refresh(call)
    return _call_json(call, order)


@router.post("/vendor/calls", status_code=201)
@limiter.limit("5/minute")
async def vendor_start_call(
    request: Request,
    body: CallStart,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor),
):
    """
    Vendor calls the customer on a booking they accepted. Airtel rings the vendor's
    phone first, then connects the customer, so neither side sees the other's number.
    """
    order = (await db.execute(select(Order).where(
        Order.booking_reference == body.booking_id.strip(), Order.vendor_id == current_vendor.id,
    ))).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Booking not found")
    if str(order.status or "").upper() not in CALLABLE_STATUSES:
        raise HTTPException(status_code=400, detail="You can call the customer after accepting the booking")
    if not current_vendor.mobile or not current_vendor.user_id:
        raise HTTPException(status_code=400, detail="Add a phone number to your profile to place calls")

    customer = await db.get(Customer, order.customer_id) if order.customer_id else None
    customer_phone = (customer.phone if customer else None) or order.customer_phone
    if not customer_phone:
        raise HTTPException(status_code=400, detail="The customer can't be reached by phone right now")

    recent = (await db.execute(select(BookingCall.id).where(
        BookingCall.booking_id == order.id,
        BookingCall.initiator_user_id == current_vendor.user_id,
        BookingCall.status.in_(("ringing", "answered")),
        BookingCall.created_at > dt.datetime.utcnow() - ACTIVE_CALL_WINDOW,
    ))).first()
    if recent:
        raise HTTPException(status_code=409, detail="A call is already in progress for this booking")

    call = BookingCall(booking_id=order.id, initiator_user_id=current_vendor.user_id,
                       callee_user_id=(customer.user_id if customer and customer.user_id else 0),
                       status="ringing")
    db.add(call)
    await db.flush()

    success, message, ref_id = await airtel_iq_service.initiate_click_to_call(
        agent_number=current_vendor.mobile,
        target_number=customer_phone,
        record=False,
    )
    if not success and (message or "").startswith("Invalid"):
        await db.rollback()
        if "agent" in message:
            raise HTTPException(status_code=400, detail="Your phone number is not valid for calls. Please update your profile.")
        raise HTTPException(status_code=400, detail="The customer can't be reached by phone right now")
    if not success:
        call.status = "failed"
        call.end_reason = "failed"
        call.ended_at = dt.datetime.utcnow()
        call.error_message = (message or "")[:300]
        await db.commit()
        logger.warning("Vendor booking call %s failed: %s", call.id, message)
        raise HTTPException(status_code=502, detail="Could not place the call. Please try again.")
    call.provider_ref = ref_id
    await db.commit()
    await db.refresh(call)
    return _call_json(call, order)


@router.post("/vendor/calls/{call_id}/end")
@limiter.limit("20/minute")
async def vendor_end_call(
    request: Request,
    call_id: int,
    body: Optional[CallEnd] = None,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor),
):
    """Record that the vendor's call is over. Safe to call twice."""
    row = (await db.execute(
        select(BookingCall, Order).join(Order, Order.id == BookingCall.booking_id)
        .where(BookingCall.id == call_id, BookingCall.initiator_user_id == current_vendor.user_id)
        .with_for_update(of=BookingCall)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    call, order = row
    if call.status in ("ringing", "answered"):
        reason = (body.reason if body else "hangup").strip().lower()
        call.status = "ended"
        call.ended_at = dt.datetime.utcnow()
        call.end_reason = reason if reason in END_REASONS else "hangup"
        await db.commit()
    return _call_json(call, order)


@router.post("/calls/{call_id}/answer")
@limiter.limit("20/minute")
async def answer_call(
    request: Request,
    call_id: int,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Mark the call as connected (the phone call itself is answered on the handset)."""
    call, order = await _own_call(db, call_id, current_customer, lock=True)
    if call.status == "ringing":
        call.status = "answered"
        call.answered_at = dt.datetime.utcnow()
        await db.commit()
    elif call.status != "answered":
        raise HTTPException(status_code=400, detail="This call has already ended")
    return _call_json(call, order)


@router.post("/calls/{call_id}/end")
@limiter.limit("20/minute")
async def end_call(
    request: Request,
    call_id: int,
    body: Optional[CallEnd] = None,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Record that the call is over. Safe to call twice."""
    call, order = await _own_call(db, call_id, current_customer, lock=True)
    if call.status in ("ringing", "answered"):
        reason = (body.reason if body else "hangup").strip().lower()
        call.status = "ended"
        call.ended_at = dt.datetime.utcnow()
        call.end_reason = reason if reason in END_REASONS else "hangup"
        await db.commit()
    return _call_json(call, order)
