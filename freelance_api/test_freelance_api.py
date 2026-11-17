import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.base_class import Base
from app.db.session import get_db
import freelance_api.models
from freelance_api.seed_data import seed_freelance_defaults

test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def override_get_db():
    async with TestingSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(autouse=True)
def setup_test_db():
    import asyncio
    async def init():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with TestingSessionLocal() as session:
            await seed_freelance_defaults(session)
    asyncio.run(init())
    yield

@pytest.mark.asyncio
async def test_legal_pages_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/legal-pages")
        assert response.status_code == 200
        json_data = response.json()
        assert json_data["success"] is True
        assert len(json_data["data"]) >= 2
        slugs = [p["slug"] for p in json_data["data"]]
        assert "privacy-policy" in slugs
        assert "terms-and-conditions" in slugs

@pytest.mark.asyncio
async def test_installation_rules_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/installation-rewards/rules?app_type=customer")
        assert response.status_code == 200
        json_data = response.json()
        assert json_data["success"] is True
        milestones = json_data["data"]["milestones"]
        assert len(milestones) >= 4

@pytest.mark.asyncio
async def test_referral_rules_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/referrals/rules")
        assert response.status_code == 200
        json_data = response.json()
        assert json_data["success"] is True
        assert len(json_data["data"]["rules"]) == 4

@pytest.mark.asyncio
async def test_faqs_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/faqs?audience=freelancer")
        assert response.status_code == 200
        json_data = response.json()
        assert json_data["success"] is True

@pytest.mark.asyncio
async def test_search_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/search?q=earn&scope=all")
        assert response.status_code == 200
        json_data = response.json()
        assert json_data["success"] is True
        assert "items" in json_data["data"]

@pytest.mark.asyncio
async def test_auth_registration_and_login():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        reg_payload = {
            "full_name": "Ravi Kumar",
            "mobile_number": "9876543210",
            "email": "ravi.kumar@example.com",
            "password": "Password123",
            "confirm_password": "Password123"
        }
        reg_res = await ac.post("/api/v1/auth/register", json=reg_payload)
        assert reg_res.status_code == 201
        reg_data = reg_res.json()
        assert reg_data["success"] is True
        user_id = reg_data["data"]["user_id"]

        login_payload = {
            "identifier": "ravi.kumar@example.com",
            "password": "Password123"
        }
        login_res = await ac.post("/api/v1/auth/login", json=login_payload)
        assert login_res.status_code == 200
        login_data = login_res.json()
        assert login_data["success"] is True
        token = login_data["data"]["access_token"]
        assert token is not None

        headers = {"Authorization": f"Bearer {token}"}
        prof_res = await ac.get("/api/v1/freelancer/profile", headers=headers)
        assert prof_res.status_code == 200
        prof_data = prof_res.json()
        assert prof_data["success"] is True
        assert prof_data["data"]["user_id"] == user_id
        assert prof_data["data"]["full_name"] == "Ravi Kumar"
