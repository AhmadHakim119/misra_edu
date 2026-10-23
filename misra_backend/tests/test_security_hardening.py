import unittest
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from models import AuditLog
from services.login_security_service import record_login_attempt
from tests import test_course_materials as fixtures


class LoginBudgetTests(unittest.TestCase):
    setUp = fixtures.CourseMaterialTests.setUp
    tearDown = fixtures.CourseMaterialTests.tearDown

    def test_login_checks_unknown_password_and_stops_hashing_when_limited(self):
        from fastapi import Request, Response
        from unittest.mock import patch
        from routers.auth import login
        from schemas.auth_input import LoginRequest
        request = Request({'type':'http','method':'POST','client':('synthetic-ip',1),'headers':[]})
        payload = LoginRequest(email='unknown@example.edu',password='synthetic-password')
        with patch('routers.auth.dummy_password_hash',return_value='dummy-hash'), \
             patch('routers.auth.verify_password',return_value=False) as check:
            for _ in range(10):
                with self.assertRaises(HTTPException) as error:
                    login(payload,request,Response(),self.db)
                self.assertEqual(error.exception.status_code,401)
            check.assert_called_with('synthetic-password','dummy-hash')
            with self.assertRaises(HTTPException) as error:
                login(payload,request,Response(),self.db)
            self.assertEqual(error.exception.status_code,429)
            self.assertEqual(check.call_count,10)

    def test_email_budget_applies_across_addresses_and_persists_privately(self):
        for n in range(10):
            record_login_attempt(self.db, 'synthetic@example.invalid', str(n))
        with self.assertRaises(HTTPException) as error:
            record_login_attempt(self.db, 'synthetic@example.invalid', 'new-address')
        self.assertEqual(error.exception.status_code, 429)
        self.assertEqual(error.exception.headers['Retry-After'], '900')
        self.assertNotIn('synthetic@example.invalid', str(self.db.query(AuditLog).first().extra_data))

    def test_ip_budget_applies_across_unknown_accounts(self):
        for n in range(50):
            record_login_attempt(self.db, f'{n}@example.invalid', 'synthetic-ip')
        with self.assertRaises(HTTPException) as error:
            record_login_attempt(self.db, 'another@example.invalid', 'synthetic-ip')
        self.assertEqual(error.exception.status_code, 429)

    def test_expired_budget_releases_sign_in(self):
        for _ in range(10):
            record_login_attempt(self.db, 'synthetic@example.invalid', 'synthetic-ip')
        self.db.query(AuditLog).update({AuditLog.created_at:datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(minutes=16)})
        self.db.commit()
        record_login_attempt(self.db, 'synthetic@example.invalid', 'synthetic-ip')


class ResponseHeaderTests(unittest.TestCase):
    def test_sensitive_responses_and_reset_links_have_protective_headers(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from main import prevent_sensitive_page_caching
        app = FastAPI()
        app.middleware('http')(prevent_sensitive_page_caching)
        @app.get('/api/synthetic')
        def synthetic():
            return {'synthetic':True}
        with TestClient(app) as client:
            result = client.get('/api/synthetic')
        self.assertEqual(result.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(result.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(result.headers['Referrer-Policy'], 'no-referrer')
        self.assertIn("frame-ancestors 'none'", result.headers['Content-Security-Policy'])
        self.assertIn('no-store', result.headers['Cache-Control'])
