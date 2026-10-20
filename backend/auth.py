import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import bcrypt
from sqlalchemy import select
from passlib.context import CryptContext
from models import User, async_session

_is_prod = os.environ.get("ENV", "dev").lower() in ("prod", "production")

if _is_prod:
    _secret = os.environ.get("JWT_SECRET", "")
    if not _secret or len(_secret) < 32:
        print(
            f"FATAL: JWT_SECRET must be set and ≥ 32 chars in production.\n"
            f"  Current length: {len(_secret)}\n"
            f"  Generate one: openssl rand -hex 32",
            file=sys.stderr,
        )
        sys.exit(1)
    SECRET_KEY = _secret
else:
    SECRET_KEY = os.environ.get("JWT_SECRET", "dev-only-change-in-prod-32chars-minimum!!")

ALGORITHM = "HS256"
TOKEN_MINUTES = int(os.environ.get("TOKEN_MINUTES", "60"))

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer()

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_token(sub: str) -> str:
    payload = {"sub": sub, "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def verify_token(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> User:
    return await user_from_token(creds.credentials)


async def user_from_token(token: str) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

    email: Optional[str] = payload.get("sub")
    if not email:
        raise HTTPException(401, "Invalid token")

    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.email == email))).first()
    if user is None:
        raise HTTPException(401, "User not found")
    return user


get_current_user = verify_token   