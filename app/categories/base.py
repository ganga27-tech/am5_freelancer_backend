"""Helpers shared by every category module."""
from typing import Dict, List, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor_media import VendorMedia


class SocialMedia(BaseModel):
    """Optional social handles. Either a username/ID or a profile URL is accepted."""
    facebook_id: Optional[str] = None
    instagram_id: Optional[str] = None
    youtube_id: Optional[str] = None
    linkedin_id: Optional[str] = None


def validation_error(errors: Dict[str, List[str]]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": "Validation failed", "errors": errors},
    )


async def load_vendor_media(
    db: AsyncSession, vendor_id: int, media_ids: List[int]
) -> Dict[int, VendorMedia]:
    """Return {media_id: VendorMedia} for ids that exist AND belong to this vendor."""
    if not media_ids:
        return {}
    rows = (
        await db.execute(
            select(VendorMedia).where(
                VendorMedia.id.in_(set(media_ids)),
                VendorMedia.vendor_id == vendor_id,
            )
        )
    ).scalars().all()
    return {m.id: m for m in rows}
