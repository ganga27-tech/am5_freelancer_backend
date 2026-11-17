from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.db.session import get_db
from app.models.freelancer import Freelancer
from app.services.security_service import security_service

security_bearer = HTTPBearer(auto_error=False)

def mask_account_number(account_no: Optional[str]) -> Optional[str]:
    if not account_no:
        return None
    clean = str(account_no).strip()
    if len(clean) <= 4:
        return "XXXX" + clean
    return "X" * (len(clean) - 4) + clean[-4:]

def mask_pan_or_aadhaar(id_val: Optional[str]) -> Optional[str]:
    if not id_val:
        return None
    clean = str(id_val).strip()
    if len(clean) <= 4:
        return "XXXX"
    return "X" * (len(clean) - 4) + clean[-4:]

async def get_current_freelancer(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: AsyncSession = Depends(get_db)
) -> Freelancer:
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required"
        )
    token = auth.credentials

    # Check blacklisted tokens
    if await security_service.is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated",
        )

    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_sub = payload.get("sub")
        if not token_sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        freelancer_id = int(token_sub)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate authentication credentials",
        )

    stmt = select(Freelancer).where(Freelancer.id == freelancer_id)
    result = await db.execute(stmt)
    freelancer = result.scalar_one_or_none()

    if not freelancer:
        raise HTTPException(status_code=404, detail="Freelancer account not found")

    if freelancer.status in ("inactive", "suspended", "blocked", "banned", "deleted"):
        raise HTTPException(status_code=403, detail="Freelancer account is not active")

    return freelancer

async def get_optional_freelancer(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: AsyncSession = Depends(get_db)
) -> Optional[Freelancer]:
    if not auth or not auth.credentials:
        return None
    try:
        token = auth.credentials
        if await security_service.is_token_blacklisted(token):
            return None
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_sub = payload.get("sub")
        if not token_sub:
            return None
        freelancer_id = int(token_sub)
        stmt = select(Freelancer).where(Freelancer.id == freelancer_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except Exception:
        return None

