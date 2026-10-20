import unittest

from sqlalchemy import text

from models import (Answer, AnswerKeyVersion, AuditLog, ProcessingJob, Question,
                    QuestionGradingPolicy, QuestionMaterialScopeVersion, RubricSuggestion,
                    RubricVersion, Submission)
from tests import test_account_settings as fixtures


class QuestionDeletionTests(unittest.TestCase):
    setUp = fixtures.AccountSettingsTests.setUp
    tearDown = fixtures.AccountSettingsTests.tearDown
    sign_in = fixtures.AccountSettingsTests.sign_in
    question = fixtures.AccountSettingsTests.question
    rubric = fixtures.AccountSettingsTests.rubric

    def draft(self):
        question=self.question()
        row=RubricVersion(id='draft',question_id=question.id,version_number=1,status='draft',
            schema_version=2,rubric_json=self.rubric(),grading_approach='balanced',source='manual',created_by='teacher')
        self.db.add(row);self.db.commit()
        return question,row

    def delete(self,identifier='question',headers=True):
        return self.client.delete('/api/questions/'+identifier,headers=self.headers if headers else {})

    def test_delete_only_target_draft_and_children_with_foreign_keys_enabled(self):
        # Verify explicit cleanup on the same restrictive FKs used by MariaDB.
        with self.engine.connect() as connection:
            connection.execute(text('PRAGMA foreign_keys=ON'))
        question,_=self.draft()
        self.db.add_all([
            AnswerKeyVersion(question_id=question.id,version_number=1,status='draft',mode='no_fixed_answer',created_by='teacher'),
            QuestionMaterialScopeVersion(question_id=question.id,version_number=1,status='draft',mode='inherit',bindings=[],created_by='teacher'),
            QuestionGradingPolicy(question_id=question.id,mode='adaptive'),
            Question(id='keep',institution_id='i',exam_id='exam',question_number='2',question_text='Keep me',max_score=2,rubric_json=self.rubric(),order_index=2,language='en'),
        ]);self.db.commit()
        response=self.delete();self.assertEqual(response.status_code,204,response.text)
        self.db.expire_all();self.assertIsNone(self.db.get(Question,'question'))
        self.assertEqual(self.db.get(Question,'keep').question_text,'Keep me')
        for model in [RubricVersion,AnswerKeyVersion,QuestionMaterialScopeVersion,QuestionGradingPolicy]:
            self.assertEqual(self.db.query(model).count(),0)
        self.assertEqual(self.db.query(AuditLog).filter_by(action='draft_question_deleted').count(),1)
        self.assertEqual(self.delete().status_code,404)

    def test_foreign_institution_and_missing_question_are_uniform_404(self):
        self.draft();self.sign_in('other@example.edu')
        self.assertEqual(self.delete().status_code,404);self.assertEqual(self.delete('missing').status_code,404)
        self.assertIsNotNone(self.db.get(Question,'question'))

    def test_delete_requires_csrf(self):
        self.draft();self.assertEqual(self.delete(headers=False).status_code,403)
        self.assertIsNotNone(self.db.get(Question,'question'))

    def test_approved_or_superseded_rubric_cannot_be_deleted(self):
        _,row=self.draft()
        for status in ['approved','superseded']:
            row.status=status;self.db.commit()
            self.assertEqual(self.delete().status_code,409)
            self.db.refresh(row);self.assertEqual(row.status,status)

    def test_legacy_and_active_rubric_are_protected(self):
        question=self.question();self.assertEqual(self.delete().status_code,409)
        self.db.add(RubricVersion(id='draft',question_id=question.id,version_number=1,status='draft',rubric_json=self.rubric(),grading_approach='balanced',source='manual'))
        self.db.flush();question.active_rubric_version_id='draft';self.db.commit()
        self.assertEqual(self.delete().status_code,409)

    def test_approved_answer_key_or_source_scope_blocks_deletion(self):
        self.draft()
        key=AnswerKeyVersion(question_id='question',version_number=1,status='approved',mode='no_fixed_answer')
        self.db.add(key);self.db.commit();self.assertEqual(self.delete().status_code,409)
        key.status='draft'
        self.db.add(QuestionMaterialScopeVersion(question_id='question',version_number=1,status='approved',mode='disabled',bindings=[]))
        self.db.commit();self.assertEqual(self.delete().status_code,409)
        self.assertEqual(self.db.query(AnswerKeyVersion).count(),1)

    def test_papers_answers_and_instructor_marks_are_preserved(self):
        self.draft()
        self.db.add(Submission(id='paper',institution_id='i',exam_id='exam',original_file_path='synthetic-only.pdf',status='reviewed'))
        self.db.flush()
        self.db.add(Answer(id='answer',institution_id='i',submission_id='paper',question_id='question',score=2,teacher_override_score=1.5,teacher_notes='Keep synthetic decision'))
        self.db.commit();self.assertEqual(self.delete().status_code,409)
        self.db.expire_all();self.assertEqual(float(self.db.get(Answer,'answer').teacher_override_score),1.5)
        self.assertIsNotNone(self.db.get(Submission,'paper'));self.assertIsNotNone(self.db.get(RubricVersion,'draft'))

    def test_pending_exam_work_blocks_deletion(self):
        self.draft();self.db.add(ProcessingJob(institution_id='i',requested_by='teacher',job_type='exam_setup',status='processing',payload={'exam_id':'exam'}));self.db.commit()
        self.assertEqual(self.delete().status_code,409);self.assertIsNotNone(self.db.get(Question,'question'))

    def test_original_ai_suggestion_is_preserved(self):
        self.draft();self.db.add(RubricSuggestion(question_id='question',suggested_json={'synthetic':'retained'},status='pending'));self.db.commit()
        self.assertEqual(self.delete().status_code,409)
        self.assertEqual(self.db.query(RubricSuggestion).one().suggested_json,{'synthetic':'retained'})


if __name__=='__main__':
    unittest.main()
