from fastapi import APIRouter

from app.categories.registry import CATEGORIES

router = APIRouter()
for _c in CATEGORIES:
    router.include_router(_c.router, prefix=_c.prefix, tags=[f"category:{_c.form_type}"])
