from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.api import api_router
from app.exceptions.handlers import setup_exception_handlers
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.core.rate_limit import limiter
from sqlalchemy import text
from app.db.session import engine
from app.db.base_class import Base
import app.models  # Ensure all models are registered

from app.core.firebase_config import init_firebase

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Real Estate / category-module columns + tables (own transaction, independent of the block below).
    # Must run BEFORE the create_all/seed steps below, which query these columns.
    # Own try-block + logged, so a failure here is visible and independent of other startup steps.
    try:
        from app.db.migrate_real_estate import apply_migrations, seed_categories
        await apply_migrations()
        await seed_categories()
    except Exception as e:
        import structlog
        structlog.get_logger().error("category_migration_error", error=str(e))

    # Auto-create all missing tables on startup (non-destructive CREATE TABLE IF NOT EXISTS)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # create_all never adds columns to existing tables.
            await conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS material_option VARCHAR(10)"))
            await conn.execute(text("ALTER TABLE vendor_subscriptions ADD COLUMN IF NOT EXISTS leads_total INTEGER"))
            await conn.execute(text("ALTER TABLE vendor_subscriptions ADD COLUMN IF NOT EXISTS leads_used INTEGER NOT NULL DEFAULT 0"))
            await conn.execute(text("ALTER TABLE vendor_subscriptions ADD COLUMN IF NOT EXISTS missed_uncharged INTEGER NOT NULL DEFAULT 0"))
            # Give subscriptions bought before lead counting their plan's leads.
            await conn.execute(text(
                "UPDATE vendor_subscriptions vs SET leads_total = COALESCE(sp.free_leads, 0) "
                "FROM subscription_plans sp WHERE vs.subscription_plan_id = sp.id AND vs.leads_total IS NULL"
            ))

        # Ensure new columns on existing freelancers table and seed defaults
        from sqlalchemy import text
        from app.db.session import AsyncSessionLocal
        from freelance_api.seed_data import seed_freelance_defaults

        async with AsyncSessionLocal() as session:
            alter_queries = [
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS photo_url VARCHAR;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS city VARCHAR;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS state VARCHAR;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS address TEXT;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS pincode VARCHAR;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS bio TEXT;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS profile_status VARCHAR DEFAULT 'active';",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS profile_completion_percentage INTEGER DEFAULT 25;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS bank_verification_status VARCHAR DEFAULT 'NOT_VERIFIED';",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS kyc_status VARCHAR DEFAULT 'NOT_STARTED';",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS face_verification_status VARCHAR DEFAULT 'NOT_STARTED';",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS total_earnings NUMERIC(12, 2) DEFAULT 0.00;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS available_balance NUMERIC(12, 2) DEFAULT 0.00;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS pending_balance NUMERIC(12, 2) DEFAULT 0.00;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS processing_balance NUMERIC(12, 2) DEFAULT 0.00;",
                "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS total_withdrawn NUMERIC(12, 2) DEFAULT 0.00;",
            ]
            for q in alter_queries:
                try:
                    await session.execute(text(q))
                except Exception:
                    pass
            await session.commit()

            try:
                await seed_freelance_defaults(session)
            except Exception:
                pass
    except Exception as e:
        import structlog
        structlog.get_logger().error("db_table_init_error", error=str(e))
        
    # Initialize Firebase Admin SDK
    init_firebase()

    
    # Setup Logging
    from app.logging.config import setup_logging
    setup_logging()
    
    # Initialize APScheduler cron jobs
    from app.workers.cron_jobs import setup_cron_jobs
    setup_cron_jobs()
    
    yield

    from app.services.otp_service import otp_service
    await otp_service.aclose()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Rate Limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Allowed origins for CORS
allowed_origins = [
    "https://am5royal.com",
    "https://www.am5royal.com",
    "https://vendor.am5royal.com",
    "https://admin.am5royal.com",
    "https://am5vendor.web.app",
    "https://am5vendor.firebaseapp.com",
    "https://fb-chi-nine.vercel.app",
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:8000",
]

# Add any origins from settings
origins = [str(origin) for origin in settings.BACKEND_CORS_ORIGINS] if settings.BACKEND_CORS_ORIGINS else []
for o in origins:
    if o not in allowed_origins and o != "*":
        allowed_origins.append(o)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://([a-zA-Z0-9-]+\.)?am5royal\.com|https://.*\.web\.app|https://.*\.firebaseapp\.com|https://.*\.vercel\.app|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_exception_handlers(app)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
