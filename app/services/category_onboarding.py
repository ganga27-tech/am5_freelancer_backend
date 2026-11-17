from sqlalchemy.ext.asyncio import AsyncSession

from app.categories.registry import CATEGORIES


async def vendor_has_category_details(db: AsyncSession, vendor_id: int) -> bool:
    """True if the vendor completed the details form of ANY registered category module.

    Used next to the legacy `vendor_services` check so non-Home-Services vendors
    can continue through the existing registration flow.
    """
    for c in CATEGORIES:
        if await c.has_details(db, vendor_id):
            return True
    return False
