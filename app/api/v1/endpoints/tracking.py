from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.geo import estimate_route
from app.core.rate_limit import limiter
from app.dependencies.auth import get_current_customer
from app.models.user_location import Customer

router = APIRouter()


class RouteEstimateRequest(BaseModel):
    from_lat: float = Field(..., ge=-90, le=90)
    from_lng: float = Field(..., ge=-180, le=180)
    to_lat: float = Field(..., ge=-90, le=90)
    to_lng: float = Field(..., ge=-180, le=180)


class RouteEstimateResponse(BaseModel):
    distance_km: float
    eta_minutes: int
    bearing_degrees: float
    provider: str


@router.post("/route-estimate", response_model=RouteEstimateResponse)
@limiter.limit("30/minute")
async def route_estimate(
    request: Request,
    body: RouteEstimateRequest,
    current_customer: Customer = Depends(get_current_customer),
):
    """
    Approximate distance and ETA between two points. Uses straight-line distance
    with a road factor and an average city speed, so it is an estimate, not turn-by-turn routing.
    """
    return estimate_route(body.from_lat, body.from_lng, body.to_lat, body.to_lng)
