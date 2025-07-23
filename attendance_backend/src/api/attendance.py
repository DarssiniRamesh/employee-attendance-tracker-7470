from fastapi import APIRouter, Depends, HTTPException, status, Security
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime
from typing import Optional

from src.api.main import SessionLocal
from src.api.models import Attendance, User
from src.api.auth import get_current_active_employee_user, get_current_active_admin_user

attendance_router = APIRouter(
    prefix="/attendance",
    tags=["Attendance"],
    responses={404: {"description": "Not found"}},
)

# --- Pydantic Schemas ---

class MarkAttendanceRequest(BaseModel):
    """
    Request model for marking today's attendance.
    """
    # Can be extended in the future for more data (e.g., location, session id, etc.)
    pass

class AttendanceResponse(BaseModel):
    """
    Response model for an attendance record.
    """
    id: int
    user_id: int
    attendance_date: datetime = Field(..., alias="date", description="Calendar date when attendance was marked.")
    time_in: datetime = Field(..., description="Timestamp when the attendance was marked.")
    time_out: Optional[datetime] = Field(None, description="Optional timestamp for marking out (not used now).")

    class Config:
        from_attributes = True
        allow_population_by_field_name = True

# Response schemas for admin's real-time status
class DailyAttendanceUserStatus(BaseModel):
    id: int
    username: str
    full_name: str | None = None
    is_present: bool = Field(..., description="Whether user marked attendance today.")

class DailyAttendanceStatusResponse(BaseModel):
    date: datetime = Field(..., description="Date of status reporting (today).")
    present_count: int
    absent_count: int
    users: list[DailyAttendanceUserStatus]

# --- Endpoints ---

# PUBLIC_INTERFACE
@attendance_router.get(
    "/status/today",
    response_model=DailyAttendanceStatusResponse,
    summary="List real-time attendance status for current day",
    description=(
        "Returns a realtime list of which employees are present or absent for today's date. "
        "Accessible only to admins. Response includes employee IDs, usernames, names, and presence status."
    ),
    tags=["Attendance"],
)
def attendance_status_today(
    current_user: User = Security(get_current_active_admin_user),
    db: Session = Depends(SessionLocal)
):
    """
    Get real-time attendance status for all employees today.

    - **Admin only**: Only users with admin privileges may call this endpoint.
    - Each listed user will be marked as present if they've checked in for today.
    - The response includes both present and absent employees.

    Returns:
        - date: Today's date
        - present_count: number of employees present today
        - absent_count: number of employees absent today
        - users: List of all employees, with presence indicator
    """
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # Gather all employees
    employees = db.query(User).filter(User.role == "employee", User.is_active == 1).all()
    # IDs of those present today
    present_attendance = (
        db.query(Attendance.user_id)
        .filter(
            Attendance.date >= today_start,
            Attendance.date <= today_end
        )
        .distinct()
        .all()
    )
    present_ids = set(uid for (uid,) in present_attendance)

    user_statuses = [
        DailyAttendanceUserStatus(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            is_present=(user.id in present_ids)
        )
        for user in employees
    ]
    present_count = sum(u.is_present for u in user_statuses)
    absent_count = len(user_statuses) - present_count

    return DailyAttendanceStatusResponse(
        date=today,
        present_count=present_count,
        absent_count=absent_count,
        users=user_statuses
    )

# PUBLIC_INTERFACE
@attendance_router.post(
    "/mark",
    response_model=AttendanceResponse,
    summary="Mark employee attendance for the day",
    status_code=status.HTTP_201_CREATED,
    tags=["Attendance"]
)
def mark_attendance(
    mark_req: MarkAttendanceRequest = Depends(),
    current_user: User = Security(get_current_active_employee_user),
    db: Session = Depends(SessionLocal)
):
    """
    Mark the current user's attendance for today.

    - Only employees can mark their own attendance.
    - Can only mark once per day.
    - Records the check-in timestamp (`time_in`).
    - Returns the attendance record.

    Raises:
        - 409 Conflict if already marked for today.
    """
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    # Check for duplicate attendance for today
    existing = (
        db.query(Attendance)
        .filter(
            Attendance.user_id == current_user.id,
            Attendance.date >= today_start,
            Attendance.date <= today_end
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attendance already marked for today."
        )
    now = datetime.now()
    attendance_rec = Attendance(
        user_id=current_user.id,
        date=now,
        time_in=now,
        time_out=None
    )
    db.add(attendance_rec)
    try:
        db.commit()
        db.refresh(attendance_rec)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate attendance. Already marked for today."
        )
    return attendance_rec
