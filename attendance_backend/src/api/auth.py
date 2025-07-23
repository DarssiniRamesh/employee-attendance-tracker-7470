from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status, Security
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from pydantic import BaseModel, Field
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from src.api.models import User, RoleEnum
from src.api.db import SessionLocal

import os
import secrets

# Secret key for JWT, should come from env var in real deployment
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12 hours access token lifetime

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", scopes={
    "admin": "Admin access actions",
    "employee": "Employee access actions",
})

# --- Pydantic schemas ---

class Token(BaseModel):
    access_token: str = Field(..., description="The JWT access token.")
    token_type: str = Field(..., description="Type of token (bearer).")


class TokenData(BaseModel):
    username: Optional[str] = None
    scopes: list[str] = []


class UserIn(BaseModel):
    username: str = Field(..., description="Unique username for registration and login.")
    password: str = Field(..., description="Password, plain string.")
    full_name: Optional[str] = Field("", description="Full name display value.")


class UserOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str]
    role: RoleEnum
    is_active: bool

    class Config:
        from_attributes = True


# --- Password hashing ---

# PUBLIC_INTERFACE
def get_password_hash(password: str) -> str:
    """Hash a user password using bcrypt."""
    return pwd_context.hash(password)

# PUBLIC_INTERFACE
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Securely verify password by hashing and comparing with the hash."""
    return pwd_context.verify(plain_password, hashed_password)

# --- User DB accessors ---

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()

# --- JWT Token utilities ---

# PUBLIC_INTERFACE
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a new JWT access token with expiration and payload data."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# PUBLIC_INTERFACE
def decode_access_token(token: str) -> dict:
    """Decode JWT access token and validate signature. Raises on fail."""
    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return decoded
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})

# PUBLIC_INTERFACE
def get_current_user(
    security_scopes: SecurityScopes,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(SessionLocal)
) -> User:
    """
    FastAPI dependency to get the current user from a JWT, enforces required scopes.
    Throws HTTP 401/403 if token is invalid or insufficient permissions.
    """
    authenticate_value = f'Bearer scope="{security_scopes.scope_str}"'
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or permissions",
        headers={"WWW-Authenticate": authenticate_value},
    )
    payload = decode_access_token(token)
    username: str = payload.get("sub")
    scopes = payload.get("scopes", [])
    if username is None:
        raise credentials_exception
    token_data = TokenData(username=username, scopes=scopes)
    # Permissions check
    for scope in security_scopes.scopes:
        if scope not in token_data.scopes:
            raise HTTPException(
                status_code=403,
                detail=f"Not enough permissions. Required: {scope}",
                headers={"WWW-Authenticate": authenticate_value}
            )
    user = get_user_by_username(db, username=token_data.username)
    if user is None or not user.is_active:
        raise credentials_exception
    return user

# PUBLIC_INTERFACE
def get_current_active_admin_user(
    current_user: User = Security(get_current_user, scopes=["admin"])
) -> User:
    """
    Dependency - ensures the current user has admin privileges.
    """
    if current_user.role != RoleEnum.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins may perform this action.")
    return current_user

# PUBLIC_INTERFACE
def get_current_active_employee_user(
    current_user: User = Security(get_current_user, scopes=["employee"])
) -> User:
    """
    Dependency - ensures the current user has employee privileges.
    """
    if current_user.role != RoleEnum.EMPLOYEE:
        raise HTTPException(status_code=403, detail="Only employees may perform this action.")
    return current_user
