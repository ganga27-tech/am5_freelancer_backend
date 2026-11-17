-- Removes the TEST DATA created by 03_real_estate_test_data.sql (dummy media, example.com URLs).
-- Does NOT touch master data or any real property/media.
DELETE FROM re_properties WHERE id IN (
  SELECT property_id FROM re_property_media WHERE url LIKE 'https://example.com/test/%'
  UNION SELECT id FROM re_properties WHERE building_name IN ('Green Valley Apartments', 'Business Plaza')
  UNION SELECT id FROM re_properties WHERE area_locality = 'Shamshabad' AND sale_price = 5000000 AND price_per_sq_yard = 12000);
DELETE FROM re_showcase WHERE state IN ('Telangana', 'Andhra Pradesh') AND district IN ('Hyderabad', 'Rangareddy', 'Guntur')
  AND vendor_id IN (SELECT DISTINCT vendor_id FROM vendor_media WHERE url LIKE 'https://example.com/test/%');
DELETE FROM vendor_media WHERE url LIKE 'https://example.com/test/%';
