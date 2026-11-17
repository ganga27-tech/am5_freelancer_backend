from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.db.session import get_db
from app.models.catalog import ServiceCategory, ServiceSubcategory
from freelance_api.schemas import (
    ApiResponse,
    ServiceCategoryItemResponse,
    ServiceSubcategoryItemResponse,
)

router = APIRouter(tags=["Services & Categories"])

@router.get("/service-categories", response_model=ApiResponse[List[ServiceCategoryItemResponse]])
async def get_service_categories(
    status_filter: Optional[str] = Query("active", alias="status", description="Status filter: active, all"),
    db: AsyncSession = Depends(get_db)
):
    """Return active main categories, including Home Services."""
    conditions = []
    if status_filter == "active":
        conditions.append(ServiceCategory.is_active.is_(True))

    stmt = select(ServiceCategory).where(and_(*conditions)) if conditions else select(ServiceCategory)
    res = await db.execute(stmt)
    categories = res.scalars().all()

    items = [
        ServiceCategoryItemResponse(
            id=cat.id,
            name=cat.name,
            slug=cat.name.lower().strip().replace(" ", "-"),
            category_image_url=cat.icon,
            banner_url=cat.icon,
            active_status=cat.is_active,
            display_order=0
        )
        for cat in categories
    ]

    return ApiResponse(
        success=True,
        message="Service categories retrieved successfully",
        data=items
    )


@router.get("/service-categories/{categoryId}/subcategories", response_model=ApiResponse[List[ServiceSubcategoryItemResponse]])
async def get_subcategories(
    categoryId: int,
    status_filter: Optional[str] = Query("active", alias="status", description="Status filter: active, all"),
    db: AsyncSession = Depends(get_db)
):
    """Return sub-services under the selected main category."""
    # Check parent category
    stmt_cat = select(ServiceCategory).where(ServiceCategory.id == categoryId)
    res_cat = await db.execute(stmt_cat)
    cat = res_cat.scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service category not found")

    conditions = [ServiceSubcategory.main_category_id == categoryId]
    if status_filter == "active":
        conditions.append(ServiceSubcategory.is_active.is_(True))

    stmt = select(ServiceSubcategory).where(and_(*conditions)).order_by(ServiceSubcategory.sort_order.asc())
    res = await db.execute(stmt)
    subs = res.scalars().all()

    items = [
        ServiceSubcategoryItemResponse(
            id=sub.id,
            name=sub.name,
            slug=sub.name.lower().strip().replace(" ", "-"),
            image_url=sub.icon_url,
            banner_url=sub.icon_url,
            active_status=sub.is_active,
            referral_eligibility=True  # All active subservices are eligible for referral commission
        )
        for sub in subs
    ]

    return ApiResponse(
        success=True,
        message="Subcategories retrieved successfully",
        data=items
    )

