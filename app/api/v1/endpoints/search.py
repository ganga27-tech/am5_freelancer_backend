"""Service search: results, typeahead suggestions and popular terms (mounted at /search)."""
import datetime as dt
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, func, case, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.db.session import get_db
from app.dependencies.auth import get_current_customer
from app.models.catalog import Service, ServiceCategory, ServiceSubcategory
from app.models.search_log import SearchQueryStat
from app.models.user_location import Customer
from app.models.vendor import VendorService

router = APIRouter()

MIN_TERM_LENGTH = 2
POPULAR_WINDOW_DAYS = 30
# Shown while there is not enough search history yet.
DEFAULT_POPULAR = ["AC repair", "Home cleaning", "Plumbing", "Electrician", "Salon at home"]
# Same fallback pricing as GET /catalog/services.
MIN_VENDOR_PRICE = 49
FALLBACK_PRICE = 299.0


def _escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _like(term: str) -> str:
    return f"%{_escape(term)}%"


def _prefix(term: str) -> str:
    return f"{_escape(term)}%"


def _priced_services():
    """SELECT services with their starting price (cheapest active vendor price)."""
    by_service = (
        select(VendorService.service_id.label("sid"), func.min(VendorService.price).label("p"))
        .where(VendorService.is_active == True, VendorService.price >= MIN_VENDOR_PRICE)
        .group_by(VendorService.service_id)
        .subquery()
    )
    by_subcategory = (
        select(VendorService.sub_category_id.label("scid"), func.min(VendorService.price).label("sp"))
        .where(VendorService.is_active == True, VendorService.price >= MIN_VENDOR_PRICE)
        .group_by(VendorService.sub_category_id)
        .subquery()
    )
    price = func.coalesce(by_service.c.p, by_subcategory.c.sp, FALLBACK_PRICE)
    query = (
        select(Service, price.label("starting_price"))
        .outerjoin(by_service, by_service.c.sid == Service.id)
        .outerjoin(by_subcategory, by_subcategory.c.scid == Service.sub_category_id)
        .outerjoin(ServiceSubcategory, ServiceSubcategory.id == Service.sub_category_id)
        .outerjoin(ServiceCategory, ServiceCategory.id == Service.main_category_id)
        .where(Service.is_active == True)
    )
    return query, price


def _service_json(service: Service, starting_price) -> dict:
    # Same shape as GET /catalog/services, so the app parses both the same way.
    p = float(starting_price or FALLBACK_PRICE)
    return {
        "id": service.id,
        "main_category_id": service.main_category_id,
        "category_id": service.main_category_id,
        "sub_category_id": service.sub_category_id,
        "name": service.name,
        "image_url": service.image_url,
        "is_active": service.is_active,
        "created_at": service.created_at.isoformat() if service.created_at else None,
        "base_price": p,
        "price": p,
        "duration_minutes": 60,
    }


async def _record_search(db: AsyncSession, term: str) -> None:
    """Count a term that returned results. Never lets a logging problem break the search."""
    try:
        async with db.begin_nested():
            stmt = pg_insert(SearchQueryStat).values(
                term=term, hit_count=1, last_searched_at=dt.datetime.utcnow())
            await db.execute(stmt.on_conflict_do_update(
                index_elements=[SearchQueryStat.term],
                set_={"hit_count": SearchQueryStat.hit_count + 1,
                      "last_searched_at": dt.datetime.utcnow()},
            ))
        await db.commit()
    except Exception:
        await db.rollback()


@router.get("/popular")
@limiter.limit("60/minute")
async def popular_searches(
    request: Request,
    limit: int = Query(10, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Most used search terms in the last 30 days, topped up with defaults while history is small."""
    since = dt.datetime.utcnow() - dt.timedelta(days=POPULAR_WINDOW_DAYS)
    rows = (await db.execute(
        select(SearchQueryStat.term, SearchQueryStat.hit_count)
        .where(SearchQueryStat.last_searched_at >= since)
        .order_by(SearchQueryStat.hit_count.desc(), SearchQueryStat.term)
        .limit(limit)
    )).all()
    items = [{"query": term, "hit_count": int(count)} for term, count in rows]
    seen = {i["query"].lower() for i in items}
    for default in DEFAULT_POPULAR:
        if len(items) >= limit:
            break
        if default.lower() not in seen:
            items.append({"query": default, "hit_count": 0})
    return items


@router.get("/suggest")
@limiter.limit("120/minute")
async def suggest(
    request: Request,
    q: str = Query(..., max_length=60),
    limit: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Typeahead: matching services, categories and popular terms. Empty lists for short input."""
    term = q.strip().lower()
    if len(term) < MIN_TERM_LENGTH:
        return {"services": [], "categories": [], "queries": []}

    base, _ = _priced_services()
    services = (await db.execute(
        base.where(Service.name.ilike(_like(term), escape="\\"))
        .order_by(
            case((Service.name.ilike(_prefix(term), escape="\\"), 0), else_=1),
            Service.name,
        )
        .limit(limit)
    )).all()

    categories = (await db.execute(
        select(ServiceCategory)
        .where(ServiceCategory.is_active == True, ServiceCategory.name.ilike(_like(term), escape="\\"))
        .order_by(ServiceCategory.sort_order, ServiceCategory.name)
        .limit(limit)
    )).scalars().all()

    queries = (await db.execute(
        select(SearchQueryStat.term)
        .where(SearchQueryStat.term.like(_like(term), escape="\\"))
        .order_by(SearchQueryStat.hit_count.desc())
        .limit(limit)
    )).scalars().all()
    for default in DEFAULT_POPULAR:
        if term in default.lower() and default.lower() not in queries and len(queries) < limit:
            queries.append(default)

    return {
        "services": [_service_json(s, price) for s, price in services],
        "categories": [
            {
                "id": str(c.id),
                "category_id": str(c.id),
                "name": c.name,
                "description": c.description,
                "icon_url": c.icon_url,
                "is_active": c.is_active,
                "sort_order": c.sort_order,
                "subcategories": [],
            }
            for c in categories
        ],
        "queries": queries,
    }


@router.get("")
@limiter.limit("60/minute")
async def search_services(
    request: Request,
    q: Optional[str] = Query(None, max_length=60),
    category: Optional[int] = Query(None, description="Main category id"),
    subcategory_id: Optional[int] = Query(None),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    sort: Literal["relevance", "price_asc", "price_desc"] = "relevance",
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """
    Search services by name (also by category / sub-category name), with price range,
    sort and pagination. Returns {items, total}; an empty list when nothing matches.
    """
    term = (q or "").strip().lower()
    query, price = _priced_services()

    if term:
        like = _like(term)
        query = query.where(or_(
            Service.name.ilike(like, escape="\\"),
            ServiceSubcategory.name.ilike(like, escape="\\"),
            ServiceCategory.name.ilike(like, escape="\\"),
        ))
    if category:
        query = query.where(Service.main_category_id == category)
    if subcategory_id:
        query = query.where(Service.sub_category_id == subcategory_id)
    if min_price is not None:
        query = query.where(price >= min_price)
    if max_price is not None:
        query = query.where(price <= max_price)

    total = (await db.execute(select(func.count()).select_from(query.order_by(None).subquery()))).scalar() or 0

    if sort == "price_asc":
        order = [price.asc(), Service.name]
    elif sort == "price_desc":
        order = [price.desc(), Service.name]
    elif term:
        # exact name, then name starts with the term, then name contains it, then category matches
        order = [
            case(
                (func.lower(Service.name) == term, 0),
                (Service.name.ilike(_prefix(term), escape="\\"), 1),
                (Service.name.ilike(_like(term), escape="\\"), 2),
                else_=3,
            ),
            Service.name,
        ]
    else:
        order = [Service.name]
    rows = (await db.execute(query.order_by(*order, Service.id).offset(offset).limit(limit))).all()

    if term and len(term) >= MIN_TERM_LENGTH and total > 0 and offset == 0:
        await _record_search(db, term[:60])

    return {
        "query": q,
        "total": int(total),
        "sort": sort,
        "items": [_service_json(s, p) for s, p in rows],
    }
