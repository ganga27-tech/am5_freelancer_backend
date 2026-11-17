from datetime import date, datetime
from typing import Dict, List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.categories.base import SocialMedia


class Location(BaseModel):
    state: str = Field(..., min_length=1, max_length=100)
    district: str = Field(..., min_length=1, max_length=100)
    city: str = Field(..., min_length=1, max_length=100)
    area_locality: str = Field(..., min_length=1, max_length=255)


class PropertyDetails(BaseModel):
    building_name: Optional[str] = Field(None, max_length=255)


class ResidentialDetails(BaseModel):
    bhk_type_ids: List[int] = []
    furniture_type_id: Optional[int] = None
    built_up_area: Optional[str] = Field(None, max_length=50)


class CommercialDetails(BaseModel):
    built_up_area: Optional[str] = Field(None, max_length=50)


class OpenLandDetails(BaseModel):
    price_per_square_yard: Optional[float] = None


class Pricing(BaseModel):
    sale_price: Optional[float] = None
    negotiable_price: bool = True

    @field_validator("negotiable_price")
    @classmethod
    def _negotiable_must_remain_enabled(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Negotiable price must be enabled")
        return value


class MediaRefs(BaseModel):
    """IDs returned by POST /media/upload."""
    image_ids: List[int] = []
    video_ids: List[int] = []
    reel_id: Optional[int] = None


class SellingCoverageLocation(BaseModel):
    state_id: int = Field(..., gt=0)
    district_id: Optional[int] = Field(None, gt=0)


class SellingCoverage(BaseModel):
    mode: Literal["PAN_INDIA", "STATE", "DISTRICT", "LOCAL_ONLY"]
    locations: List[SellingCoverageLocation] = []

    @field_validator("locations")
    @classmethod
    def _coverage_mode_matches_locations(cls, locations, info):
        mode = info.data.get("mode")
        pairs = [(item.state_id, item.district_id) for item in locations]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Duplicate Selling Coverage location")
        if mode in ("PAN_INDIA", "LOCAL_ONLY") and locations:
            raise ValueError(f"{mode} coverage must not include locations")
        if mode == "STATE" and (not locations or any(district_id is not None for _, district_id in pairs)):
            raise ValueError("STATE coverage requires State IDs without District IDs")
        if mode == "DISTRICT" and (not locations or any(district_id is None for _, district_id in pairs)):
            raise ValueError("DISTRICT coverage requires State-District ID pairs")
        return locations

class PropertyRequest(BaseModel):
    """Body for both POST (create) and PUT (full replace)."""
    sub_category_id: int
    property_type_id: int
    property_details: PropertyDetails = PropertyDetails()
    location: Location
    selling_coverage: SellingCoverage
    residential_details: Optional[ResidentialDetails] = None
    commercial_details: Optional[CommercialDetails] = None
    open_land_details: Optional[OpenLandDetails] = None
    pricing: Pricing = Pricing()
    available_from: Optional[date] = None
    media: MediaRefs = MediaRefs()
    social_media: SocialMedia = SocialMedia()

    @field_validator("media")
    @classmethod
    def _no_duplicate_media(cls, v: MediaRefs) -> MediaRefs:
        ids = v.image_ids + v.video_ids + ([v.reel_id] if v.reel_id else [])
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate media ids")
        return v


# ------------------------------ showcase -------------------------------
class ShowcaseLocation(BaseModel):
    state: str = Field(..., min_length=1, max_length=100)
    districts: List[str] = Field(..., min_length=1)


class ShowcaseRequest(BaseModel):
    sub_category_id: Optional[int] = None  # required on POST, optional on PUT
    showcase_locations: List[ShowcaseLocation] = Field(..., min_length=1)


# ------------------------------ responses ------------------------------
class MasterItem(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)


class PropertyTypeItem(MasterItem):
    code: str


class MediaOut(BaseModel):
    media_id: int
    url: str


class PropertyOut(BaseModel):
    id: int
    sub_category_id: int
    property_type_id: int
    property_type: str
    building_name: Optional[str]
    location: Location
    selling_coverage: Optional[dict] = None
    residential_details: Optional[dict]
    commercial_details: Optional[dict]
    open_land_details: Optional[dict]
    pricing: Pricing
    available_from: Optional[date]
    media: Dict[str, object]
    social_media: SocialMedia
    created_at: Optional[datetime]
