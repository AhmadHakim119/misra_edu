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
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile
from database import Base
from models import Answer, Course, Exam, Institution, ProcessingJob, Question, RubricVersion, Submission, User
from routers import exam_setup
from services import exam_setup_service as service
from services.rubric_version_service import get_effective_rubric
from services.openrouter_client import OpenRouterError


class ExamSetupTests(unittest.TestCase):
    def test_exact_repeated_stem_is_removed_but_not_partial_shared_text(self):
        stem='A wheel starts at 6.35 rad/s. How long does it rotate?'
        self.assertEqual(service._remove_exact_repetition(stem+' '+stem),stem)
        self.assertEqual(service._remove_exact_repetition(stem+' Explain your method.'),stem+' Explain your method.')

    def test_similar_wording_is_retained_as_a_variant_instead_of_doubled(self):
        stem='Find the moment of inertia about the x axis and calculate the applied torque.'
        existing={'question_number':'p6.1','question_text':stem};warnings=[]
        incoming={'question_text':stem.replace('x axis','y axis')}
        service._merge_question_wording(existing,incoming,'1:9',warnings)
        self.assertEqual(existing['question_text'],stem)
        self.assertEqual(existing['wording_variants'][0]['question_text'],incoming['question_text'])
        self.assertTrue(warnings)

    def test_real_continuation_is_kept(self):
        existing={'question_number':'p6.1','question_text':'Find the moment of inertia.'}
        service._merge_question_wording(existing,{'question_text':'(b) Calculate the torque for angular acceleration 1.20 rad/s².'},'0:10',[])
        self.assertIn('(b) Calculate',existing['question_text'])

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

    def approved_profile(self):
        from models import InstructorPreferenceVersion
        self.db.add(InstructorPreferenceVersion(institution_id='i',user_id='u',created_by='u',approved_by='u',
            version_number=1,status='approved',scenario_answers=[],explicit_preferences={},proposal_provenance={},
            derived_proposal={'units_policy':'do_not_penalize','rounding_tolerance_percent':0}))
        self.db.commit()

    def test_import_uses_survey_defaults_once_without_approval_or_retry_rewrite(self):
        from models import InstructorAccountSettings
        self.approved_profile();job=self.draft()
        first=exam_setup.confirm('e',job.id,self.request(),self.db,self.user)
        rubric=self.db.query(RubricVersion).one()
        self.assertEqual(rubric.status,'draft')
        self.assertEqual(rubric.rubric_json['policy']['units_policy'],'do_not_penalize')
        self.assertEqual(rubric.rubric_json['policy']['rounding_tolerance_percent'],0)
        self.db.add(InstructorAccountSettings(user_id='u',institution_id='i',use_marking_preferences=False));self.db.commit()
        again=exam_setup.confirm('e',job.id,self.request(),self.db,self.user)
        self.assertEqual(first,again);self.assertEqual(self.db.query(RubricVersion).count(),1)
        self.db.refresh(rubric);self.assertEqual(rubric.rubric_json['policy']['units_policy'],'do_not_penalize')

    def test_import_respects_account_opt_out(self):
        from models import InstructorAccountSettings
        self.approved_profile()
        self.db.add(InstructorAccountSettings(user_id='u',institution_id='i',use_marking_preferences=False));self.db.commit()
        job=self.draft();exam_setup.confirm('e',job.id,self.request(),self.db,self.user)
        self.assertEqual(self.db.query(RubricVersion).one().rubric_json['policy']['units_policy'],'required_when_applicable')

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

    def test_explicit_mcq_import_accepts_blank_guide_as_binary_draft(self):
        job = self.draft()
        request = service.ConfirmImport(questions=[dict(question_number='1',
            question_text='Choose the SI unit of force: a) N b) J.', max_score=1,
            marking_guide='', answer_key='a) N', multiple_choice=True)])
        first = exam_setup.confirm('e', job.id, request, self.db, self.user)
        again = exam_setup.confirm('e', job.id, request, self.db, self.user)
        self.assertEqual(first['question_ids'], again['question_ids'])
        rubric = self.db.query(RubricVersion).one()
        self.assertEqual(rubric.status, 'draft')
        criterion = rubric.rubric_json['criteria'][0]
        self.assertEqual(criterion['title'], 'Correct option')
        self.assertEqual(criterion['scoring_type'], 'binary')
        self.assertFalse(criterion['partial_credit_allowed'])
        self.assertEqual(criterion['points'], 1)
        self.assertEqual(rubric.rubric_json['reference_context'], 'a) N')
        self.assertIsNone(self.db.query(Question).one().active_rubric_version_id)
        with self.assertRaises(HTTPException):
            service.require_ready(self.db, 'e')

    def test_blank_guides_still_require_explicit_mcq_and_a_correct_answer(self):
        common = dict(question_number='1', question_text='Choose an option.', max_score=1)
        for fields in [dict(marking_guide='', answer_key='a'),
                       dict(marking_guide='   ', answer_key='a'),
                       dict(marking_guide='', answer_key='', multiple_choice=True),
                       dict(marking_guide='', answer_key='  ', multiple_choice=True)]:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                service.ConfirmImport(questions=[dict(common, **fields)])
        for marks in [None, 0, float('nan')]:
            with self.subTest(marks=marks), self.assertRaises(ValidationError):
                service.ConfirmImport(questions=[dict(common, max_score=marks,
                    marking_guide='', answer_key='a', multiple_choice=True)])
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

    def test_invalid_question_shape_gets_one_same_page_format_repair(self):
        result = self.upload()
        job = self.db.get(ProcessingJob, result['job']['id'])
        invalid = json.dumps({'questions':[dict(question_number='1', question_text=None,
            max_score=None, marking_guide='', answer_key='PRIVATE_PROVIDER_OUTPUT')], 'warnings':[]})
        valid = json.dumps({'questions':[dict(question_number='1', question_text='Printed question',
            max_score=None, marking_guide='', answer_key='Checked reference')], 'warnings':[]})
        with patch.object(service, 'generate', side_effect=[invalid, valid]) as generate:
            service.extract_setup_documents(job, self.db, lambda *args: self.db.commit())
        self.assertEqual(generate.call_count, 2)
        first, repair = [c.args[0] for c in generate.call_args_list]
        self.assertIs(first[1], repair[1])
        self.assertIn('Required response JSON schema', first[0])
        self.assertIn('questions.0.question_text', repair[0])
        self.assertNotIn('PRIVATE_PROVIDER_OUTPUT', repair[0])
        self.assertIsNone(job.payload['draft_questions'][0]['max_score'])
        self.assertEqual(job.payload['draft_questions'][0]['question_text'], 'Printed question')
        self.assertEqual(self.db.query(Question).count(), 0)

    def test_invalid_json_gets_one_format_repair(self):
        result = self.upload()
        job = self.db.get(ProcessingJob, result['job']['id'])
        valid = json.dumps({'questions':[dict(question_number='1', question_text='Printed question',
            max_score=2)], 'warnings':[]})
        with patch.object(service, 'generate', side_effect=['not JSON PRIVATE_PROVIDER_OUTPUT', valid]) as generate:
            service.extract_setup_documents(job, self.db, lambda *args: self.db.commit())
        self.assertEqual(generate.call_count, 2)
        self.assertNotIn('PRIVATE_PROVIDER_OUTPUT', generate.call_args.args[0][0])
        self.assertEqual(set(job.payload['pages']), {'0:0'})

    def test_repeated_invalid_question_data_stops_without_checkpoint_or_output_leak(self):
        result = self.upload()
        job = self.db.get(ProcessingJob, result['job']['id'])
        invalid = json.dumps({'questions':[dict(question_number='1', question_text=None,
            answer_key='PRIVATE_PROVIDER_OUTPUT')], 'warnings':[]})
        with patch.object(service, 'generate', return_value=invalid) as generate:
            with self.assertRaisesRegex(ValueError, 'after one format retry') as caught:
                service.extract_setup_documents(job, self.db, lambda *args: self.db.commit())
        self.assertEqual(generate.call_count, 2)
        self.assertNotIn('PRIVATE_PROVIDER_OUTPUT', str(caught.exception))
        self.assertNotIn('input_value', str(caught.exception))
        self.assertFalse(job.payload.get('pages'))
        self.assertNotIn('draft_questions', job.payload)
        self.assertEqual(self.db.query(Question).count(), 0)

    def test_partial_setup_provider_failure_resumes_after_committed_page(self):
        pdf = io.BytesIO()
        Image.new('RGB', (30, 30), 'white').save(pdf, 'PDF', save_all=True,
            append_images=[Image.new('RGB', (30, 30), 'white')])
        pdf.seek(0)
        result = asyncio.run(exam_setup.upload_setup('e',
            UploadFile(filename='synthetic.pdf', file=pdf), None, self.db, self.user))
        job = self.db.get(ProcessingJob, result['job']['id'])
        first = json.dumps({'questions':[dict(question_number='1', question_text='First question',
            max_score=2, marking_guide='First guide', answer_key='First reference')], 'warnings':[]})
        second = json.dumps({'questions':[dict(question_number='2', question_text='Second question',
            max_score=2, marking_guide='Second guide', answer_key='Second reference')], 'warnings':[]})

        def progress(current, total, message):
            job.progress_current, job.progress_total = current, total
            job.progress_message = message
            self.db.commit()

        def page_image(*args, **kwargs):
            return [Image.new('RGB', (30, 30), 'white')]

        with patch.object(service, 'convert_from_path', side_effect=page_image), \
             patch.object(service, 'generate', side_effect=[first, OpenRouterError('HTTP 502')]):
            with self.assertRaisesRegex(OpenRouterError, '502'):
                service.extract_setup_documents(job, self.db, progress)
        self.db.rollback()
        self.db.expire_all()
        job = self.db.get(ProcessingJob, result['job']['id'])
        self.assertEqual(set(job.payload['pages']), {'0:0'})
        self.assertEqual(job.progress_current, 1)
        self.assertNotIn('draft_questions', job.payload)

        with patch.object(service, 'convert_from_path', side_effect=page_image) as render, \
             patch.object(service, 'generate', return_value=second) as generate:
            service.extract_setup_documents(job, self.db, progress)
        generate.assert_called_once()
        self.assertEqual(render.call_args.kwargs['first_page'], 2)
        self.assertEqual([q['question_number'] for q in job.payload['draft_questions']], ['1', '2'])
        self.assertEqual(job.progress_current, 2)
        self.assertEqual(self.db.query(Question).count(), 0)
        self.assertEqual(self.db.query(Submission).count(), 0)

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
        request = service.ConfirmImport(questions=[self.request().questions[0].model_dump(), dict(question_number='2', question_text=' ', marking_guide='Valid marking rule.', max_score=1)])
        with self.assertRaises(HTTPException): exam_setup.confirm('e', job.id, request, self.db, self.user)
        self.assertEqual(self.db.query(Question).count(), 0)
        self.assertEqual(self.db.query(RubricVersion).count(), 0)
