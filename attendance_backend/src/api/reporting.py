from fastapi import APIRouter, Depends, Query, Security, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime, date
from typing import Optional, List
import csv
from io import StringIO

from src.api.main import SessionLocal
from src.api.models import Attendance, User
from src.api.auth import (
    get_current_active_employee_user,
    get_current_active_admin_user
)

reporting_router = APIRouter(
    prefix="/reports",
    tags=["Attendance Reporting"],
    responses={404: {"description": "Not found"}},
)

# ============================ SCHEMAS =============================

class AttendanceHistoryRecord(BaseModel):
    id: int
    date: datetime = Field(..., description="Attendance date (and check-in's datetime)")
    time_in: datetime = Field(..., description="Check-in time stamp")
    time_out: Optional[datetime] = Field(None, description="Check-out time stamp, if ever used")
    class Config:
        from_attributes = True

class AttendanceHistoryResponse(BaseModel):
    total_days: int
    records: List[AttendanceHistoryRecord]

class UserAttendanceSummary(BaseModel):
    user_id: int
    username: str
    full_name: Optional[str]
    total_days_present: int
    last_attendance: Optional[datetime]

class AttendanceReportRecord(BaseModel):
    id: int
    user_id: int
    username: str
    full_name: Optional[str]
    date: datetime
    time_in: datetime
    time_out: Optional[datetime]

class AttendanceReportResponse(BaseModel):
    total_records: int
    records: List[AttendanceReportRecord]

# ============================ ENDPOINTS ===========================

# PUBLIC_INTERFACE
@reporting_router.get(
    "/my-history",
    response_model=AttendanceHistoryResponse,
    summary="Get your own attendance history",
    description="Return all attendance records for logged-in employee, optionally filtered by date range.",
    tags=["Attendance Reporting"],
)
def get_my_attendance_history(
    start_date: Optional[date] = Query(None, description="(Optional) Start date, inclusive"),
    end_date: Optional[date] = Query(None, description="(Optional) End date, inclusive"),
    current_user: User = Security(get_current_active_employee_user),
    db: Session = Depends(SessionLocal)
):
    """Get complete attendance history for current employee (optionally limited to date range)"""
    q = db.query(Attendance).filter(Attendance.user_id == current_user.id)
    if start_date:
        q = q.filter(Attendance.date >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        q = q.filter(Attendance.date <= datetime.combine(end_date, datetime.max.time()))
    q = q.order_by(Attendance.date.desc())
    records = q.all()
    return AttendanceHistoryResponse(
        total_days=len(records),
        records=records
    )

# PUBLIC_INTERFACE
@reporting_router.get(
    "/admin/history",
    response_model=AttendanceReportResponse,
    summary="Admin: List/filter attendance records for any user",
    description="Admins can filter/search attendance logs with options for date range and user. Returns an array of attendance for multiple users.",
    tags=["Attendance Reporting"],
)
def admin_attendance_history(
    user_id: Optional[int] = Query(None, description="(Optional) Filter for a single employee ID"),
    start_date: Optional[date] = Query(None, description="(Optional) Start date, inclusive"),
    end_date: Optional[date] = Query(None, description="(Optional) End date, inclusive"),
    db: Session = Depends(SessionLocal),
    current_user: User = Security(get_current_active_admin_user)
):
    """Admin can search attendance for any/all employees, filtered by user and date."""
    q = db.query(Attendance, User).join(User, Attendance.user_id == User.id)
    if user_id is not None:
        q = q.filter(Attendance.user_id == user_id)
    if start_date:
        q = q.filter(Attendance.date >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        q = q.filter(Attendance.date <= datetime.combine(end_date, datetime.max.time()))
    q = q.order_by(Attendance.date.desc())
    items = q.all()
    results = [
        AttendanceReportRecord(
            id=attendance.id,
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            date=attendance.date,
            time_in=attendance.time_in,
            time_out=attendance.time_out
        )
        for attendance, user in items
    ]
    return AttendanceReportResponse(
        total_records=len(results),
        records=results
    )

# PUBLIC_INTERFACE
@reporting_router.get(
    "/admin/user-summary",
    response_model=List[UserAttendanceSummary],
    summary="Admin: Attendance summary for each employee",
    description="Admin-only: Returns a summary list for each employee (total present days + last date). Supports date filtering.",
    tags=["Attendance Reporting"],
)
def admin_employee_summaries(
    start_date: Optional[date] = Query(None, description="(Optional) Filter - start date"),
    end_date: Optional[date] = Query(None, description="(Optional) Filter - end date"),
    db: Session = Depends(SessionLocal),
    current_user: User = Security(get_current_active_admin_user)
):
    """Shows present count and last attendance date for each employee. Useful for HR/reports."""
    q = db.query(User).filter(User.role == "employee", User.is_active == 1)
    users = q.all()
    summaries: List[UserAttendanceSummary] = []
    for user in users:
        aq = db.query(Attendance).filter(Attendance.user_id == user.id)
        if start_date:
            aq = aq.filter(Attendance.date >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            aq = aq.filter(Attendance.date <= datetime.combine(end_date, datetime.max.time()))
        attendance_recs = aq.order_by(Attendance.date.desc()).all()
        total_days = len(attendance_recs)
        last_date = attendance_recs[0].date if attendance_recs else None
        summaries.append(UserAttendanceSummary(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            total_days_present=total_days,
            last_attendance=last_date
        ))
    return summaries

# PUBLIC_INTERFACE
@reporting_router.get(
    "/admin/export-csv",
    summary="Admin: Export filtered attendance records as CSV",
    description="Admin endpoint to download CSV export of attendance records (with filters for user/date). Response is a text/csv stream.",
    tags=["Attendance Reporting"],
    response_class=Response
)
def admin_export_attendance_csv(
    user_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(SessionLocal),
    current_user: User = Security(get_current_active_admin_user)
):
    """Exports the result of /admin/history as csv."""
    q = db.query(Attendance, User).join(User, Attendance.user_id == User.id)
    if user_id is not None:
        q = q.filter(Attendance.user_id == user_id)
    if start_date:
        q = q.filter(Attendance.date >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        q = q.filter(Attendance.date <= datetime.combine(end_date, datetime.max.time()))
    q = q.order_by(Attendance.date.desc())
    items = q.all()
    output = StringIO()
    csv_writer = csv.writer(output)
    csv_writer.writerow(['attendance_id', 'user_id', 'username', 'full_name', 'date', 'time_in', 'time_out'])
    for attendance, user in items:
        csv_writer.writerow([
            attendance.id,
            user.id,
            user.username,
            user.full_name or "",
            attendance.date.isoformat(),
            attendance.time_in.isoformat(),
            attendance.time_out.isoformat() if attendance.time_out else ""
        ])
    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=attendance_export.csv"
    return response

