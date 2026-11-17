-- Real Estate: 3) TEST DATA for trying the APIs (dummy media + 3 sample properties + showcase).
-- Run AFTER 01 and 02. Attaches everything to ONE vendor: change v_vendor below if needed.
-- Re-running adds another set. To remove it all, run 04_real_estate_test_data_cleanup.sql.

DO $$
DECLARE
  v_vendor  bigint := (SELECT id FROM vendors ORDER BY id LIMIT 1);   -- <-- put a specific vendor id here
  v_agency  bigint := (SELECT sc.id FROM sub_categories sc JOIN main_categories mc ON mc.id = sc.main_category_id
                       WHERE mc.form_type = 'real_estate' AND sc.name = 'Agency');
  t_res int := (SELECT id FROM re_property_types WHERE code = 'residential');
  t_com int := (SELECT id FROM re_property_types WHERE code = 'commercial');
  t_land int := (SELECT id FROM re_property_types WHERE code = 'open_land');
  f_semi int := (SELECT id FROM re_furniture_types WHERE name = 'Semi Furnished');
  img_ids bigint[]; vid_ids bigint[];
  p1 bigint; p2 bigint; p3 bigint;
BEGIN
  IF v_vendor IS NULL THEN RAISE EXCEPTION 'No vendor found. Log in once as a vendor first, or set v_vendor.'; END IF;
  IF v_agency IS NULL THEN RAISE EXCEPTION 'Run 02_real_estate_seed.sql first.'; END IF;

  -- dummy uploaded media (so no R2 upload is needed)
  WITH i AS (
    INSERT INTO vendor_media (vendor_id, media_type, url, created_at)
    SELECT v_vendor, 'image', 'https://example.com/test/img' || g || '.jpg', now() FROM generate_series(1, 6) g
    RETURNING id)
  SELECT array_agg(id) INTO img_ids FROM i;
  WITH v AS (
    INSERT INTO vendor_media (vendor_id, media_type, url, created_at)
    SELECT v_vendor, 'video', 'https://example.com/test/vid' || g || '.mp4', now() FROM generate_series(1, 3) g
    RETURNING id)
  SELECT array_agg(id) INTO vid_ids FROM v;

  -- 1) Residential (Agency): 2 BHK + 3 BHK, semi furnished, 3 images, 1 video, 1 reel
  INSERT INTO re_properties (vendor_id, sub_category_id, property_type_id, building_name, state, district, city,
      area_locality, furniture_type_id, built_up_area, sale_price, negotiable, available_from, instagram_id,
      facebook_id, is_active, created_at, updated_at)
  VALUES (v_vendor, v_agency, t_res, 'Green Valley Apartments', 'Telangana', 'Hyderabad', 'Hyderabad', 'Madhapur',
      f_semi, '1500 sq.ft', 7500000, true, '2026-12-01', 'test_insta', 'https://facebook.com/test', true, now(), now())
  RETURNING id INTO p1;
  INSERT INTO re_property_bhk (property_id, bhk_type_id, created_at)
    SELECT p1, id, now() FROM re_bhk_types WHERE name IN ('2 BHK', '3 BHK');
  INSERT INTO re_property_media (property_id, media_id, role, url, sort_order, created_at)
    SELECT p1, m.id, CASE WHEN m.id = vid_ids[2] THEN 'reel' WHEN m.media_type = 'video' THEN 'video' ELSE 'image' END,
           m.url, 0, now()
    FROM vendor_media m WHERE m.id IN (img_ids[1], img_ids[2], img_ids[3], vid_ids[1], vid_ids[2]);

  -- 2) Commercial (Agency)
  INSERT INTO re_properties (vendor_id, sub_category_id, property_type_id, building_name, state, district, city,
      area_locality, built_up_area, sale_price, negotiable, available_from, is_active, created_at, updated_at)
  VALUES (v_vendor, v_agency, t_com, 'Business Plaza', 'Telangana', 'Hyderabad', 'Hyderabad', 'Hitech City',
      '2500 sq.ft', 15000000, true, '2026-12-01', true, now(), now())
  RETURNING id INTO p2;
  INSERT INTO re_property_media (property_id, media_id, role, url, sort_order, created_at)
    SELECT p2, id, 'image', url, 0, now() FROM vendor_media WHERE id IN (img_ids[4], img_ids[5]);

  -- 3) Open Land (Agency): sale price + price per square yard
  INSERT INTO re_properties (vendor_id, sub_category_id, property_type_id, state, district, city, area_locality,
      sale_price, price_per_sq_yard, negotiable, available_from, is_active, created_at, updated_at)
  VALUES (v_vendor, v_agency, t_land, 'Telangana', 'Rangareddy', 'Hyderabad', 'Shamshabad',
      5000000, 12000, true, '2026-12-01', true, now(), now())
  RETURNING id INTO p3;

  -- Showcase locations (Agency/Builder only): 3 districts in 2 states. Skipped if the vendor already has some.
  IF NOT EXISTS (SELECT 1 FROM re_showcase WHERE vendor_id = v_vendor) THEN
    INSERT INTO re_showcase (vendor_id, sub_category_id, state, district, created_at) VALUES
      (v_vendor, v_agency, 'Telangana', 'Hyderabad', now()),
      (v_vendor, v_agency, 'Telangana', 'Rangareddy', now()),
      (v_vendor, v_agency, 'Andhra Pradesh', 'Guntur', now());
  END IF;

  RAISE NOTICE 'Vendor % -> properties %, %, %; image media ids %, video media ids %', v_vendor, p1, p2, p3, img_ids, vid_ids;
END $$;

-- Check
SELECT p.id, t.code AS type, p.building_name, p.area_locality, p.sale_price, p.negotiable FROM re_properties p
JOIN re_property_types t ON t.id = p.property_type_id ORDER BY p.id DESC LIMIT 5;
