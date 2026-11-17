from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func

from app.db.session import get_db
from app.models.freelancer import Freelancer
from freelance_api.dependencies import get_current_freelancer
from freelance_api.models import FreelancerWalletTransaction
from freelance_api.schemas import (
    ApiResponse,
    PaginatedData,
    WalletSummaryResponse,
    WalletTransactionItem,
    PayoutRequestInput,
    PayoutRequestResponse,
)
from freelance_api.service import FreelanceService

router = APIRouter(tags=["Earnings & Wallet"])

@router.get("/wallet/summary", response_model=ApiResponse[WalletSummaryResponse])
async def get_wallet_summary(
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Show earnings and wallet balances."""
    # Find last transaction date
    stmt_last = select(FreelancerWalletTransaction.created_at).where(
        FreelancerWalletTransaction.freelancer_id == current_freelancer.id
    ).order_by(desc(FreelancerWalletTransaction.created_at)).limit(1)
    res_last = await db.execute(stmt_last)
    last_dt = res_last.scalar_one_or_none()

    return ApiResponse(
        success=True,
        message="Wallet summary retrieved successfully",
        data=WalletSummaryResponse(
            total_earnings=float(current_freelancer.total_earnings or 0.0),
            available_balance=float(current_freelancer.available_balance or 0.0),
            pending_balance=float(current_freelancer.pending_balance or 0.0),
            processing_balance=float(current_freelancer.processing_balance or 0.0),
            total_withdrawn=float(current_freelancer.total_withdrawn or 0.0),
            currency="INR",
            last_transaction_date=last_dt.isoformat() + "Z" if last_dt else None
        )
    )


@router.get("/wallet/transactions", response_model=ApiResponse[PaginatedData[WalletTransactionItem]])
async def list_wallet_transactions(
    type_filter: Optional[str] = Query(None, alias="type", description="credit, debit"),
    category: Optional[str] = Query(None, description="referral_reward, installation_reward, cashback, withdrawal"),
    status_filter: Optional[str] = Query(None, alias="status", description="completed, pending, failed"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    sort: Optional[str] = Query("createdAt:desc", description="Sort string e.g. createdAt:desc"),
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """List wallet credits, debits, rewards, cashback and adjustments."""
    conditions = [FreelancerWalletTransaction.freelancer_id == current_freelancer.id]

    if type_filter and type_filter.lower() != "all":
        conditions.append(FreelancerWalletTransaction.transaction_type == type_filter.lower().strip())

    if category and category.lower() != "all":
        conditions.append(FreelancerWalletTransaction.category == category.lower().strip())

    if status_filter and status_filter.lower() != "all":
        conditions.append(FreelancerWalletTransaction.status == status_filter.lower().strip())

    count_stmt = select(func.count(FreelancerWalletTransaction.id)).where(and_(*conditions))
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0

    order_clause = desc(FreelancerWalletTransaction.created_at) if "desc" in (sort or "").lower() else FreelancerWalletTransaction.created_at.asc()

    stmt = (
        select(FreelancerWalletTransaction)
        .where(and_(*conditions))
        .order_by(order_clause)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()

    items = [
        WalletTransactionItem(
            transaction_id=r.transaction_id,
            type=r.transaction_type,
            category=r.category,
            description=r.description,
            amount=float(r.amount),
            currency=r.currency,
            status=r.status,
            balance_after=float(r.balance_after) if r.balance_after is not None else None,
            date=r.created_at.isoformat() + "Z",
            reference_id=r.reference_id
        )
        for r in rows
    ]

    return ApiResponse(
        success=True,
        message="Wallet transactions retrieved successfully",
        data=PaginatedData(
            items=items,
            page=page,
            limit=limit,
            total=total,
            hasMore=(page * limit) < total
        )
    )


@router.post("/wallet/payout-request", response_model=ApiResponse[PayoutRequestResponse], status_code=status.HTTP_201_CREATED)
async def request_payout(
    req: PayoutRequestInput,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Submit a wallet withdrawal / payout request to the freelancer's registered bank account."""
    try:
        payout = await FreelanceService.create_payout_request(db, current_freelancer, req.amount)
        return ApiResponse(
            success=True,
            message="Payout request submitted successfully. Processing will take 24-48 hours.",
            data=PayoutRequestResponse(
                payout_id=payout.payout_id,
                amount=float(payout.amount),
                currency=payout.currency,
                bank_name=payout.bank_name or "Bank Account",
                masked_account_number=payout.bank_account_number or "",
                status=payout.status,
                created_at=payout.created_at.isoformat() + "Z"
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Payout request failed: {str(e)}")

