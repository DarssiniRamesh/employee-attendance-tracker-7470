from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Enum,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()

class RoleEnum(str, enum.Enum):
    ADMIN = "admin"
    EMPLOYEE = "employee"

# PUBLIC_INTERFACE
class User(Base):
    """
    This model represents a user in the attendance system.
    Fields:
        - id: Primary key.
        - username: Unique username for login.
        - hashed_password: Hashed user password.
        - full_name: Full display name.
        - role: User role (admin/employee).
        - is_active: Status.
        - created_at: When the user was created.

    CRITICAL:
    Do NOT remove or change the unique=True and index=True properties on username,
    or the unique constraint on username at the DB layer.
    If you modify the username column or User table, ensure the DB is migrated properly and check all migrations for unique/index.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(Enum(RoleEnum), default=RoleEnum.EMPLOYEE, nullable=False)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # relationship: if an employee, their attendance records
    attendance_records = relationship("Attendance", back_populates="user")

# PUBLIC_INTERFACE
class Attendance(Base):
    """
    This model tracks daily attendance logs for each employee/user.
    Fields:
        - id: Primary key.
        - user_id: Foreign key to users.
        - date: The calendar date of attendance.
        - time_in: Timestamp for attendance mark-in.
        - time_out: Optional timestamp for mark-out.
    """
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("user_id", "date", name="unique_user_attendance"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(DateTime, nullable=False, index=True)
    time_in = Column(DateTime, nullable=False)
    time_out = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="attendance_records")

# PUBLIC_INTERFACE
class TokenBlacklist(Base):
    """
    Stores blacklisted JWT tokens (for logout/blocklist).
    """
    __tablename__ = "token_blacklist"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
