import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base_class import Base

_now = datetime.datetime.utcnow


# --------------------------- master data --------------------------------
class RePropertyType(Base):
    __tablename__ = "re_property_types"

    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False)  # residential | commercial | open_land
    name = Column(String(60), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)


class ReSubcategoryPropertyType(Base):
    """Which property types a Real Estate subcategory may use (Builder -> no open_land)."""
    __tablename__ = "re_subcategory_property_types"
    __table_args__ = (UniqueConstraint("sub_category_id", "property_type_id"),)

    id = Column(Integer, primary_key=True)
    sub_category_id = Column(BigInteger, ForeignKey("sub_categories.id"), index=True, nullable=False)
    property_type_id = Column(Integer, ForeignKey("re_property_types.id"), nullable=False)
    created_at = Column(DateTime, default=_now)


class ReBhkType(Base):
    __tablename__ = "re_bhk_types"

    id = Column(Integer, primary_key=True)
    name = Column(String(30), unique=True, nullable=False)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)


class ReFurnitureType(Base):
    __tablename__ = "re_furniture_types"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)


# --------------------------- vendor data --------------------------------
class ReProperty(Base):
    __tablename__ = "re_properties"

    id = Column(BigInteger, primary_key=True, index=True)
    vendor_id = Column(BigInteger, ForeignKey("vendors.id"), index=True, nullable=False)
    sub_category_id = Column(BigInteger, ForeignKey("sub_categories.id"), nullable=False)
    property_type_id = Column(Integer, ForeignKey("re_property_types.id"), nullable=False)

    building_name = Column(String(255), nullable=True)

    state = Column(String(100), nullable=False)
    district = Column(String(100), nullable=False)
    city = Column(String(100), nullable=False)
    area_locality = Column(String(255), nullable=False)

    furniture_type_id = Column(Integer, ForeignKey("re_furniture_types.id"), nullable=True)
    built_up_area = Column(String(50), nullable=True)

    sale_price = Column(Numeric(14, 2), nullable=False)
    price_per_sq_yard = Column(Numeric(12, 2), nullable=True)
    negotiable = Column(Boolean, nullable=False, default=True)
    # Nullable only for properties created before Selling Coverage was introduced.
    selling_coverage_mode = Column(String(20), nullable=True)
    available_from = Column(Date, nullable=True)

    facebook_id = Column(String(255), nullable=True)
    instagram_id = Column(String(255), nullable=True)
    youtube_id = Column(String(255), nullable=True)
    linkedin_id = Column(String(255), nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    bhk_links = relationship("RePropertyBhk", cascade="all, delete-orphan", lazy="selectin")
    coverage_locations = relationship("RePropertyCoverageLocation", cascade="all, delete-orphan", lazy="selectin")
    media = relationship("RePropertyMedia", cascade="all, delete-orphan", lazy="selectin")


class RePropertyBhk(Base):
    __tablename__ = "re_property_bhk"
    __table_args__ = (UniqueConstraint("property_id", "bhk_type_id"),)

    id = Column(BigInteger, primary_key=True)
    property_id = Column(BigInteger, ForeignKey("re_properties.id", ondelete="CASCADE"), index=True, nullable=False)
    bhk_type_id = Column(Integer, ForeignKey("re_bhk_types.id"), nullable=False)
    created_at = Column(DateTime, default=_now)


class RePropertyMedia(Base):
    __tablename__ = "re_property_media"

    id = Column(BigInteger, primary_key=True)
    property_id = Column(BigInteger, ForeignKey("re_properties.id", ondelete="CASCADE"), index=True, nullable=False)
    media_id = Column(BigInteger, ForeignKey("vendor_media.id"), nullable=False)
    role = Column(String(10), nullable=False)  # image | video | reel
    url = Column(Text, nullable=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)


class ReShowcase(Base):
    """Districts a vendor (Agency/Builder) promotes properties in."""
    __tablename__ = "re_showcase"
    __table_args__ = (UniqueConstraint("vendor_id", "state", "district"),)

    id = Column(BigInteger, primary_key=True)
    vendor_id = Column(BigInteger, ForeignKey("vendors.id"), index=True, nullable=False)
    sub_category_id = Column(BigInteger, ForeignKey("sub_categories.id"), nullable=False)
    state = Column(String(100), nullable=False)
    district = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=_now)

class ReCoverageState(Base):
    __tablename__ = "re_coverage_states"

    id = Column(Integer, primary_key=True)
    code = Column(String(16), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    districts = relationship("ReCoverageDistrict", cascade="all, delete-orphan", lazy="selectin")


class ReCoverageDistrict(Base):
    __tablename__ = "re_coverage_districts"
    __table_args__ = (
        UniqueConstraint("state_id", "code"),
        UniqueConstraint("state_id", "name"),
    )

    id = Column(Integer, primary_key=True)
    state_id = Column(Integer, ForeignKey("re_coverage_states.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(64), nullable=False)
    name = Column(String(100), nullable=False)
    state = relationship("ReCoverageState", back_populates="districts")


class RePropertyCoverageLocation(Base):
    __tablename__ = "re_property_coverage_locations"

    id = Column(BigInteger, primary_key=True)
    property_id = Column(BigInteger, ForeignKey("re_properties.id", ondelete="CASCADE"), nullable=False, index=True)
    state_id = Column(Integer, ForeignKey("re_coverage_states.id"), nullable=False)
    district_id = Column(Integer, ForeignKey("re_coverage_districts.id"), nullable=True)
    state = relationship("ReCoverageState", lazy="joined")
    district = relationship("ReCoverageDistrict", lazy="joined")