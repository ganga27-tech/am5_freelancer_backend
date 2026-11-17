-- Real Estate: 2) master data (category, subcategories, property types, BHK, furniture).
-- Run AFTER 01_real_estate_schema.sql. Safe to re-run: nothing is inserted twice.

-- Category (tags an existing "Real Estate" row, or creates it HIDDEN: is_active = false).
-- Show it in the apps later with:  UPDATE main_categories SET is_active = true WHERE form_type = 'real_estate';
INSERT INTO main_categories (name, is_active, created_at)
SELECT 'Real Estate', false, now()
WHERE NOT EXISTS (SELECT 1 FROM main_categories WHERE lower(name) = 'real estate');

UPDATE main_categories SET form_type = 'real_estate' WHERE lower(name) = 'real estate';

-- Subcategories
INSERT INTO sub_categories (main_category_id, name, is_active, sort_order, created_at)
SELECT c.id, s.name, true, s.ord, now()
FROM main_categories c
CROSS JOIN (VALUES ('Agency', 0), ('Builder', 1), ('Single Owner', 2)) AS s(name, ord)
WHERE c.form_type = 'real_estate'
  AND NOT EXISTS (SELECT 1 FROM sub_categories x WHERE x.main_category_id = c.id AND x.name = s.name);

-- Property types
INSERT INTO re_property_types (code, name, is_active, created_at) VALUES
  ('residential', 'Residential', true, now()),
  ('commercial',  'Commercial',  true, now()),
  ('open_land',   'Open Land',   true, now())
ON CONFLICT (code) DO NOTHING;

-- Which property types each subcategory may use. Builder gets NO Open Land.
INSERT INTO re_subcategory_property_types (sub_category_id, property_type_id, created_at)
SELECT sc.id, pt.id, now()
FROM sub_categories sc
JOIN main_categories mc ON mc.id = sc.main_category_id AND mc.form_type = 'real_estate'
JOIN re_property_types pt ON
     (sc.name IN ('Agency', 'Single Owner') AND pt.code IN ('residential', 'commercial', 'open_land'))
  OR (sc.name = 'Builder'                   AND pt.code IN ('residential', 'commercial'))
ON CONFLICT (sub_category_id, property_type_id) DO NOTHING;

-- BHK types
INSERT INTO re_bhk_types (name, sort_order, is_active, created_at) VALUES
  ('1 RK', 0, true, now()), ('1 BHK', 1, true, now()), ('2 BHK', 2, true, now()),
  ('3 BHK', 3, true, now()), ('4 BHK', 4, true, now()), ('5+ BHK', 5, true, now())
ON CONFLICT (name) DO NOTHING;

-- Furniture types
INSERT INTO re_furniture_types (name, is_active, created_at) VALUES
  ('Semi Furnished', true, now()), ('Fully Furnished', true, now())
ON CONFLICT (name) DO NOTHING;

-- Check
SELECT sc.name AS subcategory, string_agg(pt.name, ', ' ORDER BY pt.id) AS property_types
FROM sub_categories sc
JOIN main_categories mc ON mc.id = sc.main_category_id AND mc.form_type = 'real_estate'
JOIN re_subcategory_property_types l ON l.sub_category_id = sc.id
JOIN re_property_types pt ON pt.id = l.property_type_id
GROUP BY sc.name, sc.sort_order ORDER BY sc.sort_order;
