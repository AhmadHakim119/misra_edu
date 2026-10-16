import copy
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault('AUTH_SECRET', 'synthetic-auth-secret-that-is-longer-than-thirty-two-characters')
os.environ.setdefault('COOKIE_SECURE', 'false')
os.environ.setdefault('GEMINI_API_KEY', 'synthetic-unused')

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from models import (Institution, User, InstructorAccountSettings, InstructorPreferenceVersion,
                    PasswordResetToken, Course, Exam, Question, RubricVersion, ProcessingJob)
from routers import auth, admin_users, questions, rubric_versions
from schemas.instructor_preferences import SCENARIO_OPTIONS
from services.auth_service import hash_password, SESSION_COOKIE, CSRF_COOKIE
from services.account_settings_service import apply_to_new_draft
from services.rubric_service import build_rubric


class AccountSettingsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.db = self.factory()
        self.password = 'Synthetic account password'
        self.user = User(id='teacher', institution_id='i', email='teacher@example.edu', full_name='Synthetic teacher',
                         role='teacher', hashed_password=hash_password(self.password))
        self.admin = User(id='admin', institution_id='i', email='admin@example.edu', role='admin', hashed_password=hash_password(self.password))
        self.other = User(id='other', institution_id='other-i', email='other@example.edu', role='admin', hashed_password=hash_password(self.password))
        self.db.add_all([Institution(id='i', name='Synthetic'), Institution(id='other-i', name='Other'), self.user, self.admin, self.other])
        self.db.commit()
        app = FastAPI()
        for router in [auth.router, admin_users.router, questions.router, rubric_versions.router]:
            app.include_router(router)
        def database():
            session = self.factory()
            try:
                yield session
            finally:
                session.close()
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)
        self.sign_in(self.user.email)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def sign_in(self, email):
        result = self.client.post('/api/auth/login', json={'email':email, 'password':self.password})
        self.assertEqual(result.status_code, 200)
        self.headers = {'X-CSRF-Token':self.client.cookies.get(CSRF_COOKIE)}

    def profile(self, *, complete=True):
        row = InstructorPreferenceVersion(id='profile', institution_id='i', user_id='teacher', created_by='teacher', approved_by='teacher',
            version_number=1, status='approved', explicit_preferences={}, proposal_provenance={},
            scenario_answers=[{'scenario_id':key,'selected_option':next(iter(value))} for key,value in SCENARIO_OPTIONS.items()] if complete else [],
            derived_proposal={'units_policy':'do_not_penalize','rounding_tolerance_percent':0,'custom_instructions':'Flag ambiguous working for review.'})
        self.db.add(row); self.db.commit()
        return row

    def rubric(self):
        return build_rubric(max_score=2, criteria=[{'title':'Method','description':'Correct method','points':2}], grading_approach='balanced').model_dump()

    def question(self):
        self.db.add(Course(id='course', institution_id='i', teacher_id='teacher', course_code='SYN', title='Synthetic'))
        self.db.add(Exam(id='exam', institution_id='i', course_id='course', title='Synthetic'))
        self.db.flush()
        question = Question(id='question', institution_id='i', exam_id='exam', question_number='1', question_text='Calculate work.', max_score=2, rubric_json=self.rubric(), order_index=1, language='en')
        self.db.add(question); self.db.commit()
        return question

    def test_default_on_opt_out_persists_and_is_scoped(self):
        state = self.client.get('/api/auth/settings').json()
        self.assertTrue(state['use_marking_preferences']); self.assertFalse(state['survey_completed'])
        response = self.client.put('/api/auth/settings', json={'use_marking_preferences':False}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.get('/api/auth/settings').json()['use_marking_preferences'])
        self.assertEqual(self.client.put('/api/auth/settings', json={'use_marking_preferences':'false'}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.put('/api/auth/settings', json={'use_marking_preferences':True,'user_id':'other'}, headers=self.headers).status_code, 422)
        self.sign_in('other@example.edu')
        self.assertTrue(self.client.get('/api/auth/settings').json()['use_marking_preferences'])

    def test_completion_uses_approved_twelve_answers(self):
        row = self.profile()
        self.assertTrue(self.client.get('/api/auth/settings').json()['survey_completed'])
        row.status='draft'; self.db.commit()
        self.assertFalse(self.client.get('/api/auth/settings').json()['survey_completed'])

    def test_new_draft_defaults_preserve_zero_existing_rubric_and_opt_out(self):
        self.profile()
        original=self.rubric(); snapshot=copy.deepcopy(original)
        applied=apply_to_new_draft(self.db,self.user,original).model_dump()
        self.assertEqual(original,snapshot)
        self.assertEqual(applied['criteria'],original['criteria'])
        self.assertEqual(applied['policy']['rounding_tolerance_percent'],0)
        self.assertEqual(applied['policy']['units_policy'],'do_not_penalize')
        self.db.add(InstructorAccountSettings(user_id='teacher',institution_id='i',use_marking_preferences=False));self.db.commit()
        self.assertEqual(apply_to_new_draft(self.db,self.user,original),original)
        self.assertEqual(apply_to_new_draft(self.db,self.other,original),original)

    def test_new_rubric_api_fills_preferences_without_approving(self):
        self.profile(); question=self.question(); before=copy.deepcopy(question.rubric_json)
        response=self.client.post('/api/questions/question/rubric-versions',json={'rubric':before,'apply_instructor_preferences':True},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'draft')
        self.assertEqual(response.json()['rubric_json']['policy']['units_policy'],'do_not_penalize')
        self.db.refresh(question);self.assertEqual(question.rubric_json,before);self.assertIsNone(question.active_rubric_version_id)

    def test_new_manual_question_draft_gets_defaults_but_explicit_policy_wins(self):
        self.profile();self.question()
        body={'approve_initial_rubric':False,'question_number':'2','question_text':'Synthetic question','max_score':2,'criteria':[{'title':'Method','description':'Correct method','points':2}]}
        response=self.client.post('/api/exams/exam/questions',json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        row=self.db.query(RubricVersion).filter_by(question_id=response.json()['id']).one()
        self.assertEqual(row.rubric_json['policy']['units_policy'],'do_not_penalize')
        body['question_number']='3';body['policy']=self.rubric()['policy'];body['policy']['units_policy']='required'
        response=self.client.post('/api/exams/exam/questions',json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        row=self.db.query(RubricVersion).filter_by(question_id=response.json()['id']).one()
        self.assertEqual(row.rubric_json['policy']['units_policy'],'required')

    def test_delete_requires_csrf_password_and_typed_confirmation(self):
        body={'current_password':self.password,'confirmation':'DELETE'}
        self.assertEqual(self.client.request('DELETE','/api/auth/account',json=body).status_code,403)
        self.assertEqual(self.client.request('DELETE','/api/auth/account',json={**body,'confirmation':'yes'},headers=self.headers).status_code,422)
        self.assertEqual(self.client.request('DELETE','/api/auth/account',json={**body,'current_password':'wrong'},headers=self.headers).status_code,400)
        self.db.refresh(self.user);self.assertTrue(self.user.is_active)

    def test_delete_anonymizes_revokes_sessions_retains_history_and_blocks_reactivation(self):
        self.profile();question=self.question();before=copy.deepcopy(question.rubric_json)
        self.db.add(PasswordResetToken(user_id='teacher', email_hash='a'*64,token_hash='b'*64,expires_at=datetime.now()+timedelta(hours=1)))
        self.db.commit()
        old_cookie=self.client.cookies.get(SESSION_COOKIE)
        response=self.client.request('DELETE','/api/auth/account',json={'current_password':self.password,'confirmation':'DELETE'},headers=self.headers)
        self.assertEqual(response.status_code,204,response.text)
        self.assertIsNone(self.client.cookies.get(SESSION_COOKIE))
        self.db.expire_all();self.assertFalse(self.user.is_active);self.assertEqual(self.user.full_name,'Deleted instructor')
        self.assertNotEqual(self.user.email,'teacher@example.edu');self.assertIsNotNone(self.db.query(PasswordResetToken).one().used_at)
        self.assertEqual(self.db.query(InstructorPreferenceVersion).count(),1);self.assertEqual(self.db.get(Question,'question').rubric_json,before)
        self.client.cookies.set(SESSION_COOKIE,old_cookie)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.client.cookies.clear();self.sign_in('admin@example.edu')
        self.assertEqual(self.client.patch('/api/admin/instructors/teacher',json={'is_active':True},headers=self.headers).status_code,409)

    def test_last_administrator_and_running_tasks_block_deletion(self):
        self.sign_in('admin@example.edu')
        body={'current_password':self.password,'confirmation':'DELETE'}
        self.assertEqual(self.client.request('DELETE','/api/auth/account',json=body,headers=self.headers).status_code,409)
        self.sign_in('teacher@example.edu')
        self.db.add(ProcessingJob(institution_id='i',requested_by='teacher',job_type='exam_setup',status='queued'));self.db.commit()
        self.assertEqual(self.client.request('DELETE','/api/auth/account',json=body,headers=self.headers).status_code,409)
        self.db.refresh(self.user);self.assertTrue(self.user.is_active)

    def test_schema_upgrade_is_additive_idempotent_and_missing_schema_is_actionable(self):
        InstructorAccountSettings.__table__.drop(self.engine)
        self.assertEqual(self.client.get('/api/auth/settings').status_code,503)
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)
        from scripts import upgrade_account_settings
        with patch.object(upgrade_account_settings,'engine',self.engine):
            upgrade_account_settings.main();upgrade_account_settings.main()
        self.assertEqual(self.client.get('/api/auth/settings').status_code,200)
        self.assertEqual(self.db.query(User).count(),3)


if __name__=='__main__':
    unittest.main()
