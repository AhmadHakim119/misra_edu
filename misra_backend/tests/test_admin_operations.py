from __future__ import annotations

import os
from unittest import TestCase

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ.setdefault("AUTH_SECRET", "test-auth-secret-that-is-longer-than-thirty-two-characters")
os.environ.setdefault("COOKIE_SECURE", "false")

from database import Base, get_db  # noqa: E402
import models  # noqa: E402,F401
from models import AuditLog, Institution, ProcessingJob, User  # noqa: E402
from routers.admin_operations import router as operations_router  # noqa: E402
from routers.auth import router as auth_router  # noqa: E402
from services.audit_service import record_audit_event, safe_error_message  # noqa: E402
from services.auth_service import hash_password  # noqa: E402


class AdminOperationsTests(TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        db = self.session_factory()
        db.add_all(
            [
                Institution(id="institution-a", name="University A"),
                Institution(id="institution-b", name="University B"),
                User(
                    id="admin-a",
                    institution_id="institution-a",
                    email="admin@example.edu",
                    hashed_password=hash_password("admin password 123"),
                    full_name="Account Admin",
                    role="admin",
                ),
                User(
                    id="teacher-a",
                    institution_id="institution-a",
                    email="teacher@example.edu",
                    hashed_password=hash_password("teacher password 123"),
                    full_name="Test Teacher",
                    role="teacher",
                ),
                User(
                    id="admin-b",
                    institution_id="institution-b",
                    email="other-admin@example.edu",
                    hashed_password=hash_password("other password 123"),
                    full_name="Other Admin",
                    role="admin",
                ),
            ]
        )
        db.flush()
        record_audit_event(
            db,
            institution_id="institution-a",
            actor_id="teacher-a",
            action="paper_uploaded",
            entity_type="submission",
            entity_id="submission-a",
            details={"page_count": 3, "password": "must-not-appear"},
        )
        record_audit_event(
            db,
            institution_id="institution-b",
            actor_id="admin-b",
            action="paper_uploaded",
            entity_type="submission",
            entity_id="submission-b",
        )
        db.add_all(
            [
                ProcessingJob(
                    id="job-a",
                    institution_id="institution-a",
                    requested_by="teacher-a",
                    job_type="ocr_submission",
                    status="failed",
                    progress_total=3,
                    error_message="Safe failure",
                ),
                ProcessingJob(
                    id="job-b",
                    institution_id="institution-b",
                    requested_by="admin-b",
                    job_type="ocr_submission",
                    status="failed",
                    progress_total=2,
                ),
            ]
        )
        db.commit()
        db.close()

        def override_db():
            test_db = self.session_factory()
            try:
                yield test_db
            finally:
                test_db.close()

        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(operations_router)
        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _login(self, email: str, password: str):
        response = self.client.post("/api/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200, response.text)

    def test_activity_and_jobs_are_scoped_to_admin_institution(self):
        self._login("admin@example.edu", "admin password 123")
        activity = self.client.get("/api/admin/operations/audit?category=activity")
        self.assertEqual(activity.status_code, 200, activity.text)
        items = activity.json()["items"]
        self.assertEqual([item["target"]["id"] for item in items], ["submission-a"])
        self.assertEqual(items[0]["actor"]["name"], "Test Teacher")
        self.assertNotIn("password", items[0]["details"])

        jobs = self.client.get("/api/admin/operations/jobs")
        self.assertEqual(jobs.status_code, 200, jobs.text)
        self.assertEqual([item["id"] for item in jobs.json()], ["job-a"])

    def test_teacher_cannot_open_admin_operations(self):
        self._login("teacher@example.edu", "teacher password 123")
        response = self.client.get("/api/admin/operations/audit")
        self.assertEqual(response.status_code, 403)
        db = self.session_factory()
        denied = db.query(AuditLog).filter(
            AuditLog.institution_id == "institution-a",
            AuditLog.actor_id == "teacher-a",
            AuditLog.action == "admin_access_denied",
        ).one()
        self.assertEqual(denied.extra_data["category"], "security")
        self.assertEqual(denied.extra_data["outcome"], "failure")
        db.close()

    def test_csv_export_contains_only_safe_tenant_rows(self):
        self._login("admin@example.edu", "admin password 123")
        response = self.client.get("/api/admin/operations/audit.csv?category=activity")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("submission-a", response.text)
        self.assertNotIn("submission-b", response.text)
        self.assertNotIn("must-not-appear", response.text)

    def test_error_messages_drop_raw_model_responses_and_credentials(self):
        safe = safe_error_message(
            "Gemini failed api_key=secret-value Raw response: complete OCR answer content"
        )
        self.assertNotIn("secret-value", safe)
        self.assertNotIn("complete OCR", safe)


if __name__ == "__main__":
    import unittest

    unittest.main()
