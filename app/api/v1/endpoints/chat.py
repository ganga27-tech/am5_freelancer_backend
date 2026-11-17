"""Booking chat between a customer and the vendor on their booking.

Customer side is mounted at /chat, vendor side at /vendor/chat. Delivery is by polling
(`after` message id) plus a push notification to the other party.
"""
import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.db.session import get_db
from app.dependencies.auth import get_current_customer, get_current_vendor
from app.models.chat import ChatMessage, ChatThread
from app.models.orders import Order
from app.models.user_location import Customer
from app.models.vendor import Vendor
from app.services.notification_service import send_user_push_notification

router = APIRouter()          # customer, /chat
vendor_router = APIRouter()   # vendor, /vendor/chat

CHAT_AFTER_CLOSE = dt.timedelta(hours=48)
ENDED_STATUSES = ("COMPLETED", "CANCELLED")
OPENABLE_STATUSES = ("ACCEPTED", "CONFIRMED", "IN_PROGRESS", "COMPLETED")
PAGE_DEFAULT, PAGE_MAX = 50, 100


class MessageIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=1000)


class OpenThreadIn(BaseModel):
    booking_id: str = Field(..., min_length=1, max_length=40)  # booking reference


def _iso(value: Optional[dt.datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


def _is_open(order: Order) -> bool:
    """Chat is open from vendor acceptance until 48 hours after the booking ends."""
    status = str(order.status or "").upper()
    if status not in ENDED_STATUSES:
        return status in OPENABLE_STATUSES
    ended = order.completed_at if status == "COMPLETED" else order.cancelled_at
    if status == "CANCELLED" and not order.accepted_at:
        return False
    return bool(ended) and dt.datetime.utcnow() - ended < CHAT_AFTER_CLOSE


def _thread_json(t: ChatThread, order: Order, customer_user_id, vendor_user_id, side: str) -> dict:
    return {
        "id": str(t.id),
        "booking_id": order.booking_reference,
        "booking_code": order.booking_reference,
        "service_name": order.service_name,
        "status": "open" if _is_open(order) else "closed",
        "customer_user_id": str(customer_user_id),
        "professional_user_id": str(vendor_user_id),
        "last_message_at": _iso(t.last_message_at),
        "last_message_preview": t.last_message_preview,
        "unread_count": (t.customer_unread if side == "customer" else t.vendor_unread) or 0,
    }


def _message_json(m: ChatMessage, order: Order) -> dict:
    return {
        "id": str(m.id),
        "thread_id": str(m.thread_id),
        "booking_id": order.booking_reference,
        "sender_user_id": str(m.sender_user_id),
        "sender_type": m.sender_type,
        "message_type": "text",
        "body": m.body,
        "created_at": _iso(m.created_at),
        "read_at": _iso(m.read_at),
    }


async def _vendor_user_ids(db: AsyncSession, vendor_ids: List[int]) -> dict:
    if not vendor_ids:
        return {}
    rows = await db.execute(select(Vendor.id, Vendor.user_id).where(Vendor.id.in_(vendor_ids)))
    return {vid: uid for vid, uid in rows.all()}


async def _customer_user_ids(db: AsyncSession, customer_ids: List[int]) -> dict:
    if not customer_ids:
        return {}
    rows = await db.execute(select(Customer.id, Customer.user_id).where(Customer.id.in_(customer_ids)))
    return {cid: uid for cid, uid in rows.all()}


async def _threads_json(db: AsyncSession, rows, side: str) -> List[dict]:
    """rows: [(ChatThread, Order)]"""
    vmap = await _vendor_user_ids(db, list({t.vendor_id for t, _ in rows}))
    cmap = await _customer_user_ids(db, list({t.customer_id for t, _ in rows}))
    return [_thread_json(t, o, cmap.get(t.customer_id, t.customer_id), vmap.get(t.vendor_id, t.vendor_id), side)
            for t, o in rows]


async def _load_thread(db: AsyncSession, thread_id: int, side: str, owner_id: int, lock: bool = False):
    column = ChatThread.customer_id if side == "customer" else ChatThread.vendor_id
    query = (select(ChatThread, Order).join(Order, Order.id == ChatThread.booking_id)
             .where(ChatThread.id == thread_id, column == owner_id))
    if lock:
        query = query.with_for_update(of=ChatThread)
    row = (await db.execute(query)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Chat not found")
    return row


async def _list_threads(db: AsyncSession, side: str, owner_id: int, skip: int, limit: int) -> List[dict]:
    column = ChatThread.customer_id if side == "customer" else ChatThread.vendor_id
    rows = (await db.execute(
        select(ChatThread, Order).join(Order, Order.id == ChatThread.booking_id)
        .where(column == owner_id)
        .order_by(ChatThread.last_message_at.desc().nullslast(), ChatThread.id.desc())
        .offset(skip).limit(limit)
    )).all()
    return await _threads_json(db, rows, side)


async def _list_messages(db: AsyncSession, side: str, owner_id: int, thread_id: int,
                         after: Optional[int], before: Optional[int], limit: int) -> List[dict]:
    thread, order = await _load_thread(db, thread_id, side, owner_id)
    query = select(ChatMessage).where(ChatMessage.thread_id == thread.id)
    if after is not None:
        messages = (await db.execute(query.where(ChatMessage.id > after)
                                     .order_by(ChatMessage.id).limit(limit))).scalars().all()
    else:
        if before is not None:
            query = query.where(ChatMessage.id < before)
        newest_first = (await db.execute(query.order_by(ChatMessage.id.desc()).limit(limit))).scalars().all()
        messages = list(reversed(newest_first))

    # Reading marks the other party's messages as read.
    other = "vendor" if side == "customer" else "customer"
    now = dt.datetime.utcnow()
    await db.execute(update(ChatMessage).where(
        ChatMessage.thread_id == thread.id, ChatMessage.sender_type == other, ChatMessage.read_at.is_(None),
    ).values(read_at=now))
    if side == "customer":
        thread.customer_unread = 0
    else:
        thread.vendor_unread = 0
    await db.commit()
    return [_message_json(m, order) for m in messages]


async def _send(db: AsyncSession, background: BackgroundTasks, side: str, owner_id: int, sender_user_id: int,
                thread_id: int, text: str) -> dict:
    thread, order = await _load_thread(db, thread_id, side, owner_id, lock=True)
    if not _is_open(order):
        raise HTTPException(status_code=400, detail="This chat is closed")
    text = text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    message = ChatMessage(thread_id=thread.id, sender_type=side, sender_user_id=sender_user_id, body=text)
    db.add(message)
    thread.last_message_at = dt.datetime.utcnow()
    thread.last_message_preview = text[:120]
    if side == "customer":
        thread.vendor_unread = (thread.vendor_unread or 0) + 1
    else:
        thread.customer_unread = (thread.customer_unread or 0) + 1
    await db.commit()
    await db.refresh(message)

    if side == "customer":
        target = (await _vendor_user_ids(db, [thread.vendor_id])).get(thread.vendor_id)
    else:
        target = (await _customer_user_ids(db, [thread.customer_id])).get(thread.customer_id)
    if target:
        background.add_task(
            send_user_push_notification, target, "New message", text[:100],
            {"type": "chat", "thread_id": str(thread.id), "booking_id": order.booking_reference},
        )
    return _message_json(message, order)


# ------------------------------------------------------------------ customer

@router.post("/threads")
@limiter.limit("30/minute")
async def open_thread(
    request: Request,
    body: OpenThreadIn,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Open (or fetch) the chat for one of your bookings. Needs an assigned vendor."""
    order = (await db.execute(select(Order).where(
        Order.booking_reference == body.booking_id.strip(),
        Order.customer_id == current_customer.id,
    ))).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Booking not found")
    if not order.vendor_id or str(order.status or "").upper() not in OPENABLE_STATUSES + ("CANCELLED",):
        raise HTTPException(status_code=400, detail="Chat opens once a professional accepts your booking")

    thread = (await db.execute(select(ChatThread).where(ChatThread.booking_id == order.id))).scalar_one_or_none()
    if thread is None:
        if not _is_open(order):
            raise HTTPException(status_code=400, detail="Chat opens once a professional accepts your booking")
        thread = ChatThread(booking_id=order.id, customer_id=current_customer.id, vendor_id=order.vendor_id)
        db.add(thread)
        try:
            await db.commit()
        except IntegrityError:  # opened twice at once
            await db.rollback()
            thread = (await db.execute(select(ChatThread).where(ChatThread.booking_id == order.id))).scalar_one()
        await db.refresh(thread)
    return (await _threads_json(db, [(thread, order)], "customer"))[0]


@router.get("/threads")
@limiter.limit("60/minute")
async def list_threads(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    return await _list_threads(db, "customer", current_customer.id, skip, limit)


@router.get("/threads/{thread_id}/messages")
@limiter.limit("120/minute")
async def list_messages(
    request: Request,
    thread_id: int,
    after: Optional[int] = Query(None, ge=0, description="Only messages newer than this id (polling)"),
    before: Optional[int] = Query(None, ge=0, description="Only messages older than this id (history)"),
    limit: int = Query(PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Oldest first. Without `after`/`before` you get the latest `limit` messages."""
    return await _list_messages(db, "customer", current_customer.id, thread_id, after, before, limit)


@router.post("/threads/{thread_id}/messages")
@limiter.limit("20/minute")
async def send_message(
    request: Request,
    thread_id: int,
    message_in: MessageIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    return await _send(db, background, "customer", current_customer.id, current_customer.user_id,
                       thread_id, message_in.body)


# -------------------------------------------------------------------- vendor

@vendor_router.get("/threads")
@limiter.limit("60/minute")
async def vendor_list_threads(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor),
):
    return await _list_threads(db, "vendor", current_vendor.id, skip, limit)


@vendor_router.get("/threads/{thread_id}/messages")
@limiter.limit("120/minute")
async def vendor_list_messages(
    request: Request,
    thread_id: int,
    after: Optional[int] = Query(None, ge=0),
    before: Optional[int] = Query(None, ge=0),
    limit: int = Query(PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor),
):
    return await _list_messages(db, "vendor", current_vendor.id, thread_id, after, before, limit)


@vendor_router.post("/threads/{thread_id}/messages")
@limiter.limit("20/minute")
async def vendor_send_message(
    request: Request,
    thread_id: int,
    message_in: MessageIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_vendor),
):
    return await _send(db, background, "vendor", current_vendor.id, current_vendor.user_id,
                       thread_id, message_in.body)
