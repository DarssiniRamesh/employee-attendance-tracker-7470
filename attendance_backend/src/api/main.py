from fastapi import FastAPI, APIRouter, Depends, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.api.models import Base, User, RoleEnum
from src.api.auth import (
    UserIn, UserOut, Token, get_password_hash, verify_password,
    create_access_token, get_user_by_username,
)
from src.api.dashboard import dashboard_router
from src.api.attendance import attendance_router
from src.api.reporting import reporting_router
from src.api.admin import admin_router
from fastapi.security import OAuth2PasswordRequestForm

import os

DATABASE_URL = os.getenv(
    "DATABASE_URL", "sqlite:///./attendance.db"
)  # Default local SQLite file

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    future=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

# PUBLIC_INTERFACE
app = FastAPI(
    title="Employee Attendance Tracker Backend",
    description=(
        "FastAPI backend with SQLite and role-based attendance management. "
        "This API provides RESTful endpoints for user authentication, registration, attendance marking, "
        "reporting, dashboards for employees/admins, and employee/admin management.\n\n"
        "**Security:**\n"
        "- All endpoints (except root, /auth/login, /auth/register) require authentication using JWT Bearer tokens.\n"
        "- Role-based permissions are enforced using FastAPI Security dependencies.\n"
        "- CORS is enabled for all origins to support frontend connections."
    ),
    version="0.1.0",
    openapi_tags=[
        {"name": "Health", "description": "Health check and diagnostics."},
        {"name": "Auth", "description": "Authentication, registration, token endpoints (login/register)."},
        {"name": "Dashboard", "description": "Dashboard statistics for both admins and employees based on role."},
        {"name": "Attendance", "description": "Attendance marking and real-time status APIs."},
        {"name": "Attendance Reporting", "description": "Attendance reporting, history, summaries, and CSV export."}
    ]
)

# CORS is required for browser-based clients to access the REST API from a different origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
# PUBLIC_INTERFACE
def on_startup():
    """
    Application startup event: Initialize database schema.
    
    Ensures all DB tables are created (no-op if already exist). Safe for repeated calls.
    """
    Base.metadata.create_all(bind=engine)

# PUBLIC_INTERFACE
@app.get(
    "/",
    tags=["Health"],
    summary="Health check",
    description="Check if backend is running; returns static message.",
    responses={
        200: {
            "description": "API is healthy/ready",
            "content": {"application/json": {"example": {"message": "Healthy"}}}
        }
    }
)
def health_check():
    """
    Health check endpoint.

    Returns:
        dict: {"message": "Healthy"}
    """
    return {"message": "Healthy"}

auth_router = APIRouter(prefix="/auth", tags=["Auth"])

# --- Registration endpoint ---

# PUBLIC_INTERFACE
@auth_router.post(
    "/register",
    response_model=UserOut,
    summary="Register new user",
    status_code=status.HTTP_201_CREATED,
    description=(
        "Register a new user (first call makes an admin, subsequent calls make employees). "
        "Returns the user object. Usernames must be unique."
    ),
)
def register_user(user_in: UserIn, db: Session = Depends(SessionLocal)):
    """
    Register a new user.

    - **username**: Unique username
    - **password**: Plain text password (will be hashed)
    - **full_name**: Optional display name

    The first registered user is given admin role, others as employee.

    Raises:
        - 400: Username already registered.
    Returns:
        The created user object.
    """
    if get_user_by_username(db, user_in.username):
        raise HTTPException(status_code=400, detail="Username already registered.")
    user_count = db.query(User).count()
    user_role = RoleEnum.ADMIN if user_count == 0 else RoleEnum.EMPLOYEE
    db_user = User(
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=user_role,
        is_active=True
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# --- Login endpoint ---

# PUBLIC_INTERFACE
@auth_router.post(
    "/login",
    response_model=Token,
    summary="Login and get JWT access token",
    description=(
        "Authenticate via username and password. Returns JWT access token on successful authentication. "
        "Token must be supplied as a Bearer token for all subsequent calls (except health check/register)."
    ),
)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(SessionLocal)
):
    """
    Authenticate user with username & password.

    - Returns JWT access token for authenticated session.

    The JWT contains user's role as a scope ("admin" or "employee").
    Raises:
        - 401: Incorrect credentials
        - 403: Inactive user
    Returns:
        Token object with access_token, token_type.
    """
    user = get_user_by_username(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive or disabled user. Contact admin.")
    access_token = create_access_token(
        data={"sub": user.username, "scopes": [user.role.value]}
    )
    return Token(access_token=access_token, token_type="bearer")

# Attach routers for modules:
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(attendance_router)
app.include_router(reporting_router)
app.include_router(admin_router)
