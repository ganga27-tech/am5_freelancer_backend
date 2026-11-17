from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
from decimal import Decimal

class CityBase(BaseModel):
    name: str
    code: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None
    active: bool = True
    tier: Optional[str] = None

    @field_validator("active", mode="before")
    @classmethod
    def default_active(cls, v):
        # Rows inserted by raw SQL can have NULL here.
        return True if v is None else v

class City(CityBase):
    id: int
    # NULL on rows inserted by raw SQL (no DB-level default).
    created_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

class AddressBase(BaseModel):
    label: str
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    pincode: str
    latitude: Optional[Decimal] = Field(default=None, ge=-90, le=90)
    longitude: Optional[Decimal] = Field(default=None, ge=-180, le=180)
    is_default: bool = False

    @field_validator('label')
    @classmethod
    def validate_label(cls, v: str) -> str:
        v_upper = v.upper()
        if v_upper not in {"HOME", "OFFICE", "OTHER"}:
            raise ValueError("Label must be one of 'HOME', 'OFFICE', or 'OTHER'")
        return v_upper


def _check_pincode(v: str) -> str:
    v = v.strip()
    if not (v.isdigit() and len(v) == 6):
        raise ValueError("Pincode must be 6 digits")
    return v

class AddressCreate(AddressBase):
    # Checked on input only, so old saved rows with odd pincodes can still be listed.
    @field_validator('pincode')
    @classmethod
    def validate_pincode(cls, v: str) -> str:
        return _check_pincode(v)

class AddressUpdate(BaseModel):
    """Partial update: only the fields sent are changed."""
    label: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    latitude: Optional[Decimal] = Field(default=None, ge=-90, le=90)
    longitude: Optional[Decimal] = Field(default=None, ge=-180, le=180)
    is_default: Optional[bool] = None

    @field_validator('label')
    @classmethod
    def validate_label(cls, v):
        if v is None:
            return None
        if v.upper() not in {"HOME", "OFFICE", "OTHER"}:
            raise ValueError("Label must be one of 'HOME', 'OFFICE', or 'OTHER'")
        return v.upper()

    @field_validator('pincode')
    @classmethod
    def validate_pincode(cls, v):
        return None if v is None else _check_pincode(v)

class ServiceabilityResponse(BaseModel):
    serviceable: bool
    message: str
    city: Optional[str] = None

class Address(AddressBase):
    id: int
    customer_id: int
    
    model_config = ConfigDict(from_attributes=True)
