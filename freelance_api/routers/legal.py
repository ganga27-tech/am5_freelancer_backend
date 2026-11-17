from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime

from app.db.session import get_db
from app.models.freelancer import Freelancer
from freelance_api.dependencies import get_current_freelancer
from freelance_api.models import FreelancerLegalPage, FreelancerLegalAcceptance
from freelance_api.schemas import (
    ApiResponse,
    LegalPageResponse,
    RecordLegalAcceptanceRequest,
    LegalAcceptanceResponse,
)

router = APIRouter(tags=["Legal Pages & Compliance"])

@router.get("/legal-pages", response_model=ApiResponse[List[LegalPageResponse]])
async def get_legal_pages(
    slug: Optional[str] = Query(None, description="privacy-policy or terms-and-conditions"),
    db: AsyncSession = Depends(get_db)
):
    """Fetch backend/admin-managed Privacy Policy and Terms & Conditions."""
    conditions = [FreelancerLegalPage.is_active.is_(True)]
    if slug:
        conditions.append(FreelancerLegalPage.slug == slug.lower().strip())

    stmt = select(FreelancerLegalPage).where(and_(*conditions))
    res = await db.execute(stmt)
    pages = res.scalars().all()

    # Fallback default pages if not yet seeded
    if not pages:
        fallback = [
            LegalPageResponse(
                slug="privacy-policy",
                title="AM5 Royal Freelancer Privacy Policy",
                content="""
# Privacy Policy for Freelancers & Partners

Effective Date: October 2026

AM5 Royal is committed to protecting your privacy and ensuring your personal and financial data is handled securely.

### 1. Information Collected
- Basic contact info: Full name, phone number, email address.
- Financial details: Bank account number, IFSC code for payout disbursements.
- Identity verification (KYC): Aadhaar, PAN card, and optional face verification selfie.

### 2. How We Use Your Data
- Processing partner payouts and commissions.
- Preventing fraud and duplicate account creation.
- Providing customer and vendor attribution analytics.

### 3. Data Protection
- Bank account details and identity documents are encrypted at rest.
- We never share your personal information with unauthorized third parties.
                """.strip(),
                version="1.0",
                effective_date="2026-10-01T00:00:00Z",
                last_updated_date="2026-10-23T00:00:00Z"
            ),
            LegalPageResponse(
                slug="terms-and-conditions",
                title="AM5 Royal Freelancer Terms & Conditions",
                content="""
# Terms & Conditions for Freelance Partners

Effective Date: October 2026

By joining the AM5 Freelancer program, you agree to these terms:

### 1. Referral Program Eligibility
- Referral links remain valid for 7 or 15 days as selected. Expired links are not eligible for commission.
- Customer referral bonus is credited upon completion of the user's first paid booking.
- Vendor referral bonus requires successful vendor verification.

### 2. Fraud & Manipulation Prevention
- Self-referrals and artificial device manipulation are strictly forbidden and will result in permanent account suspension and forfeiture of accumulated points.

### 3. Payouts
- Minimum withdrawal threshold is ₹500.
- Payouts are transferred directly to verified bank accounts within 24-48 business hours.
                """.strip(),
                version="1.0",
                effective_date="2026-10-01T00:00:00Z",
                last_updated_date="2026-10-23T00:00:00Z"
            )
        ]
        if slug:
            fallback = [p for p in fallback if p.slug == slug.lower().strip()]
        return ApiResponse(
            success=True,
            message="Legal pages retrieved successfully",
            data=fallback
        )

    items = [
        LegalPageResponse(
            slug=p.slug,
            title=p.title,
            content=p.content,
            version=p.version,
            effective_date=p.effective_date.isoformat() + "Z",
            last_updated_date=p.last_updated_date.isoformat() + "Z"
        )
        for p in pages
    ]

    return ApiResponse(
        success=True,
        message="Legal pages retrieved successfully",
        data=items
    )


@router.post("/freelancer/legal-acceptances", response_model=ApiResponse[LegalAcceptanceResponse], status_code=status.HTTP_201_CREATED)
async def record_legal_acceptance(
    req: RecordLegalAcceptanceRequest,
    request: Request,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Record acceptance when explicit user acknowledgement is required."""
    client_ip = request.client.host if request.client else "unknown"

    acceptance = FreelancerLegalAcceptance(
        freelancer_id=current_freelancer.id,
        document_slug=req.document_slug.lower().strip(),
        document_version=req.document_version.strip(),
        ip_address=client_ip,
        accepted_at=datetime.utcnow()
    )
    db.add(acceptance)
    await db.commit()
    await db.refresh(acceptance)

    return ApiResponse(
        success=True,
        message="Legal acceptance recorded",
        data=LegalAcceptanceResponse(
            acceptance_status="recorded",
            timestamp=acceptance.accepted_at.isoformat() + "Z"
        )
    )

