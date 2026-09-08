from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.config import get_settings
from app.database import engine, Base, SessionLocal
from app.models import User
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
    """Seed demo users in both local and cloud mode."""
    from datetime import datetime
    import uuid

    db = SessionLocal()
    try:
        demo_users = [
            {"user_id": "USR-04", "name": "Amruth", "email": "admin@vst.com", "role": "Admin"},
            {"user_id": "USR-05", "name": "Priya Sharma", "email": "manager@vst.com", "role": "Manager"},
            {"user_id": "USR-06", "name": "Rahul Desai", "email": "cashier@vst.com", "role": "Cashier"},
            {"user_id": "USR-01", "name": "Amit Verma", "email": "amit.verma@vst.com", "role": "Admin"},
            {"user_id": "USR-02", "name": "Priya Sharma", "email": "priya.s@vst.com", "role": "Store Manager"},
            {"user_id": "USR-03", "name": "Rahul Dravid", "email": "rahul.d@vst.com", "role": "Cashier"},
        ]
        hashed = "vst2026"
        now = datetime.now()
        for du in demo_users:
            user = db.query(User).filter(
                (User.user_id.ilike(du["user_id"])) | (User.email.ilike(du["email"]))
            ).first()
            if user:
                user.user_id = du["user_id"]
                user.name = du["name"]
                user.email = du["email"]
                user.role = du["role"]
                user.password_hash = hashed
                user.status = "Active"
                user.updated_at = now
            else:
                new_user = User(
                    id=uuid.uuid4(),
                    user_id=du["user_id"],
                    name=du["name"],
                    email=du["email"],
                    password_hash=hashed,
                    role=du["role"],
                    status="Active",
                    created_at=now,
                    updated_at=now,
                )
                db.add(new_user)
        db.commit()
        logger.info("Demo users seeded/verified successfully")
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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
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
