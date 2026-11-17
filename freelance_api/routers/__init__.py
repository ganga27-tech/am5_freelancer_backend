from fastapi import APIRouter
from freelance_api.routers.auth import router as auth_router
from freelance_api.routers.home import router as home_router
from freelance_api.routers.services import router as services_router
from freelance_api.routers.referrals import router as referrals_router
from freelance_api.routers.installation_rewards import router as installation_router
from freelance_api.routers.rewards import router as rewards_router
from freelance_api.routers.wallet import router as wallet_router
from freelance_api.routers.profile import router as profile_router
from freelance_api.routers.kyc import router as kyc_router
from freelance_api.routers.settings import router as settings_router
from freelance_api.routers.support import router as support_router
from freelance_api.routers.legal import router as legal_router
from freelance_api.routers.notifications import router as notifications_router
from freelance_api.routers.search import router as search_router

# Master freelance router
freelance_router = APIRouter()

# 1. Auth routes - both under /auth and /freelancer/auth for flexible client integration
freelance_router.include_router(auth_router, prefix="/auth")
freelance_router.include_router(auth_router, prefix="/freelancer/auth")

# 2. Home & Content
freelance_router.include_router(home_router)

# 3. Services
freelance_router.include_router(services_router)

# 4. Referrals & Refer and Earn
freelance_router.include_router(referrals_router)

# 5. App Installation & Activation Rewards
freelance_router.include_router(installation_router)

# 6. Rewards & Cashback
freelance_router.include_router(rewards_router)

# 7. Wallet & Payouts (also under /freelancer/wallet for convenience)
freelance_router.include_router(wallet_router)
freelance_router.include_router(wallet_router, prefix="/freelancer")

# 8. Freelancer Profile, Bank, KYC, Settings, Notifications, Acceptances
freelance_router.include_router(profile_router)
freelance_router.include_router(kyc_router)
freelance_router.include_router(settings_router)
freelance_router.include_router(notifications_router)

# 9. Support & FAQs
freelance_router.include_router(support_router)

# 10. Legal Pages
freelance_router.include_router(legal_router)

# 11. Search
freelance_router.include_router(search_router)

__all__ = ["freelance_router"]

