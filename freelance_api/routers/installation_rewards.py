from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func
from datetime import datetime

from app.db.session import get_db
from app.models.freelancer import Freelancer
from freelance_api.dependencies import get_current_freelancer
from freelance_api.models import (
    FreelancerInstallationRule,
    FreelancerInstallationTracking,
    FreelancerRewardItem,
)
from freelance_api.schemas import (
    ApiResponse,
    PaginatedData,
    InstallationRulesResponse,
    MilestoneRewardRule,
    InstallationStatisticsResponse,
    InstallationTrackingItem,
    InstallationEligibilityResponse,
    MilestoneEligibilityProgress,
    InstallationRewardStatusItem,
)
from freelance_api.service import FreelanceService

router = APIRouter(tags=["App Installation & Activation"])

@router.get("/installation-rewards/rules", response_model=ApiResponse[InstallationRulesResponse])
async def get_installation_rules(
    app_type: Optional[str] = Query("all", description="App type: customer, vendor, or all"),
    db: AsyncSession = Depends(get_db)
):
    """Fetch admin-configured milestones, reward amounts, voucher details and eligibility rules."""
    conditions = [FreelancerInstallationRule.is_active.is_(True)]
    if app_type and app_type.lower() != "all":
        conditions.append(FreelancerInstallationRule.app_type == app_type.lower().strip())

    stmt = select(FreelancerInstallationRule).where(and_(*conditions)).order_by(FreelancerInstallationRule.milestone_target.asc())
    res = await db.execute(stmt)
    rules = res.scalars().all()

    # Fallback default slabs if none seeded in DB
    if not rules:
        default_rules = [
            MilestoneRewardRule(
                milestone_id=1,
                app_type="customer",
                target_count=300,
                reward_amount=1500.0,
                voucher_type="amazon",
                voucher_title="₹1,500 Amazon Voucher",
                voucher_value=1500.0,
                conditions="300 genuine customer app installs with 30-day retention",
                retention_days=30
            ),
            MilestoneRewardRule(
                milestone_id=2,
                app_type="customer",
                target_count=500,
                reward_amount=3000.0,
                voucher_type="amazon",
                voucher_title="₹3,000 Amazon Voucher",
                voucher_value=3000.0,
                conditions="500 genuine customer app installs with 30-day retention",
                retention_days=30
            ),
            MilestoneRewardRule(
                milestone_id=3,
                app_type="customer",
                target_count=1000,
                reward_amount=7500.0,
                voucher_type="cash",
                voucher_title="₹7,500 Cash Payout",
                voucher_value=7500.0,
                conditions="1,000 genuine customer app installs with 30-day retention",
                retention_days=30
            ),
            MilestoneRewardRule(
                milestone_id=4,
                app_type="customer",
                target_count=2500,
                reward_amount=20000.0,
                voucher_type="cash",
                voucher_title="₹20,000 Mega Cash Reward",
                voucher_value=20000.0,
                conditions="2,500 genuine customer app installs with 30-day retention",
                retention_days=30
            ),
            MilestoneRewardRule(
                milestone_id=5,
                app_type="vendor",
                target_count=50,
                reward_amount=2500.0,
                voucher_type="cash",
                voucher_title="₹2,500 Vendor Milestone Bonus",
                voucher_value=2500.0,
                conditions="50 onboarded & verified service vendors",
                retention_days=30
            ),
            MilestoneRewardRule(
                milestone_id=6,
                app_type="vendor",
                target_count=150,
                reward_amount=8000.0,
                voucher_type="cash",
                voucher_title="₹8,000 Vendor Mega Bonus",
                voucher_value=8000.0,
                conditions="150 onboarded & verified service vendors",
                retention_days=30
            ),
        ]
        return ApiResponse(
            success=True,
            message="Installation reward rules retrieved successfully",
            data=InstallationRulesResponse(
                app_type=app_type or "all",
                milestones=[r for r in default_rules if app_type in ("all", None) or r.app_type == app_type],
                retention_days=30,
                last_updated_date=datetime.utcnow().isoformat() + "Z"
            )
        )

    items = [
        MilestoneRewardRule(
            milestone_id=r.id,
            app_type=r.app_type,
            target_count=r.milestone_target,
            reward_amount=float(r.reward_amount),
            currency=r.currency,
            voucher_type=r.voucher_type,
            voucher_title=r.voucher_title,
            voucher_value=float(r.voucher_value or 0.0),
            conditions=r.conditions or "",
            retention_days=r.retention_days
        )
        for r in rules
    ]

    return ApiResponse(
        success=True,
        message="Installation reward rules retrieved successfully",
        data=InstallationRulesResponse(
            app_type=app_type or "all",
            milestones=items,
            retention_days=30,
            last_updated_date=datetime.utcnow().isoformat() + "Z"
        )
    )


@router.get("/installation-rewards/statistics", response_model=ApiResponse[InstallationStatisticsResponse])
async def get_installation_statistics(
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Show separate installation/activation totals and progress for Customer App and Vendor App."""
    stats = await FreelanceService.get_installation_statistics(db, current_freelancer)
    return ApiResponse(
        success=True,
        message="Installation statistics retrieved successfully",
        data=InstallationStatisticsResponse(**stats)
    )


@router.get("/installation-rewards/tracking", response_model=ApiResponse[PaginatedData[InstallationTrackingItem]])
async def list_installation_tracking(
    app_type: Optional[str] = Query(None, description="customer or vendor"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """List installs and activations attributed to the freelancer's referral links."""
    conditions = [FreelancerInstallationTracking.freelancer_id == current_freelancer.id]
    if app_type and app_type.lower() != "all":
        conditions.append(FreelancerInstallationTracking.app_type == app_type.lower().strip())

    count_stmt = select(func.count(FreelancerInstallationTracking.id)).where(and_(*conditions))
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0

    stmt = (
        select(FreelancerInstallationTracking)
        .where(and_(*conditions))
        .order_by(desc(FreelancerInstallationTracking.install_date))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()

    items = [
        InstallationTrackingItem(
            tracking_id=r.tracking_id,
            app_type=r.app_type,
            referral_code=r.referral_code,
            install_date=r.install_date.isoformat() + "Z" if r.install_date else None,
            activation_date=r.activation_date.isoformat() + "Z" if r.activation_date else None,
            retention_days_completed=r.retention_days_completed,
            retention_status=r.retention_status,
            eligibility_status=r.eligibility_status,
            reward_status=r.reward_status
        )
        for r in rows
    ]

    return ApiResponse(
        success=True,
        message="Installation tracking records retrieved successfully",
        data=PaginatedData(
            items=items,
            page=page,
            limit=limit,
            total=total,
            hasMore=(page * limit) < total
        )
    )


@router.get("/installation-rewards/eligibility", response_model=ApiResponse[InstallationEligibilityResponse])
async def get_milestone_eligibility(
    app_type: Optional[str] = Query("customer", description="customer or vendor"),
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Show progress towards each milestone and reward eligibility/status."""
    milestones = await FreelanceService.get_milestone_eligibility(db, current_freelancer, app_type.lower())
    items = [MilestoneEligibilityProgress(**m) for m in milestones]
    return ApiResponse(
        success=True,
        message="Milestone eligibility retrieved successfully",
        data=InstallationEligibilityResponse(
            app_type=app_type,
            milestones=items
        )
    )


@router.get("/installation-rewards/status", response_model=ApiResponse[List[InstallationRewardStatusItem]])
async def get_installation_reward_status(
    app_type: Optional[str] = Query(None, description="customer or vendor"),
    status_filter: Optional[str] = Query(None, alias="status", description="pending, claimed, locked"),
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Return the current state of each installation/activation reward."""
    # Look for reward items tagged with installation
    conditions = [
        FreelancerRewardItem.freelancer_id == current_freelancer.id,
        FreelancerRewardItem.reward_type == "installation"
    ]
    if status_filter and status_filter.lower() != "all":
        conditions.append(FreelancerRewardItem.status == status_filter.lower().strip())

    stmt = select(FreelancerRewardItem).where(and_(*conditions)).order_by(desc(FreelancerRewardItem.created_at))
    res = await db.execute(stmt)
    items = res.scalars().all()

    data = [
        InstallationRewardStatusItem(
            reward_id=r.reward_id,
            app_type=app_type or "customer",
            milestone=300,
            reward_amount=float(r.amount),
            voucher_title=r.title,
            status=r.status,
            eligibility_reason="Qualified 30-day active retention period",
            updated_date=r.updated_at.isoformat() + "Z"
        )
        for r in items
    ]

    return ApiResponse(
        success=True,
        message="Installation reward statuses retrieved successfully",
        data=data
    )

