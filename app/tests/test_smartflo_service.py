import pytest
from app.services.smartflo_service import smartflo_service

def test_normalize_phone_number_valid():
    assert smartflo_service.normalize_phone_number("9876543210") == "9876543210"
    assert smartflo_service.normalize_phone_number("+91 9876543210") == "9876543210"
    assert smartflo_service.normalize_phone_number("+91-98765-43210") == "9876543210"
    assert smartflo_service.normalize_phone_number("09876543210") == "9876543210"
    assert smartflo_service.normalize_phone_number("919876543210") == "9876543210"
    assert smartflo_service.normalize_phone_number("060123") == "060123"  # Extension

def test_normalize_phone_number_invalid():
    with pytest.raises(ValueError):
        smartflo_service.normalize_phone_number("")
    with pytest.raises(ValueError):
        smartflo_service.normalize_phone_number("12")
