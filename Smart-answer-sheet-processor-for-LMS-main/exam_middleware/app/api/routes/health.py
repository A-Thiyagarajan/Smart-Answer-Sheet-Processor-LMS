"""
Health Check and System Routes
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, timezone
import logging

from app.db.database import get_db
from app.schemas import HealthCheckResponse
from app.services.moodle_client import moodle_client
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=HealthCheckResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check endpoint
    
    Checks:
    - Database connectivity
    - Moodle connectivity
    """
    # Check database
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = f"unhealthy: {str(e)[:50]}"
    
    # Check Moodle
    moodle_status = "healthy"
    try:
        if settings.mock_lms_enabled:
            moodle_status = "healthy: local mock LMS enabled"
        else:
            is_connected, message = await moodle_client.check_connection()
            if not is_connected:
                moodle_status = f"unhealthy: {message[:50]}"
    except Exception as e:
        logger.error(f"Moodle health check failed: {e}")
        moodle_status = f"unhealthy: {str(e)[:50]}"
    
    overall_status = "healthy"
    if "unhealthy" in db_status or "unhealthy" in moodle_status:
        overall_status = "degraded"
    
    return HealthCheckResponse(
        status=overall_status,
        version=settings.app_version,
        database=db_status,
        moodle_connection=moodle_status,
        timestamp=datetime.now(timezone.utc)
    )

@router.get("/config")
async def get_public_config():
    """
    Get public configuration (non-sensitive)
    """
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "moodle_url": settings.moodle_base_url,
        "max_file_size_mb": settings.max_file_size_mb,
        "allowed_extensions": settings.allowed_extensions_list,
        "subject_mappings": list(settings.get_subject_assignment_mapping().keys())
    }
