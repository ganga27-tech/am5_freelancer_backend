from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.categories.base import SocialMedia, load_vendor_media, validation_error
from app.categories.real_estate import rules
from app.categories.real_estate.models import (
    ReBhkType, ReFurnitureType, ReProperty, RePropertyBhk, RePropertyMedia,
    RePropertyType, ReShowcase, ReSubcategoryPropertyType,
    ReCoverageState, ReCoverageDistrict, RePropertyCoverageLocation,
)
from app.categories.real_estate.schemas import PropertyRequest, ShowcaseRequest
from app.models.catalog import ServiceCategory, ServiceSubcategory
from app.models.vendor import Vendor

FORM_TYPE = "real_estate"


# ----------------------------- lookups ---------------------------------
async def get_subcategory_key(db: AsyncSession, sub_category_id: int) -> str:
    """Resolve a subcategory id to agency/builder/single_owner, or 422."""
    row = (
        await db.execute(
            select(ServiceSubcategory.name)
            .join(ServiceCategory, ServiceCategory.id == ServiceSubcategory.main_category_id)
            .where(
                ServiceSubcategory.id == sub_category_id,
                ServiceSubcategory.is_active == True,  # noqa: E712
                ServiceCategory.form_type == FORM_TYPE,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise validation_error({"sub_category_id": ["Invalid Real Estate subcategory"]})
    return rules.subcategory_key(row)


async def _property_type_code(db: AsyncSession, sub_category_id: int, property_type_id: int) -> str:
    """Property type must exist AND be linked to the subcategory (master-data driven)."""
    code = (
        await db.execute(
            select(RePropertyType.code)
            .join(ReSubcategoryPropertyType, ReSubcategoryPropertyType.property_type_id == RePropertyType.id)
            .where(
                RePropertyType.id == property_type_id,
                RePropertyType.is_active == True,  # noqa: E712
                ReSubcategoryPropertyType.sub_category_id == sub_category_id,
            )
        )
    ).scalar_one_or_none()
    if code is None:
        raise validation_error({"property_type_id": ["Invalid property type for this subcategory"]})
    return code


# ----------------------------- properties ------------------------------
async def _validate_selling_coverage(db: AsyncSession, sub_key: str, coverage) -> list:
    mode = coverage.mode
    locations = coverage.locations
    allowed = {"PAN_INDIA", "STATE", "DISTRICT"} if sub_key in (rules.AGENCY, rules.BUILDER) else {"LOCAL_ONLY"}
    if mode not in allowed:
        raise validation_error({"selling_coverage.mode": [f"{mode} coverage is not allowed for {sub_key}"]})

    state_ids = {item.state_id for item in locations}
    states = set()
    if state_ids:
        states = set((await db.execute(
            select(ReCoverageState.id).where(ReCoverageState.id.in_(state_ids))
        )).scalars())
    if states != state_ids:
        raise validation_error({"selling_coverage.locations": ["Unknown State ID"]})

    district_ids = {item.district_id for item in locations if item.district_id is not None}
    district_state = {}
    if district_ids:
        district_state = dict((await db.execute(
            select(ReCoverageDistrict.id, ReCoverageDistrict.state_id)
            .where(ReCoverageDistrict.id.in_(district_ids))
        )).all())
    if set(district_state) != district_ids:
        raise validation_error({"selling_coverage.locations": ["Unknown District ID"]})
    if any(district_state[item.district_id] != item.state_id
           for item in locations if item.district_id is not None):
        raise validation_error({"selling_coverage.locations": ["District does not belong to the selected State"]})
    return [{"state_id": item.state_id, "district_id": item.district_id} for item in locations]

async def _validated_parts(
    db: AsyncSession, vendor: Vendor, p: PropertyRequest
) -> Tuple[str, dict, dict]:
    """Run all validation. Returns (type_code, columns, media_by_role)."""
    sub_key = await get_subcategory_key(db, p.sub_category_id)
    type_code = await _property_type_code(db, p.sub_category_id, p.property_type_id)
    coverage_locations = await _validate_selling_coverage(db, sub_key, p.selling_coverage)

    res, com, land = p.residential_details, p.commercial_details, p.open_land_details
    built_up = (res.built_up_area if res else None) if type_code == rules.RESIDENTIAL else (
        (com.built_up_area if com else None) if type_code == rules.COMMERCIAL else None
    )
    bhk_ids = list(dict.fromkeys(res.bhk_type_ids)) if (res and type_code == rules.RESIDENTIAL) else []
    furniture_id = res.furniture_type_id if (res and type_code == rules.RESIDENTIAL) else None
    per_yard = land.price_per_square_yard if (land and type_code == rules.OPEN_LAND) else None

    errors = rules.validate_property(
        sub_key=sub_key,
        type_code=type_code,
        sale_price=p.pricing.sale_price,
        built_up_area=built_up,
        furniture_type_id=furniture_id,
        bhk_type_ids=bhk_ids,
        price_per_sq_yard=per_yard,
        image_count=len(p.media.image_ids),
        video_count=len(p.media.video_ids),
        has_reel=p.media.reel_id is not None,
    )

    # master-data existence checks
    if bhk_ids:
        found = set(
            (await db.execute(select(ReBhkType.id).where(ReBhkType.id.in_(bhk_ids), ReBhkType.is_active == True))).scalars()  # noqa: E712
        )
        if found != set(bhk_ids):
            errors.setdefault("residential_details.bhk_type_ids", []).append("Invalid BHK type")
    if furniture_id:
        ok = (
            await db.execute(select(ReFurnitureType.id).where(ReFurnitureType.id == furniture_id, ReFurnitureType.is_active == True))  # noqa: E712
        ).scalar_one_or_none()
        if ok is None:
            errors.setdefault("residential_details.furniture_type_id", []).append("Invalid furniture type")

    # media checks: must exist, belong to this vendor, and have the right type
    wanted = list(p.media.image_ids) + list(p.media.video_ids) + ([p.media.reel_id] if p.media.reel_id else [])
    owned = await load_vendor_media(db, vendor.id, wanted)
    for field, ids, mtype in (
        ("media.image_ids", p.media.image_ids, "image"),
        ("media.video_ids", p.media.video_ids, "video"),
        ("media.reel_id", [p.media.reel_id] if p.media.reel_id else [], "video"),
    ):
        for mid in ids:
            m = owned.get(mid)
            if m is None:
                errors.setdefault(field, []).append(f"Media {mid} not found")
            elif m.media_type != mtype:
                errors.setdefault(field, []).append(f"Media {mid} must be a {mtype}")

    if errors:
        raise validation_error(errors)

    cols = dict(
        sub_category_id=p.sub_category_id,
        property_type_id=p.property_type_id,
        selling_coverage_mode=p.selling_coverage.mode,
        building_name=(p.property_details.building_name or None),
        state=p.location.state.strip(),
        district=p.location.district.strip(),
        city=p.location.city.strip(),
        area_locality=p.location.area_locality.strip(),
        furniture_type_id=furniture_id,
        built_up_area=(built_up or None),
        sale_price=p.pricing.sale_price,
        price_per_sq_yard=per_yard,
        negotiable=p.pricing.negotiable_price,
        available_from=p.available_from,
        facebook_id=p.social_media.facebook_id,
        instagram_id=p.social_media.instagram_id,
        youtube_id=p.social_media.youtube_id,
        linkedin_id=p.social_media.linkedin_id,
    )
    media = {
        "image": [owned[i] for i in p.media.image_ids],
        "video": [owned[i] for i in p.media.video_ids],
        "reel": [owned[p.media.reel_id]] if p.media.reel_id else [],
    }
    return type_code, {**cols, "_bhk": bhk_ids, "_coverage": coverage_locations}, media


def _attach_children(prop: ReProperty, bhk_ids: List[int], media: dict) -> None:
    prop.bhk_links = [RePropertyBhk(bhk_type_id=b) for b in bhk_ids]
    prop.media = [
        RePropertyMedia(media_id=m.id, role=role, url=m.url, sort_order=i)
        for role, items in media.items()
        for i, m in enumerate(items)
    ]


async def create_property(db: AsyncSession, vendor: Vendor, p: PropertyRequest) -> ReProperty:
    _, cols, media = await _validated_parts(db, vendor, p)
    bhk_ids = cols.pop("_bhk")
    coverage = cols.pop("_coverage")
    prop = ReProperty(vendor_id=vendor.id, **cols)
    _attach_children(prop, bhk_ids, media)
    prop.coverage_locations = [RePropertyCoverageLocation(**item) for item in coverage]
    db.add(prop)
    await db.flush()
    return prop


async def get_owned_property(db: AsyncSession, vendor: Vendor, property_id: int) -> ReProperty:
    """404 (not 403) when missing OR owned by someone else, so ids can't be probed."""
    prop = (
        await db.execute(
            select(ReProperty).where(
                ReProperty.id == property_id,
                ReProperty.vendor_id == vendor.id,
                ReProperty.is_active == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


async def update_property(db: AsyncSession, vendor: Vendor, property_id: int, p: PropertyRequest) -> ReProperty:
    prop = await get_owned_property(db, vendor, property_id)
    _, cols, media = await _validated_parts(db, vendor, p)
    bhk_ids = cols.pop("_bhk")
    coverage = cols.pop("_coverage")
    for k, v in cols.items():
        setattr(prop, k, v)
    # Delete old children first: the unit of work would otherwise INSERT new rows
    # before DELETE-ing old ones and violate the (property_id, bhk_type_id) unique key.
    prop.bhk_links = []
    prop.media = []
    prop.coverage_locations = []
    await db.flush()
    _attach_children(prop, bhk_ids, media)
    prop.coverage_locations = [RePropertyCoverageLocation(**item) for item in coverage]
    await db.flush()
    return prop


async def delete_property(db: AsyncSession, vendor: Vendor, property_id: int) -> None:
    prop = await get_owned_property(db, vendor, property_id)
    await db.delete(prop)  # children cascade
    await db.flush()


async def list_properties(db: AsyncSession, vendor: Vendor) -> List[ReProperty]:
    return list(
        (
            await db.execute(
                select(ReProperty)
                .where(ReProperty.vendor_id == vendor.id, ReProperty.is_active == True)  # noqa: E712
                .order_by(ReProperty.id.desc())
            )
        ).scalars().all()
    )


async def serialize(db: AsyncSession, props: List[ReProperty]) -> List[dict]:
    types = {t.id: t for t in (await db.execute(select(RePropertyType))).scalars()}
    bhks = {b.id: b.name for b in (await db.execute(select(ReBhkType))).scalars()}
    furn = {f.id: f.name for f in (await db.execute(select(ReFurnitureType))).scalars()}
    out = []
    for pr in props:
        code = types[pr.property_type_id].code if pr.property_type_id in types else None
        residential = commercial = land = None
        if code == rules.RESIDENTIAL:
            residential = {
                "bhk_types": [{"id": l.bhk_type_id, "name": bhks.get(l.bhk_type_id)} for l in pr.bhk_links],
                "furniture_type": {"id": pr.furniture_type_id, "name": furn.get(pr.furniture_type_id)},
                "built_up_area": pr.built_up_area,
            }
        elif code == rules.COMMERCIAL:
            commercial = {"built_up_area": pr.built_up_area}
        elif code == rules.OPEN_LAND:
            land = {"price_per_square_yard": float(pr.price_per_sq_yard) if pr.price_per_sq_yard is not None else None}

        def _m(role):
            return [{"media_id": m.media_id, "url": m.url} for m in sorted(pr.media, key=lambda x: x.sort_order) if m.role == role]

        reel = _m("reel")
        out.append({
            "id": pr.id,
            "sub_category_id": pr.sub_category_id,
            "property_type_id": pr.property_type_id,
            "property_type": code,
            "building_name": pr.building_name,
            "selling_coverage": {
                "mode": pr.selling_coverage_mode,
                "locations": [{
                    "state_id": item.state_id, "state": item.state.name,
                    "district_id": item.district_id,
                    "district": item.district.name if item.district else None,
                } for item in pr.coverage_locations],
            } if pr.selling_coverage_mode else None,
            "location": {"state": pr.state, "district": pr.district, "city": pr.city, "area_locality": pr.area_locality},
            "residential_details": residential,
            "commercial_details": commercial,
            "open_land_details": land,
            "pricing": {"sale_price": float(pr.sale_price), "negotiable_price": pr.negotiable},
            "available_from": pr.available_from,
            "media": {"images": _m("image"), "videos": _m("video"), "reel": reel[0] if reel else None},
            "social_media": SocialMedia(
                facebook_id=pr.facebook_id, instagram_id=pr.instagram_id,
                youtube_id=pr.youtube_id, linkedin_id=pr.linkedin_id,
            ).model_dump(),
            "created_at": pr.created_at,
        })
    return out


async def has_details(db: AsyncSession, vendor_id: int) -> bool:
    """Registry hook: has this vendor completed Real Estate details?"""
    n = (
        await db.execute(
            select(func.count()).select_from(ReProperty).where(
                ReProperty.vendor_id == vendor_id, ReProperty.is_active == True  # noqa: E712
            )
        )
    ).scalar_one()
    return n > 0


# ------------------------------ master ---------------------------------
async def master_data(db: AsyncSession, sub_category_id: Optional[int]) -> dict:
    q = (
        select(RePropertyType, ReSubcategoryPropertyType.sub_category_id)
        .join(ReSubcategoryPropertyType, ReSubcategoryPropertyType.property_type_id == RePropertyType.id)
        .where(RePropertyType.is_active == True)  # noqa: E712
        .order_by(RePropertyType.id)
    )
    if sub_category_id is not None:
        q = q.where(ReSubcategoryPropertyType.sub_category_id == sub_category_id)
    rows = (await db.execute(q)).all()
    by_sub: Dict[int, list] = {}
    for t, sid in rows:
        by_sub.setdefault(sid, []).append({"id": t.id, "code": t.code, "name": t.name})

    subs = (
        await db.execute(
            select(ServiceSubcategory)
            .join(ServiceCategory, ServiceCategory.id == ServiceSubcategory.main_category_id)
            .where(ServiceCategory.form_type == FORM_TYPE, ServiceSubcategory.is_active == True)  # noqa: E712
            .order_by(ServiceSubcategory.sort_order, ServiceSubcategory.id)
        )
    ).scalars().all()
    bhk = (await db.execute(select(ReBhkType).where(ReBhkType.is_active == True).order_by(ReBhkType.sort_order))).scalars().all()  # noqa: E712
    furn = (await db.execute(select(ReFurnitureType).where(ReFurnitureType.is_active == True).order_by(ReFurnitureType.id))).scalars().all()  # noqa: E712

    flat = by_sub.get(sub_category_id, []) if sub_category_id is not None else None
    return {
        "sub_categories": [
            {
                "id": s.id, "name": s.name,
                "reel_allowed": rules.REEL_ALLOWED.get(rules.subcategory_key(s.name), False),
                "showcase_allowed": rules.SHOWCASE_ALLOWED.get(rules.subcategory_key(s.name), False),
                "property_types": by_sub.get(s.id, []),
            }
            for s in subs
        ],
        "property_types": flat,  # only set when sub_category_id was passed
        "bhk_types": [{"id": b.id, "name": b.name} for b in bhk],
        "furniture_types": [{"id": f.id, "name": f.name} for f in furn],
        "max_images": rules.MAX_IMAGES,
        "negotiable_default": True,
        "coverage_states": [
            {"id": state.id, "code": state.code, "name": state.name,
             "districts": [{"id": district.id, "code": district.code, "name": district.name} for district in state.districts]}
            for state in (await db.execute(select(ReCoverageState).options(selectinload(ReCoverageState.districts)).order_by(ReCoverageState.name))).scalars().all()
        ],
    }


# ------------------------------ showcase -------------------------------
async def _showcase_rows(db: AsyncSession, vendor_id: int) -> List[ReShowcase]:
    return list(
        (await db.execute(select(ReShowcase).where(ReShowcase.vendor_id == vendor_id).order_by(ReShowcase.state, ReShowcase.district))).scalars()
    )


def _group(rows: List[ReShowcase]) -> dict:
    grouped: Dict[str, List[str]] = {}
    for r in rows:
        grouped.setdefault(r.state, []).append(r.district)
    return {
        "sub_category_id": rows[0].sub_category_id if rows else None,
        "showcase_locations": [{"state": s, "districts": d} for s, d in grouped.items()],
        "total_states": len(grouped),
        "total_districts": len(rows),
    }


def _flatten(req: ShowcaseRequest) -> List[Tuple[str, str]]:
    seen, dupes, flat = set(), [], []
    for loc in req.showcase_locations:
        for d in loc.districts:
            pair = (loc.state.strip(), d.strip())
            if not pair[0] or not pair[1]:
                raise validation_error({"showcase_locations": ["State and district must not be blank"]})
            if pair in seen:
                dupes.append(f"{pair[1]}, {pair[0]}")
            seen.add(pair)
            flat.append(pair)
    if dupes:
        raise HTTPException(status_code=409, detail={"message": "Duplicate state/district in request", "duplicates": dupes})
    return flat


async def _require_showcase_allowed(db: AsyncSession, sub_category_id: int) -> None:
    key = await get_subcategory_key(db, sub_category_id)
    if not rules.SHOWCASE_ALLOWED.get(key, False):
        raise HTTPException(status_code=403, detail="Property Showcase is available only for Agency and Builder")


async def save_showcase(db: AsyncSession, vendor: Vendor, req: ShowcaseRequest) -> dict:
    if req.sub_category_id is None:
        raise validation_error({"sub_category_id": ["sub_category_id is required"]})
    await _require_showcase_allowed(db, req.sub_category_id)
    if await _showcase_rows(db, vendor.id):
        raise HTTPException(status_code=409, detail="Showcase already exists. Use PUT to update it.")
    for state, district in _flatten(req):
        db.add(ReShowcase(vendor_id=vendor.id, sub_category_id=req.sub_category_id, state=state, district=district))
    await db.flush()
    return _group(await _showcase_rows(db, vendor.id))


async def get_showcase(db: AsyncSession, vendor: Vendor) -> dict:
    return _group(await _showcase_rows(db, vendor.id))


async def replace_showcase(db: AsyncSession, vendor: Vendor, req: ShowcaseRequest) -> dict:
    existing = await _showcase_rows(db, vendor.id)
    sub_id = req.sub_category_id or (existing[0].sub_category_id if existing else None)
    if sub_id is None:
        raise validation_error({"sub_category_id": ["sub_category_id is required"]})
    await _require_showcase_allowed(db, sub_id)
    flat = _flatten(req)
    await db.execute(delete(ReShowcase).where(ReShowcase.vendor_id == vendor.id))
    for state, district in flat:
        db.add(ReShowcase(vendor_id=vendor.id, sub_category_id=sub_id, state=state, district=district))
    await db.flush()
    return _group(await _showcase_rows(db, vendor.id))


async def delete_showcase(db: AsyncSession, vendor: Vendor) -> None:
    await db.execute(delete(ReShowcase).where(ReShowcase.vendor_id == vendor.id))
