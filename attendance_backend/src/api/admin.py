from fastapi import APIRouter, Depends, HTTPException, status, Security, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from src.api.main import SessionLocal
from src.api.models import User, RoleEnum
from src.api.auth import (
    get_password_hash,
    UserOut,
    get_current_active_admin_user,
    get_user_by_username,
)

admin_router = APIRouter(
    prefix="/admin",
    tags=["Admin: User & Employee Management"],
    responses={404: {"description": "Not found"}},
)

# --- Pydantic schemas ---

class UserCreateRequest(BaseModel):
    username: str = Field(..., description="Unique username.")
    password: str = Field(..., min_length=4, description="Initial plain password.")
    full_name: Optional[str] = Field("", description="Full name for user.")
    role: RoleEnum = Field(..., description="Role: employee or admin.")

class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(None, description="Full name (optional).")
    is_active: Optional[bool] = Field(None, description="Set active/inactive status.")
    role: Optional[RoleEnum] = Field(None, description="Change role [admin/employee].")

class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=4, description="New password.")

class UserListResponse(BaseModel):
    users: List[UserOut]
    total: int

# --- ENDPOINTS ---

# PUBLIC_INTERFACE
@admin_router.post(
    "/users",
    response_model=UserOut,
    summary="Admin: Create user (employee or admin)",
    status_code=status.HTTP_201_CREATED,
    description="Admin only: Create new user/employee account.",
)
def create_user(
    req: UserCreateRequest,
    current_admin: User = Security(get_current_active_admin_user),
    db: Session = Depends(SessionLocal),
):
    """Create user (employee or admin)."""
    if get_user_by_username(db, req.username):
        raise HTTPException(status_code=400, detail="Username already exists.")
    new_user = User(
        username=req.username,
        hashed_password=get_password_hash(req.password),
        full_name=req.full_name,
        role=req.role,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

# PUBLIC_INTERFACE
@admin_router.get(
    "/users",
    response_model=UserListResponse,
    summary="Admin: List users",
    description="Retrieve all users/employees with optional filters for active and role.",
)
def list_users(
    role: Optional[RoleEnum] = Query(None, description="(Optional) Filter by role: admin/employee"),
    is_active: Optional[bool] = Query(None, description="(Optional) Filter by status active/inactive"),
    current_admin: User = Security(get_current_active_admin_user),
    db: Session = Depends(SessionLocal),
):
    """List users, filterable by role and status."""
    q = db.query(User)
    if role:
        q = q.filter(User.role == role)
    if is_active is not None:
        q = q.filter(User.is_active == int(is_active))
    results = q.order_by(User.id.asc()).all()
    return UserListResponse(users=results, total=len(results))

# PUBLIC_INTERFACE
@admin_router.get(
    "/users/{user_id}",
    response_model=UserOut,
    summary="Admin: Get user details",
    description="Get single user/employee details by id.",
)
def get_user(
    user_id: int,
    current_admin: User = Security(get_current_active_admin_user),
    db: Session = Depends(SessionLocal),
):
    """Get user by id."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user

# PUBLIC_INTERFACE
@admin_router.put(
    "/users/{user_id}",
    response_model=UserOut,
    summary="Admin: Update user (partial)",
    description="Update user's name/status/role. Only provided fields are updated.",
)
def update_user(
    user_id: int,
    req: UserUpdateRequest,
    current_admin: User = Security(get_current_active_admin_user),
    db: Session = Depends(SessionLocal),
):
    """Update user fields (partial)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if req.full_name is not None:
        user.full_name = req.full_name
    if req.is_active is not None:
        user.is_active = int(req.is_active)
    if req.role is not None:
        user.role = req.role
    db.commit()
    db.refresh(user)
    return user

# PUBLIC_INTERFACE
@admin_router.delete(
    "/users/{user_id}",
    response_model=dict,
    summary="Admin: Delete user/employee",
    description="Delete user/employee by id. Action is irreversible."
)
def delete_user(
    user_id: int,
    current_admin: User = Security(get_current_active_admin_user),
    db: Session = Depends(SessionLocal),
):
    """Delete user/employee account (by id)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    db.delete(user)
    db.commit()
    return {"success": True}

# PUBLIC_INTERFACE
@admin_router.post(
    "/users/{user_id}/activate",
    response_model=UserOut,
    summary="Admin: Activate user",
    description="Activate a user account (set is_active=True).",
)
def activate_user(
    user_id: int,
    current_admin: User = Security(get_current_active_admin_user),
    db: Session = Depends(SessionLocal),
):
    """Mark user as active."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.is_active = 1
    db.commit()
    db.refresh(user)
    return user

# PUBLIC_INTERFACE
@admin_router.post(
    "/users/{user_id}/deactivate",
    response_model=UserOut,
    summary="Admin: Deactivate user",
    description="Deactivate a user account (set is_active=False).",
)
def deactivate_user(
    user_id: int,
    current_admin: User = Security(get_current_active_admin_user),
    db: Session = Depends(SessionLocal),
):
    """Mark user as inactive."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.is_active = 0
    db.commit()
    db.refresh(user)
    return user

# PUBLIC_INTERFACE
@admin_router.post(
    "/users/{user_id}/reset-password",
    response_model=UserOut,
    summary="Admin: Reset user password",
    description="Reset an employee/user password (admin only).",
)
def reset_user_password(
    user_id: int,
    req: PasswordResetRequest,
    current_admin: User = Security(get_current_active_admin_user),
    db: Session = Depends(SessionLocal),
):
    """Reset a user's password (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.hashed_password = get_password_hash(req.new_password)
    db.commit()
    db.refresh(user)
    return user
