from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func

from app.db.session import get_db
from app.models.freelancer import Freelancer
from freelance_api.dependencies import get_current_freelancer
from freelance_api.models import FreelancerRewardItem
from freelance_api.schemas import (
    ApiResponse,
    PaginatedData,
    RewardsSummaryResponse,
    RewardHistoryItem,
)

router = APIRouter(tags=["Rewards & Cashback"])

@router.get("/rewards/summary", response_model=ApiResponse[RewardsSummaryResponse])
async def get_rewards_summary(
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Show total rewards, approved rewards, pending rewards, processing rewards, paid rewards and cashback rewards."""
    stmt = select(
        FreelancerRewardItem.status,
        FreelancerRewardItem.reward_type,
        func.sum(FreelancerRewardItem.amount).label("sum_amount")
    ).where(
        FreelancerRewardItem.freelancer_id == current_freelancer.id
    ).group_by(FreelancerRewardItem.status, FreelancerRewardItem.reward_type)

    res = await db.execute(stmt)
    rows = res.all()

    total = 0.0
    approved = 0.0
    pending = 0.0
    processing = 0.0
    paid = 0.0
    cashback = 0.0

    for row in rows:
        st = (row.status or "").lower()
        amt = float(row.sum_amount or 0.0)
        total += amt
        if st == "approved":
            approved += amt
        elif st == "pending":
            pending += amt
        elif st == "processing":
            processing += amt
        elif st == "paid":
            paid += amt

        if (row.reward_type or "").lower() == "cashback":
            cashback += amt

    return ApiResponse(
        success=True,
        message="Rewards summary retrieved successfully",
        data=RewardsSummaryResponse(
            total_rewards=total,
            approved_rewards=approved,
            pending_rewards=pending,
            processing_rewards=processing,
            paid_rewards=paid,
            cashback_rewards=cashback,
            currency="INR"
        )
    )


@router.get("/rewards/history", response_model=ApiResponse[PaginatedData[RewardHistoryItem]])
async def get_rewards_history(
    status_filter: Optional[str] = Query("all", alias="status", description="all, approved, pending, processing, paid"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Show reward history with status tabs (All, Approved, Pending, Processing, Paid)."""
    conditions = [FreelancerRewardItem.freelancer_id == current_freelancer.id]
    if status_filter and status_filter.lower() != "all":
        conditions.append(FreelancerRewardItem.status == status_filter.lower().strip())

    count_stmt = select(func.count(FreelancerRewardItem.id)).where(and_(*conditions))
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0

    stmt = (
        select(FreelancerRewardItem)
        .where(and_(*conditions))
        .order_by(desc(FreelancerRewardItem.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()

    items = [
        RewardHistoryItem(
            reward_id=r.reward_id,
            reward_type=r.reward_type,
            title=r.title,
            amount=float(r.amount),
            currency=r.currency,
            status=r.status,
            reference_id=r.reference_id,
            created_at=r.created_at.isoformat() + "Z",
            updated_at=r.updated_at.isoformat() + "Z",
            paid_date=r.paid_date.isoformat() + "Z" if r.paid_date else None
        )
        for r in rows
    ]

    return ApiResponse(
        success=True,
        message="Rewards history retrieved successfully",
        data=PaginatedData(
            items=items,
            page=page,
            limit=limit,
            total=total,
            hasMore=(page * limit) < total
        )
    )

