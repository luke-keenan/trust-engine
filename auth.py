import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from sqlalchemy import select

from models import User, async_session

SECRET_KEY = os.environ.get("JWT_SECRET", "dev-only-change-in-prod")
ALGORITHM = "HS256"
TOKEN_MINUTES = 60

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer()


def hash_password(plain: str) -> str:
    return pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd.verify(plain, hashed)


def create_token(sub: str) -> str:
    payload = {"sub": sub, "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def verify_token(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> User:
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
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