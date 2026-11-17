from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from datetime import datetime

from app.db.session import get_db
from freelance_api.schemas import ApiResponse, BannerItemResponse, DemoVideoItemResponse
from freelance_api.models import FreelancerBanner, FreelancerDemoVideo

router = APIRouter(tags=["Home & Banners"])

@router.get("/banners", response_model=ApiResponse[List[BannerItemResponse]])
async def get_banners(
    placement: Optional[str] = Query("home", description="Placement: home, services, refer_earn, installation_activation, rewards_cashback, earnings_wallet, profile"),
    audience: Optional[str] = Query(None, description="Audience filter e.g. freelancer, customer, vendor"),
    category_id: Optional[int] = Query(None, description="Filter banners for a specific service category"),
    db: AsyncSession = Depends(get_db)
):
    """Return active banners by placement and audience."""
    now = datetime.utcnow()
    conditions = [
        FreelancerBanner.is_active.is_(True),
        or_(FreelancerBanner.start_date.is_(None), FreelancerBanner.start_date <= now),
        or_(FreelancerBanner.end_date.is_(None), FreelancerBanner.end_date >= now),
    ]

    if placement and placement.lower() != "all":
        conditions.append(FreelancerBanner.placement == placement.lower().strip())

    if audience:
        conditions.append(FreelancerBanner.target_audience == audience.lower().strip())

    if category_id:
        conditions.append(FreelancerBanner.category_id == category_id)

    stmt = select(FreelancerBanner).where(and_(*conditions)).order_by(FreelancerBanner.priority.desc())
    res = await db.execute(stmt)
    banners = res.scalars().all()

    items = [
        BannerItemResponse(
            id=b.banner_id or f"bnr_{b.id}",
            title=b.title,
            subtitle=b.subtitle,
            image_url=b.image_url,
            mobile_image_url=b.mobile_image_url or b.image_url,
            placement=b.placement,
            target_audience=b.target_audience,
            action_type=b.action_type,
            action_value=b.action_value,
            priority=b.priority,
            start_date=b.start_date.isoformat() + "Z" if b.start_date else None,
            end_date=b.end_date.isoformat() + "Z" if b.end_date else None,
            active=b.is_active,
        )
        for b in banners
    ]

    return ApiResponse(
        success=True,
        message="Active banners retrieved successfully",
        data=items
    )


@router.get("/demo-videos", response_model=ApiResponse[List[DemoVideoItemResponse]])
async def get_demo_videos(
    audience: Optional[str] = Query("freelancer", description="Target audience: freelancer, customer, vendor"),
    video_type: Optional[str] = Query(None, alias="type", description="Video type: customer_app, vendor_app, rewards_guide, freelancer_guide"),
    db: AsyncSession = Depends(get_db)
):
    """Return tutorial/demo videos for Customer App, Vendor App, Rewards Guide and Freelancer Guide."""
    conditions = [FreelancerDemoVideo.is_active.is_(True)]

    if audience and audience.lower() != "all":
        conditions.append(FreelancerDemoVideo.audience == audience.lower().strip())

    if video_type:
        conditions.append(FreelancerDemoVideo.video_type == video_type.lower().strip())

    stmt = select(FreelancerDemoVideo).where(and_(*conditions)).order_by(FreelancerDemoVideo.display_order.asc())
    res = await db.execute(stmt)
    videos = res.scalars().all()

    items = [
        DemoVideoItemResponse(
            video_id=v.video_id or f"vid_{v.id}",
            title=v.title,
            type=v.video_type,
            video_url=v.video_url,
            thumbnail_url=v.thumbnail_url,
            duration=v.duration or "03:00",
            display_order=v.display_order,
            active_status=v.is_active
        )
        for v in videos
    ]

    return ApiResponse(
        success=True,
        message="Demo videos retrieved successfully",
        data=items
    )

