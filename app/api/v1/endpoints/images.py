from fastapi import APIRouter, Depends, Query, File, UploadFile, HTTPException
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.db.session import get_db
from app.models.engagement import Banner as BannerModel
from app.models.user_location import City as CityModel
from app.services.upload_service import upload_service

router = APIRouter()

@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...)
):
    """
    Upload an image to Cloudflare R2 and return the URL.
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")
    
    contents = await file.read()
    url = await upload_service.upload_file(contents, file.filename, file.content_type)
    
    if not url:
        raise HTTPException(status_code=500, detail="Failed to upload image")
    
    return {"url": url}

@router.get("/themeImages")
async def get_theme_images(
    db: AsyncSession = Depends(get_db),
    city: Optional[str] = Query(None, description="Name of the city"),
    requestedBy: str = Query("user")
):
    """
    Get banner and theme images for a specific city (Matches PDF Page 42).
    """
    query = select(BannerModel).where(BannerModel.active == True)

    if city and city.strip():
        # Match every city with that name (e.g. "Delhi" / "New Delhi") and also
        # include banners with no city, which are shown everywhere.
        city_ids = (
            await db.execute(
                select(CityModel.id).where(CityModel.name.ilike(f"%{city.strip()}%"))
            )
        ).scalars().all()
        query = query.where(
            or_(BannerModel.city_id.is_(None), BannerModel.city_id.in_(city_ids))
        )

    result = await db.execute(query.order_by(BannerModel.position, BannerModel.id))
    banners = result.scalars().all()

    return {
        "imageUrls": [b.image_url for b in banners]
    }
