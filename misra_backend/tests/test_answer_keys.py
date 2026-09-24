import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('GEMINI_API_KEY', 'test-key-not-used')
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile
from database import Base
from models import AnswerKeyVersion, Course, Exam, Institution, ProcessingJob, Question, Submission, User
from routers import answer_keys, exam_setup
from schemas.answer_keys import AnswerKeyDraftRequest
from services import answer_key_service as service


class AnswerKeyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(id='u', institution_id='i', email='test@example.edu', hashed_password='unused', role='teacher')
        self.other = User(id='v', institution_id='other', email='other@example.edu', hashed_password='unused', role='teacher')
        self.question = Question(id='q', institution_id='i', exam_id='e', question_number='1', question_text='Synthetic?', max_score=2, rubric_json={}, order_index=1)
        self.db.add_all([Institution(id='i', name='Test'), Institution(id='other', name='Other'), self.user, self.other,
            Course(id='c', institution_id='i', teacher_id='u', course_code='TEST', title='Testing'),
            Exam(id='e', institution_id='i', course_id='c', title='Test exam', language='en'), self.question])
        self.db.commit()
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.patches = [patch.object(answer_keys, 'SETUP_DIR', self.directory), patch.object(service, 'SETUP_DIR', self.directory),
            patch('services.exam_setup_service.SETUP_DIR', self.directory)]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def upload(self):
        stream = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(stream, 'PNG')
        stream.seek(0)
        return asyncio.run(answer_keys.upload_document('q', UploadFile(filename='key.png', file=stream), self.db, self.user))

    def draft(self, **kwargs):
        return answer_keys.create_version('q', AnswerKeyDraftRequest(**(kwargs or {'reference_text': 'Synthetic key'})), self.db, self.user)

    def test_draft_approval_history_and_immutable_content(self):
        first = self.draft()
        self.assertTrue(service.resolve_answer_key(self.question, self.db, {})['is_legacy_fallback'])
        answer_keys.approve_version('q', first['id'], self.db, self.user)
        with self.assertRaises(HTTPException):
            answer_keys.edit_version('q', first['id'], AnswerKeyDraftRequest(reference_text='Changed'), self.db, self.user)
        second = self.draft(mode='no_fixed_answer')
        answer_keys.approve_version('q', second['id'], self.db, self.user)
        versions = answer_keys.list_versions('q', self.db, self.user)
        self.assertEqual([v['status'] for v in versions], ['approved', 'superseded'])
        self.assertEqual(versions[1]['reference_text'], 'Synthetic key')
        resolved = service.resolve_answer_key(self.question, self.db, {'reference_context': 'old'})
        self.assertEqual(resolved['mode'], 'no_fixed_answer')
        self.assertFalse(resolved['is_legacy_fallback'])

    def test_legacy_alternatives_preserved(self):
        result = service.resolve_answer_key(self.question, self.db, {'acceptable_answers': ['A', 'B']})
        self.assertEqual(result['alternatives'], ['A', 'B'])
        self.assertEqual(result['mode'], 'reference')

    def test_document_ingestion_private_read_and_hash_snapshot(self):
        with patch('services.exam_setup_service.generate') as generate:
            document = self.upload()
            generate.assert_not_called()
        job = self.db.get(ProcessingJob, document['job_id'])
        self.assertEqual(job.status, 'completed')
        self.assertEqual(job.payload['purpose'], 'answer_key_reference')
        self.assertEqual(exam_setup.list_imports('e', self.db, self.user), [])
        with self.assertRaises(HTTPException) as error:
            exam_setup.confirm('e', job.id, exam_setup.ConfirmImport(questions=[dict(question_number='2', question_text='Synthetic', max_score=1, marking_guide='Synthetic')]), self.db, self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.query(Submission).count(), 0)
        self.assertNotIn('path', document)
        response = exam_setup.get_document('e', job.id, 0, self.db, self.user)
        self.assertTrue(Path(response.path).is_file())
        draft = self.draft(document_refs=[dict(job_id=job.id, page_indices=[0])])
        approved = answer_keys.approve_version('q', draft['id'], self.db, self.user)
        self.assertEqual(len(approved['document_refs'][0]['sha256']), 64)
        resolved = service.resolve_answer_key(self.question, self.db, {})
        self.assertNotIn('path', service.public_snapshot(resolved)['document_refs'][0])
        Path(response.path).write_bytes(b'mutated synthetic file')
        with self.assertRaisesRegex(ValueError, 'has changed'):
            service.resolve_answer_key(self.question, self.db, {'reference_context': 'must not fallback'})

    def test_missing_document_fails_closed(self):
        document = self.upload()
        draft = self.draft(document_refs=[dict(job_id=document['job_id'], page_indices=[0])])
        answer_keys.approve_version('q', draft['id'], self.db, self.user)
        job = self.db.get(ProcessingJob, document['job_id'])
        Path(job.payload['documents'][0]['path']).unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            service.resolve_answer_key(self.question, self.db, {})

    def test_cross_tenant_and_assessment_references_rejected(self):
        document = self.upload()
        for call in [lambda: answer_keys.list_versions('q', self.db, self.other),
                     lambda: exam_setup.get_document('e', document['job_id'], 0, self.db, self.other)]:
            with self.assertRaises(HTTPException) as error: call()
            self.assertEqual(error.exception.status_code, 404)
        job = self.db.get(ProcessingJob, document['job_id'])
        for field, value in [('institution_id', 'other'), ('payload', dict(job.payload, exam_id='another'))]:
            old = getattr(job, field)
            setattr(job, field, value)
            self.db.flush()
            with self.assertRaises(ValueError):
                service.resolve_document_refs(self.question, [dict(job_id=job.id, page_indices=[0])], self.db)
            setattr(job, field, old)
            self.db.flush()

    def test_invalid_upload_cleans_files(self):
        with self.assertRaises(HTTPException):
            asyncio.run(answer_keys.upload_document('q', UploadFile(filename='bad.pdf', file=io.BytesIO(b'%PDF-broken')), self.db, self.user))
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertEqual(self.db.query(ProcessingJob).count(), 0)

    def test_reference_contract_limits(self):
        invalid = [dict(mode='no_fixed_answer', reference_text='A'), dict(reference_text=''),
            dict(document_refs=[dict(job_id='a', page_indices=[True])]),
            dict(document_refs=[dict(job_id='a', page_indices=[0, 0])]),
            dict(document_refs=[dict(job_id=str(i), page_indices=[0]) for i in range(6)]),
            dict(document_refs=[dict(job_id='a', page_indices=list(range(20))), dict(job_id='b', page_indices=[0])])]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValidationError): AnswerKeyDraftRequest(**payload)


if __name__ == '__main__':
    unittest.main()
