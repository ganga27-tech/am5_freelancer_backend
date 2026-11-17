from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.categories.real_estate import service
from app.categories.real_estate.schemas import PropertyRequest, ShowcaseRequest
from app.db.session import get_db
from app.dependencies.auth import get_current_token_payload, get_current_vendor
from app.models.vendor import Vendor

router = APIRouter()


# ------------------------------ master ---------------------------------
@router.get("/master")
async def get_master(
    sub_category_id: Optional[int] = Query(None, description="Filter property types for one subcategory"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_token_payload),
):
    """Subcategories (with reel/showcase flags), property types, BHK and furniture options."""
    return await service.master_data(db, sub_category_id)


# ----------------------------- properties ------------------------------
@router.post("/properties", status_code=status.HTTP_201_CREATED)
async def create_property(
    body: PropertyRequest,
    vendor: Vendor = Depends(get_current_vendor),
    db: AsyncSession = Depends(get_db),
):
    prop = await service.create_property(db, vendor, body)
    return {"message": "Property saved successfully", "id": prop.id, "status": "saved"}


@router.get("/properties")
async def list_properties(
    vendor: Vendor = Depends(get_current_vendor),
    db: AsyncSession = Depends(get_db),
):
    props = await service.list_properties(db, vendor)
    return {"items": await service.serialize(db, props), "total": len(props)}


@router.get("/properties/{property_id}")
async def get_property(
    property_id: int,
    vendor: Vendor = Depends(get_current_vendor),
    db: AsyncSession = Depends(get_db),
):
    prop = await service.get_owned_property(db, vendor, property_id)
    return (await service.serialize(db, [prop]))[0]


@router.put("/properties/{property_id}")
async def update_property(
    property_id: int,
    body: PropertyRequest,
    vendor: Vendor = Depends(get_current_vendor),
    db: AsyncSession = Depends(get_db),
):
    """Full replace: send the complete property body."""
    prop = await service.update_property(db, vendor, property_id, body)
    return {"message": "Property updated successfully", "id": prop.id, "status": "saved"}


@router.delete("/properties/{property_id}")
async def delete_property(
    property_id: int,
    vendor: Vendor = Depends(get_current_vendor),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_property(db, vendor, property_id)
    return {"message": "Property deleted successfully"}


# ------------------------------ showcase -------------------------------
@router.post("/showcase", status_code=status.HTTP_201_CREATED)
async def create_showcase(
    body: ShowcaseRequest,
    vendor: Vendor = Depends(get_current_vendor),
    db: AsyncSession = Depends(get_db),
):
    data = await service.save_showcase(db, vendor, body)
    return {"message": "Property Showcase locations saved successfully", "vendor_id": vendor.id, **data}


@router.get("/showcase")
async def get_showcase(
    vendor: Vendor = Depends(get_current_vendor),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_showcase(db, vendor)


@router.put("/showcase")
async def update_showcase(
    body: ShowcaseRequest,
    vendor: Vendor = Depends(get_current_vendor),
    db: AsyncSession = Depends(get_db),
):
    data = await service.replace_showcase(db, vendor, body)
    return {"message": "Property Showcase locations updated successfully", "vendor_id": vendor.id, **data}


@router.delete("/showcase")
async def delete_showcase(
    vendor: Vendor = Depends(get_current_vendor),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_showcase(db, vendor)
    return {"message": "Property Showcase locations deleted successfully"}
