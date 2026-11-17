from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from freelance_api.schemas import ApiResponse, SearchResponse, SearchResultItem
from freelance_api.service import FreelanceService

router = APIRouter(tags=["Global Search"])

@router.get("/search", response_model=ApiResponse[SearchResponse])
async def search_content(
    q: str = Query(..., min_length=1, max_length=100, description="Search query string"),
    scope: Optional[str] = Query("all", description="Search scope: all, services, faqs, videos"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
    """Search supported website content such as service categories, sub-services, FAQs and demo videos."""
    query_clean = q.strip()
    if not query_clean:
        return ApiResponse(
            success=True,
            message="Empty search query",
            data=SearchResponse(
                query="",
                items=[],
                page=page,
                limit=limit,
                total=0,
                hasMore=False
            )
        )

    items, total = await FreelanceService.search_content(
        db=db,
        query=query_clean,
        scope=scope.lower().strip() if scope else "all",
        page=page,
        limit=limit
    )

    data_items = [SearchResultItem(**item) for item in items]

    return ApiResponse(
        success=True,
        message="Search results retrieved",
        data=SearchResponse(
            query=query_clean,
            items=data_items,
            page=page,
            limit=limit,
            total=total,
            hasMore=(page * limit) < total
        )
    )

