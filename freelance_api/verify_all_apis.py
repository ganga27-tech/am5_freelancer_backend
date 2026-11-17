import asyncio
import sys
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

async def run_all_checks():
    print("Initializing test in-memory database...")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        await seed_freelance_defaults(session)

    print("Running API verification tests against all doc endpoints...")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Banners
        res = await ac.get("/api/v1/banners?placement=home")
        assert res.status_code == 200, res.text
        assert res.json()["success"] is True
        print("✓ GET /api/v1/banners?placement=home")

        # 2. Demo Videos
        res = await ac.get("/api/v1/demo-videos?audience=freelancer")
        assert res.status_code == 200, res.text
        assert res.json()["success"] is True
        print("✓ GET /api/v1/demo-videos?audience=freelancer")

        # 3. Service Categories
        res = await ac.get("/api/v1/service-categories")
        assert res.status_code == 200, res.text
        assert res.json()["success"] is True
        print("✓ GET /api/v1/service-categories")

        # 4. Referral Rules
        res = await ac.get("/api/v1/referrals/rules")
        assert res.status_code == 200, res.text
        assert res.json()["success"] is True
        assert len(res.json()["data"]["rules"]) == 4
        print("✓ GET /api/v1/referrals/rules")

        # 5. Installation Rules
        res = await ac.get("/api/v1/installation-rewards/rules?app_type=customer")
        assert res.status_code == 200, res.text
        assert res.json()["success"] is True
        print("✓ GET /api/v1/installation-rewards/rules")

        # 6. FAQs
        res = await ac.get("/api/v1/faqs?audience=freelancer")
        assert res.status_code == 200, res.text
        assert res.json()["success"] is True
        print("✓ GET /api/v1/faqs")

        # 7. Legal Pages
        res = await ac.get("/api/v1/legal-pages")
        assert res.status_code == 200, res.text
        assert res.json()["success"] is True
        print("✓ GET /api/v1/legal-pages")

        # 8. Search
        res = await ac.get("/api/v1/search?q=referral&scope=all")
        assert res.status_code == 200, res.text
        assert res.json()["success"] is True
        print("✓ GET /api/v1/search")

        # 9. Register Freelancer
        reg_payload = {
            "full_name": "Suresh Reddy",
            "mobile_number": "9123456789",
            "email": "suresh.reddy@example.com",
            "password": "Password123",
            "confirm_password": "Password123"
        }
        res = await ac.post("/api/v1/auth/register", json=reg_payload)
        assert res.status_code == 201, res.text
        reg_json = res.json()
        assert reg_json["success"] is True
        user_id = reg_json["data"]["user_id"]
        print(f"✓ POST /api/v1/auth/register (User ID: {user_id})")

        # 10. Login
        login_res = await ac.post("/api/v1/auth/login", json={
            "identifier": "suresh.reddy@example.com",
            "password": "Password123"
        })
        assert login_res.status_code == 200, login_res.text
        token = login_res.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("✓ POST /api/v1/auth/login (JWT Token generated)")

        # 11. Profile
        res = await ac.get("/api/v1/freelancer/profile", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["full_name"] == "Suresh Reddy"
        print("✓ GET /api/v1/freelancer/profile")

        # 12. Update Profile
        res = await ac.patch("/api/v1/freelancer/profile", json={"city": "Vijayawada", "pincode": "520001", "address": "Bunder Road"}, headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["city"] == "Vijayawada"
        print("✓ PATCH /api/v1/freelancer/profile")

        # 13. Bank details
        res = await ac.put("/api/v1/freelancer/bank-details", json={
            "account_holder_name": "Suresh Reddy",
            "account_number": "50100234567890",
            "ifsc_code": "HDFC0000123",
            "bank_name": "HDFC Bank"
        }, headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["masked_account_number"] == "XXXXXXXXXX7890"
        print("✓ PUT /api/v1/freelancer/bank-details (Masked account number verified)")

        # 14. Profile Completion
        res = await ac.get("/api/v1/freelancer/profile/completion", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["completion_percentage"] >= 50
        print(f"✓ GET /api/v1/freelancer/profile/completion ({res.json()['data']['completion_percentage']}%)")

        # 15. Generate Referral Link
        res = await ac.post("/api/v1/referrals/links", json={
            "referral_type": "customer",
            "validity_days": 15
        }, headers=headers)
        assert res.status_code == 201, res.text
        ref_code = res.json()["data"]["referral_code"]
        print(f"✓ POST /api/v1/referrals/links (Generated code: {ref_code})")

        # 16. Validate Referral Code
        res = await ac.get(f"/api/v1/referrals/validate/{ref_code}")
        assert res.status_code == 200, res.text
        assert res.json()["data"]["valid"] is True
        print("✓ GET /api/v1/referrals/validate/{code}")

        # 17. List Referral Links
        res = await ac.get("/api/v1/referrals/links", headers=headers)
        assert res.status_code == 200, res.text
        assert len(res.json()["data"]["items"]) >= 1
        print("✓ GET /api/v1/referrals/links")

        # 18. Referral Rewards Summary
        res = await ac.get("/api/v1/referrals/rewards/summary", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["total_points"] >= 50
        print("✓ GET /api/v1/referrals/rewards/summary")

        # 19. Level & Progress
        res = await ac.get("/api/v1/referrals/level-progress", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["current_level"] == "Bronze"
        print("✓ GET /api/v1/referrals/level-progress")

        # 20. Installation Statistics
        res = await ac.get("/api/v1/installation-rewards/statistics", headers=headers)
        assert res.status_code == 200, res.text
        print("✓ GET /api/v1/installation-rewards/statistics")

        # 21. Installation Eligibility
        res = await ac.get("/api/v1/installation-rewards/eligibility?app_type=customer", headers=headers)
        assert res.status_code == 200, res.text
        print("✓ GET /api/v1/installation-rewards/eligibility")

        # 22. Rewards Summary
        res = await ac.get("/api/v1/rewards/summary", headers=headers)
        assert res.status_code == 200, res.text
        print("✓ GET /api/v1/rewards/summary")

        # 23. Rewards History
        res = await ac.get("/api/v1/rewards/history?status=all", headers=headers)
        assert res.status_code == 200, res.text
        print("✓ GET /api/v1/rewards/history")

        # 24. Wallet Summary
        res = await ac.get("/api/v1/wallet/summary", headers=headers)
        assert res.status_code == 200, res.text
        print("✓ GET /api/v1/wallet/summary")

        # 25. Wallet Transactions
        res = await ac.get("/api/v1/wallet/transactions", headers=headers)
        assert res.status_code == 200, res.text
        print("✓ GET /api/v1/wallet/transactions")

        # 26. KYC Status
        res = await ac.get("/api/v1/freelancer/kyc/status", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["overall_status"] == "NOT_STARTED"
        print("✓ GET /api/v1/freelancer/kyc/status")

        # 27. Start Face Verification
        res = await ac.post("/api/v1/freelancer/kyc/face-verification", json={"consent": True}, headers=headers)
        assert res.status_code == 200, res.text
        fv_id = res.json()["data"]["verification_id"]
        session_token = res.json()["data"]["session_token"]
        print(f"✓ POST /api/v1/freelancer/kyc/face-verification (Session: {fv_id})")

        # 28. Face Verification Webhook
        res = await ac.post("/api/v1/freelancer/kyc/face-verification/webhook", json={
            "session_token": session_token,
            "verification_id": fv_id,
            "status": "VERIFIED",
            "liveness_score": 0.98
        })
        assert res.status_code == 200, res.text
        print("✓ POST /api/v1/freelancer/kyc/face-verification/webhook")

        # 29. Check Verified Status
        res = await ac.get("/api/v1/freelancer/kyc/face-verification/status", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["status"] == "VERIFIED"
        print("✓ GET /api/v1/freelancer/kyc/face-verification/status (Verified)")

        # 30. Notifications List & Unread Count
        res = await ac.get("/api/v1/freelancer/notifications", headers=headers)
        assert res.status_code == 200, res.text
        notifs = res.json()["data"]["items"]
        assert len(notifs) >= 1
        notif_id = notifs[0]["notificationId"]
        print(f"✓ GET /api/v1/freelancer/notifications ({len(notifs)} items)")

        # 31. Mark Notification Read
        res = await ac.patch(f"/api/v1/freelancer/notifications/{notif_id}/read", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["isRead"] is True
        print(f"✓ PATCH /api/v1/freelancer/notifications/{notif_id}/read")

        # 32. Settings
        res = await ac.get("/api/v1/freelancer/settings", headers=headers)
        assert res.status_code == 200, res.text
        print("✓ GET /api/v1/freelancer/settings")

        # 33. Update Notification Settings
        res = await ac.patch("/api/v1/freelancer/settings/notifications", json={"sms_notifications": False}, headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["sms_notifications"] is False
        print("✓ PATCH /api/v1/freelancer/settings/notifications")

        # 34. Support Ticket
        res = await ac.post("/api/v1/support/tickets", json={
            "full_name": "Suresh Reddy",
            "email_address": "suresh@example.com",
            "query_category": "referrals",
            "subject": "Inquiry about referral milestone bonus",
            "query_description": "Can you please clarify when the 30-day retention countdown begins?"
        }, headers=headers)
        assert res.status_code == 201, res.text
        print(f"✓ POST /api/v1/support/tickets (Ticket: {res.json()['data']['ticket_number']})")

        # 35. Legal Acceptance
        res = await ac.post("/api/v1/freelancer/legal-acceptances", json={
            "document_slug": "terms-and-conditions",
            "document_version": "1.0"
        }, headers=headers)
        assert res.status_code == 201, res.text
        print("✓ POST /api/v1/freelancer/legal-acceptances")

    print("\n=======================================================")
    print(" ALL 35 END-TO-END FREELANCER API TESTS PASSED! 🚀")
    print("=======================================================")

if __name__ == "__main__":
    asyncio.run(run_all_checks())

