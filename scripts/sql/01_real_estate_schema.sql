-- Real Estate: 1) schema. Generated from the SQLAlchemy models. Safe to re-run (IF NOT EXISTS).
-- Prerequisite: tables vendors, main_categories, sub_categories already exist (they do in your DB).

ALTER TABLE IF EXISTS main_categories ADD COLUMN IF NOT EXISTS form_type VARCHAR NOT NULL DEFAULT 'service_list';
ALTER TABLE IF EXISTS cities ADD COLUMN IF NOT EXISTS district VARCHAR;

CREATE TABLE IF NOT EXISTS re_bhk_types (
	id SERIAL NOT NULL, 
	name VARCHAR(30) NOT NULL, 
	sort_order INTEGER, 
	is_active BOOLEAN, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS re_furniture_types (
	id SERIAL NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	is_active BOOLEAN, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS re_property_types (
	id SERIAL NOT NULL, 
	code VARCHAR(30) NOT NULL, 
	name VARCHAR(60) NOT NULL, 
	is_active BOOLEAN, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE TABLE IF NOT EXISTS re_properties (
	id BIGSERIAL NOT NULL, 
	vendor_id BIGINT NOT NULL, 
	sub_category_id BIGINT NOT NULL, 
	property_type_id INTEGER NOT NULL, 
	building_name VARCHAR(255), 
	state VARCHAR(100) NOT NULL, 
	district VARCHAR(100) NOT NULL, 
	city VARCHAR(100) NOT NULL, 
	area_locality VARCHAR(255) NOT NULL, 
	furniture_type_id INTEGER, 
	built_up_area VARCHAR(50), 
	sale_price NUMERIC(14, 2) NOT NULL, 
	price_per_sq_yard NUMERIC(12, 2), 
	negotiable BOOLEAN NOT NULL, 
	available_from DATE, 
	facebook_id VARCHAR(255), 
	instagram_id VARCHAR(255), 
	youtube_id VARCHAR(255), 
	linkedin_id VARCHAR(255), 
	is_active BOOLEAN, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
	FOREIGN KEY(sub_category_id) REFERENCES sub_categories (id), 
	FOREIGN KEY(property_type_id) REFERENCES re_property_types (id), 
	FOREIGN KEY(furniture_type_id) REFERENCES re_furniture_types (id)
);
CREATE INDEX IF NOT EXISTS ix_re_properties_id ON re_properties (id);
CREATE INDEX IF NOT EXISTS ix_re_properties_vendor_id ON re_properties (vendor_id);

CREATE TABLE IF NOT EXISTS re_showcase (
	id BIGSERIAL NOT NULL, 
	vendor_id BIGINT NOT NULL, 
	sub_category_id BIGINT NOT NULL, 
	state VARCHAR(100) NOT NULL, 
	district VARCHAR(100) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (vendor_id, state, district), 
	FOREIGN KEY(vendor_id) REFERENCES vendors (id), 
	FOREIGN KEY(sub_category_id) REFERENCES sub_categories (id)
);
CREATE INDEX IF NOT EXISTS ix_re_showcase_vendor_id ON re_showcase (vendor_id);

CREATE TABLE IF NOT EXISTS re_subcategory_property_types (
	id SERIAL NOT NULL, 
	sub_category_id BIGINT NOT NULL, 
	property_type_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (sub_category_id, property_type_id), 
	FOREIGN KEY(sub_category_id) REFERENCES sub_categories (id), 
	FOREIGN KEY(property_type_id) REFERENCES re_property_types (id)
);
CREATE INDEX IF NOT EXISTS ix_re_subcategory_property_types_sub_category_id ON re_subcategory_property_types (sub_category_id);

CREATE TABLE IF NOT EXISTS vendor_media (
	id BIGSERIAL NOT NULL, 
	vendor_id BIGINT NOT NULL, 
	media_type VARCHAR(20) NOT NULL, 
	url TEXT NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(vendor_id) REFERENCES vendors (id)
);
CREATE INDEX IF NOT EXISTS ix_vendor_media_id ON vendor_media (id);
CREATE INDEX IF NOT EXISTS ix_vendor_media_vendor_id ON vendor_media (vendor_id);

CREATE TABLE IF NOT EXISTS re_property_bhk (
	id BIGSERIAL NOT NULL, 
	property_id BIGINT NOT NULL, 
	bhk_type_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (property_id, bhk_type_id), 
	FOREIGN KEY(property_id) REFERENCES re_properties (id) ON DELETE CASCADE, 
	FOREIGN KEY(bhk_type_id) REFERENCES re_bhk_types (id)
);
CREATE INDEX IF NOT EXISTS ix_re_property_bhk_property_id ON re_property_bhk (property_id);

CREATE TABLE IF NOT EXISTS re_property_media (
	id BIGSERIAL NOT NULL, 
	property_id BIGINT NOT NULL, 
	media_id BIGINT NOT NULL, 
	role VARCHAR(10) NOT NULL, 
	url TEXT NOT NULL, 
	sort_order INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(property_id) REFERENCES re_properties (id) ON DELETE CASCADE, 
	FOREIGN KEY(media_id) REFERENCES vendor_media (id)
);
CREATE INDEX IF NOT EXISTS ix_re_property_media_property_id ON re_property_media (property_id);
