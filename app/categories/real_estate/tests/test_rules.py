"""Pure rule tests: no DB needed."""
from app.categories.real_estate import rules as r


def _v(**kw):
    base = dict(
        sub_key=r.AGENCY, type_code=r.RESIDENTIAL, sale_price=100.0, built_up_area="1500 sq.ft",
        furniture_type_id=1, bhk_type_ids=[2], price_per_sq_yard=None,
        image_count=0, video_count=0, has_reel=False,
    )
    base.update(kw)
    return r.validate_property(**base)


def test_valid_residential():
    assert _v() == {}


def test_builder_cannot_use_open_land():
    e = _v(sub_key=r.BUILDER, type_code=r.OPEN_LAND, price_per_sq_yard=10)
    assert "property_type_id" in e


def test_agency_and_owner_can_use_open_land():
    for k in (r.AGENCY, r.SINGLE_OWNER):
        assert _v(sub_key=k, type_code=r.OPEN_LAND, price_per_sq_yard=10) == {}


def test_single_owner_no_reel_but_agency_builder_ok():
    assert "media.reel_id" in _v(sub_key=r.SINGLE_OWNER, has_reel=True)
    assert _v(sub_key=r.AGENCY, has_reel=True) == {}
    assert _v(sub_key=r.BUILDER, has_reel=True) == {}


def test_max_five_images():
    assert _v(image_count=5) == {}
    assert "media.image_ids" in _v(image_count=6)


def test_residential_requires_bhk_furniture_area():
    e = _v(bhk_type_ids=[], furniture_type_id=None, built_up_area="")
    assert {"residential_details.bhk_type_ids", "residential_details.furniture_type_id",
            "residential_details.built_up_area"} <= set(e)


def test_commercial_requires_area_only():
    assert _v(type_code=r.COMMERCIAL, bhk_type_ids=[], furniture_type_id=None) == {}
    assert "commercial_details.built_up_area" in _v(type_code=r.COMMERCIAL, built_up_area=None)


def test_open_land_requires_price_per_yard():
    assert "open_land_details.price_per_square_yard" in _v(type_code=r.OPEN_LAND, price_per_sq_yard=None)


def test_sale_price_required():
    assert "pricing.sale_price" in _v(sale_price=None)
    assert "pricing.sale_price" in _v(sale_price=0)


def test_unknown_subcategory():
    assert "sub_category_id" in _v(sub_key="agent")
