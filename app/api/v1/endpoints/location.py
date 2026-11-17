from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, String, and_
from app.db.session import get_db
from app.models.user_location import City as CityModel, Address as AddressModel
from app.schemas.location import City, Address, AddressCreate, AddressUpdate, ServiceabilityResponse
from app.dependencies.auth import get_current_customer
from app.models.user_location import Customer
from app.models.vendor import Vendor
from app.core.geo import haversine_km, pincode_in_city_record, MAX_SEARCH_RADIUS_KM

router = APIRouter()

@router.get("/cities", response_model=List[City])
async def get_cities(
    db: AsyncSession = Depends(get_db),
    active_only: bool = True
):
    """
    Get all cities supported by the platform.
    """
    query = select(CityModel)
    if active_only:
        query = query.where(CityModel.active == True)
    
    result = await db.execute(query.order_by(CityModel.name))
    return result.scalars().all()

@router.get("/states")
async def get_states(db: AsyncSession = Depends(get_db)):
    """Distinct states from the cities master (for state dropdowns)."""
    rows = (
        await db.execute(
            select(CityModel.state, func.max(CityModel.state_code))
            .where(CityModel.state.isnot(None), CityModel.active == True)
            .group_by(CityModel.state)
            .order_by(CityModel.state)
        )
    ).all()
    return [{"name": s, "code": c} for s, c in rows]


@router.get("/districts")
async def get_districts(state: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    """Districts of a state. Empty until cities.district is populated."""
    rows = (
        await db.execute(
            select(CityModel.district)
            .where(CityModel.state == state, CityModel.district.isnot(None), CityModel.active == True)
            .distinct()
            .order_by(CityModel.district)
        )
    ).scalars().all()
    return [{"name": d} for d in rows]


@router.get("/city-options")
async def get_city_options(
    state: str = Query(..., min_length=1),
    district: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """City names for a state (optionally narrowed to a district)."""
    q = select(CityModel.id, CityModel.name).where(CityModel.state == state, CityModel.active == True)
    if district:
        q = q.where(CityModel.district == district)
    rows = (await db.execute(q.order_by(CityModel.name))).all()
    return [{"id": i, "name": n} for i, n in rows]


@router.get("/serviceability", response_model=ServiceabilityResponse)
async def check_serviceability(
    db: AsyncSession = Depends(get_db),
    city: Optional[str] = Query(None),
    pincode: Optional[str] = Query(None),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
):
    """
    Is service available here? Public, so it can be used before login.
    Serviceable when the pincode or city matches an active city, or an active
    vendor's service radius covers the given coordinates.
    """
    pincode = (pincode or "").strip() or None
    city = (city or "").strip() or None
    if not (pincode or city or (lat is not None and lng is not None)):
        raise HTTPException(status_code=422, detail="Provide a pincode, city, or lat/lng")
    if (lat is None) != (lng is None):
        raise HTTPException(status_code=422, detail="lat and lng must be sent together")

    active_cities = (
        await db.execute(select(CityModel).where(CityModel.active == True))
    ).scalars().all()

    matched_city = None
    if pincode:
        matched_city = next(
            (c for c in active_cities if pincode_in_city_record(pincode, c.pincodes)), None
        )
    if not matched_city and city:
        needle = city.lower()
        matched_city = next((c for c in active_cities if c.name and c.name.lower() == needle), None)

    serviceable = matched_city is not None
    if not serviceable and lat is not None and lng is not None:
        # Bounding-box prefilter (~0.7 degrees ≈ 78 km), then exact distance vs vendor radius.
        box = MAX_SEARCH_RADIUS_KM / 111.0
        vendors = (
            await db.execute(
                select(Vendor.latitude, Vendor.longitude, Vendor.service_radius_km).where(
                    Vendor.status == "active",
                    Vendor.latitude.is_not(None),
                    Vendor.longitude.is_not(None),
                    Vendor.latitude.between(lat - box, lat + box),
                    Vendor.longitude.between(lng - box * 2, lng + box * 2),
                )
            )
        ).all()
        serviceable = any(
            haversine_km(lat, lng, float(v_lat), float(v_lng)) <= min(v_radius or 25, MAX_SEARCH_RADIUS_KM)
            for v_lat, v_lng, v_radius in vendors
        )

    return ServiceabilityResponse(
        serviceable=serviceable,
        city=matched_city.name if matched_city else None,
        message="Service is available in this area"
        if serviceable
        else "Sorry, we don't serve this area yet",
    )

@router.get("/addresses", response_model=List[Address])
async def get_my_addresses(
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer)
):
    """
    Get all saved addresses for the logged-in customer.
    """
    query = select(AddressModel).where(
        AddressModel.customer_id == current_customer.id,
        AddressModel.deleted == False
    ).order_by(AddressModel.is_default.desc(), AddressModel.id)
    result = await db.execute(query)
    return result.scalars().all()

@router.post("/addresses", response_model=Address)
async def create_address(
    address_in: AddressCreate,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer)
):
    """
    Add a new address to the customer's account (Matches PDF Page 9).
    """
    if address_in.is_default:
        await db.execute(
            update(AddressModel)
            .where(
                AddressModel.customer_id == current_customer.id,
                AddressModel.deleted == False,
            )
            .values(is_default=False)
        )

    new_address = AddressModel(
        **address_in.model_dump(),
        customer_id=current_customer.id
    )
    db.add(new_address)
    await db.commit()
    await db.refresh(new_address)
    return new_address

@router.put("/addresses/{address_id}", response_model=Address)
async def update_address(
    address_id: int,
    address_in: AddressUpdate,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer)
):
    """
    Update an existing address. Only the fields sent are changed;
    sending is_default=true makes this the only default address.
    """
    result = await db.execute(
        select(AddressModel).where(
            AddressModel.id == address_id,
            AddressModel.customer_id == current_customer.id,
            AddressModel.deleted == False,
        )
    )
    address = result.scalar_one_or_none()
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")

    changes = address_in.model_dump(exclude_unset=True)
    for required in ("label", "address_line1", "city", "state", "pincode"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"{required} cannot be empty")

    if changes.get("is_default"):
        await db.execute(
            update(AddressModel)
            .where(
                AddressModel.customer_id == current_customer.id,
                AddressModel.deleted == False,
                AddressModel.id != address.id,
            )
            .values(is_default=False)
        )

    for field, value in changes.items():
        setattr(address, field, value)

    await db.commit()
    await db.refresh(address)
    return address

@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer)
):
    """
    Soft-delete an address.
    """
    result = await db.execute(
        select(AddressModel).where(
            AddressModel.id == address_id,
            AddressModel.customer_id == current_customer.id,
            AddressModel.deleted == False,
        )
    )
    address = result.scalar_one_or_none()
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")
    
    address.deleted = True
    address.is_default = False
    await db.commit()
    return None
