import itertools

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def env():
    import app.main  # noqa: F401  (registers every model with Base.metadata)
    from app.db.base_class import Base
    from app.db.session import AsyncSessionLocal, engine
    import app.models  # noqa: F401
    from app.categories.registry import CATEGORIES
    from app.models.vendor import Vendor
    from app.models.vendor_media import VendorMedia

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as s:
        for c in CATEGORIES:
            await c.seed(s, True)
            await c.seed(s, True)  # idempotent
        v1, v2 = Vendor(user_id=1, first_name="a"), Vendor(user_id=2, first_name="b")
        s.add_all([v1, v2])
        await s.flush()
        ids = {}
        for who, v in (("v1", v1), ("v2", v2)):
            ids[who] = {"imgs": [], "vids": []}
            for _ in range(7):
                m = VendorMedia(vendor_id=v.id, media_type="image", url="http://x/i.jpg")
                s.add(m); await s.flush(); ids[who]["imgs"].append(m.id)
            for _ in range(3):
                m = VendorMedia(vendor_id=v.id, media_type="video", url="http://x/v.mp4")
                s.add(m); await s.flush(); ids[who]["vids"].append(m.id)
        ids["v1_obj"], ids["v2_obj"] = v1, v2
        await s.commit()

        from sqlalchemy import select
        from app.models.catalog import ServiceSubcategory
        subs = {r.name: r.id for r in (await s.execute(select(ServiceSubcategory))).scalars()}
        ids["subs"] = subs
    yield ids
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def api(env):
    from app.main import app
    from app.dependencies.auth import get_current_token_payload, get_current_vendor

    state = {"vendor": env["v1_obj"]}
    app.dependency_overrides[get_current_vendor] = lambda: state["vendor"]
    app.dependency_overrides[get_current_token_payload] = lambda: {"sub": "1"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        c.as_vendor = lambda key: state.__setitem__("vendor", env[f"{key}_obj"])
        yield c
        c.as_vendor("v1")
    app.dependency_overrides.clear()


def body(env, sub="Agency", type_id=1, **over):
    b = {
        "sub_category_id": env["subs"][sub],
        "property_type_id": type_id,
        "property_details": {"building_name": "Green Valley"},
        "location": {"state": "Telangana", "district": "Hyderabad", "city": "Hyderabad", "area_locality": "Madhapur"},
        "residential_details": {"bhk_type_ids": [2, 3], "furniture_type_id": 1, "built_up_area": "1500 sq.ft"},
        "pricing": {"sale_price": 7500000},
        "available_from": "2026-12-01",
        "media": {"image_ids": env["v1"]["imgs"][:3], "video_ids": env["v1"]["vids"][:1], "reel_id": env["v1"]["vids"][1]},
        "social_media": {"instagram_id": "ex"},
    }
    b.update(over)
    return b


async def test_master_builder_has_no_open_land(api, env):
    r = await api.get("/api/v1/real-estate/master")
    assert r.status_code == 200
    subs = {s["name"]: s for s in r.json()["sub_categories"]}
    assert [t["code"] for t in subs["Builder"]["property_types"]] == ["residential", "commercial"]
    assert len(subs["Agency"]["property_types"]) == 3
    assert subs["Single Owner"]["reel_allowed"] is False and subs["Agency"]["reel_allowed"] is True
    assert subs["Single Owner"]["showcase_allowed"] is False
    assert [b["name"] for b in r.json()["bhk_types"]][:2] == ["1 RK", "1 BHK"]
    assert len(r.json()["furniture_types"]) == 2


async def test_main_categories_exposes_form_type(api, env):
    r = await api.get("/api/v1/vendor/catalog/main-categories")
    assert r.status_code == 200, r.text
    re_ = [c for c in r.json() if c["name"] == "Real Estate"][0]
    assert re_["form_type"] == "real_estate"


async def test_create_get_list_update_delete_residential(api, env):
    r = await api.post("/api/v1/real-estate/properties", json=body(env))
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    g = await api.get(f"/api/v1/real-estate/properties/{pid}")
    j = g.json()
    assert j["property_type"] == "residential"
    assert [b["name"] for b in j["residential_details"]["bhk_types"]] == ["1 BHK", "2 BHK"][::-1] or len(j["residential_details"]["bhk_types"]) == 2
    assert j["pricing"] == {"sale_price": 7500000.0, "negotiable_price": True}  # default on
    assert len(j["media"]["images"]) == 3 and j["media"]["reel"]["media_id"] == env["v1"]["vids"][1]
    assert j["social_media"]["instagram_id"] == "ex"

    lst = (await api.get("/api/v1/real-estate/properties")).json()
    assert lst["total"] >= 1

    upd = body(env, pricing={"sale_price": 9000000, "negotiable_price": False})
    assert (await api.put(f"/api/v1/real-estate/properties/{pid}", json=upd)).status_code == 200
    j = (await api.get(f"/api/v1/real-estate/properties/{pid}")).json()
    assert j["pricing"] == {"sale_price": 9000000.0, "negotiable_price": False}
    assert len(j["residential_details"]["bhk_types"]) == 2 and len(j["media"]["images"]) == 3  # replaced, not duplicated

    assert (await api.delete(f"/api/v1/real-estate/properties/{pid}")).status_code == 200
    assert (await api.get(f"/api/v1/real-estate/properties/{pid}")).status_code == 404


async def test_commercial_and_open_land(api, env):
    c = body(env, type_id=2, residential_details=None, commercial_details={"built_up_area": "2500 sq.ft"})
    assert (await api.post("/api/v1/real-estate/properties", json=c)).status_code == 201
    land = body(env, type_id=3, residential_details=None, open_land_details={"price_per_square_yard": 12000})
    land["media"]["reel_id"] = None
    r = await api.post("/api/v1/real-estate/properties", json=land)
    assert r.status_code == 201, r.text
    j = (await api.get(f"/api/v1/real-estate/properties/{r.json()['id']}")).json()
    assert j["open_land_details"] == {"price_per_square_yard": 12000.0}


async def _errors(api, payload):
    r = await api.post("/api/v1/real-estate/properties", json=payload)
    assert r.status_code == 422, r.text
    return r.json()["detail"]["errors"]


async def test_builder_open_land_rejected(api, env):
    land = body(env, sub="Builder", type_id=3, residential_details=None, open_land_details={"price_per_square_yard": 1})
    assert "property_type_id" in await _errors(api, land)


async def test_single_owner_reel_rejected(api, env):
    assert "media.reel_id" in await _errors(api, body(env, sub="Single Owner"))


async def test_more_than_five_images_rejected(api, env):
    p = body(env)
    p["media"]["image_ids"] = env["v1"]["imgs"][:6]
    p["media"]["reel_id"] = None
    assert "media.image_ids" in await _errors(api, p)


async def test_other_vendors_media_and_wrong_type_rejected(api, env):
    p = body(env)
    p["media"] = {"image_ids": [env["v2"]["imgs"][0]], "video_ids": [], "reel_id": None}
    assert "media.image_ids" in await _errors(api, p)          # not owned
    p["media"] = {"image_ids": [env["v1"]["vids"][2]], "video_ids": [], "reel_id": None}
    assert "media.image_ids" in await _errors(api, p)          # video used as image
    p["media"] = {"image_ids": [999999], "video_ids": [], "reel_id": None}
    assert "media.image_ids" in await _errors(api, p)          # missing


async def test_missing_required_fields(api, env):
    p = body(env, residential_details={"bhk_type_ids": []}, pricing={})
    e = await _errors(api, p)
    assert "pricing.sale_price" in e and "residential_details.bhk_type_ids" in e


async def test_non_real_estate_subcategory_rejected(api, env):
    assert "sub_category_id" in await _errors(api, body(env, sub_category_id=987654))


async def test_vendor_cannot_touch_others_property(api, env):
    pid = (await api.post("/api/v1/real-estate/properties", json=body(env))).json()["id"]
    api.as_vendor("v2")
    assert (await api.get(f"/api/v1/real-estate/properties/{pid}")).status_code == 404
    assert (await api.delete(f"/api/v1/real-estate/properties/{pid}")).status_code == 404
    assert (await api.put(f"/api/v1/real-estate/properties/{pid}", json=body(env))).status_code == 404
    assert (await api.get("/api/v1/real-estate/properties")).json()["total"] == 0
    api.as_vendor("v1")
    assert (await api.get(f"/api/v1/real-estate/properties/{pid}")).status_code == 200


async def test_showcase_lifecycle_and_rules(api, env):
    base = "/api/v1/real-estate/showcase"
    agency = env["subs"]["Agency"]
    payload = {"sub_category_id": agency, "showcase_locations": [
        {"state": "Telangana", "districts": ["Hyderabad", "Rangareddy"]}, {"state": "Andhra Pradesh", "districts": ["Guntur"]}]}
    r = await api.post(base, json=payload)
    assert r.status_code == 201, r.text
    assert (r.json()["total_states"], r.json()["total_districts"]) == (2, 3)
    assert (await api.post(base, json=payload)).status_code == 409                 # already exists
    g = (await api.get(base)).json()
    assert g["total_districts"] == 3
    dup = {"showcase_locations": [{"state": "Telangana", "districts": ["Hyderabad", "Hyderabad"]}]}
    assert (await api.put(base, json=dup)).status_code == 409                      # duplicate in request
    ok = {"showcase_locations": [{"state": "Telangana", "districts": ["Hyderabad"]}]}
    u = await api.put(base, json=ok)
    assert u.status_code == 200 and u.json()["total_districts"] == 1
    assert (await api.delete(base)).status_code == 200
    assert (await api.get(base)).json()["total_districts"] == 0
    # Single Owner not allowed
    so = {"sub_category_id": env["subs"]["Single Owner"], "showcase_locations": ok["showcase_locations"]}
    assert (await api.post(base, json=so)).status_code == 403
    # Builder allowed
    bu = {"sub_category_id": env["subs"]["Builder"], "showcase_locations": ok["showcase_locations"]}
    assert (await api.post(base, json=bu)).status_code == 201


async def test_complete_service_selection_accepts_category_details(env):
    from app.db.session import AsyncSessionLocal
    from app.services.category_onboarding import vendor_has_category_details
    async with AsyncSessionLocal() as s:
        assert await vendor_has_category_details(s, env["v1_obj"].id) is True   # created properties above
        assert await vendor_has_category_details(s, 424242) is False


async def test_media_upload_returns_media_id_usable_by_property(api, env, monkeypatch):
    from app.api.v1.endpoints import media as media_ep

    async def fake_upload(contents, filename, content_type):
        return "https://cdn.example/uploads/" + filename

    monkeypatch.setattr(media_ep.upload_service, "upload_file", fake_upload)
    r = await api.post("/api/v1/media/upload", files={"file": ("a.mp4", b"x", "video/mp4")})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["media_type"] == "video" and j["url"].endswith("a.mp4") and isinstance(j["media_id"], int)
    p = body(env)
    p["media"] = {"image_ids": [], "video_ids": [j["media_id"]], "reel_id": None}
    assert (await api.post("/api/v1/real-estate/properties", json=p)).status_code == 201
