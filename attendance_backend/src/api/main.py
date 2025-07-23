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
    Prints model/table schema status and any discrepancies at startup.

    Exception details and tracebacks are printed to server logs if DB/model setup fails,
    to aid debugging of missing/misnamed tables or DB connection issues.
    """
    import sys
    import traceback
    try:
        Base.metadata.create_all(bind=engine)

        # Diagnostics: print schema for User and check table and constraints
        from sqlalchemy import inspect
        inspector = inspect(engine)
        print("=== DB Startup Schema Diagnostics ===", file=sys.stderr)
        # Check all expected tables:
        expected_tables = ['users', 'attendance', 'token_blacklist']
        missing_tables = [t for t in expected_tables if t not in inspector.get_table_names()]
        if missing_tables:
            print(f"[STARTUP ERROR] Missing tables: {missing_tables}", file=sys.stderr)
        else:
            print("All expected tables present: ", inspector.get_table_names(), file=sys.stderr)
        # Check User fields and constraints
        user_cols = inspector.get_columns('users')
        col_names = [c['name'] for c in user_cols]
        print("User table columns: ", col_names, file=sys.stderr)
        for uc in inspector.get_unique_constraints('users'):
            print("User table unique constraint: ", uc, file=sys.stderr)
        print("=====================================", file=sys.stderr)
    except Exception as e:
        print("[CRITICAL ERROR][STARTUP]: Exception during DB/model initialization", file=sys.stderr)
        traceback.print_exc()
        print(f"Exception details: {repr(e)}", file=sys.stderr)
        # Optionally reraise or allow app to continue

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
        # Post-check: Ensure that the username is unique as per DB model & index.
        existing_count = db.query(User).filter(User.username == user_in.username).count()
        if existing_count > 1:
            import sys
            print(f"CRITICAL ERROR: Duplicate usernames detected in DB after supposed unique constraint. Count: {existing_count}, username: {user_in.username}", file=sys.stderr)
            raise HTTPException(
                status_code=500,
                detail="Duplicate usernames detected after registration. DB schema may be corrupted.",
            )
        return db_user
    except IntegrityError as e:
        db.rollback()
        # Defensive: if there's a DB constraint violation, convert to 409 conflict + print
        import sys
        print("IntegrityError during registration:", str(e), file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Database integrity error: possible duplicate username or invalid schema. "
                   f"See server logs. Error: {str(e)}"
        )
    except SQLAlchemyError as e:
        db.rollback()
        import sys
        print("SQLAlchemyError during registration:", str(e), file=sys.stderr)
        # Generic database error
        raise HTTPException(
            status_code=500,
            detail=f"A database error occurred during registration. See server logs. Error: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        # For unanticipated errors, print and write traceback to console and temp file for diagnostics
        import traceback, sys
        print("Exception during registration:", file=sys.stderr)
        tb_str = traceback.format_exc()
        print(tb_str, file=sys.stderr)
        print(f"Exception details: {repr(e)}", file=sys.stderr)
        # Additionally, write the full traceback and error context to a temp file
        diagnostics_path = "/tmp/auth_register_exception.log"
        try:
            with open(diagnostics_path, "a") as f:
                f.write("="*32 + "\n")
                f.write("Exception during /auth/register\n")
                f.write(tb_str)
                f.write(f"Exception details: {repr(e)}\n")
                f.write(f"Request fields: {user_in.__dict__}\n")
                f.write("Client Info: (unavailable; add request if needed)\n")
                f.write("="*32 + "\n")
        except Exception as write_err:
            # Print file write errors, too, but do not fail the API for it
            print(f"Error writing diagnostics file: {write_err}", file=sys.stderr)
        # TEMP: return the traceback in the HTTP response for debugging (DO NOT DO IN PRODUCTION)
        raise HTTPException(
            status_code=500,
            detail=(
                f"Internal server error during registration. "
                f"Exception details: {repr(e)}\nTraceback:\n{tb_str}\n"
                f"Check backend console log or /tmp/auth_register_exception.log for full traceback/context."
            )
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
