"""
Admin API Routes
Administrative functions for system management
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy import text
from typing import Optional
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
import logging
import os

from app.db.database import get_db
from app.db.models import StaffUser, SubjectMapping, ExaminationArtifact, WorkflowStatus
from app.schemas import (
    SubjectMappingCreate,
    SubjectMappingResponse,
    AuditLogResponse,
    SystemStatsResponse,
)
from app.services.artifact_service import ArtifactService, SubjectMappingService, AuditService, compose_subject_session_key, split_subject_session_key
from app.services.submission_service import SubmissionService
from app.services.moodle_client import MoodleClient, MoodleAPIError
from app.api.routes.auth import get_current_staff
from app.core.config import settings
from app.core.security import generate_transaction_id
from app.db.models import AuditLog
from app.services.mock_lms_service import mock_lms_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================
# Subject Mapping Management
# ============================================

@router.get("/mappings", response_model=list[SubjectMappingResponse])
async def list_subject_mappings(
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    List all subject to assignment mappings
    """
    mapping_service = SubjectMappingService(db)
    mappings = await mapping_service.get_all_active()
    
    return [
        SubjectMappingResponse(
            id=m.id,
            subject_code=m.subject_code,
            subject_name=m.subject_name,
            moodle_course_id=m.moodle_course_id,
            moodle_assignment_id=m.moodle_assignment_id,
            moodle_assignment_name=m.moodle_assignment_name,
            exam_session=m.exam_session,
            is_active=m.is_active,
            created_at=m.created_at,
            last_verified_at=m.last_verified_at
        )
        for m in mappings
    ]


@router.post("/mappings", response_model=SubjectMappingResponse)
async def create_subject_mapping(
    mapping: SubjectMappingCreate,
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Create a new subject to assignment mapping
    """
    mapping_service = SubjectMappingService(db)
    
    # Check if mapping already exists
    existing = await mapping_service.get_mapping(mapping.subject_code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mapping for {mapping.subject_code} already exists"
        )
    
    new_mapping = await mapping_service.create_mapping(
        subject_code=mapping.subject_code,
        moodle_course_id=mapping.moodle_course_id,
        moodle_assignment_id=mapping.moodle_assignment_id,
        subject_name=mapping.subject_name,
        moodle_assignment_name=mapping.moodle_assignment_name,
        exam_session=mapping.exam_session
    )
    
    await db.commit()
    
    return SubjectMappingResponse(
        id=new_mapping.id,
        subject_code=new_mapping.subject_code,
        subject_name=new_mapping.subject_name,
        moodle_course_id=new_mapping.moodle_course_id,
        moodle_assignment_id=new_mapping.moodle_assignment_id,
        moodle_assignment_name=new_mapping.moodle_assignment_name,
        exam_session=new_mapping.exam_session,
        is_active=new_mapping.is_active,
        created_at=new_mapping.created_at,
        last_verified_at=new_mapping.last_verified_at
    )


@router.post("/mappings/sync")
async def sync_mappings_from_config(
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Sync subject mappings from configuration
    """
    mapping_service = SubjectMappingService(db)
    created = await mapping_service.sync_from_config()
    await db.commit()
    
    return {
        "message": f"Synced {created} new mappings from configuration",
        "created": created
    }


@router.post("/mappings/discover")
async def discover_assignments_from_moodle(
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Discover assignments from Moodle using admin token
    
    This uses the configured admin token to fetch course and assignment information
    """
    if not settings.moodle_admin_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin token not configured"
        )
    
    client = MoodleClient(token=settings.moodle_admin_token)
    
    try:
        # Get site info to verify token works
        site_info = await client.get_site_info()
        
        # This is a simplified example - in production you would:
        # 1. Get all courses the admin can see
        # 2. For each course, get assignments
        # 3. Create or update mappings
        
        return {
            "message": "Discovery successful",
            "site": site_info.get("sitename"),
            "user": site_info.get("fullname"),
            "note": "Use the Moodle admin panel to find course and assignment IDs"
        }
        
    except MoodleAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Moodle API error: {e.message}"
        )
    finally:
        await client.close()


@router.delete("/mappings/{mapping_id}")
async def delete_subject_mapping(
    mapping_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Delete (deactivate) a subject mapping
    """
    result = await db.execute(
        select(SubjectMapping).where(SubjectMapping.id == mapping_id)
    )
    mapping = result.scalar_one_or_none()
    
    if not mapping:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mapping not found"
        )
    
    mapping.is_active = False
    await db.commit()
    
    return {"message": f"Mapping {mapping.subject_code} deactivated"}


# ============================================
# System Statistics
# ============================================

@router.get("/stats", response_model=SystemStatsResponse)
async def get_system_stats(
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Get system-wide statistics
    """
    artifact_service = ArtifactService(db)
    stats = await artifact_service.get_stats()
    
    # Count active sessions
    from app.db.models import StudentSession

    now_ref = datetime.now(timezone.utc)
    result = await db.execute(select(StudentSession))
    active_sessions = sum(
        1
        for session in result.scalars().all()
        if session.expires_at
        and (
            session.expires_at.replace(tzinfo=timezone.utc)
            if session.expires_at.tzinfo is None or session.expires_at.utcoffset() is None
            else session.expires_at.astimezone(timezone.utc)
        ) > now_ref
    )
    
    return SystemStatsResponse(
        total_artifacts=sum(stats.values()),
        pending_review=stats.get("pending", 0) + stats.get("pending_review", 0),
        submitted=stats.get("completed", 0) + stats.get("submitted_to_lms", 0),
        failed=stats.get("failed", 0),
        queued=stats.get("queued", 0),
        active_sessions=active_sessions
    )


# ============================================
# Audit Logs
# ============================================

@router.get("/audit-logs", response_model=list[AuditLogResponse])
async def get_audit_logs(
    limit: int = Query(default=100, le=500),
    artifact_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Get audit logs
    """
    audit_service = AuditService(db)
    
    if artifact_id:
        logs = await audit_service.get_for_artifact(artifact_id)
    else:
        logs = await audit_service.get_recent(limit=limit)
    
    return [
        {
            "id": log.id,
            "action": log.action,
            "action_category": log.action_category,
            "description": log.description,
            "actor_type": log.actor_type,
            "actor_id": log.actor_id,
            "actor_username": log.actor_username,
            "actor_ip": log.actor_ip,
            "artifact_id": log.artifact_id,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "request_data": log.request_data,
            "response_data": log.response_data,
            "created_at": log.created_at,
        }
        for log in logs
    ]


# ============================================
# Queue Management
# ============================================

@router.post("/queue/retry")
async def retry_queued_submissions(
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Manually trigger retry of queued submissions
    """
    if not settings.moodle_admin_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin token not configured for queue processing"
        )
    
    submission_service = SubmissionService(db)
    result = await submission_service.retry_queued_submissions(settings.moodle_admin_token)
    
    return result


@router.get("/queue/status")
async def get_queue_status(
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Get status of the submission queue
    """
    from app.db.models import SubmissionQueue
    
    result = await db.execute(select(SubmissionQueue))
    queue_items = result.scalars().all()
    
    status_counts = {}
    for item in queue_items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
    
    return {
        "total_items": len(queue_items),
        "by_status": status_counts,
        "items": [
            {
                "id": item.id,
                "artifact_id": item.artifact_id,
                "status": item.status,
                "retry_count": item.retry_count,
                "queued_at": item.queued_at.isoformat() if item.queued_at else None,
                "last_error": item.last_error
            }
            for item in queue_items[:50]
        ]
    }


# ============================================
# Artifact Management
# ============================================

@router.get("/artifacts/{artifact_uuid}")
async def get_artifact_details(
    artifact_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Get detailed artifact information (admin view)
    """
    artifact_service = ArtifactService(db)
    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found"
        )
    
    return {
        "id": artifact.id,
        "artifact_uuid": str(artifact.artifact_uuid),
        "raw_filename": artifact.raw_filename,
        "original_filename": artifact.original_filename,
        "parsed_reg_no": artifact.parsed_reg_no,
        "parsed_subject_code": split_subject_session_key(artifact.parsed_subject_code)[0],
        "exam_session": split_subject_session_key(artifact.parsed_subject_code)[1],
        "file_hash": artifact.file_hash,
        "file_size_bytes": artifact.file_size_bytes,
        "workflow_status": artifact.workflow_status.value,
        "moodle_user_id": artifact.moodle_user_id,
        "moodle_assignment_id": artifact.moodle_assignment_id,
        "moodle_draft_item_id": artifact.moodle_draft_item_id,
        "moodle_submission_id": artifact.moodle_submission_id,
        "transaction_id": artifact.transaction_id,
        "uploaded_at": artifact.uploaded_at.isoformat() if artifact.uploaded_at else None,
        "submit_timestamp": artifact.submit_timestamp.isoformat() if artifact.submit_timestamp else None,
        "error_message": artifact.error_message,
        "retry_count": artifact.retry_count,
        "transaction_log": artifact.transaction_log
    }


@router.post("/artifacts/{artifact_uuid}/reset")
async def reset_artifact_status(
    artifact_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Reset artifact status to pending (for retry)
    """
    artifact_service = ArtifactService(db)
    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found"
        )
    
    from app.db.models import WorkflowStatus
    
    artifact = await artifact_service.update_status(
        artifact_id=artifact.id,
        status=WorkflowStatus.PENDING_REVIEW,
        log_action="admin_reset",
        log_details={"reset_by": current_staff.username}
    )
    
    # Clear error state
    artifact.error_message = None
    artifact.moodle_draft_item_id = None
    
    await db.commit()
    
    return {"message": "Artifact status reset to pending"}



@router.post("/artifacts/{artifact_uuid}/edit")
async def edit_artifact_metadata(
    artifact_uuid: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Allow staff to edit parsed metadata of an artifact (reg no, subject code)
    Body: { "parsed_reg_no": Optional[str], "parsed_subject_code": Optional[str] }
    """
    artifact_service = ArtifactService(db)
    audit_service = AuditService(db)

    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    parsed_reg = payload.get("parsed_reg_no")
    parsed_sub = payload.get("parsed_subject_code")
    original_fname = payload.get("original_filename")
    _, current_exam_session = split_subject_session_key(artifact.parsed_subject_code)

    # Determine the target values after edit (use existing if not provided)
    new_parsed_reg = parsed_reg if parsed_reg is not None else artifact.parsed_reg_no
    new_parsed_sub = compose_subject_session_key(parsed_sub, current_exam_session) if parsed_sub is not None else artifact.parsed_subject_code

    # If both values are present, ensure uniqueness of the (parsed_reg_no, parsed_subject_code) pair
    if new_parsed_reg and new_parsed_sub:
        existing_q = await db.execute(
            select(ExaminationArtifact).where(
                ExaminationArtifact.parsed_reg_no == new_parsed_reg,
                ExaminationArtifact.parsed_subject_code == new_parsed_sub,
                ExaminationArtifact.id != artifact.id
            )
        )
        existing_art = existing_q.scalar_one_or_none()
        if existing_art:
            # If the conflicting artifact is already deleted, allow reuse by clearing the identifiers
            from app.db.models import WorkflowStatus as _WS
            if getattr(existing_art, 'workflow_status', None) == _WS.DELETED:
                existing_art.add_log_entry("cleared_identifiers_for_reuse", {
                    "cleared_by": current_staff.username,
                    "reason": "reusing (reg,subject) for another artifact"
                })
                existing_art.parsed_reg_no = None
                existing_art.parsed_subject_code = None
                existing_art.transaction_id = None
                # flush the change so unique constraint is freed
                await db.flush()
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Another artifact (id={existing_art.id}) already has parsed_reg_no='{new_parsed_reg}' "
                        f"and parsed_subject_code='{new_parsed_sub}'. Edit rejected to preserve uniqueness."
                    )
                )

    changes = {}
    if parsed_reg and parsed_reg != artifact.parsed_reg_no:
        changes["parsed_reg_no"] = {"old": artifact.parsed_reg_no, "new": parsed_reg}

    if parsed_sub and compose_subject_session_key(parsed_sub, current_exam_session) != artifact.parsed_subject_code:
        changes["parsed_subject_code"] = {"old": split_subject_session_key(artifact.parsed_subject_code)[0], "new": parsed_sub}

    if original_fname and original_fname != artifact.original_filename:
        changes["original_filename"] = {"old": artifact.original_filename, "new": original_fname}

    if not changes:
        return {"message": "No changes applied"}

    # Policy: instead of mutating the existing artifact in-place, create a new artifact
    # with the updated metadata and mark the original artifact as deleted/superseded.
    try:
        # Determine target values for the new artifact
        target_reg = parsed_reg if parsed_reg is not None else artifact.parsed_reg_no
        target_sub = parsed_sub if parsed_sub is not None else split_subject_session_key(artifact.parsed_subject_code)[0]
        target_original = original_fname if original_fname is not None else artifact.original_filename

        old_subject_code, old_exam_session = split_subject_session_key(artifact.parsed_subject_code)

        # If the artifact was already pushed to the LMS, remove the stale LMS record first.
        old_submission_removed = False
        if settings.mock_lms_enabled:
            old_submission = mock_lms_service.get_submission_by_artifact(
                artifact_uuid=str(artifact.artifact_uuid),
                exam_session=old_exam_session,
            )
            if old_submission:
                old_submission_removed = mock_lms_service.delete_submission(
                    course_code=old_submission["course_code"],
                    submission_id=str(old_submission["submission_id"]),
                )

        # Create a new artifact record by copying file metadata from the existing artifact
        new_artifact = await artifact_service.create_artifact(
            raw_filename=artifact.raw_filename,
            original_filename=target_original,
            file_blob_path=artifact.file_blob_path,
            file_hash=artifact.file_hash,
            parsed_reg_no=target_reg,
            parsed_subject_code=target_sub,
            exam_session=current_exam_session,
            file_size_bytes=artifact.file_size_bytes,
            mime_type=artifact.mime_type,
            uploaded_by_staff_id=current_staff.id,
            allow_existing_hash=True,
        )

        # Clear LMS/submission linkage on the old artifact so the edit is reflected
        # across student portal and LMS-derived pages immediately.
        await artifact_service.reset_lms_sync(
            artifact.id,
            reason="staff_metadata_edit_replaced_artifact",
            new_status=WorkflowStatus.PENDING,
            clear_identity_links=True,
        )

        # Mark the old artifact as deleted/superseded
        from app.db.models import WorkflowStatus as _WS
        try:
            artifact.workflow_status = _WS.DELETED
            # Clear transaction_id and parsed identifiers so this row no longer blocks uploads
            artifact.transaction_id = None
            artifact.parsed_reg_no = None
            artifact.parsed_subject_code = None
            artifact.moodle_draft_item_id = None
            artifact.moodle_submission_id = None
            artifact.lms_transaction_id = None
            artifact.moodle_user_id = None
            artifact.moodle_username = None
            artifact.moodle_course_id = None
            artifact.moodle_assignment_id = None
            artifact.submitted_by_user_id = None
            artifact.submit_timestamp = None
            artifact.completed_at = None
            artifact.validated_at = None
        except Exception:
            artifact.error_message = (artifact.error_message or "") + f"; Superseded by artifact {new_artifact.id}"

        artifact.add_log_entry("admin_replaced", {
            "replaced_by": new_artifact.id,
            "replaced_by_uuid": str(new_artifact.artifact_uuid),
            "edited_by": current_staff.username,
            "old_subject_code": old_subject_code,
            "old_exam_session": old_exam_session,
            "stale_lms_submission_removed": old_submission_removed,
        })

        # Audit the replacement
        await audit_service.log_action(
            action="admin_replace",
            action_category="admin",
            actor_type="staff",
            actor_id=str(current_staff.id),
            actor_username=current_staff.username,
            artifact_id=new_artifact.id,
            description=f"Created new artifact {new_artifact.id} replacing {artifact.id}",
            request_data={"original_artifact": artifact.id, "changes": changes},
            response_data={"new_artifact": new_artifact.id}
        )

        await db.commit()

        return {
            "message": "Artifact replaced by new artifact with updated metadata",
            "artifact": {
                "id": new_artifact.id,
                "artifact_uuid": str(new_artifact.artifact_uuid),
                "parsed_reg_no": new_artifact.parsed_reg_no,
                "parsed_subject_code": split_subject_session_key(new_artifact.parsed_subject_code)[0],
                "exam_session": split_subject_session_key(new_artifact.parsed_subject_code)[1],
            }
        }
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Update failed: unique constraint violation")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))



@router.delete("/artifacts/{artifact_uuid}")
async def delete_artifact(
    artifact_uuid: str,
    reason: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Permanently delete an artifact from storage, database, and mock LMS state.
    """
    artifact_service = ArtifactService(db)

    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    try:
        # Attempt to remove the file from local storage.
        if artifact.file_blob_path:
            path = artifact.file_blob_path.replace("\\", "/")
            if os.path.exists(path):
                os.remove(path)

        # Remove the associated submission from the mock LMS when running in demo mode.
        if settings.mock_lms_enabled:
            _, exam_session = split_subject_session_key(artifact.parsed_subject_code)
            submission = mock_lms_service.get_submission_by_artifact(
                artifact_uuid=str(artifact.artifact_uuid),
                exam_session=exam_session,
            )
            if submission:
                course_code = submission.get("course_code")
                submission_id = submission.get("submission_id")
                if course_code and submission_id:
                    mock_lms_service.delete_submission(course_code=course_code, submission_id=submission_id)

        await artifact_service.delete_artifact_permanently(artifact)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.exception("Failed to permanently delete artifact %s", artifact_uuid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not permanently delete artifact: {exc}",
        )

    return {"message": "Artifact permanently removed"}


@router.post("/artifacts/{artifact_uuid}/reports/{report_id}/resolve")
async def resolve_report(
    artifact_uuid: str,
    report_id: int,
    payload: dict = None,
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Mark a student report as resolved. Creates an audit entry `report_resolved`
    that targets the original report audit log entry.
    Body: { "note": Optional[str] }
    """
    artifact_service = ArtifactService(db)
    audit_service = AuditService(db)

    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    # Ensure the referenced audit log exists and belongs to this artifact
    result = await db.execute(
        select(AuditLog).where(AuditLog.id == report_id, AuditLog.artifact_id == artifact.id)
    )
    report_log = result.scalar_one_or_none()
    if not report_log or report_log.action != 'report_issue':
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report entry not found")

    # Prevent resolving a report that the student has withdrawn
    deleted_q = await db.execute(
        select(AuditLog).where(AuditLog.action == 'report_deleted', AuditLog.target_id == str(report_id))
    )
    deleted_entry = deleted_q.scalars().first()
    if deleted_entry:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot resolve a withdrawn report")

    note = None
    if isinstance(payload, dict):
        note = payload.get('note')

    # Create resolution audit log referencing the original report id
    await audit_service.log_action(
        action="report_resolved",
        action_category="report",
        actor_type="staff",
        actor_id=str(current_staff.id),
        actor_username=current_staff.username,
        artifact_id=artifact.id,
        description=note or f"Resolved report {report_id}",
        request_data={"resolved_report_id": report_id},
        response_data={"note": note} if note else None,
        target_type='audit_log',
        target_id=str(report_id)
    )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {"message": "Report marked resolved"}


@router.post("/artifacts/{artifact_uuid}/clear-transaction")
async def clear_artifact_transaction_id(
    artifact_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_staff: StaffUser = Depends(get_current_staff)
):
    """
    Clear the transaction_id for a given artifact.

    Use this when a stale or incorrect transaction_id is preventing new uploads.
    This action is audited and requires staff authentication.
    """
    artifact_service = ArtifactService(db)
    audit_service = AuditService(db)

    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    old_tid = artifact.transaction_id
    if not old_tid:
        return {"message": "No transaction_id set on this artifact"}

    artifact.transaction_id = None
    artifact.add_log_entry("cleared_transaction_id", {"cleared_by": current_staff.username})

    await audit_service.log_action(
        action="clear_transaction_id",
        action_category="admin",
        actor_type="staff",
        actor_id=str(current_staff.id),
        actor_username=current_staff.username,
        artifact_id=artifact.id,
        description=f"Cleared transaction_id on artifact {artifact.id}",
        request_data={"old_transaction_id": old_tid}
    )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not clear transaction_id")

    return {"message": "transaction_id cleared", "old_transaction_id": old_tid}
