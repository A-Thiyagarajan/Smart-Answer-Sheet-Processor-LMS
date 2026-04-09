"""
Artifact Service
Business logic for managing examination artifacts
"""

import logging
import uuid
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    ExaminationArtifact,
    SubjectMapping,
    AuditLog,
    SubmissionQueue,
    WorkflowStatus
)
from app.schemas import (
    ArtifactCreate,
    ArtifactResponse,
    StudentPendingPaper,
    StudentDashboardResponse,
)
from app.core.security import generate_transaction_id
from app.core.config import settings

logger = logging.getLogger(__name__)

CIA_SESSION_VALUES = {"CIA-I", "CIA-II", "CIA-III"}


def normalize_exam_session(value: Optional[str]) -> str:
    """Normalize user-provided CIA labels to a stable internal form."""
    raw = (value or "").strip().upper().replace("_", "-").replace(" ", "")
    mapping = {
        "CIA1": "CIA-I",
        "CIA-I": "CIA-I",
        "CIAI": "CIA-I",
        "CIA2": "CIA-II",
        "CIA-II": "CIA-II",
        "CIAII": "CIA-II",
        "CIA3": "CIA-III",
        "CIA-III": "CIA-III",
        "CIAIII": "CIA-III",
    }
    return mapping.get(raw, "CIA-I")


def compose_subject_session_key(subject_code: Optional[str], exam_session: Optional[str]) -> Optional[str]:
    if not subject_code:
        return subject_code
    session = normalize_exam_session(exam_session)
    return f"{subject_code.upper()}__{session}"


def split_subject_session_key(value: Optional[str]) -> tuple[Optional[str], str]:
    if not value:
        return value, "CIA-I"
    text = str(value)
    if "__" in text:
        subject_code, exam_session = text.split("__", 1)
        return subject_code, normalize_exam_session(exam_session)
    return text, "CIA-I"


class ArtifactService:
    """
    Service for managing examination artifacts
    Implements the business logic from the design document
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_artifact(
        self,
        raw_filename: str,
        original_filename: str,
        file_blob_path: str,
        file_hash: str,
        parsed_reg_no: Optional[str] = None,
        parsed_subject_code: Optional[str] = None,
        exam_session: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        mime_type: Optional[str] = None,
        uploaded_by_staff_id: Optional[int] = None,
        allow_existing_hash: bool = False,
    ) -> ExaminationArtifact:
        """
        Create a new examination artifact
        
        Args:
            raw_filename: Original uploaded filename
            original_filename: Sanitized filename
            file_blob_path: Path to stored file
            file_hash: SHA-256 hash of file content
            parsed_reg_no: Extracted register number
            parsed_subject_code: Extracted subject code
            file_size_bytes: File size
            mime_type: MIME type
            uploaded_by_staff_id: Staff user who uploaded
            
        Returns:
            Created ExaminationArtifact
        """
        normalized_exam_session = normalize_exam_session(exam_session)
        stored_subject_code = compose_subject_session_key(parsed_subject_code, normalized_exam_session)
        
        # Reject same-content uploads only when the exact register + subject + CIA tuple matches.
        # Different students may legitimately upload files that hash the same.
        existing_same_hash = None if allow_existing_hash else await self.get_active_by_file_hash(file_hash)
        if existing_same_hash:
            existing_subject_code, existing_exam_session = split_subject_session_key(existing_same_hash.parsed_subject_code)
            same_register = bool(parsed_reg_no) and existing_same_hash.parsed_reg_no == parsed_reg_no
            same_subject_session = bool(stored_subject_code) and existing_same_hash.parsed_subject_code == stored_subject_code
            if same_register and same_subject_session:
                raise Exception(
                    "This file has already been uploaded for the same register, subject, and CIA "
                    f"(register={existing_same_hash.parsed_reg_no or 'unknown'}, "
                    f"subject={existing_subject_code or 'unknown'}, "
                    f"session={existing_exam_session})."
                )
            logger.info(
                "Allowing same-hash upload for different tuple: existing(reg=%s, subject=%s, session=%s) incoming(reg=%s, subject=%s, session=%s)",
                existing_same_hash.parsed_reg_no,
                existing_subject_code,
                existing_exam_session,
                parsed_reg_no,
                parsed_subject_code,
                normalized_exam_session,
            )

        # Generate transaction ID for idempotency
        transaction_id = None
        if parsed_reg_no and parsed_subject_code:
            transaction_id = generate_transaction_id(
                parsed_reg_no,
                f"{parsed_subject_code}_{normalized_exam_session}",
                datetime.now(timezone.utc).strftime("%Y%m")
            )
            
            # Check for existing artifact with same transaction ID
            existing = await self.get_by_transaction_id(transaction_id)
            if existing:
                # If the existing artifact has different parsed metadata, it may be
                # a stale/deleted row that still holds the transaction id. If so,
                # clear its transaction id and allow creation to proceed. Otherwise
                # refuse to overwrite an unrelated artifact.
                if (existing.parsed_reg_no != parsed_reg_no) or (existing.parsed_subject_code != stored_subject_code):
                    if getattr(existing, 'workflow_status', None) == WorkflowStatus.DELETED:
                        logger.info("Clearing stale transaction_id on DELETED artifact id=%s to allow new upload", existing.id)
                        try:
                            existing.add_log_entry("cleared_stale_transaction_on_collision", {"reason": "allow_new_upload", "incoming_parsed": (parsed_reg_no, stored_subject_code)})
                        except Exception:
                            pass
                        existing.transaction_id = None
                        # Also clear parsed fields to fully free the unique tuple if present
                        existing.parsed_reg_no = None
                        existing.parsed_subject_code = None
                        await self.db.flush()
                        # continue to creation flow (do not return)
                    else:
                        logger.error(
                            "Transaction id collision but metadata mismatch: existing(%s,%s) vs incoming(%s,%s)",
                            existing.parsed_reg_no,
                            existing.parsed_subject_code,
                            parsed_reg_no,
                            parsed_subject_code
                        )
                        raise Exception(
                            f"Transaction ID conflict: an unrelated artifact already uses this transaction id. "
                            f"Please verify the file metadata or contact an administrator."
                        )

                # If metadata matches, treat as re-upload for idempotency
                logger.warning(f"Duplicate artifact detected: {transaction_id}, updating with new file")
                existing.file_blob_path = file_blob_path.replace('\\', '/')  # Normalize path
                existing.file_hash = file_hash
                existing.file_size_bytes = file_size_bytes
                existing.workflow_status = WorkflowStatus.PENDING  # Reset to pending
                existing.error_message = None  # Clear any previous errors
                try:
                    existing.add_log_entry("re-uploaded", {
                        "new_file_path": file_blob_path,
                        "new_hash": file_hash
                    })
                except Exception:
                    pass
                await self.db.flush()
                await self.db.refresh(existing)
                return existing

        # Pre-check uniqueness of parsed_reg_no + parsed_subject_code to avoid DB constraint failure
        if parsed_reg_no and parsed_subject_code:
            result = await self.db.execute(
                select(ExaminationArtifact).where(
                    ExaminationArtifact.parsed_reg_no == parsed_reg_no,
                    ExaminationArtifact.parsed_subject_code == stored_subject_code
                )
            )
            existing_pair = result.scalar_one_or_none()
            if existing_pair:
                # If it's the same transaction id, update as a re-upload
                if existing_pair.transaction_id and transaction_id and existing_pair.transaction_id == transaction_id:
                    logger.warning(f"Duplicate artifact detected by transaction id: {transaction_id}, updating with new file")
                    # Use the provided file_blob_path (normalized) for re-uploads
                    existing_pair.file_blob_path = (file_blob_path or '').replace('\\', '/')
                    existing_pair.file_hash = file_hash
                    existing_pair.file_size_bytes = file_size_bytes
                    existing_pair.workflow_status = WorkflowStatus.PENDING
                    existing_pair.error_message = None
                    try:
                        existing_pair.add_log_entry("re-uploaded", {"new_file_path": file_blob_path, "new_hash": file_hash})
                    except Exception:
                        # Don't let logging failures break the re-upload flow
                        pass
                    await self.db.flush()
                    await self.db.refresh(existing_pair)
                    return existing_pair

                # If the conflicting artifact is deleted, clear its identifiers so we can reuse the pair
                if getattr(existing_pair, 'workflow_status', None) == WorkflowStatus.DELETED:
                    existing_pair.add_log_entry("cleared_identifiers_for_reuse", {
                        "reason": "upload_reuse",
                    })
                    existing_pair.parsed_reg_no = None
                    existing_pair.parsed_subject_code = None
                    existing_pair.transaction_id = None
                    await self.db.flush()
                else:
                    # Prevent accidental duplicate uploads
                    raise Exception(f"An artifact for register {parsed_reg_no} and subject {parsed_subject_code} already exists (id={existing_pair.id}).")
        
        artifact = ExaminationArtifact(
            raw_filename=raw_filename,
            original_filename=original_filename,
            file_blob_path=file_blob_path,
            file_hash=file_hash,
            parsed_reg_no=parsed_reg_no,
            parsed_subject_code=stored_subject_code,
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            uploaded_by_staff_id=uploaded_by_staff_id,
            transaction_id=transaction_id,
            workflow_status=WorkflowStatus.PENDING if parsed_reg_no else WorkflowStatus.FAILED
        )
        
        # Add initial log entry
        artifact.add_log_entry("created", {
            "filename": raw_filename,
            "parsed_reg_no": parsed_reg_no,
            "parsed_subject_code": stored_subject_code,
            "exam_session": normalized_exam_session,
        })
        
        self.db.add(artifact)
        try:
            await self.db.flush()
        except IntegrityError as e:
            # Handle potential race-condition unique constraint violation explicitly
            try:
                await self.db.rollback()
            except Exception:
                pass
            logger.exception("IntegrityError flushing new artifact - likely duplicate")
            raise
        except Exception as e:
            # Unexpected error - rollback and re-raise
            try:
                await self.db.rollback()
            except Exception:
                pass
            logger.exception("Failed to flush new artifact - unexpected error")
            raise

        await self.db.refresh(artifact)
        
        logger.info(f"Created artifact: {artifact.artifact_uuid}")
        return artifact

    async def get_active_by_file_hash(self, file_hash: str) -> Optional[ExaminationArtifact]:
        """Return an active artifact with the same file hash, if any."""
        result = await self.db.execute(
            select(ExaminationArtifact).where(
                and_(
                    ExaminationArtifact.file_hash == file_hash,
                    ExaminationArtifact.workflow_status != WorkflowStatus.DELETED,
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def get_by_uuid(self, artifact_uuid: str) -> Optional[ExaminationArtifact]:
        """Get artifact by UUID"""
        try:
            normalized_uuid = uuid.UUID(str(artifact_uuid))
        except (ValueError, TypeError, AttributeError):
            return None

        result = await self.db.execute(
            select(ExaminationArtifact)
            .where(ExaminationArtifact.artifact_uuid == normalized_uuid)
        )
        return result.scalar_one_or_none()
    
    async def get_by_transaction_id(self, transaction_id: str) -> Optional[ExaminationArtifact]:
        """Get artifact by transaction ID (for idempotency)"""
        result = await self.db.execute(
            select(ExaminationArtifact)
            .where(ExaminationArtifact.transaction_id == transaction_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_id(self, artifact_id: int) -> Optional[ExaminationArtifact]:
        """Get artifact by ID"""
        result = await self.db.execute(
            select(ExaminationArtifact)
            .where(ExaminationArtifact.id == artifact_id)
        )
        return result.scalar_one_or_none()
    
    async def get_pending_for_student(
        self,
        register_number: Optional[str],
        moodle_user_id: Optional[int],
        moodle_username: Optional[str] = None
    ) -> List[ExaminationArtifact]:
        """
        Get pending artifacts for a specific student.

        Security: Strictly return artifacts that either:
          - match the student's university `parsed_reg_no` (only when a valid 12-digit register is provided), OR
          - are already linked to the student's Moodle account (both `moodle_username` and `moodle_user_id` must match).

        This avoids the previous ambiguous behaviour where a single `register_number` string
        could be treated as either a register or a Moodle username.
        """
        from sqlalchemy import or_, and_

        # Allowed workflow states for pending dashboard
        allowed_states = [
            WorkflowStatus.PENDING,
            WorkflowStatus.PENDING_REVIEW,
            WorkflowStatus.VALIDATED,
            WorkflowStatus.READY_FOR_REVIEW,
        ]

        # Build identity conditions conservatively
        identity_conditions = []

        if register_number:
            # Only treat as a register number match; callers should pass a 12-digit register_number when available
            identity_conditions.append(ExaminationArtifact.parsed_reg_no == register_number)

        if moodle_user_id is not None and moodle_username:
            # Require both moodle_user_id and moodle_username to match to avoid accidental matches
            identity_conditions.append(and_(
                ExaminationArtifact.moodle_user_id == moodle_user_id,
                ExaminationArtifact.moodle_username == moodle_username
            ))

        if not identity_conditions:
            # No valid identity information supplied — return empty list to be safe
            return []

        stmt = (
            select(ExaminationArtifact)
            .where(
                and_(
                    or_(*identity_conditions),
                    ExaminationArtifact.workflow_status.in_(allowed_states)
                )
            )
            .order_by(ExaminationArtifact.uploaded_at.desc())
        )

        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_submitted_for_student(
        self,
        register_number: str
    ) -> List[ExaminationArtifact]:
        """Get submitted artifacts for a student"""
        result = await self.db.execute(
            select(ExaminationArtifact)
            .where(
                and_(
                    ExaminationArtifact.parsed_reg_no == register_number,
                    ExaminationArtifact.workflow_status.in_([
                        WorkflowStatus.SUBMITTED_TO_LMS,
                        WorkflowStatus.COMPLETED
                    ])
                )
            )
            .order_by(ExaminationArtifact.submit_timestamp.desc())
        )
        return list(result.scalars().all())
    
    async def update_status(
        self,
        artifact_id: int,
        status: WorkflowStatus,
        log_action: Optional[str] = None,
        log_details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> Optional[ExaminationArtifact]:
        """Update artifact workflow status"""
        artifact = await self.get_by_id(artifact_id)
        if not artifact:
            return None
        
        old_status = artifact.workflow_status
        artifact.workflow_status = status
        
        if error_message:
            artifact.error_message = error_message
        
        if log_action:
            artifact.add_log_entry(log_action, {
                "old_status": old_status.value if old_status else None,
                "new_status": status.value,
                **(log_details or {})
            })
        
        await self.db.flush()
        await self.db.refresh(artifact)
        
        logger.info(f"Updated artifact {artifact_id} status: {old_status} -> {status}")
        return artifact
    
    async def resolve_moodle_mapping(
        self,
        artifact_id: int,
        moodle_user_id: int,
        moodle_username: str,
        moodle_assignment_id: int,
        moodle_course_id: Optional[int] = None
    ) -> Optional[ExaminationArtifact]:
        """
        Resolve Moodle mapping for an artifact
        
        This is called after student authentication to link
        the artifact to their Moodle user and the correct assignment
        """
        artifact = await self.get_by_id(artifact_id)
        if not artifact:
            return None
        
        artifact.moodle_user_id = moodle_user_id
        artifact.moodle_username = moodle_username
        artifact.moodle_assignment_id = moodle_assignment_id
        artifact.moodle_course_id = moodle_course_id
        artifact.validated_at = datetime.now(timezone.utc)
        
        if artifact.workflow_status == WorkflowStatus.PENDING:
            artifact.workflow_status = WorkflowStatus.READY_FOR_REVIEW
        
        artifact.add_log_entry("moodle_resolved", {
            "moodle_user_id": moodle_user_id,
            "moodle_assignment_id": moodle_assignment_id
        })
        
        await self.db.flush()
        await self.db.refresh(artifact)
        
        return artifact
    
    async def mark_submitting(
        self,
        artifact_id: int,
        moodle_draft_item_id: int
    ) -> Optional[ExaminationArtifact]:
        """Mark artifact as currently being submitted (for retry logic)"""
        artifact = await self.get_by_id(artifact_id)
        if not artifact:
            return None
        
        artifact.workflow_status = WorkflowStatus.UPLOADING
        artifact.moodle_draft_item_id = moodle_draft_item_id
        
        artifact.add_log_entry("upload_started", {
            "draft_item_id": moodle_draft_item_id
        })
        
        await self.db.flush()
        await self.db.refresh(artifact)
        # Persist immediately so other requests see the uploading state
        try:
            await self.db.commit()
        except IntegrityError as e:
            try:
                await self.db.rollback()
            except Exception:
                pass
            logger.exception("IntegrityError during mark_submitting commit")
            raise
        except Exception:
            await self.db.rollback()
            raise
        return artifact
    
    async def mark_submitted(
        self,
        artifact_id: int,
        moodle_submission_id: Optional[str] = None,
        lms_transaction_id: Optional[str] = None
    ) -> Optional[ExaminationArtifact]:
        """Mark artifact as successfully submitted to Moodle"""
        artifact = await self.get_by_id(artifact_id)
        if not artifact:
            return None
        
        artifact.workflow_status = WorkflowStatus.COMPLETED
        # Use timezone-aware UTC timestamps
        now = datetime.now(timezone.utc)
        artifact.submit_timestamp = now
        artifact.completed_at = now
        # Ensure moodle_submission_id is a string (database column is VARCHAR)
        artifact.moodle_submission_id = str(moodle_submission_id) if moodle_submission_id is not None else None
        artifact.lms_transaction_id = lms_transaction_id
        
        artifact.add_log_entry("submission_completed", {
            "moodle_submission_id": moodle_submission_id,
            "lms_transaction_id": lms_transaction_id
        })
        
        await self.db.flush()
        await self.db.refresh(artifact)
        # Persist immediately so submission time is stored
        try:
            await self.db.commit()
        except IntegrityError as e:
            try:
                await self.db.rollback()
            except Exception:
                pass
            logger.exception("IntegrityError during mark_submitted commit")
            raise
        except Exception:
            await self.db.rollback()
            raise

        logger.info(f"Artifact {artifact_id} marked as submitted")
        return artifact
    
    
    async def mark_failed(
        self,
        artifact_id: int,
        error_message: str,
        queue_for_retry: bool = False
    ) -> Optional[ExaminationArtifact]:
        """Mark artifact as failed"""
        artifact = await self.get_by_id(artifact_id)
        if not artifact:
            return None
        
        artifact.workflow_status = WorkflowStatus.QUEUED if queue_for_retry else WorkflowStatus.FAILED
        artifact.error_message = error_message
        artifact.retry_count = (artifact.retry_count or 0) + 1
        
        artifact.add_log_entry("submission_failed", {
            "error": error_message,
            "retry_count": artifact.retry_count,
            "queued": queue_for_retry
        })
        
        # Add to retry queue if needed
        if queue_for_retry:
            queue_item = SubmissionQueue(
                artifact_id=artifact_id,
                status="QUEUED",
                last_error=error_message
            )
            self.db.add(queue_item)
        
        await self.db.flush()
        await self.db.refresh(artifact)
        # Persist failure state immediately
        try:
            await self.db.commit()
        except IntegrityError as e:
            try:
                await self.db.rollback()
            except Exception:
                pass
            logger.exception("IntegrityError during mark_failed commit")
            raise
        except Exception:
            await self.db.rollback()
            raise

        return artifact
    
    async def get_all_pending(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[ExaminationArtifact], int]:
        """Get all pending artifacts (for admin view)"""
        # Get count
        count_result = await self.db.execute(
            select(ExaminationArtifact)
            .where(
                ExaminationArtifact.workflow_status.in_([
                    WorkflowStatus.PENDING,
                    WorkflowStatus.PENDING_REVIEW
                ])
            )
        )
        total = len(count_result.scalars().all())
        
        # Get paginated results
        result = await self.db.execute(
            select(ExaminationArtifact)
            .where(
                ExaminationArtifact.workflow_status.in_([
                    WorkflowStatus.PENDING,
                    WorkflowStatus.PENDING_REVIEW
                ])
            )
            .order_by(ExaminationArtifact.uploaded_at.desc())
            .limit(limit)
            .offset(offset)
        )
        
        return list(result.scalars().all()), total
    
    async def get_all_artifacts(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[ExaminationArtifact], int]:
        """Get all artifacts regardless of status (for admin view)"""
        # Get count
        count_result = await self.db.execute(
            select(ExaminationArtifact)
        )
        total = len(count_result.scalars().all())
        
        # Get paginated results
        result = await self.db.execute(
            select(ExaminationArtifact)
            .order_by(ExaminationArtifact.uploaded_at.desc())
            .limit(limit)
            .offset(offset)
        )
        
        return list(result.scalars().all()), total
    
    async def get_stats(self) -> Dict[str, int]:
        """Get artifact statistics"""
        stats = {}
        
        for status in WorkflowStatus:
            result = await self.db.execute(
                select(ExaminationArtifact)
                .where(ExaminationArtifact.workflow_status == status)
            )
            stats[status.value.lower()] = len(result.scalars().all())
        
        return stats

    async def delete_artifact_permanently(self, artifact: ExaminationArtifact) -> None:
        """Remove an artifact and its dependent rows from the database."""
        queue_rows = await self.db.execute(
            select(SubmissionQueue).where(SubmissionQueue.artifact_id == artifact.id)
        )
        for queue_item in queue_rows.scalars().all():
            await self.db.delete(queue_item)

        audit_rows = await self.db.execute(
            select(AuditLog).where(AuditLog.artifact_id == artifact.id)
        )
        for audit_log in audit_rows.scalars().all():
            await self.db.delete(audit_log)

        await self.db.delete(artifact)
        await self.db.flush()


class SubjectMappingService:
    """Service for managing subject to assignment mappings"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_mapping(self, subject_code: str) -> Optional[SubjectMapping]:
        """Get mapping for a subject code"""
        base_subject_code, _ = split_subject_session_key(subject_code)
        result = await self.db.execute(
            select(SubjectMapping)
            .where(
                and_(
                    SubjectMapping.subject_code == (base_subject_code or "").upper(),
                    SubjectMapping.is_active == True
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def get_assignment_id(self, subject_code: str) -> Optional[int]:
        """Get assignment ID for a subject code"""
        base_subject_code, _ = split_subject_session_key(subject_code)
        # First check database
        mapping = await self.get_mapping(base_subject_code or subject_code)
        if mapping:
            return mapping.moodle_assignment_id
        
        # Fall back to config
        config_mapping = settings.get_subject_assignment_mapping()
        return config_mapping.get((base_subject_code or subject_code).upper())
    
    async def create_mapping(
        self,
        subject_code: str,
        moodle_course_id: int,
        moodle_assignment_id: int,
        subject_name: Optional[str] = None,
        moodle_assignment_name: Optional[str] = None,
        exam_session: Optional[str] = None
    ) -> SubjectMapping:
        """Create a new subject mapping"""
        mapping = SubjectMapping(
            subject_code=subject_code.upper(),
            subject_name=subject_name,
            moodle_course_id=moodle_course_id,
            moodle_assignment_id=moodle_assignment_id,
            moodle_assignment_name=moodle_assignment_name,
            exam_session=exam_session,
            is_active=True
        )
        
        self.db.add(mapping)
        await self.db.flush()
        await self.db.refresh(mapping)
        
        return mapping
    
    async def get_all_active(self) -> List[SubjectMapping]:
        """Get all active mappings"""
        result = await self.db.execute(
            select(SubjectMapping)
            .where(SubjectMapping.is_active == True)
            .order_by(SubjectMapping.subject_code)
        )
        return list(result.scalars().all())
    
    async def sync_from_config(self) -> int:
        """Sync mappings from configuration"""
        config_mapping = settings.get_subject_assignment_mapping()
        created = 0
        
        for subject_code, assignment_id in config_mapping.items():
            existing = await self.get_mapping(subject_code)
            if not existing:
                await self.create_mapping(
                    subject_code=subject_code,
                    moodle_course_id=0,  # Will be resolved later
                    moodle_assignment_id=assignment_id
                )
                created += 1
        
        return created


class AuditService:
    """Service for audit logging"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def log_action(
        self,
        action: str,
        action_category: str,
        actor_type: str,
        actor_id: Optional[str] = None,
        actor_username: Optional[str] = None,
        actor_ip: Optional[str] = None,
        artifact_id: Optional[int] = None,
        description: Optional[str] = None,
        request_data: Optional[Dict[str, Any]] = None,
        response_data: Optional[Dict[str, Any]] = None,
        moodle_api_function: Optional[str] = None,
        moodle_response_code: Optional[int] = None
        ,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None
    ) -> AuditLog:
        """Create an audit log entry"""
        log = AuditLog(
            action=action,
            action_category=action_category,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_username=actor_username,
            actor_ip=actor_ip,
            artifact_id=artifact_id,
            description=description,
            request_data=request_data,
            response_data=response_data,
            moodle_api_function=moodle_api_function,
            moodle_response_code=moodle_response_code
            ,
            target_type=target_type,
            target_id=target_id
        )
        
        self.db.add(log)
        await self.db.flush()
        
        return log
    
    async def get_for_artifact(self, artifact_id: int) -> List[AuditLog]:
        """Get all audit logs for an artifact"""
        # Primary logs tied to the artifact
        res_primary = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.artifact_id == artifact_id)
            .order_by(AuditLog.created_at.desc())
        )
        primary_logs = list(res_primary.scalars().all())

        # Also include any 'report_deleted' logs that target report_issue audit ids
        # belonging to this artifact. Some older deletions may not have artifact_id
        # set, so we fetch them by matching target_id to the report_issue ids.
        issue_ids_q = await self.db.execute(
            select(AuditLog.id).where(AuditLog.action == 'report_issue', AuditLog.artifact_id == artifact_id)
        )
        issue_ids = [str(r[0]) for r in issue_ids_q.all()]

        deleted_logs = []
        if issue_ids:
            res_deleted = await self.db.execute(
                select(AuditLog).where(AuditLog.action == 'report_deleted', AuditLog.target_id.in_(issue_ids)).order_by(AuditLog.created_at.desc())
            )
            deleted_logs = list(res_deleted.scalars().all())

        # Merge and deduplicate (favor primary logs' ordering)
        combined = {str(l.id): l for l in primary_logs}
        for dl in deleted_logs:
            combined_key = str(dl.id)
            if combined_key not in combined:
                combined[combined_key] = dl

        # Return logs sorted by created_at desc
        return sorted(list(combined.values()), key=lambda x: x.created_at or 0, reverse=True)
    
    async def get_recent(self, limit: int = 100) -> List[AuditLog]:
        """Get recent audit logs"""
        result = await self.db.execute(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
