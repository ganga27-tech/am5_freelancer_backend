"""Pure business rules for Real Estate. No DB / framework imports, so they unit-test easily."""
from typing import Dict, List, Optional

MAX_IMAGES = 5

# Subcategory keys (derived from the subcategory name, see `subcategory_key`)
AGENCY = "agency"
BUILDER = "builder"
SINGLE_OWNER = "single_owner"

# Property type codes
RESIDENTIAL = "residential"
COMMERCIAL = "commercial"
OPEN_LAND = "open_land"

SUBCATEGORY_NAMES = [AGENCY, BUILDER, SINGLE_OWNER]

ALLOWED_PROPERTY_TYPES = {
    AGENCY: {RESIDENTIAL, COMMERCIAL, OPEN_LAND},
    SINGLE_OWNER: {RESIDENTIAL, COMMERCIAL, OPEN_LAND},
    BUILDER: {RESIDENTIAL, COMMERCIAL},  # Open Land is not permitted for Builder
}
REEL_ALLOWED = {AGENCY: True, BUILDER: True, SINGLE_OWNER: False}
SHOWCASE_ALLOWED = {AGENCY: True, BUILDER: True, SINGLE_OWNER: False}


def subcategory_key(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def validate_property(
    *,
    sub_key: str,
    type_code: str,
    sale_price: Optional[float],
    built_up_area: Optional[str],
    furniture_type_id: Optional[int],
    bhk_type_ids: List[int],
    price_per_sq_yard: Optional[float],
    image_count: int,
    video_count: int,
    has_reel: bool,
) -> Dict[str, List[str]]:
    """Return {field: [messages]}; empty dict means valid."""
    errors: Dict[str, List[str]] = {}

    def add(field: str, msg: str) -> None:
        errors.setdefault(field, []).append(msg)

    allowed = ALLOWED_PROPERTY_TYPES.get(sub_key)
    if allowed is None:
        add("sub_category_id", "Not a Real Estate subcategory")
        return errors
    if type_code not in allowed:
        add("property_type_id", f"{type_code.replace('_', ' ').title()} is not allowed for {sub_key.replace('_', ' ').title()}")

    if sale_price is None or sale_price <= 0:
        add("pricing.sale_price", "Sale price is required")

    if type_code == RESIDENTIAL:
        if not bhk_type_ids:
            add("residential_details.bhk_type_ids", "Select at least one BHK type")
        if not furniture_type_id:
            add("residential_details.furniture_type_id", "Furniture type is required")
        if not (built_up_area or "").strip():
            add("residential_details.built_up_area", "Built-up area is required")
    elif type_code == COMMERCIAL:
        if not (built_up_area or "").strip():
            add("commercial_details.built_up_area", "Built-up area is required")
    elif type_code == OPEN_LAND:
        if price_per_sq_yard is None or price_per_sq_yard <= 0:
            add("open_land_details.price_per_square_yard", "Price per square yard is required")

    if image_count > MAX_IMAGES:
        add("media.image_ids", f"Maximum {MAX_IMAGES} images allowed")
    if has_reel and not REEL_ALLOWED.get(sub_key, False):
        add("media.reel_id", "Property reel is not available for Single Owner")

    return errors
