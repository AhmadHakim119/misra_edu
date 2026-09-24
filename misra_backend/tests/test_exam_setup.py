import asyncio
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('GEMINI_API_KEY', 'test-key-not-used')
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile
from database import Base
from models import Answer, Course, Exam, Institution, ProcessingJob, Question, RubricVersion, Submission, User
from routers import exam_setup
from services import exam_setup_service as service
from services.rubric_version_service import get_effective_rubric


class ExamSetupTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(id='u', institution_id='i', email='test@example.edu', hashed_password='unused', role='teacher')
        self.other = User(id='v', institution_id='other', email='other@example.edu', hashed_password='unused', role='teacher')
        self.db.add_all([Institution(id='i', name='Test'), Institution(id='other', name='Other'), self.user, self.other,
            Course(id='c', institution_id='i', teacher_id='u', course_code='TEST', title='Testing'),
            Exam(id='e', institution_id='i', course_id='c', title='Test exam', language='en')])
        self.db.commit()
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.patches = [patch.object(exam_setup, 'SETUP_DIR', self.dir), patch.object(service, 'SETUP_DIR', self.dir), patch.object(exam_setup, 'dispatch_processing_job')]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.db.close(); self.engine.dispose(); self.temp.cleanup()

    def upload(self, **kwargs):
        out = io.BytesIO(); Image.new('RGB', (30, 30), 'white').save(out, 'PNG'); out.seek(0)
        return asyncio.run(exam_setup.upload_setup('e', UploadFile(filename='exam.png', file=out), None, self.db, kwargs.get('user', self.user)))

    def draft(self):
        data = self.upload()
        job = self.db.get(ProcessingJob, data['job']['id'])
        output = json.dumps({'questions': [{'question_number': '1', 'question_text': 'Explain your reasoning.', 'max_score': 3, 'marking_guide': 'Award credit for valid reasoning.', 'answer_key': ''}], 'warnings': []})
        with patch.object(service, 'generate', return_value=output) as generate:
            service.extract_setup_documents(job, self.db, lambda *args: self.db.commit())
            generate.assert_called_once()
        job.status = 'completed'; self.db.commit()
        return job

    def request(self):
        return service.ConfirmImport(questions=[dict(question_number='1', question_text='Explain.', max_score=3, marking_guide='Valid reasoning.')])

    def test_setup_upload_is_separate_and_private(self):
        result = self.upload()
        self.assertEqual(result['job']['job_type'], 'exam_setup')
        self.assertIsNone(result['job']['submission_id'])
        self.assertEqual(self.db.query(Submission).count(), 0)
        self.assertEqual(self.db.query(Answer).count(), 0)
        self.assertEqual(self.db.query(Question).count(), 0)
        self.assertNotIn('payload', result['job'])
        self.assertNotIn('path', result['documents'][0])
        self.assertEqual(len(exam_setup.list_imports('e', self.db, self.user)), 1)

    def test_institution_isolation(self):
        job = self.draft()
        for call in [lambda: self.upload(user=self.other), lambda: exam_setup.get_import('e', job.id, self.db, self.other),
                     lambda: exam_setup.get_document('e', job.id, 0, self.db, self.other),
                     lambda: exam_setup.confirm('e', job.id, self.request(), self.db, self.other)]:
            with self.assertRaises(HTTPException) as error: call()
            self.assertEqual(error.exception.status_code, 404)

    def test_confirm_creates_only_drafts_and_is_idempotent(self):
        job = self.draft()
        first = exam_setup.confirm('e', job.id, self.request(), self.db, self.user)
        second = exam_setup.confirm('e', job.id, self.request(), self.db, self.user)
        self.assertEqual(first['question_ids'], second['question_ids'])
        self.assertEqual(self.db.query(Question).count(), 1)
        version = self.db.query(RubricVersion).one()
        self.assertEqual(version.status, 'draft')
        question = self.db.query(Question).one()
        self.assertIsNone(question.active_rubric_version_id)
        with self.assertRaises(ValueError): get_effective_rubric(question, self.db)
        with self.assertRaises(HTTPException): service.require_ready(self.db, 'e')
        version.status = 'approved'; question.active_rubric_version_id = version.id; self.db.commit()
        self.assertTrue(service.setup_readiness(self.db, 'e')['ready'])
        self.assertEqual(self.db.query(Submission).count(), 0)

    def test_existing_numbers_not_overwritten(self):
        job = self.draft()
        self.db.add(Question(institution_id='i', exam_id='e', question_number='1', question_text='Original', max_score=1, rubric_json={}, order_index=1))
        self.db.commit()
        with self.assertRaises(HTTPException) as error: exam_setup.confirm('e', job.id, self.request(), self.db, self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.query(Question).one().question_text, 'Original')

    def test_readiness_blocks_student_upload_before_file_write(self):
        from routers.exams import upload_exam
        with patch('routers.exams.store_validated_upload') as store:
            with self.assertRaises(HTTPException) as error:
                asyncio.run(upload_exam('e', UploadFile(filename='student.pdf', file=io.BytesIO(b'')), self.db, self.user))
            self.assertEqual(error.exception.status_code, 409)
            store.assert_not_called()

    def test_checkpoint_retry_does_not_repeat_gemini(self):
        job = self.draft()
        with patch.object(service, 'generate') as generate:
            service.extract_setup_documents(job, self.db, lambda *args: None)
            generate.assert_not_called()

    def test_worker_finishes_setup_without_creating_student_records(self):
        from services.job_execution_service import execute_processing_job
        result = self.upload()
        output = json.dumps({'questions': [{'question_number': '1', 'question_text': 'Test question', 'max_score': 2}], 'warnings': []})
        with patch('services.job_execution_service.SessionLocal', return_value=self.db), patch.object(service, 'generate', return_value=output):
            execute_processing_job(result['job']['id'])
        job = self.db.get(ProcessingJob, result['job']['id'])
        self.assertEqual(job.status, 'completed')
        self.assertEqual(job.progress_current, 1)
        self.assertEqual(len(job.payload['draft_questions']), 1)
        self.assertEqual(self.db.query(Submission).count(), 0)

    def test_blank_exam_null_optional_text_is_normalized(self):
        result = self.upload()
        job = self.db.get(ProcessingJob, result['job']['id'])
        output = json.dumps({'questions': [{
            'question_number': '1',
            'question_text': 'Explain the process.',
            'max_score': 2,
            'marking_guide': None,
            'answer_key': None,
        }], 'warnings': []})

        with patch.object(service, 'generate', return_value=output):
            service.extract_setup_documents(job, self.db, lambda *args: self.db.commit())

        draft = job.payload['draft_questions'][0]
        self.assertEqual(draft['marking_guide'], '')
        self.assertEqual(draft['answer_key'], '')
        self.assertEqual(draft['question_text'], 'Explain the process.')

    def test_unknown_marks_stay_unknown_after_conflicting_pages(self):
        job = self.draft()
        question = job.payload['draft_questions'][0]
        pages = {f'0:{i}': dict(questions=[dict(question, max_score=marks)], warnings=[]) for i, marks in enumerate([3, 4, 3])}
        job.payload = dict(job.payload, pages=pages)
        self.db.commit()
        with patch.object(service, 'generate') as generate:
            service.extract_setup_documents(job, self.db, lambda *args: None)
            generate.assert_not_called()
        self.assertIsNone(job.payload['draft_questions'][0]['max_score'])

    def test_corrupt_second_document_cleans_first(self):
        out = io.BytesIO(); Image.new('RGB', (30, 30)).save(out, 'PNG'); out.seek(0)
        with self.assertRaises(HTTPException):
            asyncio.run(exam_setup.upload_setup('e', UploadFile(filename='valid.png', file=out),
                UploadFile(filename='bad.pdf', file=io.BytesIO(b'%PDF-broken')), self.db, self.user))
        self.assertEqual(list(self.dir.iterdir()), [])
        self.assertEqual(self.db.query(ProcessingJob).count(), 0)

    def test_confirm_failure_rolls_back_all_questions(self):
        job = self.draft()
        request = service.ConfirmImport(questions=[self.request().questions[0].model_dump(), dict(question_number='2', question_text=' ', marking_guide=' ', max_score=1)])
        with self.assertRaises(HTTPException): exam_setup.confirm('e', job.id, request, self.db, self.user)
        self.assertEqual(self.db.query(Question).count(), 0)
        self.assertEqual(self.db.query(RubricVersion).count(), 0)
