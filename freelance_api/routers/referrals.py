from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func

from app.db.session import get_db
from app.models.freelancer import Freelancer
from freelance_api.dependencies import get_current_freelancer
from freelance_api.models import FreelancerReferralLink, FreelancerReferralReward
from freelance_api.schemas import (
    ApiResponse,
    PaginatedData,
    GenerateReferralLinkRequest,
    ReferralLinkItemResponse,
    ReferralValidationResponse,
    ReferralRewardsSummaryResponse,
    ReferralLevelProgressResponse,
    ReferralPointHistoryItem,
    ReferralRulesResponse,
    ReferralRuleItem,
)
from freelance_api.service import FreelanceService

router = APIRouter(tags=["Referrals & Refer & Earn"])

@router.post("/referrals/links", response_model=ApiResponse[ReferralLinkItemResponse], status_code=status.HTTP_201_CREATED)
async def generate_referral_link(
    req: GenerateReferralLinkRequest,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Generate a shareable referral link for Customer, Vendor, or a Sub-service (7 or 15 days validity)."""
    try:
        link = await FreelanceService.generate_referral_link(
            db=db,
            freelancer=current_freelancer,
            referral_type=req.referral_type,
            validity_days=req.validity_days,
            target_sub_service_id=req.target_sub_service_id
        )
        return ApiResponse(
            success=True,
            message="Referral link generated successfully",
            data=ReferralLinkItemResponse(
                referral_id=f"ref_{link.id}",
                referral_code=link.referral_code,
                referral_type=link.referral_type,
                target_service_id=link.target_sub_service_id,
                target_service_name=link.target_sub_service_name,
                url=link.url,
                created_at=link.created_at.isoformat() + "Z",
                expires_at=link.expires_at.isoformat() + "Z",
                status=link.status,
                clicks_count=link.clicks_count,
                conversions_count=link.conversions_count
            )
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to generate link: {str(e)}")


@router.get("/referrals/validate/{code}", response_model=ApiResponse[ReferralValidationResponse])
async def validate_referral_link(code: str, db: AsyncSession = Depends(get_db)):
    """Check whether a referral link or code is valid when opened or used."""
    result = await FreelanceService.validate_referral_code(db, code)
    if not result.get("valid"):
        return ApiResponse(
            success=False,
            message=f"Referral code is {result.get('status', 'invalid')}",
            data=ReferralValidationResponse(
                valid=False,
                status=result.get("status", "invalid"),
                referral_type=result.get("referral_type"),
                expires_at=result.get("expires_at"),
            )
        )

    return ApiResponse(
        success=True,
        message="Referral link is active and valid",
        data=ReferralValidationResponse(
            valid=True,
            status=result["status"],
            referral_type=result["referral_type"],
            target_service=result.get("target_service"),
            expires_at=result.get("expires_at"),
            referrer_name=result.get("referrer_name")
        )
    )


@router.get("/referrals/links", response_model=ApiResponse[PaginatedData[ReferralLinkItemResponse]])
async def list_referral_links(
    type_filter: Optional[str] = Query(None, alias="type", description="customer, vendor, service"),
    status_filter: Optional[str] = Query(None, alias="status", description="active, expired, revoked"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """List the authenticated freelancer's previously generated links."""
    conditions = [FreelancerReferralLink.freelancer_id == current_freelancer.id]

    if type_filter and type_filter.lower() != "all":
        conditions.append(FreelancerReferralLink.referral_type == type_filter.lower().strip())

    if status_filter and status_filter.lower() != "all":
        conditions.append(FreelancerReferralLink.status == status_filter.lower().strip())

    count_stmt = select(func.count(FreelancerReferralLink.id)).where(and_(*conditions))
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0

    stmt = (
        select(FreelancerReferralLink)
        .where(and_(*conditions))
        .order_by(desc(FreelancerReferralLink.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    res = await db.execute(stmt)
    links = res.scalars().all()

    items = [
        ReferralLinkItemResponse(
            referral_id=f"ref_{l.id}",
            referral_code=l.referral_code,
            referral_type=l.referral_type,
            target_service_id=l.target_sub_service_id,
            target_service_name=l.target_sub_service_name,
            url=l.url,
            created_at=l.created_at.isoformat() + "Z",
            expires_at=l.expires_at.isoformat() + "Z",
            status=l.status,
            clicks_count=l.clicks_count,
            conversions_count=l.conversions_count
        )
        for l in links
    ]

    return ApiResponse(
        success=True,
        message="Referral links retrieved successfully",
        data=PaginatedData(
            items=items,
            page=page,
            limit=limit,
            total=total,
            hasMore=(page * limit) < total
        )
    )


@router.get("/referrals/rewards/summary", response_model=ApiResponse[ReferralRewardsSummaryResponse])
async def get_referral_rewards_summary(
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Show total referral points and point balance summary."""
    total_pts = current_freelancer.total_points or 0
    # Pending points from uncompleted activations or bookings
    stmt_pending = select(func.coalesce(func.sum(FreelancerReferralReward.points), 0)).where(
        and_(
            FreelancerReferralReward.freelancer_id == current_freelancer.id,
            FreelancerReferralReward.status == "pending"
        )
    )
    res_pen = await db.execute(stmt_pending)
    pending_pts = int(res_pen.scalar() or 0)

    # 1 point = ₹1
    currency_equiv = float(total_pts * 1.0)

    return ApiResponse(
        success=True,
        message="Referral rewards summary retrieved successfully",
        data=ReferralRewardsSummaryResponse(
            total_points=total_pts,
            available_points=total_pts,
            pending_points=pending_pts,
            redeemed_points=0,
            currency_equivalent=currency_equiv
        )
    )


@router.get("/referrals/level-progress", response_model=ApiResponse[ReferralLevelProgressResponse])
async def get_level_progress(current_freelancer: Freelancer = Depends(get_current_freelancer)):
    """Show current level, next level and progress to next level."""
    prog = await FreelanceService.get_level_progress(current_freelancer)
    return ApiResponse(
        success=True,
        message="Level and progress retrieved successfully",
        data=ReferralLevelProgressResponse(**prog)
    )


@router.get("/referrals/points/history", response_model=ApiResponse[PaginatedData[ReferralPointHistoryItem]])
async def get_points_history(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Show when and why referral points were earned or adjusted."""
    conditions = [FreelancerReferralReward.freelancer_id == current_freelancer.id]
    if status_filter and status_filter.lower() != "all":
        conditions.append(FreelancerReferralReward.status == status_filter.lower().strip())

    count_stmt = select(func.count(FreelancerReferralReward.id)).where(and_(*conditions))
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0

    stmt = (
        select(FreelancerReferralReward)
        .where(and_(*conditions))
        .order_by(desc(FreelancerReferralReward.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    res = await db.execute(stmt)
    rewards = res.scalars().all()

    items = [
        ReferralPointHistoryItem(
            transaction_id=f"TXN_{r.id}",
            event_description=r.description,
            points=r.points,
            amount=float(r.amount) if r.amount else None,
            status=r.status,
            created_at=r.created_at.isoformat() + "Z",
            reference_id=r.reference_id
        )
        for r in rewards
    ]

    return ApiResponse(
        success=True,
        message="Points history retrieved successfully",
        data=PaginatedData(
            items=items,
            page=page,
            limit=limit,
            total=total,
            hasMore=(page * limit) < total
        )
    )


@router.get("/referrals/rules", response_model=ApiResponse[ReferralRulesResponse])
async def get_referral_rules():
    """Fetch admin-configured referral program rules, point values and guidelines."""
    rules = [
        ReferralRuleItem(
            tier="Bronze (0-250 Points)",
            criteria="New partners & starter level",
            points_per_referral=50,
            cash_value=50.0,
            description="Earn 50 points per customer signup who books their first service."
        ),
        ReferralRuleItem(
            tier="Silver (251-1000 Points)",
            criteria="5+ active customer or vendor conversions",
            points_per_referral=75,
            cash_value=75.0,
            description="Earn 75 points per referral + 5% recurring booking commission."
        ),
        ReferralRuleItem(
            tier="Gold (1001-3000 Points)",
            criteria="15+ active customer or vendor conversions",
            points_per_referral=100,
            cash_value=100.0,
            description="Earn 100 points per referral + 7.5% recurring commission + ₹1000 milestone bonus."
        ),
        ReferralRuleItem(
            tier="Platinum (3001+ Points)",
            criteria="30+ conversions with 30-day retention",
            points_per_referral=150,
            cash_value=150.0,
            description="Top VIP tier: 150 points per referral + 10% commission + executive support."
        ),
    ]
    guidelines = [
        "Referral links expire in 7 or 15 days as selected during creation.",
        "Expired links do not qualify for referral credit.",
        "Points are credited once the referred customer completes their first verified order.",
        "Vendor referrals require completed KYC and active profile status.",
        "Self-referral or fraudulent device manipulation results in immediate account disqualification."
    ]

    return ApiResponse(
        success=True,
        message="Referral rules retrieved successfully",
        data=ReferralRulesResponse(
            rules=rules,
            guidelines=guidelines,
            retention_period_days=30
        )
    )

