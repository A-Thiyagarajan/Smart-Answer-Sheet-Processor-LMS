"""
Student API Routes
Handles student dashboard and submission
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Header
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import logging
import os
from pathlib import Path
from datetime import datetime

from app.db.database import get_db
from app.db.models import StudentSession
from app.schemas import (
    StudentDashboardResponse,
    StudentPendingPaper,
    SubmissionRequest,
    SubmissionResponse,
    ArtifactResponse,
    WorkflowStatusEnum,
)
from app.services.artifact_service import (
    ArtifactService,
    SubjectMappingService,
    AuditService,
    split_subject_session_key,
)
from app.services.submission_service import SubmissionService
from app.services.mock_lms_service import mock_lms_service
from app.core.config import settings
from app.api.routes.auth import get_current_student_session, get_decrypted_token

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_session_register_number(session: StudentSession) -> str:
    import re

    register_number = session.register_number
    if not register_number and session.moodle_fullname:
        match = re.search(r"\b(\d{12})\b", session.moodle_fullname)
        if match:
            register_number = match.group(1)

    return register_number or session.moodle_username


def _resolve_artifact_file_path(
    file_blob_path: str,
    original_filename: str,
    parsed_reg_no: Optional[str] = None,
    parsed_subject_code: Optional[str] = None,
) -> Optional[str]:
    """Resolve an artifact file path robustly across relative/Windows paths.

    The DB may contain a relative path (e.g. ./uploads/...) or a stale path.
    This attempts safe resolutions within the project directory.
    """
    base_dir = Path(__file__).resolve().parents[3]  # .../exam_middleware
    upload_dir = settings.upload_dir_path
    storage_dir = settings.storage_dir_path

    candidates: list[Path] = []

    if file_blob_path:
        raw = Path(os.path.normpath(file_blob_path))
        candidates.append(raw)
        # If it is a relative path, also try resolving from the project root
        if not raw.is_absolute():
            candidates.append((base_dir / raw).resolve())
            # Common case: stored as "./uploads/..." with a leading "./"
            if str(raw).startswith("./") or str(raw).startswith(".\\"):
                candidates.append((base_dir / str(raw)[2:]).resolve())

    blob_name = Path(file_blob_path).name if file_blob_path else ""
    orig_name = Path(original_filename).name if original_filename else ""

    # Search in known upload directories only
    search_dirs = [
        upload_dir / "pending",
        upload_dir / "processed",
        upload_dir / "failed",
        upload_dir / "temp",
        upload_dir,
        storage_dir / "uploads" / "pending",
        storage_dir / "uploads" / "processed",
        storage_dir / "uploads" / "failed",
        storage_dir / "uploads" / "temp",
        storage_dir / "uploads",
        base_dir,
    ]

    for d in search_dirs:
        if blob_name:
            candidates.append(d / blob_name)
        if orig_name and orig_name != blob_name:
            candidates.append(d / orig_name)

    # Last-resort: reconstruct standard filename pattern used by uploads
    # Example: 212222240047_19AI405.pdf
    if parsed_reg_no and parsed_subject_code:
        # Try common allowed extensions without expensive recursion
        for ext in (".pdf", ".jpg", ".jpeg", ".png"):
            guessed = f"{parsed_reg_no}_{parsed_subject_code}{ext}"
            candidates.append(base_dir / guessed)
            candidates.append(upload_dir / "pending" / guessed)
            candidates.append(upload_dir / "processed" / guessed)
            candidates.append(upload_dir / "failed" / guessed)
            candidates.append(upload_dir / "temp" / guessed)
            candidates.append(upload_dir / guessed)

    for p in candidates:
        try:
            if p and p.exists() and p.is_file():
                return str(p)
        except OSError:
            continue

    # Very last-resort: glob match in a few small directories (non-recursive)
    if parsed_reg_no and parsed_subject_code:
        pattern = f"{parsed_reg_no}_{parsed_subject_code}.*"
        for d in [
            base_dir,
            upload_dir,
            upload_dir / "pending",
            upload_dir / "processed",
            upload_dir / "failed",
            upload_dir / "temp",
        ]:
            try:
                if d.exists() and d.is_dir():
                    for hit in d.glob(pattern):
                        if hit.is_file():
                            return str(hit)
            except OSError:
                continue

    return None


async def get_student_session(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session: Optional[str] = Query(None, alias="session"),
    db: AsyncSession = Depends(get_db),
) -> StudentSession:
    """Get student session from header or query.

    - Use `X-Session-ID` header for normal `fetch()` requests.
    - Use `?session=...` for iframe/preview URLs (iframes can't send custom headers).
    """
    session_id = x_session_id or session
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Session-ID header or session query parameter required",
        )
    return await get_current_student_session(session_id, db)


@router.get("/dashboard", response_model=StudentDashboardResponse)
async def get_dashboard(
    request: Request,
    session: StudentSession = Depends(get_student_session),
    db: AsyncSession = Depends(get_db)
):
    """
    Get student dashboard
    
    Returns:
    - List of papers pending submission
    - List of already submitted papers
    - User information
    """
    artifact_service = ArtifactService(db)
    mapping_service = SubjectMappingService(db)
    
    # Derive a strict register number (12-digit) if available; otherwise rely on Moodle identity
    import re
    extracted_reg = None
    if session.register_number:
        extracted_reg = session.register_number
    else:
        if session.moodle_fullname:
            match = re.search(r'\b(\d{12})\b', session.moodle_fullname)
            if match:
                extracted_reg = match.group(1)

    # Only use the register_number when it looks like a 12-digit university register
    register_number = extracted_reg if extracted_reg and re.fullmatch(r"\d{12}", extracted_reg) else None

    logger.info(f"Dashboard for register_number: {register_number or '(none)'} moodle_username: {session.moodle_username}")

    # Get pending papers for this student. Provide both register (when present) and Moodle identity.
    pending_artifacts = await artifact_service.get_pending_for_student(
        register_number=register_number,
        moodle_user_id=session.moodle_user_id,
        moodle_username=session.moodle_username
    )
    
    # Get submitted papers
    submitted_artifacts = await artifact_service.get_submitted_for_student(
        register_number=register_number
    )
    
    # Build pending papers list with subject info
    pending_papers = []
    for artifact in pending_artifacts:
        subject_code, exam_session = split_subject_session_key(artifact.parsed_subject_code)
        # Get subject mapping for additional info
        mapping = None
        if artifact.parsed_subject_code:
            mapping = await mapping_service.get_mapping(artifact.parsed_subject_code)
        
        # Check if we have a valid assignment mapping
        assignment_id = await mapping_service.get_assignment_id(artifact.parsed_subject_code) if artifact.parsed_subject_code else None
        
        pending_papers.append(StudentPendingPaper(
            artifact_uuid=str(artifact.artifact_uuid),
            subject_code=subject_code or "Unknown",
            exam_session=exam_session,
            subject_name=mapping.subject_name if mapping else None,
            assignment_name=mapping.moodle_assignment_name if mapping else None,
            filename=artifact.original_filename,
            uploaded_at=artifact.uploaded_at,
            workflow_status=artifact.workflow_status.value.lower() if artifact.workflow_status else None,
            can_submit=assignment_id is not None,
            message=None if assignment_id else "Assignment mapping not found. Contact admin."
        ))
    
    # Build submitted papers list (include subject_name from mapping if available)
    submitted_papers = []
    for a in submitted_artifacts:
        subject_code, exam_session = split_subject_session_key(a.parsed_subject_code)
        mapping = None
        submission = None
        if a.parsed_subject_code:
            mapping = await mapping_service.get_mapping(a.parsed_subject_code)
        if settings.mock_lms_enabled:
            submission = mock_lms_service.get_submission_by_artifact(
                artifact_uuid=str(a.artifact_uuid),
                exam_session=exam_session,
            )

        submitted_papers.append(
            ArtifactResponse(
                id=a.id,
                artifact_uuid=str(a.artifact_uuid),
                raw_filename=a.raw_filename,
                original_filename=a.original_filename,
                subject_name=mapping.subject_name if mapping else None,
                parsed_reg_no=a.parsed_reg_no,
                parsed_subject_code=subject_code,
                exam_session=exam_session,
                workflow_status=WorkflowStatusEnum(a.workflow_status.value),
                moodle_assignment_id=a.moodle_assignment_id,
                grading_status=submission.get("grading_status") if submission else None,
                grade=submission.get("grade") if submission else None,
                grade_max=submission.get("grade_max") if submission else None,
                graded_on=datetime.fromisoformat(submission["graded_on"]) if submission and submission.get("graded_on") else None,
                graded_by=submission.get("graded_by") if submission else None,
                feedback_pdf=submission.get("feedback_pdf") if submission else None,
                uploaded_at=a.uploaded_at,
                submit_timestamp=a.submit_timestamp
            )
        )
    
    return StudentDashboardResponse(
        moodle_user_id=session.moodle_user_id,
        moodle_username=session.moodle_username,
        full_name=session.moodle_fullname,
        pending_papers=pending_papers,
        submitted_papers=submitted_papers,
        total_pending=len(pending_papers),
        total_submitted=len(submitted_papers)
    )


@router.get("/paper/{artifact_uuid}")
async def get_paper_details(
    artifact_uuid: str,
    session: StudentSession = Depends(get_student_session),
    db: AsyncSession = Depends(get_db)
):
    """
    Get details of a specific paper
    
    Security: Only returns if the paper belongs to the logged-in student
    """
    artifact_service = ArtifactService(db)
    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper not found"
        )
    
    # Security check (match against the student's register number)
    session_reg_no = _get_session_register_number(session)
    if artifact.parsed_reg_no != session_reg_no:
        logger.warning(
            f"Unauthorized access attempt: {session_reg_no} tried to access "
            f"paper belonging to {artifact.parsed_reg_no}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own papers"
        )
    
    # Log the view
    audit_service = AuditService(db)
    await audit_service.log_action(
        action="paper_viewed",
        action_category="view",
        actor_type="student",
        actor_id=str(session.moodle_user_id),
        actor_username=session.moodle_username,
        artifact_id=artifact.id,
        description=f"Student viewed paper: {artifact.original_filename}"
    )
    await db.commit()
    
    return {
        "artifact_uuid": str(artifact.artifact_uuid),
        "filename": artifact.original_filename,
        "register_number": artifact.parsed_reg_no,
        "subject_code": split_subject_session_key(artifact.parsed_subject_code)[0],
        "exam_session": split_subject_session_key(artifact.parsed_subject_code)[1],
        "status": artifact.workflow_status.value,
        "uploaded_at": artifact.uploaded_at.isoformat() if artifact.uploaded_at else None,
        "submitted_at": artifact.submit_timestamp.isoformat() if artifact.submit_timestamp else None,
        "file_size": artifact.file_size_bytes,
        "mime_type": artifact.mime_type
    }


@router.get("/paper/{artifact_uuid}/view")
async def view_paper_file(
    artifact_uuid: str,
    session: StudentSession = Depends(get_student_session),
    db: AsyncSession = Depends(get_db)
):
    """
    View/download the actual paper file
    
    Returns the file for display in the browser
    """
    artifact_service = ArtifactService(db)
    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper not found"
        )
    
    # Security check (match against the student's register number)
    session_reg_no = _get_session_register_number(session)
    if artifact.parsed_reg_no != session_reg_no:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own papers"
        )
    
    resolved_path = _resolve_artifact_file_path(
        artifact.file_blob_path,
        artifact.original_filename,
        parsed_reg_no=artifact.parsed_reg_no,
        parsed_subject_code=split_subject_session_key(artifact.parsed_subject_code)[0],
    )
    if not resolved_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on server"
        )

    # Self-heal: update stored blob path if it was stale
    try:
        if artifact.file_blob_path != resolved_path:
            artifact.file_blob_path = resolved_path.replace('\\', '/')
            await db.commit()
    except Exception:
        await db.rollback()
    
    # Determine media type
    media_type = artifact.mime_type or "application/pdf"
    
    safe_name = (artifact.original_filename or "paper").replace('"', "")
    return FileResponse(
        path=resolved_path,
        media_type=media_type,
        filename=safe_name,
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.post("/paper/{artifact_uuid}/report")
async def report_artifact_issue(
    artifact_uuid: str,
    request: Request,
    session: StudentSession = Depends(get_student_session),
    db: AsyncSession = Depends(get_db)
):
    """
    Allow a student to report an issue with an uploaded paper (wrong reg/subject etc.)

    Body: { "message": str, "suggested_reg_no": Optional[str], "suggested_subject_code": Optional[str] }
    """
    artifact_service = ArtifactService(db)
    audit_service = AuditService(db)

    payload = await request.json()
    message = (payload or {}).get("message")
    suggested_reg = (payload or {}).get("suggested_reg_no")
    suggested_subject = (payload or {}).get("suggested_subject_code")

    if not message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Report message is required")

    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    # Security: only the owning student may report this artifact
    session_reg = _get_session_register_number(session)
    if artifact.parsed_reg_no != session_reg:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You may only report your own papers")

    # Log the report in audit logs so staff can view
    await audit_service.log_action(
        action="report_issue",
        action_category="report",
        actor_type="student",
        actor_id=str(session.moodle_user_id),
        actor_username=session.moodle_username,
        artifact_id=artifact.id,
        description=message,
        request_data={
            "suggested_reg_no": suggested_reg,
            "suggested_subject_code": suggested_subject
        }
    )

    # Persist audit log
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {"success": True, "message": "Report submitted. Staff will review and take action."}


@router.get("/reports")
async def get_my_reports(
    session: StudentSession = Depends(get_student_session),
    db: AsyncSession = Depends(get_db)
):
    """
    Return reports submitted by the currently logged-in student, with resolved status.
    """
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session required")

    artifact_service = ArtifactService(db)

    from app.db.models import AuditLog

    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.actor_type == 'student',
            AuditLog.actor_id == str(session.moodle_user_id),
            AuditLog.action == 'report_issue'
        )
        .order_by(AuditLog.created_at.desc())
    )

    reports = result.scalars().all()
    out = []

    for r in reports:
        artifact = await artifact_service.get_by_id(r.artifact_id) if r.artifact_id else None
        # Skip reports that have been deleted (student withdrew) - check audit logs
        deleted_q = await db.execute(
            select(AuditLog).where(AuditLog.action == 'report_deleted', AuditLog.target_id == str(r.id)).order_by(AuditLog.created_at.desc())
        )
        deleted_entry = deleted_q.scalars().first()
        if deleted_entry:
            # skip this report (it was deleted/withdrawn)
            continue

        resolved_q = await db.execute(
            select(AuditLog).where(AuditLog.action == 'report_resolved', AuditLog.target_id == str(r.id)).order_by(AuditLog.created_at.desc())
        )
        # use scalars().first() to tolerate multiple resolution entries and pick latest
        resolved = resolved_q.scalars().first()

        resolved_note = None
        if resolved:
            rd = resolved.request_data or {}
            resolved_note = rd.get('note') or (resolved.response_data and resolved.response_data.get('note'))

        out.append({
            "id": r.id,
            "artifact_id": r.artifact_id,
            "artifact_uuid": str(artifact.artifact_uuid) if artifact else None,
            "description": r.description,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "resolved": bool(bool(resolved)),
            "resolved_by": resolved.actor_username if resolved and resolved.actor_username else (resolved.actor_id if resolved else None),
            "resolved_at": resolved.created_at.isoformat() if resolved and resolved.created_at else None,
            "resolved_note": resolved_note
        })

    return out


@router.delete("/reports/{report_id}")
async def delete_my_report(
    report_id: int,
    session: StudentSession = Depends(get_student_session),
    db: AsyncSession = Depends(get_db)
):
    """
    Allow a student to delete (withdraw) a previously submitted report.
    This creates an audit entry `report_deleted` and leaves original report for traceability.
    """
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session required")

    from app.db.models import AuditLog

    # Verify the report exists and belongs to this student
    q = await db.execute(
        select(AuditLog).where(
            AuditLog.id == int(report_id),
            AuditLog.actor_type == 'student',
            AuditLog.actor_id == str(session.moodle_user_id),
            AuditLog.action == 'report_issue'
        )
    )
    rpt = q.scalar_one_or_none()
    if not rpt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found or not owned by you")

    # Use AuditService to create a proper audit entry (ensures action_category is set)
    audit_service = AuditService(db)
    try:
        await audit_service.log_action(
            action='report_deleted',
            action_category='report',
            actor_type='student',
            actor_id=str(session.moodle_user_id),
            actor_username=session.moodle_username,
            artifact_id=rpt.artifact_id,
            target_type='audit_log',
            target_id=str(report_id),
            description='Student withdrew their report'
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete report: {e}")

    return {"success": True, "message": "Report deleted"}


@router.post("/submit/{artifact_uuid}", response_model=SubmissionResponse)
async def submit_paper_by_uuid(
    artifact_uuid: str,
    request: Request,
    session: StudentSession = Depends(get_student_session),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit a paper to Moodle by artifact UUID (simplified endpoint)
    """
    import re
    
    # Use register number from session (provided during login)
    register_number = session.register_number  # Primary: use stored register number
    if not register_number:
        # Fallback: try to extract from fullname
        if session.moodle_fullname:
            match = re.search(r'\b(\d{12})\b', session.moodle_fullname)
            if match:
                register_number = match.group(1)
        # Final fallback: use moodle username
        if not register_number:
            register_number = session.moodle_username
    
    logger.info(f"Submit attempt for {artifact_uuid} by register_number: {register_number}")
    
    # Get the decrypted Moodle token
    moodle_token = get_decrypted_token(session)
    
    # Create submission service
    submission_service = SubmissionService(db)
    
    # Execute submission
    success, message, result = await submission_service.submit_artifact(
        artifact_uuid=artifact_uuid,
        moodle_token=moodle_token,
        moodle_user_id=session.moodle_user_id,
        moodle_username=session.moodle_username,
        register_number=register_number,
        actor_ip=request.client.host if request.client else None,
        lock_submission=True
    )
    
    await db.commit()
    
    if not success:
        if result and result.get("queued"):
            return SubmissionResponse(
                success=False,
                message=message,
                artifact_uuid=artifact_uuid,
                workflow_status=WorkflowStatusEnum.QUEUED
            )
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )
    
    # Get updated artifact for response
    artifact_service = ArtifactService(db)
    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    
    return SubmissionResponse(
        success=True,
        message=message,
        artifact_uuid=artifact_uuid,
        workflow_status=WorkflowStatusEnum(artifact.workflow_status.value),
        moodle_submission_id=artifact.moodle_submission_id,
        submitted_at=artifact.submit_timestamp
    )


@router.post("/submit", response_model=SubmissionResponse)
async def submit_paper(
    submission: SubmissionRequest,
    request: Request,
    session: StudentSession = Depends(get_student_session),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit a paper to Moodle
    
    This is the main submission endpoint that:
    1. Validates the student owns the paper
    2. Uploads the file to Moodle draft area
    3. Links the file to the assignment
    4. Finalizes the submission
    
    The submission is atomic - if any step fails, the operation can be retried.
    """
    import re
    
    if not submission.confirm_submission:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must confirm the submission"
        )
    
    # Use register number from session (provided during login)
    register_number = session.register_number  # Primary: use stored register number
    if not register_number:
        # Fallback: try to extract from fullname
        if session.moodle_fullname:
            match = re.search(r'\b(\d{12})\b', session.moodle_fullname)
            if match:
                register_number = match.group(1)
        # Final fallback: use moodle username
        if not register_number:
            register_number = session.moodle_username
    
    logger.info(f"Submit request for {submission.artifact_uuid} by register_number: {register_number}")
    
    # Get the decrypted Moodle token
    moodle_token = get_decrypted_token(session)
    
    # Create submission service
    submission_service = SubmissionService(db)
    
    # Execute submission
    success, message, result = await submission_service.submit_artifact(
        artifact_uuid=submission.artifact_uuid,
        moodle_token=moodle_token,
        moodle_user_id=session.moodle_user_id,
        moodle_username=session.moodle_username,
        register_number=register_number,
        actor_ip=request.client.host if request.client else None,
        lock_submission=True
    )
    
    await db.commit()
    
    if not success:
        # Check if it was queued
        if result and result.get("queued"):
            return SubmissionResponse(
                success=False,
                message=message,
                artifact_uuid=submission.artifact_uuid,
                workflow_status=WorkflowStatusEnum.QUEUED
            )
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )
    
    # Get updated artifact for response
    artifact_service = ArtifactService(db)
    artifact = await artifact_service.get_by_uuid(submission.artifact_uuid)
    
    return SubmissionResponse(
        success=True,
        message=message,
        artifact_uuid=submission.artifact_uuid,
        workflow_status=WorkflowStatusEnum(artifact.workflow_status.value),
        moodle_submission_id=artifact.moodle_submission_id,
        submitted_at=artifact.submit_timestamp
    )


@router.get("/submission/{artifact_uuid}/status")
async def get_submission_status(
    artifact_uuid: str,
    session: StudentSession = Depends(get_student_session),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the status of a submission
    """
    artifact_service = ArtifactService(db)
    artifact = await artifact_service.get_by_uuid(artifact_uuid)
    
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper not found"
        )
    
    # Security check
    session_reg_no = _get_session_register_number(session)
    if artifact.parsed_reg_no != session_reg_no:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own submissions"
        )
    
    return {
        "artifact_uuid": str(artifact.artifact_uuid),
        "status": artifact.workflow_status.value,
        "moodle_submission_id": artifact.moodle_submission_id,
        "submitted_at": artifact.submit_timestamp.isoformat() if artifact.submit_timestamp else None,
        "error_message": artifact.error_message,
        "retry_count": artifact.retry_count
    }


@router.get("/history")
async def get_submission_history(
    limit: int = Query(default=20, le=100),
    session: StudentSession = Depends(get_student_session),
    db: AsyncSession = Depends(get_db)
):
    """
    Get submission history for the student
    """
    artifact_service = ArtifactService(db)
    
    # Get all artifacts for this student (use Moodle identity for history view)
    pending = await artifact_service.get_pending_for_student(
        register_number=None,
        moodle_user_id=session.moodle_user_id,
        moodle_username=session.moodle_username
    )

    submitted = await artifact_service.get_submitted_for_student(
        register_number=session.moodle_username
    )
    
    history = []
    
    for a in pending + submitted:
        subject_code, exam_session = split_subject_session_key(a.parsed_subject_code)
        submission = None
        if settings.mock_lms_enabled:
            submission = mock_lms_service.get_submission_by_artifact(
                artifact_uuid=str(a.artifact_uuid),
                exam_session=exam_session,
            )
        history.append({
            "artifact_uuid": str(a.artifact_uuid),
            "filename": a.original_filename,
            "subject_code": subject_code,
            "exam_session": exam_session,
            "status": a.workflow_status.value,
            "grading_status": submission.get("grading_status") if submission else None,
            "grade": submission.get("grade") if submission else None,
            "grade_max": submission.get("grade_max") if submission else None,
            "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None,
            "submitted_at": a.submit_timestamp.isoformat() if a.submit_timestamp else None
        })
    
    # Sort by upload date, newest first
    history.sort(key=lambda x: x["uploaded_at"] or "", reverse=True)
    
    return {
        "total": len(history),
        "history": history[:limit]
    }
