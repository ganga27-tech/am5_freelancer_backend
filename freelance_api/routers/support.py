from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime
import secrets

from app.db.session import get_db
from app.models.freelancer import Freelancer
from freelance_api.dependencies import get_optional_freelancer
from freelance_api.models import FreelancerFaq, FreelancerSupportTicket
from freelance_api.schemas import (
    ApiResponse,
    FaqItemResponse,
    ContactSupportRequest,
    SupportTicketResponse,
    ReportProblemRequest,
    ReportProblemResponse,
)

router = APIRouter(tags=["FAQs & Support"])

@router.get("/faqs", response_model=ApiResponse[List[FaqItemResponse]])
async def get_faqs(
    audience: Optional[str] = Query("freelancer", description="Audience: freelancer, customer, vendor, or all"),
    category: Optional[str] = Query(None, description="Optional category filter e.g. rewards, kyc, referrals"),
    db: AsyncSession = Depends(get_db)
):
    """Return active FAQs for the freelancer website."""
    conditions = [FreelancerFaq.is_active.is_(True)]
    if audience and audience.lower() != "all":
        conditions.append(FreelancerFaq.audience == audience.lower().strip())
    if category:
        conditions.append(FreelancerFaq.category == category.lower().strip())

    stmt = select(FreelancerFaq).where(and_(*conditions)).order_by(FreelancerFaq.display_order.asc())
    res = await db.execute(stmt)
    faqs = res.scalars().all()

    items = [
        FaqItemResponse(
            faq_id=f.faq_id or f"faq_{f.id}",
            question=f.question,
            answer=f.answer,
            category=f.category,
            display_order=f.display_order
        )
        for f in faqs
    ]

    return ApiResponse(
        success=True,
        message="FAQs retrieved successfully",
        data=items
    )


@router.post("/support/tickets", response_model=ApiResponse[SupportTicketResponse], status_code=status.HTTP_201_CREATED)
async def create_support_ticket(
    req: ContactSupportRequest,
    current_freelancer: Optional[Freelancer] = Depends(get_optional_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Create a support ticket."""
    ticket_num = f"TKT-{datetime.utcnow().strftime('%Y%m')}-{secrets.token_hex(3).upper()}"

    ticket = FreelancerSupportTicket(
        freelancer_id=current_freelancer.id if current_freelancer else None,
        ticket_number=ticket_num,
        ticket_type="support_ticket",
        full_name=req.full_name.strip(),
        email=req.email_address.strip().lower(),
        category=req.query_category.strip(),
        subject=req.subject.strip(),
        description=req.query_description.strip(),
        status="open"
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    return ApiResponse(
        success=True,
        message="Support ticket created successfully",
        data=SupportTicketResponse(
            ticket_id=ticket.id,
            ticket_number=ticket.ticket_number,
            status=ticket.status,
            created_date=ticket.created_at.isoformat() + "Z",
            acknowledgement_message="Thank you for reaching out. An AM5 partner specialist will respond within 24 hours."
        )
    )


@router.post("/support/problem-reports", response_model=ApiResponse[ReportProblemResponse], status_code=status.HTTP_201_CREATED)
async def report_problem(
    req: ReportProblemRequest,
    current_freelancer: Optional[Freelancer] = Depends(get_optional_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Submit a technical or user-reported problem."""
    report_id = f"REP-{datetime.utcnow().strftime('%Y%m')}-{secrets.token_hex(3).upper()}"

    ticket = FreelancerSupportTicket(
        freelancer_id=current_freelancer.id if current_freelancer else None,
        ticket_number=report_id,
        ticket_type="problem_report",
        full_name=current_freelancer.full_name if current_freelancer else "Anonymous User",
        email=current_freelancer.email if current_freelancer else "guest@am5royal.com",
        category=req.problem_category.strip(),
        subject=f"Problem report: {req.problem_category}",
        description=req.problem_description.strip(),
        page_url=req.page_url,
        device_details=req.browser_details or {},
        attachments=req.attachments or [],
        status="open"
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    return ApiResponse(
        success=True,
        message="Problem report submitted successfully",
        data=ReportProblemResponse(
            report_id=ticket.ticket_number,
            status=ticket.status,
            created_date=ticket.created_at.isoformat() + "Z"
        )
    )

