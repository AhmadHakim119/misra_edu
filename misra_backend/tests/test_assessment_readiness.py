import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import (
    AnswerKeyVersion,
    Course,
    Exam,
    Institution,
    ProcessingJob,
    Question,
    QuestionGradingPolicy,
    RubricVersion,
    User,
)
from services.assessment_readiness_service import assessment_readiness, definition_errors, definition_consistency
from services.rubric_version_service import get_effective_rubric
from routers.exam_setup import readiness
from routers.exams import list_exams


class AssessmentReadinessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(id='u', institution_id='i', email='teacher@example.test', hashed_password='unused', role='teacher')
        self.db.add_all([Institution(id='i', name='Synthetic'), self.user,
            Course(id='c', institution_id='i', teacher_id='u', title='Synthetic course'),
            Exam(id='e', institution_id='i', course_id='c', title='Synthetic exam')])
        self.q = Question(id='q', institution_id='i', exam_id='e', question_number='1', question_text='Explain.', max_score=3, order_index=0, rubric_json={})
        self.db.add(self.q)
        self.v = RubricVersion(id='v', question_id='q', version_number=1, schema_version=1, source='manual', status='approved', rubric_json={
            'max_score': 3, 'criteria': [{'id': 'reason', 'description': 'Valid reasoning', 'points': 3}]})
        self.db.add(self.v); self.q.active_rubric_version_id = 'v'; self.db.commit()

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def test_optional_reference_is_advisory_not_a_blocker(self):
        result = assessment_readiness(self.db, 'e')
        self.assertTrue(result['ready'])
        self.assertEqual(result['warning_count'], 1)
        self.assertEqual(result['total_points'], 3)
        self.assertEqual(result['questions'][0]['rubric_version'], 1)

    def test_catalog_approval_count_is_scoped_and_excludes_drafts(self):
        self.assertEqual(list_exams(self.db, self.user)[0]['approved_question_count'], 1)
        self.v.status = 'draft'; self.db.commit()
        self.assertEqual(list_exams(self.db, self.user)[0]['approved_question_count'], 0)
        self.assertEqual(list_exams(self.db, SimpleNamespace(institution_id='other')), [])

    def test_approved_mismatch_blocks_setup_and_direct_grading(self):
        self.q.max_score = 4; self.db.commit()
        self.assertFalse(assessment_readiness(self.db, 'e')['ready'])
        with self.assertRaisesRegex(ValueError, 'marks do not match'):
            get_effective_rubric(self.q, self.db)

    def test_draft_or_wrong_question_version_is_not_approval(self):
        self.v.status = 'draft'; self.db.commit()
        self.assertEqual(assessment_readiness(self.db, 'e')['pending_questions'], ['1'])
        self.v.status = 'approved'; self.v.question_id = 'not-q'; self.db.commit()
        self.assertFalse(assessment_readiness(self.db, 'e')['ready'])

    def test_valid_legacy_rubric_is_ready_only_without_version_history(self):
        self.db.delete(self.v)
        self.q.active_rubric_version_id = None
        self.q.rubric_json = {
            'max_score': 3,
            'criteria': [{
                'id': 'legacy_reason',
                'description': 'Valid legacy reasoning',
                'points': 3,
            }],
        }
        self.db.commit()

        legacy = assessment_readiness(self.db, 'e')
        self.assertTrue(legacy['ready'])
        self.assertEqual(legacy['questions'][0]['rubric_source'], 'legacy')
        self.assertTrue(legacy['questions'][0]['definition_ready'])
        self.assertIsNone(legacy['questions'][0]['rubric_version'])
        self.assertEqual(get_effective_rubric(self.q, self.db)[1], None)

        self.db.add(RubricVersion(
            id='draft', question_id='q', version_number=1, schema_version=2,
            source='manual', status='draft', rubric_json=self.q.rubric_json,
        ))
        self.db.commit()
        versioned = assessment_readiness(self.db, 'e')
        self.assertFalse(versioned['ready'])
        self.assertEqual(versioned['questions'][0]['rubric_source'], 'unapproved')
        with self.assertRaisesRegex(ValueError, 'no approved rubric'):
            get_effective_rubric(self.q, self.db)

    def test_reference_and_routing_are_reported_without_reference_content(self):
        self.v.rubric_json = {**self.v.rubric_json, 'reference_context': 'Private reference'}
        self.db.add(QuestionGradingPolicy(question_id='q', mode='image_text_required'))
        self.db.commit()
        result = assessment_readiness(self.db, 'e')
        self.assertTrue(result['questions'][0]['reference_recorded'])
        self.assertEqual(result['questions'][0]['evidence_mode'], 'image_text_required')
        self.assertNotIn('Private reference', str(result))

    def test_scope_is_checked_at_endpoint(self):
        with self.assertRaises(HTTPException) as error:
            readiness('e', self.db, SimpleNamespace(institution_id='other'))
        self.assertEqual(error.exception.status_code, 404)

    def test_approved_key_supersedes_legacy_reference_check(self):
        key = AnswerKeyVersion(id='key', question_id='q', version_number=1,
            status='draft', mode='no_fixed_answer')
        self.db.add(key); self.db.commit()
        self.assertEqual(assessment_readiness(self.db, 'e')['warning_count'], 1)
        key.status = 'approved'; self.db.commit()
        result = assessment_readiness(self.db, 'e')
        self.assertEqual(result['warning_count'], 0)
        self.assertEqual(result['questions'][0]['answer_key_mode'], 'no_fixed_answer')
        key.mode = 'reference'; key.reference_text = 'Private key'; self.db.commit()
        result = assessment_readiness(self.db, 'e')
        self.assertTrue(result['questions'][0]['reference_recorded'])
        self.assertNotIn('Private key', str(result))

    def test_missing_or_changed_approved_key_file_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            setup_dir = Path(directory)
            document = setup_dir / 'answer-key.pdf'
            document.write_bytes(b'synthetic-reference-v1')
            digest = hashlib.sha256(document.read_bytes()).hexdigest()
            self.db.add(ProcessingJob(
                id='setup-job', institution_id='i', requested_by='u',
                job_type='exam_setup', status='completed',
                payload={
                    'exam_id': 'e',
                    'documents': [{
                        'role': 'answer_key', 'path': str(document),
                        'page_count': 1, 'media_type': 'application/pdf',
                    }],
                },
            ))
            self.db.add(AnswerKeyVersion(
                id='document-key', question_id='q', version_number=1,
                status='approved', mode='reference', reference_text='',
                acceptable_answers=[], document_refs=[{
                    'job_id': 'setup-job', 'page_indices': [0],
                    'document_index': 0, 'page_count': 1,
                    'media_type': 'application/pdf', 'sha256': digest,
                }],
            ))
            self.db.commit()

            with patch('services.answer_key_service.SETUP_DIR', setup_dir):
                self.assertTrue(assessment_readiness(self.db, 'e')['ready'])
                document.write_bytes(b'synthetic-reference-changed')
                changed = assessment_readiness(self.db, 'e')
                self.assertFalse(changed['ready'])
                self.assertIn('changed', ' '.join(changed['questions'][0]['errors']))
                document.unlink()
                missing = assessment_readiness(self.db, 'e')
                self.assertFalse(missing['ready'])
                self.assertIn('missing', ' '.join(missing['questions'][0]['errors']))

    def test_invalid_criteria_and_nonfinite_scores_fail(self):
        for rubric in [None, {}, {'max_score': 3, 'criteria': []},
                       {'max_score': float('nan'), 'criteria': [{'id': 'a', 'points': 3}]},
                       {'max_score': 3, 'criteria': [{'id': 'a', 'points': 1, 'description': 'x'}]},
                       {'max_score': 3, 'criteria': [{'id': 'a', 'points': 1.5, 'description': 'x'}]*2}]:
            with self.subTest(rubric=rubric):
                self.assertTrue(definition_errors(self.q, rubric))

    def test_deterministic_conflicts_have_stable_codes_and_severity(self):
        rubric = {
            'max_score': 3,
            'reference_context': 'Legacy fixed answer',
            'criteria': [{
                'id': 'diagram', 'description': 'Draw the schema diagram', 'points': 3,
                'required_evidence': ['diagram'], 'alternative_methods': ['Equivalent notation'],
            }],
            'policy': {
                'alternative_methods_allowed': False,
                'evidence_requirement': 'final_answer_only',
            },
        }
        key = AnswerKeyVersion(question_id='q', version_number=2, status='approved',
            mode='no_fixed_answer', reference_text='', acceptable_answers=[], document_refs=[])
        routing = QuestionGradingPolicy(question_id='q', mode='text_only', enabled=True)
        result = definition_consistency(self.q, rubric, key, routing)
        self.assertEqual(result['blocking_errors'], [])
        self.assertEqual({item['code'] for item in result['advisories']}, {
            'no_fixed_answer_legacy_reference_conflict',
            'criterion_alternatives_policy_conflict',
            'criterion_evidence_policy_conflict',
            'visual_requirement_text_only_policy',
        })
        self.assertTrue(result['visual_evidence_required'])

    def test_corrupt_no_fixed_answer_definition_is_a_blocker(self):
        key = AnswerKeyVersion(question_id='q', version_number=2, status='approved',
            mode='no_fixed_answer', reference_text='Contradictory fixed answer',
            acceptable_answers=[], document_refs=[])
        result = definition_consistency(self.q, self.v.rubric_json, key)
        self.assertEqual(
            [item['code'] for item in result['blocking_errors']],
            ['no_fixed_answer_contains_reference'],
        )


if __name__ == '__main__':
    unittest.main()
