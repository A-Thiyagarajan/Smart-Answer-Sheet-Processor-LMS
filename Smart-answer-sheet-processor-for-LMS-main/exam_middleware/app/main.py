"""
Examination Middleware - Main FastAPI Application

This is the main entry point for the FastAPI application that bridges
scanned examination papers with Moodle LMS for student submissions.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.database import engine, Base, async_session_maker
from app.db.models import StaffUser, SubjectMapping
from app.api.routes import (
    auth_router,
    upload_router,
    student_router,
    admin_router,
    health_router,
    mock_moodle_router,
)
from app.services.mock_lms_service import mock_lms_service

# Resolve filesystem paths from the project root so the app can be started
# from either the repository root or the exam_middleware directory.
LOG_FILE_PATH = settings.log_file_path
LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
STATIC_DIR = settings.app_dir / "static"
TEMPLATES_DIR = settings.app_dir / "templates"
STORAGE_DIR = settings.storage_dir_path

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE_PATH, encoding="utf-8"),
    ],
)
# Set specific loggers to INFO to reduce SQLAlchemy noise
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def ensure_bootstrap_staff_user() -> None:
    """Create an initial admin user when the database is empty."""
    async with async_session_maker() as session:
        staff_count = await session.scalar(select(func.count()).select_from(StaffUser))
        if staff_count and staff_count > 0:
            return

        default_password = os.getenv("ADMIN_PASSWORD")
        if not default_password:
            default_password = "admin123" if settings.mock_lms_enabled else "ChangeMe@123"

        admin_user = StaffUser(
            username="admin",
            email=os.getenv("ADMIN_EMAIL", "admin@example.com"),
            hashed_password=get_password_hash(default_password),
            full_name="Administrator",
            role="admin",
            is_active=True,
        )
        session.add(admin_user)
        await session.commit()
        logger.warning(
            "Bootstrapped initial admin user 'admin'. "
            "Set ADMIN_PASSWORD in the environment to control the first password."
        )


async def ensure_bootstrap_subject_mappings() -> None:
    """Seed subject mappings from the local mock LMS when running in demo mode."""
    if not settings.mock_lms_enabled:
        return

    async with async_session_maker() as session:
        existing_codes = set(
            await session.scalars(select(SubjectMapping.subject_code))
        )

        created = 0
        for course in mock_lms_service.get_courses():
            subject_code = (course.get("course_code") or "").upper()
            assignment_id = course.get("assignment_id")
            course_id = course.get("course_id")
            if not subject_code or not assignment_id or not course_id or subject_code in existing_codes:
                continue

            session.add(
                SubjectMapping(
                    subject_code=subject_code,
                    subject_name=course.get("course_name"),
                    moodle_course_id=course_id,
                    moodle_assignment_id=assignment_id,
                    moodle_assignment_name=course.get("assignment_name"),
                    exam_session="CIA-I",
                    is_active=True,
                )
            )
            existing_codes.add(subject_code)
            created += 1

        if created:
            await session.commit()
            logger.warning("Bootstrapped %s subject mapping(s) from mock LMS.", created)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan events handler.
    Manages startup and shutdown events.
    """
    # Startup
    logger.info("Starting Examination Middleware...")
    
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")

    # Bootstrap the first admin account when the database is empty.
    await ensure_bootstrap_staff_user()
    await ensure_bootstrap_subject_mappings()
    
    # Ensure upload and storage directories exist
    upload_path = settings.upload_dir_path
    upload_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Upload directory: {upload_path.absolute()}")

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Storage directory: {STORAGE_DIR.absolute()}")

    # Create templates directory
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    # Create static directory
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    
    logger.info("Examination Middleware started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Examination Middleware...")
    await engine.dispose()
    logger.info("Database connections closed")


# Create FastAPI application
app = FastAPI(
    title="Examination Middleware",
    description="""
    ## Examination Paper Submission Middleware
    
    This API provides a secure bridge between scanned examination papers 
    and the Moodle LMS, enabling students to submit their answer sheets.
    
    ### Features:
    - **Staff Upload Portal**: Bulk upload of scanned answer sheets
    - **Student Portal**: View and submit assigned papers to Moodle
    - **Moodle Integration**: Direct submission to assignment modules
    - **Security**: JWT authentication, encrypted token storage
    - **Audit Trail**: Complete logging of all operations
    
    ### Workflow:
    1. Staff uploads scanned papers with standardized filenames
    2. System extracts student register number and subject code
    3. Students authenticate via Moodle credentials
    4. Students view their assigned papers and submit to Moodle
    5. System handles the complete submission workflow
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add GZip compression
app.add_middleware(GZipMiddleware, minimum_size=1000)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "An internal server error occurred",
            "detail": str(exc) if settings.debug else None,
        },
    )


# Mount static files
try:
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
except Exception:
    logger.warning("Static files directory not found, skipping mount")

# Include API routers
app.include_router(
    health_router,
    prefix="/health",
    tags=["Health"],
)

app.include_router(
    auth_router,
    prefix="/auth",
    tags=["Authentication"],
)

app.include_router(
    upload_router,
    prefix="/upload",
    tags=["Upload"],
)

app.include_router(
    student_router,
    prefix="/student",
    tags=["Student"],
)

app.include_router(
    admin_router,
    prefix="/admin",
    tags=["Administration"],
)

# Only include mock Moodle endpoints if explicitly enabled
if settings.mock_lms_enabled:
    logger.warning("Mock Moodle LMS is ENABLED - Development mode only!")
    app.include_router(
        mock_moodle_router,
        prefix="/lms",
        tags=["Mock Moodle LMS (Development Only)"],
    )
else:
    logger.info("Mock Moodle LMS is disabled (production mode)")


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint - API information.
    """
    return {
        "name": "Examination Middleware API",
        "version": "1.0.0",
        "description": "Examination Paper Submission Middleware for Moodle LMS",
        "documentation": "/docs",
        "health_check": "/health",
        "endpoints": {
            "staff_login": "/auth/staff/login",
            "student_login": "/auth/student/login",
            "upload": "/upload/single",
            "bulk_upload": "/upload/bulk",
            "student_dashboard": "/student/dashboard",
            "submit": "/student/submit/{artifact_id}",
            "admin": "/admin/mappings",
        },
    }


@app.get("/portal/staff", tags=["Portal"], include_in_schema=False)
async def staff_portal(request: Request):
    """Staff upload portal page."""
    html = (TEMPLATES_DIR / "staff_upload.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/portal/student", tags=["Portal"], include_in_schema=False)
async def student_portal(request: Request):
    """Student submission portal page."""
    html = (TEMPLATES_DIR / "student_portal.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level="info",
    )
