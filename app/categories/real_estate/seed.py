"""Idempotent seed: Real Estate category, subcategories, property types, BHK, furniture."""
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.categories.real_estate import rules
from app.categories.real_estate.models import (
    ReBhkType, ReFurnitureType, RePropertyType, ReSubcategoryPropertyType,
)
from app.models.catalog import ServiceCategory, ServiceSubcategory

CATEGORY_NAME = "Real Estate"
FORM_TYPE = "real_estate"
SUBCATEGORIES = [("Agency", rules.AGENCY), ("Builder", rules.BUILDER), ("Single Owner", rules.SINGLE_OWNER)]
PROPERTY_TYPES = [(rules.RESIDENTIAL, "Residential"), (rules.COMMERCIAL, "Commercial"), (rules.OPEN_LAND, "Open Land")]
BHK = ["1 RK", "1 BHK", "2 BHK", "3 BHK", "4 BHK", "5+ BHK"]
FURNITURE = ["Semi Furnished", "Fully Furnished"]


async def seed(db: AsyncSession, activate: Optional[bool] = None) -> None:
    """activate=None: a NEW category is created INACTIVE (hidden from app category lists) and an
    existing one keeps its current is_active. True/False sets it explicitly."""
    # category (never duplicates an existing "Real Estate" row; just tags its form_type)
    cat = (await db.execute(select(ServiceCategory).where(func.lower(ServiceCategory.name) == CATEGORY_NAME.lower()))).scalars().first()
    if cat is None:
        cat = ServiceCategory(name=CATEGORY_NAME, is_active=bool(activate), form_type=FORM_TYPE)
        db.add(cat)
        await db.flush()
    else:
        if cat.form_type != FORM_TYPE:
            cat.form_type = FORM_TYPE
        if activate is not None:
            cat.is_active = activate

    subs = {}
    for order, (name, key) in enumerate(SUBCATEGORIES):
        sc = (
            await db.execute(
                select(ServiceSubcategory).where(
                    ServiceSubcategory.main_category_id == cat.id, ServiceSubcategory.name == name
                )
            )
        ).scalars().first()
        if sc is None:
            sc = ServiceSubcategory(main_category_id=cat.id, name=name, is_active=True, sort_order=order)
            db.add(sc)
            await db.flush()
        subs[key] = sc

    types = {}
    for code, name in PROPERTY_TYPES:
        t = (await db.execute(select(RePropertyType).where(RePropertyType.code == code))).scalars().first()
        if t is None:
            t = RePropertyType(code=code, name=name)
            db.add(t)
            await db.flush()
        types[code] = t

    for key, allowed in rules.ALLOWED_PROPERTY_TYPES.items():
        for code in allowed:
            exists = (
                await db.execute(
                    select(ReSubcategoryPropertyType.id).where(
                        ReSubcategoryPropertyType.sub_category_id == subs[key].id,
                        ReSubcategoryPropertyType.property_type_id == types[code].id,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                db.add(ReSubcategoryPropertyType(sub_category_id=subs[key].id, property_type_id=types[code].id))

    for i, name in enumerate(BHK):
        if (await db.execute(select(ReBhkType.id).where(ReBhkType.name == name))).scalar_one_or_none() is None:
            db.add(ReBhkType(name=name, sort_order=i))
    for name in FURNITURE:
        if (await db.execute(select(ReFurnitureType.id).where(ReFurnitureType.name == name))).scalar_one_or_none() is None:
            db.add(ReFurnitureType(name=name))
    await db.flush()
