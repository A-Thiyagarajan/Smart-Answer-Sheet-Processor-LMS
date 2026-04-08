"""
Local mock Moodle/LMS service used for end-to-end demos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from app.core.config import settings


class MockLMSService:
    def __init__(self) -> None:
        self.store_path = settings.storage_dir_path / "mock_lms_store.json"
        self.default_users = [
            {
                "userid": 22008681,
                "username": "22008681",
                "password": "8681",
                "register_number": "212222240110",
                "fullname": "THIYAGARAJAN",
                "role": "student",
            },
            {
                "userid": 22007928,
                "username": "22007928",
                "password": "7928",
                "register_number": "212222240047",
                "fullname": "Kavinraja D",
                "role": "student",
            },
            {
                "userid": 9001001,
                "username": "faculty",
                "password": "1234",
                "register_number": "FACULTY",
                "fullname": "Saveetha",
                "role": "faculty",
            },
        ]
        self.course_defs = [
            {
                "course_code": "19AI404",
                "course_name": "Digital Image Processing Techniques",
                "course_short_name": "19AI404",
                "course_id": 404,
                "assignment_id": 4041,
                "assignment_name": "CIA Exam",
                "category": "23-24 EVEN",
                "teacher": "Dr. R. Nivedha",
                "progress": 72,
                "summary": "Modules, notes, announcements and CIA submission workflow.",
                "theme": "blue-grid",
            },
            {
                "course_code": "19AI405",
                "course_name": "Web Server Programming",
                "course_short_name": "19AI405",
                "course_id": 405,
                "assignment_id": 4051,
                "assignment_name": "CIA Exam",
                "category": "23-24 EVEN",
                "teacher": "Dr. M. Priya",
                "teacher_username": "faculty_ai",
                "progress": 18,
                "summary": "CIA answer sheet submissions, topic resources and updates.",
                "theme": "blue-tiles",
            },
            {
                "course_code": "19AI411",
                "course_name": "Natural Language Processing",
                "course_short_name": "19AI411",
                "course_id": 411,
                "assignment_id": 4111,
                "assignment_name": "CIA Exam",
                "category": "AIML",
                "teacher": "Dr. S. Harini",
                "teacher_username": "faculty_ai",
                "progress": 3,
                "summary": "Weekly materials, CIA workflow and discussion updates.",
                "theme": "purple-rings",
            },
            {
                "course_code": "19AI505",
                "course_name": "19AI512C - MERN Full Stack",
                "course_short_name": "19AI505",
                "course_id": 505,
                "assignment_id": 5051,
                "assignment_name": "CIA Exam",
                "category": "Projects",
                "teacher": "Prof. V. Arun Kumar",
                "teacher_username": "faculty_ai",
                "progress": 100,
                "summary": "Project reviews, final uploads and grading milestones.",
                "theme": "grey-facets",
            },
        ]
        self.announcements = [
            {
                "title": "CIA submission window is open",
                "body": "Students can now verify scanned answer sheets and push them to the LMS from the student portal.",
            },
            {
                "title": "Subject mappings updated",
                "body": "Recent mapping updates ensure papers appear under the correct CIA Exam assignment for each course.",
            },
        ]

    def _ensure_store(self) -> Dict[str, Any]:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            initial = {
                "users": [
                    *self.default_users
                ],
                "courses": self.course_defs,
                "submissions": [],
            }
            self._write_store(initial)
            return initial
        data = self._read_store()
        changed = False
        users_by_username = {user.get("username"): user for user in data.get("users", [])}
        for user in self.default_users:
            existing = users_by_username.get(user["username"])
            if existing:
                for key, value in user.items():
                    if existing.get(key) != value:
                        existing[key] = value
                        changed = True
            else:
                data.setdefault("users", []).append(user)
                changed = True
        normalized_submissions = []
        for submission in data.get("submissions", []):
            merged = {
                "status": "submitted",
                "grading_status": "notgraded",
                "grade": None,
                "grade_max": 100,
                "graded_on": None,
                "graded_by": None,
                "feedback_pdf": None,
                "submission_comments": 0,
                **submission,
            }
            normalized_submissions.append(merged)
            if merged != submission:
                changed = True
        data["submissions"] = normalized_submissions
        if changed:
            self._write_store(data)
        return data

    def _read_store(self) -> Dict[str, Any]:
        return json.loads(self.store_path.read_text(encoding="utf-8"))

    def _write_store(self, data: Dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _course_defaults(self) -> Dict[str, Dict[str, Any]]:
        return {course["course_code"]: course for course in self.course_defs}

    def _normalize_course(self, course: Dict[str, Any]) -> Dict[str, Any]:
        defaults = self._course_defaults().get(course.get("course_code", ""), {})
        merged = {**defaults, **course}
        merged.setdefault("course_short_name", merged.get("course_code", "COURSE"))
        merged.setdefault("course_name", merged.get("course_short_name", "Course"))
        merged.setdefault("category", "Course")
        merged.setdefault("teacher", "Faculty")
        merged.setdefault("progress", 0)
        merged.setdefault("summary", "Course page")
        merged.setdefault("theme", "blue-grid")
        merged.setdefault("assignment_name", "CIA Exam")
        merged.setdefault("teacher_username", "faculty_ai")
        return merged

    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        store = self._ensure_store()
        for user in store["users"]:
            if user["username"] == username and user["password"] == password:
                return user
        return None

    def build_token(self, user: Dict[str, Any]) -> str:
        return f"mock-lms-token::{user['username']}"

    def get_user_from_token(self, token: str) -> Optional[Dict[str, Any]]:
        if not token or not token.startswith("mock-lms-token::"):
            return None
        username = token.split("::", 1)[1]
        store = self._ensure_store()
        for user in store["users"]:
            if user["username"] == username:
                return user
        return None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        store = self._ensure_store()
        for user in store["users"]:
            if user["username"] == username:
                return user
        return None

    def get_site_info(self, token: str) -> Optional[Dict[str, Any]]:
        user = self.get_user_from_token(token)
        if not user:
            return None
        return {
            "userid": user["userid"],
            "username": user["username"],
            "fullname": f"{user['fullname']} ({user['register_number']})",
            "sitename": "Local Mock Moodle LMS",
            "role": user.get("role", "student"),
        }

    def get_courses(self) -> List[Dict[str, Any]]:
        store = self._ensure_store()
        return [self._normalize_course(course) for course in store["courses"]]

    def get_course(self, course_code: str) -> Optional[Dict[str, Any]]:
        return next((c for c in self.get_courses() if c["course_code"] == course_code), None)

    def get_course_by_assignment(self, assignment_id: int) -> Optional[Dict[str, Any]]:
        return next((c for c in self.get_courses() if c["assignment_id"] == assignment_id), None)

    def get_announcements(self) -> List[Dict[str, Any]]:
        return list(self.announcements)

    def get_online_user_count(self) -> int:
        store = self._ensure_store()
        return max(36, len(store["users"]) * 12)

    def submit_artifact(
        self,
        assignment_id: int,
        artifact_uuid: str,
        filename: str,
        subject_code: str,
        exam_session: str,
        student_username: str,
        register_number: str,
    ) -> Dict[str, Any]:
        store = self._ensure_store()
        course = self.get_course_by_assignment(assignment_id)
        if not course:
            raise ValueError(f"No mock course mapped for assignment {assignment_id}")

        submission_id = len(store["submissions"]) + 1
        created_at = datetime.now(timezone.utc).isoformat()
        submission = {
            "submission_id": str(submission_id),
            "artifact_uuid": artifact_uuid,
            "filename": filename,
            "subject_code": subject_code,
            "exam_session": exam_session,
            "course_code": course["course_code"],
            "course_name": course["course_name"],
            "assignment_id": assignment_id,
            "assignment_name": course["assignment_name"],
            "student_username": student_username,
            "register_number": register_number,
            "created_at": created_at,
            "status": "submitted",
            "grading_status": "notgraded",
            "grade": None,
            "grade_max": 100,
            "graded_on": None,
            "graded_by": None,
            "feedback_pdf": None,
            "submission_comments": 0,
        }
        store["submissions"].append(submission)
        self._write_store(store)
        return submission

    def get_submissions_for_course(self, course_code: str, exam_session: Optional[str] = None) -> List[Dict[str, Any]]:
        store = self._ensure_store()
        submissions = [s for s in store["submissions"] if s["course_code"] == course_code]
        if exam_session:
            submissions = [s for s in submissions if s.get("exam_session") == exam_session]
        return submissions

    def get_submission(self, submission_id: str) -> Optional[Dict[str, Any]]:
        store = self._ensure_store()
        return next((s for s in store["submissions"] if str(s.get("submission_id")) == str(submission_id)), None)

    def get_submission_by_artifact(self, artifact_uuid: str, exam_session: Optional[str] = None) -> Optional[Dict[str, Any]]:
        submissions = self._ensure_store().get("submissions", [])
        matches = [s for s in submissions if s.get("artifact_uuid") == artifact_uuid]
        if exam_session:
            matches = [s for s in matches if s.get("exam_session") == exam_session]
        return matches[-1] if matches else None

    def grade_submission(
        self,
        submission_id: str,
        grade: float,
        grade_max: float,
        graded_by: str,
        feedback_pdf: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        store = self._ensure_store()
        target = next((s for s in store["submissions"] if str(s.get("submission_id")) == str(submission_id)), None)
        if not target:
            return None
        target["grading_status"] = "graded"
        target["grade"] = grade
        target["grade_max"] = grade_max
        target["graded_on"] = datetime.now(timezone.utc).isoformat()
        target["graded_by"] = graded_by
        target["feedback_pdf"] = feedback_pdf or f"feedback_{target['filename']}"
        self._write_store(store)
        return target

    def remove_grade(self, submission_id: str) -> Optional[Dict[str, Any]]:
        store = self._ensure_store()
        target = next((s for s in store["submissions"] if str(s.get("submission_id")) == str(submission_id)), None)
        if not target:
            return None
        target["grading_status"] = "notgraded"
        target["grade"] = None
        target["graded_on"] = None
        target["graded_by"] = None
        target["feedback_pdf"] = None
        self._write_store(store)
        return target

    def delete_submission(self, course_code: str, submission_id: str) -> bool:
        store = self._ensure_store()
        original_count = len(store["submissions"])
        store["submissions"] = [
            submission
            for submission in store["submissions"]
            if not (
                submission["course_code"] == course_code
                and str(submission["submission_id"]) == str(submission_id)
            )
        ]
        deleted = len(store["submissions"]) != original_count
        if deleted:
            self._write_store(store)
        return deleted


mock_lms_service = MockLMSService()
