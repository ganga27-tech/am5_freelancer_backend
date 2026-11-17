import datetime as dt
import random
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.db.session import get_db
from app.dependencies.auth import get_current_customer
from app.models.engagement import FAQ as FAQModel, Ticket as TicketModel
from app.models.orders import Order as OrderModel
from app.models.support import SupportTicketMessage
from app.models.user_location import Customer

router = APIRouter()

MAX_MESSAGES_PER_TICKET = 200
CLOSED_STATUSES = ("CLOSED",)
REOPEN_STATUSES = ("RESOLVED",)


def _iso(value: Optional[dt.datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


@router.get("/FAQ")
async def get_faqs(
    db: AsyncSession = Depends(get_db),
    packageId: Optional[int] = Query(None)
):
    """
    Get FAQs for the platform or a specific package (Matches PDF Page 66).
    """
    query = select(FAQModel).where(FAQModel.active == True)
    if packageId:
        query = query.where(FAQModel.package_id == packageId)

    result = await db.execute(query)
    return result.scalars().all()


# ------------------------------------------------------------------- tickets

class TicketCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=150)
    description: str = Field(..., min_length=5, max_length=2000)
    ticketType: str = Field("others", max_length=30)
    booking_id: Optional[str] = Field(None, max_length=40)  # booking reference


async def _ticket_json(db: AsyncSession, tickets: List[TicketModel]) -> List[dict]:
    """Customer-facing ticket view: no internal fields, with the whole conversation."""
    ids = [t.id for t in tickets]
    replies: Dict[int, List[SupportTicketMessage]] = {i: [] for i in ids}
    if ids:
        rows = (await db.execute(
            select(SupportTicketMessage)
            .where(SupportTicketMessage.ticket_id.in_(ids))
            .order_by(SupportTicketMessage.created_at, SupportTicketMessage.id)
        )).scalars().all()
        for row in rows:
            replies[row.ticket_id].append(row)

    booking_ids = {t.booking_id for t in tickets if t.booking_id}
    refs: Dict[int, str] = {}
    if booking_ids:
        res = await db.execute(
            select(OrderModel.id, OrderModel.booking_reference).where(OrderModel.id.in_(booking_ids)))
        refs = {oid: ref for oid, ref in res.all()}

    result = []
    for t in tickets:
        conversation = [{
            "id": f"t{t.id}",
            "body": t.description,
            "is_staff": False,
            "created_at": _iso(t.created_at),
        }] + [
            {
                "id": str(m.id),
                "body": m.body,
                "is_staff": m.sender_type == "staff",
                "created_at": _iso(m.created_at),
            }
            for m in replies[t.id]
        ]
        result.append({
            "id": t.id,
            "ticket_number": t.ticket_number,
            "title": t.title,
            "description": t.description,
            "ticket_type": t.ticket_type,
            "priority": t.priority,
            "status": t.status,
            "booking_id": refs.get(t.booking_id) if t.booking_id else None,
            "created_at": _iso(t.created_at),
            "updated_at": _iso(t.last_activity or t.updated_at),
            "message_count": len(conversation),
            "messages": conversation,
        })
    return result


@router.post("/ticket")
@limiter.limit("5/minute")
async def create_ticket(
    request: Request,
    body: Optional[TicketCreate] = None,
    title: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
    ticketType: str = "others",
    booking_id: Optional[str] = Query(None, description="Booking reference this ticket is about"),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer)
):
    """
    Create a support ticket. Send a JSON body, or title / description / ticketType as query
    parameters (the older form, still supported).
    """
    if body is None:
        try:
            body = TicketCreate(
                title=(title or "").strip(), description=(description or "").strip(),
                ticketType=ticketType, booking_id=booking_id,
            )
        except Exception:
            raise HTTPException(
                status_code=422,
                detail="Title (3-150 characters) and description (5-2000 characters) are required",
            )
    clean_title, clean_description = body.title.strip(), body.description.strip()
    if len(clean_title) < 3 or len(clean_description) < 5:
        raise HTTPException(status_code=422, detail="Title and description are too short")

    booking_pk = None
    if body.booking_id:
        res = await db.execute(select(OrderModel.id).where(
            OrderModel.booking_reference == body.booking_id.strip(),
            OrderModel.customer_id == current_customer.id,
        ))
        booking_pk = res.scalar_one_or_none()
        if booking_pk is None:
            raise HTTPException(status_code=404, detail="Booking not found")

    new_ticket = TicketModel(
        # Millisecond clock plus a random suffix, so two tickets in the same instant cannot collide.
        ticket_number=f"TKT-{int(time.time() * 1000)}{random.randint(100, 999)}",
        customer_id=current_customer.id,
        user_id=current_customer.user_id,
        booking_id=booking_pk,
        customer_name=current_customer.full_name,
        customer_email=current_customer.email,
        title=clean_title,
        description=clean_description,
        ticket_type=(body.ticketType.strip() or "others").upper(),
        user_type="CUSTOMER",
        status="OPEN",
        priority="NORMAL",
        message_count=0,
        last_activity=dt.datetime.utcnow(),
    )
    db.add(new_ticket)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Could not create the ticket, please try again")
    await db.refresh(new_ticket)
    return {"message": "New ticket created successfully", "ticketId": new_ticket.id, "ticketNumber": new_ticket.ticket_number}


@router.get("/tickets")
@limiter.limit("30/minute")
async def get_my_tickets(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status, e.g. OPEN"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer)
):
    """
    The logged-in customer's tickets, most recent activity first, each with its conversation.
    """
    query = select(TicketModel).where(TicketModel.customer_id == current_customer.id)
    if status and status.strip():
        query = query.where(TicketModel.status == status.strip().upper())
    query = query.order_by(TicketModel.last_activity.desc(), TicketModel.id.desc()).offset(skip).limit(limit)
    tickets = (await db.execute(query)).scalars().all()
    return await _ticket_json(db, tickets)


async def _own_ticket(db: AsyncSession, ticket_id: int, customer: Customer, lock: bool = False) -> TicketModel:
    query = select(TicketModel).where(TicketModel.id == ticket_id, TicketModel.customer_id == customer.id)
    if lock:
        query = query.with_for_update()
    ticket = (await db.execute(query)).scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.get("/tickets/{ticket_id}")
@limiter.limit("60/minute")
async def get_ticket(
    request: Request,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    ticket = await _own_ticket(db, ticket_id, current_customer)
    return (await _ticket_json(db, [ticket]))[0]


class TicketMessageCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


@router.post("/tickets/{ticket_id}/messages")
@limiter.limit("10/minute")
async def add_ticket_message(
    request: Request,
    ticket_id: int,
    message_in: TicketMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Customer reply on their own ticket. A closed ticket cannot be replied to; a resolved one is reopened."""
    ticket = await _own_ticket(db, ticket_id, current_customer, lock=True)
    status_upper = str(ticket.status or "").upper()
    if status_upper in CLOSED_STATUSES:
        raise HTTPException(status_code=400, detail="This ticket is closed. Please raise a new ticket.")
    text = message_in.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Message cannot be empty")
    if (ticket.message_count or 0) >= MAX_MESSAGES_PER_TICKET:
        raise HTTPException(status_code=400, detail="This ticket has too many messages. Please raise a new ticket.")

    message = SupportTicketMessage(ticket_id=ticket.id, sender_type="customer", sender_id=current_customer.id, body=text)
    db.add(message)
    ticket.message_count = (ticket.message_count or 0) + 1
    ticket.last_activity = dt.datetime.utcnow()
    if status_upper in REOPEN_STATUSES:
        ticket.status = "OPEN"
        ticket.resolved_at = None
    await db.commit()
    await db.refresh(message)
    return {
        "id": str(message.id),
        "body": message.body,
        "is_staff": False,
        "created_at": _iso(message.created_at),
        "ticket_status": ticket.status,
    }
