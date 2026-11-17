"""Smoke test for the Real Estate APIs: creates test data, calls every endpoint, prints PASS/FAIL.

Usage (server must be running, and this script must use the SAME database as the server):
    python scripts/real_estate_smoke_test.py                       # http://localhost:8000
    python scripts/real_estate_smoke_test.py --base http://localhost:8001/api/v1
    python scripts/real_estate_smoke_test.py --keep                # keep created test data
    python scripts/real_estate_smoke_test.py --mobile 7569463687 --otp 12345

Test data it creates (and removes at the end unless --keep):
    * the vendor for the test mobile (auto-created by login if missing)
    * 7 image + 3 video media rows for that vendor (dummy URLs, so no R2 upload is needed)
    * a few properties and a showcase
"""
import argparse
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if (detail and not ok) else ""))


async def make_media(mobile):
    """Insert dummy media rows straight into the DB for the test vendor. Returns (vendor_id, imgs, vids)."""
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal, engine
    from app.models.user_location import User
    from app.models.vendor import Vendor
    from app.models.vendor_media import VendorMedia

    async with AsyncSessionLocal() as s:
        vendor = (
            await s.execute(select(Vendor).join(User, User.id == Vendor.user_id).where(User.mobile.like(f"%{mobile}")))
        ).scalars().first()
        if vendor is None:
            raise SystemExit("Vendor not found for that mobile; did login succeed against the same database?")
        imgs, vids = [], []
        for i in range(7):
            m = VendorMedia(vendor_id=vendor.id, media_type="image", url=f"https://example.com/test/img{i}.jpg")
            s.add(m); await s.flush(); imgs.append(m.id)
        for i in range(3):
            m = VendorMedia(vendor_id=vendor.id, media_type="video", url=f"https://example.com/test/vid{i}.mp4")
            s.add(m); await s.flush(); vids.append(m.id)
        await s.commit()
        vid = vendor.id
    await engine.dispose()
    return vid, imgs, vids


async def cleanup(vendor_id, media_ids):
    from sqlalchemy import delete
    from app.categories.real_estate.models import ReProperty, ReShowcase
    from app.db.session import AsyncSessionLocal, engine
    from app.models.vendor_media import VendorMedia

    async with AsyncSessionLocal() as s:
        for p in (await s.execute(__import__("sqlalchemy").select(ReProperty).where(ReProperty.vendor_id == vendor_id))).scalars():
            await s.delete(p)
        await s.flush()
        await s.execute(delete(ReShowcase).where(ReShowcase.vendor_id == vendor_id))
        await s.execute(delete(VendorMedia).where(VendorMedia.id.in_(media_ids)))
        await s.commit()
    await engine.dispose()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000/api/v1")
    ap.add_argument("--mobile", default="7569463687")
    ap.add_argument("--otp", default="12345")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    http = httpx.Client(base_url=a.base, timeout=30)

    print("\n== 1. Login ==")
    r = http.get(a.base.replace("/api/v1", "") + "/health")
    check("server health", r.status_code == 200, r.text)
    http.post("/auth/vendor/send-otp", json={"mobile": a.mobile})
    r = http.post("/auth/vendor/verify-otp", json={"mobile": a.mobile, "otp": a.otp})
    check("vendor login (verify-otp)", r.status_code == 200, r.text)
    if r.status_code != 200:
        raise SystemExit("Cannot continue without a token.")
    http.headers["Authorization"] = "Bearer " + r.json()["access_token"]

    print("\n== 2. Test data (dummy media rows) ==")
    vendor_id, imgs, vids = asyncio.run(make_media(a.mobile))
    check(f"created media for vendor {vendor_id}", len(imgs) == 7 and len(vids) == 3)

    try:
        print("\n== 3. Categories & master data ==")
        r = http.get("/vendor/catalog/main-categories")
        re_cat = [c for c in r.json() if c["name"].lower() == "real estate"] if r.status_code == 200 else []
        check("main-categories lists Real Estate with form_type=real_estate (hidden? run: python -m app.db.migrate_real_estate --activate)", bool(re_cat) and re_cat[0].get("form_type") == "real_estate", r.text[:200])
        others = [c for c in r.json() if c["name"].lower() != "real estate"] if r.status_code == 200 else []
        check("other categories keep form_type=service_list", all(c.get("form_type") == "service_list" for c in others))

        r = http.get("/real-estate/master")
        check("GET /real-estate/master", r.status_code == 200, r.text[:200])
        m = r.json()
        subs = {s["name"]: s for s in m["sub_categories"]}
        check("3 subcategories (Agency/Builder/Single Owner)", set(subs) == {"Agency", "Builder", "Single Owner"}, str(list(subs)))
        check("Builder has no Open Land", [t["code"] for t in subs["Builder"]["property_types"]] == ["residential", "commercial"])
        check("Agency & Single Owner have 3 property types", len(subs["Agency"]["property_types"]) == 3 and len(subs["Single Owner"]["property_types"]) == 3)
        check("Single Owner: no reel, no showcase", subs["Single Owner"]["reel_allowed"] is False and subs["Single Owner"]["showcase_allowed"] is False)
        check("BHK (6) and furniture (2) masters", len(m["bhk_types"]) == 6 and len(m["furniture_types"]) == 2)
        AG, BU, SO = subs["Agency"]["id"], subs["Builder"]["id"], subs["Single Owner"]["id"]
        T = {t["code"]: t["id"] for t in subs["Agency"]["property_types"]}
        BHK = [b["id"] for b in m["bhk_types"]][:2]
        FURN = m["furniture_types"][0]["id"]

        print("\n== 4. Location lookups ==")
        for path in ("/location/states", "/location/districts?state=Telangana", "/location/city-options?state=Telangana"):
            r = http.get(path)
            check(f"GET {path}", r.status_code == 200 and isinstance(r.json(), list), r.text[:150])

        loc = {"state": "Telangana", "district": "Hyderabad", "city": "Hyderabad", "area_locality": "Madhapur"}

        def prop(sub, type_code, **over):
            b = {"sub_category_id": sub, "property_type_id": T[type_code], "property_details": {"building_name": "Test Tower"},
                 "location": loc, "pricing": {"sale_price": 7500000}, "available_from": "2026-12-01",
                 "media": {"image_ids": imgs[:3], "video_ids": [vids[0]], "reel_id": None},
                 "social_media": {"instagram_id": "test_insta", "facebook_id": "https://facebook.com/test"}}
            if type_code == "residential":
                b["residential_details"] = {"bhk_type_ids": BHK, "furniture_type_id": FURN, "built_up_area": "1500 sq.ft"}
            elif type_code == "commercial":
                b["commercial_details"] = {"built_up_area": "2500 sq.ft"}
            else:
                b["open_land_details"] = {"price_per_square_yard": 12000}
            b.update(over)
            return b

        print("\n== 5. Property create / read / update / delete ==")
        r = http.post("/real-estate/properties", json=prop(AG, "residential", media={"image_ids": imgs[:3], "video_ids": [vids[0]], "reel_id": vids[1]}))
        check("create Residential (Agency, with reel)", r.status_code == 201, r.text[:300])
        pid = r.json().get("id")
        r = http.post("/real-estate/properties", json=prop(AG, "commercial"))
        check("create Commercial", r.status_code == 201, r.text[:300])
        r = http.post("/real-estate/properties", json=prop(AG, "open_land"))
        check("create Open Land (Agency)", r.status_code == 201, r.text[:300])
        r = http.post("/real-estate/properties", json=prop(SO, "residential"))
        check("create Residential (Single Owner, no reel)", r.status_code == 201, r.text[:300])
        r = http.post("/real-estate/properties", json=prop(BU, "commercial", media={"image_ids": [], "video_ids": [], "reel_id": vids[2]}))
        check("create Commercial (Builder, with reel)", r.status_code == 201, r.text[:300])

        r = http.get("/real-estate/properties")
        check("list properties (5)", r.status_code == 200 and r.json()["total"] == 5, r.text[:200])
        r = http.get(f"/real-estate/properties/{pid}")
        j = r.json() if r.status_code == 200 else {}
        check("get one: residential details, negotiable default true, media",
              j.get("property_type") == "residential" and j["pricing"]["negotiable_price"] is True
              and len(j["residential_details"]["bhk_types"]) == 2 and len(j["media"]["images"]) == 3 and j["media"]["reel"] is not None, r.text[:300])
        r = http.put(f"/real-estate/properties/{pid}", json=prop(AG, "residential", pricing={"sale_price": 9000000, "negotiable_price": False},
                                                                 residential_details={"bhk_type_ids": BHK[:1], "furniture_type_id": FURN, "built_up_area": "1400 sq.ft"}))
        check("update property", r.status_code == 200, r.text[:300])
        j = http.get(f"/real-estate/properties/{pid}").json()
        check("update replaced values (price, negotiable off, 1 BHK)",
              j["pricing"] == {"sale_price": 9000000.0, "negotiable_price": False} and len(j["residential_details"]["bhk_types"]) == 1)
        r = http.delete(f"/real-estate/properties/{pid}")
        check("delete property", r.status_code == 200, r.text)
        check("deleted property -> 404", http.get(f"/real-estate/properties/{pid}").status_code == 404)

        print("\n== 6. Validation rules (each must be 422) ==")
        def expect422(name, body):
            r = http.post("/real-estate/properties", json=body)
            check(name, r.status_code == 422, f"{r.status_code} {r.text[:200]}")
        # Builder has no Open Land row in the master, so use Agency's open-land type id
        expect422("Builder + Open Land rejected", prop(BU, "open_land"))
        expect422("Single Owner + reel rejected", prop(SO, "commercial", media={"image_ids": [], "video_ids": [], "reel_id": vids[2]}))
        expect422("more than 5 images rejected", prop(AG, "commercial", media={"image_ids": imgs[:6], "video_ids": [], "reel_id": None}))
        expect422("video used as image rejected", prop(AG, "commercial", media={"image_ids": [vids[0]], "video_ids": [], "reel_id": None}))
        expect422("non-existent media id rejected", prop(AG, "commercial", media={"image_ids": [99999999], "video_ids": [], "reel_id": None}))
        expect422("residential missing BHK/furniture/area", prop(AG, "residential", residential_details={}))
        expect422("missing sale price", prop(AG, "commercial", pricing={}))
        expect422("open land missing price per sq yard", prop(AG, "open_land", open_land_details={}))
        expect422("invalid subcategory", prop(AG, "commercial", sub_category_id=99999999))

        print("\n== 7. Showcase ==")
        S = "/real-estate/showcase"
        body = {"sub_category_id": AG, "showcase_locations": [{"state": "Telangana", "districts": ["Hyderabad", "Rangareddy"]},
                                                              {"state": "Andhra Pradesh", "districts": ["Guntur"]}]}
        r = http.post(S, json=body)
        check("create showcase (2 states, 3 districts)", r.status_code == 201 and (r.json()["total_states"], r.json()["total_districts"]) == (2, 3), r.text[:300])
        check("create again -> 409", http.post(S, json=body).status_code == 409)
        r = http.get(S)
        check("get showcase", r.status_code == 200 and r.json()["total_districts"] == 3, r.text[:200])
        r = http.put(S, json={"showcase_locations": [{"state": "Telangana", "districts": ["Hyderabad", "Hyderabad"]}]})
        check("duplicate district in request -> 409", r.status_code == 409, r.text[:200])
        r = http.put(S, json={"showcase_locations": [{"state": "Telangana", "districts": ["Hyderabad"]}]})
        check("update showcase", r.status_code == 200 and r.json()["total_districts"] == 1, r.text[:200])
        check("delete showcase", http.delete(S).status_code == 200)
        check("showcase empty after delete", http.get(S).json()["total_districts"] == 0)
        r = http.post(S, json={"sub_category_id": SO, "showcase_locations": [{"state": "Telangana", "districts": ["Hyderabad"]}]})
        check("Single Owner showcase -> 403", r.status_code == 403, r.text[:200])
        r = http.post(S, json={"sub_category_id": BU, "showcase_locations": [{"state": "Telangana", "districts": ["Hyderabad"]}]})
        check("Builder showcase allowed", r.status_code == 201, r.text[:200])
        http.delete(S)

        print("\n== 8. Registration flow ==")
        r = http.get("/vendors/me/onboarding-status")
        check("onboarding-status: services_added true (has properties)", r.status_code == 200 and r.json().get("services_added") is True, r.text[:200])
        print("  (skipped: POST /vendor/catalog/complete-service-selection, since it sends a push notification)")
    finally:
        if a.keep:
            print("\n--keep: test data left in place.")
        else:
            asyncio.run(cleanup(vendor_id, imgs + vids))
            print("\nTest data removed.")

    passed, total = sum(results), len(results)
    print(f"\n{'ALL PASSED' if passed == total else 'SOME FAILED'}: {passed}/{total}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
