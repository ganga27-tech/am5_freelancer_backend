"""Single place that knows which category modules exist.

To add a category (e.g. Packers & Movers): create app/categories/<name>/ with
models.py, schemas.py, service.py (has_details), router.py, seed.py, then add one
entry here and one import in app/models/__init__.py.
"""
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.categories.real_estate import router as re_router
from app.categories.real_estate import seed as re_seed
from app.categories.real_estate import service as re_service


@dataclass(frozen=True)
class CategoryModule:
    form_type: str
    prefix: str  # URL prefix under /api/v1
    router: APIRouter
    has_details: Callable[[AsyncSession, int], Awaitable[bool]]
    seed: Callable[[AsyncSession, Optional[bool]], Awaitable[None]]  # (session, activate)


CATEGORIES = [
    CategoryModule(
        form_type="real_estate",
        prefix="/real-estate",
        router=re_router.router,
        has_details=re_service.has_details,
        seed=re_seed.seed,
    ),
]
