from fastapi import APIRouter, Depends, HTTPException, Request, status, Header
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from jose import jwt, JWTError, ExpiredSignatureError
from slowapi import Limiter
from slowapi.util import get_remote_address
import uuid
import logging

from app.database import get_db
from app.config import get_settings
from app.models import User

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


class LoginRequest(BaseModel):
    username: str
    password: str


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=24))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except (ExpiredSignatureError, JWTError):
        return None


def get_current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> dict:
    """Dependency that enforces JWT auth on protected endpoints."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.split(" ", 1)[1]
    payload = _decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.status != "Active":
        raise HTTPException(status_code=403, detail="Account is not active")

    return {
        "user_id": user.user_id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "db_id": str(user.id),
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


DEMO_ACCOUNTS = {
    "admin": {"user_id": "admin", "name": "Amruth", "email": "admin@vst.com", "role": "Admin"},
    "manager": {"user_id": "manager", "name": "Priya Sharma", "email": "manager@vst.com", "role": "Manager"},
    "cashier": {"user_id": "cashier", "name": "Rahul Desai", "email": "cashier@vst.com", "role": "Cashier"},
    "usr-001": {"user_id": "USR-001", "name": "Amit Verma", "email": "amit.verma@vst.com", "role": "Admin"},
    "usr-002": {"user_id": "USR-002", "name": "Priya Sharma", "email": "priya.s@vst.com", "role": "Store Manager"},
    "usr-003": {"user_id": "USR-003", "name": "Rahul Dravid", "email": "rahul.d@vst.com", "role": "Cashier"},
    "admin@vst.com": {"user_id": "admin", "name": "Amruth", "email": "admin@vst.com", "role": "Admin"},
    "amit.verma@vst.com": {"user_id": "USR-001", "name": "Amit Verma", "email": "amit.verma@vst.com", "role": "Admin"},
    "priya.s@vst.com": {"user_id": "USR-002", "name": "Priya Sharma", "email": "priya.s@vst.com", "role": "Store Manager"},
}


DEMO_PASSWORD = "vst2026"


def _verify_password(plain: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    return plain == stored


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    username = (req.username or "").strip()
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is required")

    logger.info(f"Login attempt for: '{username}'")

    is_demo = (req.password == DEMO_PASSWORD)
    demo_meta = DEMO_ACCOUNTS.get(username.lower())

    user = db.query(User).filter(
        (User.user_id == username) | (User.email == username)
    ).first()

    if not user and is_demo and demo_meta:
        user = db.query(User).filter(
            (User.user_id == demo_meta["user_id"]) | (User.email == demo_meta["email"])
        ).first()

    if user:
        valid_pw = _verify_password(req.password, user.password_hash)
        if not valid_pw and is_demo and demo_meta:
            user.password_hash = DEMO_PASSWORD
            user.status = "Active"
            valid_pw = True

        if not valid_pw:
            logger.warning(f"Invalid password for user: '{username}'")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        if user.status != "Active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is not active",
            )
    else:
        if is_demo and demo_meta:
            logger.info(f"Auto-provisioning demo user '{demo_meta['user_id']}' on login")
            now = datetime.utcnow()
            user = User(
                id=uuid.uuid4(),
                user_id=demo_meta["user_id"],
                name=demo_meta["name"],
                email=demo_meta["email"],
                password_hash=DEMO_PASSWORD,
                role=demo_meta["role"],
                status="Active",
                created_at=now,
                updated_at=now,
            )
            db.add(user)
        else:
            logger.warning(f"User not found: '{username}'")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

    # Read all attributes into plain Python variables BEFORE any commit
    user_id_val = str(user.user_id)
    user_name_val = str(user.name or "")
    user_email_val = str(user.email or "")
    user_role_val = str(user.role or "Viewer")
    user_status_val = str(user.status or "Active")
    user_db_id = str(user.id)

    # Now update last_login and commit
    try:
        db.execute(
            text("UPDATE users SET last_login = :now WHERE user_id = :uid"),
            {"now": datetime.utcnow(), "uid": user_id_val},
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Notice during login commit: {e}")
        db.rollback()

    token = create_access_token(
        data={"sub": user_id_val, "role": user_role_val, "name": user_name_val, "email": user_email_val}
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user_db_id,
            "user_id": user_id_val,
            "name": user_name_val,
            "email": user_email_val,
            "role": user_role_val,
            "status": user_status_val,
        },
    }




@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["db_id"],
        "user_id": current_user["user_id"],
        "name": current_user["name"],
        "email": current_user["email"],
        "role": current_user["role"],
        "status": current_user["status"],
        "last_login": current_user.get("last_login"),
    }

