from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ.setdefault("AUTH_SECRET", "test-auth-secret-that-is-longer-than-thirty-two-characters")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("PASSWORD_RESET_DELIVERY", "console")

from database import Base, get_db  # noqa: E402
import models  # noqa: E402,F401
from models import Institution, PasswordResetToken, User  # noqa: E402
from routers.admin_users import router as admin_router  # noqa: E402
from routers.auth import router as auth_router  # noqa: E402
from services.auth_service import hash_password  # noqa: E402


class AccountManagementTests(TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        db = self.session_factory()
        institution_a = Institution(id="institution-a", name="University A")
        institution_b = Institution(id="institution-b", name="University B")
        db.add_all(
            [
                institution_a,
                institution_b,
                User(
                    id="admin-a",
                    institution_id=institution_a.id,
                    email="admin@example.edu",
                    hashed_password=hash_password("admin password 123"),
                    full_name="Account Admin",
                    role="admin",
                ),
                User(
                    id="teacher-a",
                    institution_id=institution_a.id,
                    email="teacher@example.edu",
                    hashed_password=hash_password("teacher password 123"),
                    full_name="Test Teacher",
                    role="teacher",
                ),
                User(
                    id="teacher-b",
                    institution_id=institution_b.id,
                    email="other@example.edu",
                    hashed_password=hash_password("other password 123"),
                    full_name="Other Teacher",
                    role="teacher",
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
        app.include_router(admin_router)
        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _login(self, email="teacher@example.edu", password="teacher password 123", client=None):
        active_client = client or self.client
        response = active_client.post("/api/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return {"X-CSRF-Token": active_client.cookies.get("misra_csrf")}

    def test_change_password_invalidates_every_existing_session(self):
        first_client = TestClient(self.client.app)
        second_client = TestClient(self.client.app)
        first_headers = self._login(client=first_client)
        self._login(client=second_client)

        changed = first_client.post(
            "/api/auth/change-password",
            headers=first_headers,
            json={
                "current_password": "teacher password 123",
                "new_password": "new teacher password 456",
            },
        )
        self.assertEqual(changed.status_code, 204, changed.text)
        self.assertEqual(second_client.get("/api/auth/me").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/auth/login",
                json={"email": "teacher@example.edu", "password": "teacher password 123"},
            ).status_code,
            401,
        )
        self._login(password="new teacher password 456")
        first_client.close()
        second_client.close()

    def test_change_password_requires_the_current_password(self):
        headers = self._login()
        response = self.client.post(
            "/api/auth/change-password",
            headers=headers,
            json={"current_password": "wrong password", "new_password": "new teacher password 456"},
        )
        self.assertEqual(response.status_code, 400)

    def test_password_reset_is_hashed_single_use_and_invalidates_sessions(self):
        stale_client = TestClient(self.client.app)
        self._login(client=stale_client)
        deliveries = []

        with patch("routers.auth.send_password_reset_email", side_effect=deliveries.append):
            requested = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "teacher@example.edu"},
            )
        self.assertEqual(requested.status_code, 202)
        self.assertEqual(len(deliveries), 1)
        token = parse_qs(urlparse(deliveries[0].reset_url).query)["token"][0]

        db = self.session_factory()
        stored = db.query(PasswordResetToken).one()
        self.assertNotEqual(stored.token_hash, token)
        self.assertNotIn(token, stored.token_hash)
        db.close()

        reset = self.client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "recovered password 789"},
        )
        self.assertEqual(reset.status_code, 204, reset.text)
        self.assertEqual(stale_client.get("/api/auth/me").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/auth/reset-password",
                json={"token": token, "new_password": "another password 789"},
            ).status_code,
            400,
        )
        self._login(password="recovered password 789")
        stale_client.close()

    def test_expired_reset_token_is_rejected(self):
        deliveries = []
        with patch("routers.auth.send_password_reset_email", side_effect=deliveries.append):
            self.client.post("/api/auth/forgot-password", json={"email": "teacher@example.edu"})
        token = parse_qs(urlparse(deliveries[0].reset_url).query)["token"][0]
        db = self.session_factory()
        stored = db.query(PasswordResetToken).one()
        stored.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
        db.close()

        response = self.client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "recovered password 789"},
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_and_throttled_reset_requests_keep_the_same_public_response(self):
        with patch.dict(os.environ, {"PASSWORD_RESET_EMAIL_LIMIT": "1"}):
            unknown = self.client.post("/api/auth/forgot-password", json={"email": "missing@example.edu"})
            first = self.client.post("/api/auth/forgot-password", json={"email": "teacher@example.edu"})
            second = self.client.post("/api/auth/forgot-password", json={"email": "teacher@example.edu"})
        self.assertEqual(unknown.status_code, 202)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(unknown.json(), first.json())
        self.assertEqual(first.json(), second.json())

    def test_admin_crud_is_institution_scoped_and_teacher_cannot_access_it(self):
        teacher_headers = self._login()
        self.assertEqual(
            self.client.get("/api/admin/instructors", headers=teacher_headers).status_code,
            403,
        )

        admin_client = TestClient(self.client.app)
        admin_headers = self._login("admin@example.edu", "admin password 123", admin_client)
        listed = admin_client.get("/api/admin/instructors", headers=admin_headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.json()], ["teacher-a"])

        created = admin_client.post(
            "/api/admin/instructors",
            headers=admin_headers,
            json={
                "email": "new@example.edu",
                "full_name": "New Instructor",
                "temporary_password": "temporary password 123",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        new_id = created.json()["id"]
        self.assertTrue(created.json()["must_change_password"])

        disabled = admin_client.patch(
            f"/api/admin/instructors/{new_id}",
            headers=admin_headers,
            json={"is_active": False},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/auth/login",
                json={"email": "new@example.edu", "password": "temporary password 123"},
            ).status_code,
            401,
        )
        self.assertEqual(
            admin_client.patch(
                "/api/admin/instructors/teacher-b",
                headers=admin_headers,
                json={"is_active": False},
            ).status_code,
            404,
        )
        admin_client.close()

    def test_admin_reset_forces_password_change_and_invalidates_old_cookie(self):
        stale_teacher = TestClient(self.client.app)
        self._login(client=stale_teacher)
        admin_client = TestClient(self.client.app)
        admin_headers = self._login("admin@example.edu", "admin password 123", admin_client)

        reset = admin_client.post(
            "/api/admin/instructors/teacher-a/reset-password",
            headers=admin_headers,
            json={"temporary_password": "temporary reset 123"},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertTrue(reset.json()["must_change_password"])
        self.assertEqual(stale_teacher.get("/api/auth/me").status_code, 401)

        forced_client = TestClient(self.client.app)
        forced_headers = self._login("teacher@example.edu", "temporary reset 123", forced_client)
        self.assertTrue(forced_client.get("/api/auth/me").json()["must_change_password"])
        changed = forced_client.post(
            "/api/auth/change-password",
            headers=forced_headers,
            json={"current_password": "temporary reset 123", "new_password": "permanent password 123"},
        )
        self.assertEqual(changed.status_code, 204)
        stale_teacher.close()
        admin_client.close()
        forced_client.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
