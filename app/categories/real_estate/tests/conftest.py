"""Integration fixtures. Run only when TEST_DATABASE_URL points at a THROWAWAY Postgres.

    TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@127.0.0.1:55432/retest pytest app/categories/real_estate/tests

Deliberately separate from app/tests/conftest.py (which drops all tables on the configured DB).
"""
import os

import pytest

URL = os.getenv("TEST_DATABASE_URL")
if URL:
    os.environ["SQLALCHEMY_DATABASE_URI"] = URL


def pytest_collection_modifyitems(config, items):
    if URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
