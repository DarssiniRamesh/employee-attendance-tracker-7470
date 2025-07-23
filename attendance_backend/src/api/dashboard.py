from fastapi import APIRouter, Depends, Security
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
from pydantic import BaseModel, Field

from src.api.main import SessionLocal
from src.api.models import User, Attendance, RoleEnum
from src.api.auth import (
    get_current_active_admin_user,
    get_current_active_employee_user,
)

# Dashboard router
dashboard_router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    responses={404: {"description": "Not found"}},
)

# --- Pydantic response schemas ---

class AdminDashboardStats(BaseModel):
    total_employees: int = Field(..., description="Total registered employees in the system.")
    today_present: int = Field(..., description="Total employees who have marked attendance today.")
    today_absent: int = Field(..., description="Total employees absent today.")
    total_admins: int = Field(..., description="Number of admin users.")
    system_uptime_days: int = Field(..., description="System duration (days since first registered user).")

class EmployeeDashboardStats(BaseModel):
    total_attendance_days: int = Field(..., description="Total number of days the employee has marked attendance.")
    last_attendance_date: date = Field(..., description="Date of the employee's last attendance.")
    consecutive_days_present: int = Field(..., description="How many days in a row the employee attended (until today, if present today).")
    is_present_today: bool = Field(..., description="If employee marked attendance today.")

# --- Endpoint for Admins ---

# PUBLIC_INTERFACE
@dashboard_router.get("/admin", response_model=AdminDashboardStats, summary="Dashboard statistics for administrators", tags=["Dashboard"])
async def admin_dashboard(
    current_user: User = Security(get_current_active_admin_user),
    db: Session = Depends(SessionLocal)
):
    """
    Returns key statistics for admin overview.

    - **Requires**: Admin privileges
    - **Returns**: Employee count, today's present/absent, admin count, system uptime

    """
    # Query employee and admin counts
    total_employees = db.query(User).filter(User.role == RoleEnum.EMPLOYEE).count()
    total_admins = db.query(User).filter(User.role == RoleEnum.ADMIN).count()

    # Today boundaries
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    today_present = (
        db.query(Attendance.user_id)
        .filter(Attendance.date >= today_start, Attendance.date <= today_end)
        .distinct()
        .count()
    )
    today_absent = max(total_employees - today_present, 0)

    first_user = db.query(User).order_by(User.created_at.asc()).first()
    now = datetime.now()
    if first_user and first_user.created_at:
        uptime_days = max((now - first_user.created_at).days, 1)
    else:
        uptime_days = 1

    return AdminDashboardStats(
        total_employees=total_employees,
        today_present=today_present,
        today_absent=today_absent,
        total_admins=total_admins,
        system_uptime_days=uptime_days,
    )

# --- Endpoint for Employees ---

# PUBLIC_INTERFACE
@dashboard_router.get("/employee", response_model=EmployeeDashboardStats, summary="Dashboard stats for current employee", tags=["Dashboard"])
async def employee_dashboard(
    current_user: User = Security(get_current_active_employee_user),
    db: Session = Depends(SessionLocal)
):
    """
    Returns personal attendance stats for logged-in employee.

    - **Requires**: Employee privileges
    - **Returns**: Total attendance days, last date, streak, present/absent today

    """
    attendance_q = (
        db.query(Attendance)
        .filter(Attendance.user_id == current_user.id)
        .order_by(Attendance.date.desc())
    )
    attendance_all = attendance_q.all()

    total_attendance_days = len(attendance_all)
    last_attendance_date = attendance_all[0].date.date() if attendance_all else None

    # Compute is_present_today
    today = datetime.now().date()
    is_present_today = any(record.date.date() == today for record in attendance_all)

    # Compute consecutive days streak (including today if present)
    consecutive_days = 0
    last_date = today
    for record in attendance_all:
        rec_date = record.date.date()
        if consecutive_days == 0:
            if rec_date == today:
                consecutive_days = 1
                last_date = today
            elif rec_date == today - timedelta(days=1):
                consecutive_days = 1
                last_date = rec_date
            else:
                break
        else:
            expected_date = last_date - timedelta(days=1)
            if rec_date == expected_date:
                consecutive_days += 1
                last_date = rec_date
            else:
                break

    # Handle last_attendance_date if no record exists
    last_attendance_date = last_attendance_date or None

    return EmployeeDashboardStats(
        total_attendance_days=total_attendance_days,
        last_attendance_date=last_attendance_date,
        consecutive_days_present=consecutive_days,
        is_present_today=is_present_today,
    )
