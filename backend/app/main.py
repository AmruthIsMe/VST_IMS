from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import get_settings
from app.database import engine, Base, SessionLocal
from app.routers import products, suppliers, orders, users, dashboard, sap_sync, forecast, genie, inventory, auth
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import logging
import re

logger = logging.getLogger(__name__)
settings = get_settings()

limiter = Limiter(key_func=get_remote_address)


def _seed_demo_users():
    """Seed demo users only in local mode. Never runs in production."""
    from passlib.context import CryptContext
    from sqlalchemy import text
    from datetime import datetime

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    db = SessionLocal()
    try:
        demo_users = [
            {"user_id": "manager", "name": "Priya Sharma", "email": "priya.s@vst.com", "role": "Manager"},
            {"user_id": "admin", "name": "Amruth", "email": "amit.verma@vst.com", "role": "Admin"},
            {"user_id": "cashier", "name": "Rahul Desai", "email": "rahul.d@vst.com", "role": "Cashier"},
        ]
        hashed = pwd_context.hash("vst2026")
        now = datetime.utcnow().isoformat()
        for du in demo_users:
            existing = db.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": du["email"]},
            ).fetchone()
            if existing:
                db.execute(
                    text("UPDATE users SET password_hash = :pw, user_id = :uid, role = :role, status = 'Active' WHERE email = :email"),
                    {"pw": hashed, "uid": du["user_id"], "role": du["role"], "email": du["email"]},
                )
            else:
                import uuid
                db.execute(
                    text("INSERT INTO users (id, user_id, name, email, password_hash, role, status, created_at, updated_at) VALUES (:id, :uid, :name, :email, :pw, :role, 'Active', :now, :now)"),
                    {"id": str(uuid.uuid4()), "uid": du["user_id"], "name": du["name"], "email": du["email"], "pw": hashed, "role": du["role"], "now": now},
                )
        db.commit()
        logger.info("Demo users seeded successfully")
    except Exception as e:
        logger.warning(f"Demo user seeding notice: {e}")
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
    except Exception as e:
        logger.warning(f"Database schema check notice: {e}")
    try:
        from app.database import run_light_migrations
        applied = run_light_migrations()
        if applied:
            logger.info(f"Light migrations applied: {applied}")
    except Exception as e:
        logger.warning(f"Light migration notice: {e}")
    if settings.DEPLOYMENT_MODE == "local":
        try:
            _seed_demo_users()
        except Exception as e:
            logger.warning(f"Demo user seeding notice: {e}")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

cors_origins = settings.CORS_ORIGINS
try:
    origin_regex = re.compile(settings.CORS_ORIGIN_REGEX) if settings.CORS_ORIGIN_REGEX else None
except re.error:
    origin_regex = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=origin_regex.pattern if origin_regex else None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition"],
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(products.router)
app.include_router(suppliers.router)
app.include_router(orders.router)
app.include_router(users.router)
app.include_router(sap_sync.router)
app.include_router(forecast.router)
app.include_router(genie.router)
app.include_router(inventory.router)


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "healthy", "message": "VST IMS API is running", "app": settings.APP_NAME}


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "healthy", "app": settings.APP_NAME}
