from fastapi import APIRouter, Depends, HTTPException, Request, status, Header
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from jose import jwt, JWTError, ExpiredSignatureError
from slowapi import Limiter
from slowapi.util import get_remote_address
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
    row = db.execute(
        text("SELECT id, user_id, name, email, role, status FROM users WHERE user_id = :u"),
        {"u": user_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    if row.status != "Active":
        raise HTTPException(status_code=403, detail="Account is not active")

    return {"user_id": row.user_id, "name": row.name, "email": row.email, "role": row.role}


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    row = db.execute(
        text("SELECT id, user_id, name, email, password_hash, role, status FROM users WHERE user_id = :u OR email = :u"),
        {"u": req.username},
    ).fetchone()

    if not row or not pwd_context.verify(req.password, row.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if row.status != "Active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active",
        )

    now = datetime.utcnow().isoformat()
    db.execute(
        text("UPDATE users SET last_login = :now WHERE id = :id"),
        {"id": row.id, "now": now},
    )
    db.commit()

    token = create_access_token(
        data={"sub": row.user_id, "role": row.role, "name": row.name, "email": row.email}
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(row.id),
            "user_id": row.user_id,
            "name": row.name,
            "email": row.email,
            "role": row.role,
            "status": row.status,
        },
    }


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT id, user_id, name, email, role, status, last_login FROM users WHERE user_id = :u"),
        {"u": current_user["user_id"]},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": str(row.id),
        "user_id": row.user_id,
        "name": row.name,
        "email": row.email,
        "role": row.role,
        "status": row.status,
        "last_login": row.last_login.isoformat() if row.last_login else None,
    }
