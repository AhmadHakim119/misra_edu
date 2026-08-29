import os
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ.setdefault("AUTH_SECRET", "test-auth-secret-that-is-longer-than-thirty-two-characters")
os.environ.setdefault("COOKIE_SECURE", "false")

from database import Base, get_db  # noqa: E402
import models  # noqa: E402,F401
from models import Institution, User  # noqa: E402
from routers.auth import router as auth_router  # noqa: E402
from services.auth_service import (  # noqa: E402
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)


class AuthenticationTests(unittest.TestCase):
    def test_password_hash_round_trip(self):
        encoded = hash_password("correct horse battery staple")

        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong password", encoded))
        self.assertNotIn("correct horse battery staple", encoded)

    def test_session_token_round_trip_and_tamper_rejection(self):
        token, max_age = create_session_token("teacher-1")
        claims = read_session_token(token)

        self.assertEqual(max_age, 8 * 60 * 60)
        self.assertIsNotNone(claims)
        self.assertEqual(claims.user_id, "teacher-1")
        self.assertIsNone(read_session_token(f"{token}x"))

    def test_short_password_is_rejected(self):
        with self.assertRaises(ValueError):
            hash_password("too-short")

    def test_login_me_and_csrf_protected_logout(self):
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        db = session_factory()
        institution = Institution(id="institution-1", name="Test University")
        user = User(
            id="teacher-1",
            institution_id=institution.id,
            email="teacher@example.edu",
            hashed_password=hash_password("correct horse battery staple"),
            full_name="Test Teacher",
            role="teacher",
        )
        db.add_all([institution, user])
        db.commit()
        db.close()

        def override_db():
            test_db = session_factory()
            try:
                yield test_db
            finally:
                test_db.close()

        app = FastAPI()
        app.include_router(auth_router)
        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)

        login = client.post(
            "/api/auth/login",
            json={"email": "teacher@example.edu", "password": "correct horse battery staple"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertNotIn("misra_session", login.json())
        self.assertEqual(client.get("/api/auth/me").json()["id"], "teacher-1")

        accepted = client.post("/api/auth/logout")
        self.assertEqual(accepted.status_code, 204)


if __name__ == "__main__":
    unittest.main()
