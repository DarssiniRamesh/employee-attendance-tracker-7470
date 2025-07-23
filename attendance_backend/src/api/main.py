from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session

from src.api.app_factory import create_app
from src.api.models import Base, User, RoleEnum
from src.api.db import SessionLocal, engine
from src.api.auth import (
    UserIn, UserOut, Token, get_password_hash, verify_password,
    create_access_token, get_user_by_username,
)
from src.api.dashboard import dashboard_router
from src.api.attendance import attendance_router
from src.api.reporting import reporting_router
from src.api.admin import admin_router
from fastapi.security import OAuth2PasswordRequestForm

# Create FastAPI app as recommended (from factory)
app = create_app()

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

# --- AUTH ROUTER (Registration/Login) ---
auth_router = APIRouter(prefix="/auth", tags=["Auth"])

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
# PUBLIC_INTERFACE
def register_user(
    user_in: UserIn,
    db: Session = Depends(SessionLocal),
    local_kw: str = None,
):
    """
    Register a new user.

    - **username**: Unique username
    - **password**: Plain text password (will be hashed)
    - **full_name**: Optional display name
    - **local_kw**: (optional, query param) department/keyword. Ignored on backend.

    The first registered user is given admin role, others as employee.

    Raises:
        - 400: Username already registered, bad field, or unexpected input.
        - 409: Database conflict such as username exists (from DB constraint).
        - 500: Unanticipated server/database errors (descriptive).
    Returns:
        The created user object.
    """
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError

    # If local_kw is provided in the request body (as a field in user_in), raise 400.
    posted_fields = set(user_in.__dict__.keys())
    expected_fields = set(['username', 'password', 'full_name'])
    unexpected_payload_fields = posted_fields - expected_fields
    if "local_kw" in unexpected_payload_fields:
        raise HTTPException(
            status_code=400,
            detail="local_kw must be sent as a query parameter, not in JSON body"
        )
    if get_user_by_username(db, user_in.username):
        raise HTTPException(status_code=400, detail="Username already registered.")

    try:
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
        # Ignore local_kw (query param) completely for now. Return created user.
        return db_user
    except IntegrityError:
        db.rollback()
        # Defensive: if there's a DB constraint violation, convert to a 409 conflict
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Database integrity error: possible duplicate username or invalid schema. See server logs."
        )
    except SQLAlchemyError:
        db.rollback()
        # Generic database error
        raise HTTPException(
            status_code=500,
            detail="A database error occurred during registration. See server logs."
        )
    except Exception:
        db.rollback()
        # For unanticipated errors, log and provide a clear error message
        import traceback, sys
        print("Exception during registration:", file=sys.stderr)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Internal server error during registration. Error details logged."
        )

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
