from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# PUBLIC_INTERFACE
def create_app() -> FastAPI:
    """
    Creates and configures the FastAPI application instance without
    importing or registering routers. This makes it safe to import from this file
    in any context (e.g., for OpenAPI schema generation).
    """
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app
