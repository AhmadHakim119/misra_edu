"""Isolated provider/verification/transcription contracts; no external inference."""
import json
import os
import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from PIL import Image
from models import Answer, AnswerSource, GradingRun, User
from services.free_model_gateway import FreeCompletion
from services.inference_service import complete, configuration
from services.verification_agent import verify
from services.grading_service import process_grading
from schemas.source_mapping_input import SourceTextCorrectionRequest
from schemas.public_results import ResultRecord
from routers.results import correct_source_text, get_results
from tests import test_grading_package as fixtures


class NativePipelineTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool
        with patch.object(fixtures,'create_engine',side_effect=lambda *_:create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)):
            fixtures.GradingPackageTests.setUp(self)
    tearDown = fixtures.GradingPackageTests.tearDown
    result = fixtures.GradingPackageTests.result

    def test_free_ocr_uses_explicit_provider_and_preserves_image(self):
        image=Image.new('RGB',(20,30),'white')
        with patch.dict(os.environ,{'OCR_PROVIDER':'openrouter_free','OCR_MODEL':'synthetic/vision:free'}), \
             patch('services.inference_service.complete_free',return_value=FreeCompletion('{}',{})) as call:
            complete(['Extract this synthetic page',image],task='ocr')
        self.assertIs(call.call_args.args[0][1],image)
        self.assertEqual(call.call_args.kwargs['model'],'synthetic/vision:free')

    def test_local_remote_endpoint_and_missing_vision_rejected_before_network(self):
        for endpoint,vision in [('https://example.com/v1','true'),('http://127.0.0.1:11434/v1','false')]:
            with patch.dict(os.environ,{'OCR_PROVIDER':'local','LOCAL_AI_MODEL':'synthetic','LOCAL_AI_BASE_URL':endpoint,'LOCAL_AI_VISION':vision}), \
                 patch('urllib.request.urlopen') as send:
                with self.assertRaises(ValueError): complete(['Synthetic',Image.new('RGB',(2,2))],task='ocr')
                send.assert_not_called()

    def test_verifier_requires_every_criterion_and_never_changes_marks(self):
        candidate=self.result();response={'criteria':[{'criterion_id':'logic','verdict':'needs_review','explanation':'The evidence does not establish this step.'}],'summary':'Inspect this criterion.'}
        with patch('services.verification_agent.complete',return_value=FreeCompletion(json.dumps(response),{'provider':'local','model':'synthetic'})):
            result=verify({'rubric':self.rubric},candidate)
        self.assertEqual(result['status'],'needs_review');self.assertEqual(candidate['score'],2)
        response['criteria'][0]['criterion_id']='invented'
        with patch('services.verification_agent.complete',return_value=FreeCompletion(json.dumps(response),{})):
            with self.assertRaises(ValueError): verify({},candidate)

    def test_verification_flags_a_saved_proposal_and_records_stages(self):
        decision={'status':'needs_review','summary':'Check support','criteria':[{'criterion_id':'logic','verdict':'needs_review','explanation':'Check work'}],'inference':{'model':'synthetic-verifier'}}
        with patch.dict(os.environ,{'VERIFICATION_ENABLED':'true','GRADING_PROVIDER':'gemini'}), \
             patch('services.grading_service.generate',return_value=json.dumps(self.result())), \
             patch('services.verification_agent.verify',return_value=decision) as reviewer:
            answer=process_grading('a',self.db)
        self.assertTrue(answer.needs_review);self.assertEqual(answer.score,2)
        self.assertEqual(len(answer.grading_raw_response['agent_pipeline']),3)
        sent=reviewer.call_args.args[0]
        self.assertNotIn('missing-synthetic',json.dumps(sent))
        self.assertEqual(self.db.query(GradingRun).one().response_json['verification']['status'],'needs_review')

    def test_verification_failure_saves_no_grade(self):
        with patch.dict(os.environ,{'VERIFICATION_ENABLED':'true','GRADING_PROVIDER':'gemini'}), \
             patch('services.grading_service.generate',return_value=json.dumps(self.result())), \
             patch('services.verification_agent.verify',side_effect=ValueError('Invalid verifier response')):
            with self.assertRaises(ValueError): process_grading('a',self.db)
        self.assertIsNone(self.answer.score);self.assertEqual(self.db.query(GradingRun).count(),0)

    def test_transcription_correction_preserves_original_and_rejects_stale_or_foreign(self):
        user=SimpleNamespace(id='teacher',institution_id='i')
        payload=SourceTextCorrectionRequest(text='My corrected solution',expected_text='My solution')
        report=correct_source_text('source',payload,self.db,user)
        self.assertEqual(self.db.get(AnswerSource,'source').ocr_segment['original_extracted_text'],'My solution')
        self.assertEqual(self.answer.raw_ocr_text,'My corrected solution')
        with self.assertRaises(HTTPException) as error: correct_source_text('source',payload,self.db,user)
        self.assertEqual(error.exception.status_code,409)
        with self.assertRaises(HTTPException) as error: correct_source_text('source',payload,self.db,SimpleNamespace(id='foreign',institution_id='other'))
        self.assertEqual(error.exception.status_code,404)

    def test_correction_refuses_graded_evidence(self):
        self.answer.score=1;self.db.commit()
        with self.assertRaises(HTTPException) as error:
            correct_source_text('source',SourceTextCorrectionRequest(text='Changed',expected_text='My solution'),self.db,SimpleNamespace(id='teacher',institution_id='i'))
        self.assertEqual(error.exception.status_code,409);self.assertEqual(self.answer.raw_ocr_text,'My solution')

    def test_identity_correction_keeps_unrelated_course_instructor(self):
        from models import Course
        from schemas.submission_metadata_input import SubmissionMetadataUpdate
        from routers.results import update_submission_metadata
        course=Course(id='c',institution_id='i',teacher_id='teacher',title='Synthetic course',instructor_name='Existing instructor')
        self.db.add(course);self.db.commit()
        update_submission_metadata('s',SubmissionMetadataUpdate(student_name='Synthetic student',student_number='TEST1'),self.db,SimpleNamespace(id='teacher',institution_id='i'))
        self.assertEqual(course.instructor_name,'Existing instructor')
        self.assertEqual(self.db.get(fixtures.Submission,'s').identity_status,'matched')

    def test_public_results_hide_storage_paths(self):
        import asyncio
        self.answer.grading_raw_response={'grading_package':{'answer_key':{'document_refs':[{'path':'private-location','job_id':'job'}]}}}
        self.db.commit()
        data=asyncio.run(get_results('s',self.db,SimpleNamespace(institution_id='i')))
        public=ResultRecord.model_validate(data).model_dump()
        self.assertNotIn('original_file_path',public['submission'])
        self.assertNotIn('private-location',json.dumps(public,default=str))

    def test_review_history_serializes_every_decision_and_rejects_other_institution(self):
        from routers.review_resolution import resolve_review, review_history
        from schemas.review_input import ReviewResolutionRequest
        from schemas.public_results import ReviewResolutionRecord, ReviewRecord
        user=SimpleNamespace(id='teacher',institution_id='i')
        self.answer.score=2;self.answer.max_score=2;self.db.commit()
        accepted=resolve_review('a',ReviewResolutionRequest(action='approve',was_review_warranted=False),self.db,user)
        public=ReviewResolutionRecord.model_validate(accepted).model_dump()
        self.assertEqual(public['answer']['review_status'],'approved')
        resolve_review('a',ReviewResolutionRequest(action='override',human_score=1,was_review_warranted=True,review_reason_codes=['rubric_issue']),self.db,user)
        records=[ReviewRecord.model_validate(row).model_dump() for row in review_history('a',self.db,user)]
        self.assertEqual(len(records),2)
        self.assertEqual({r['human_score'] for r in records},{1,2})
        self.assertTrue(any(r['supersedes_label_id']==public['review_label']['id'] for r in records))
        with self.assertRaises(HTTPException) as error: review_history('a',self.db,SimpleNamespace(institution_id='other'))
        self.assertEqual(error.exception.status_code,404)

    def test_policy_read_and_write_are_institution_scoped(self):
        from routers.grading_policies import get_grading_policy, upsert_grading_policy
        from schemas.grading_policy_input import QuestionGradingPolicyRequest
        foreign=SimpleNamespace(institution_id='other')
        with self.assertRaises(HTTPException) as error: get_grading_policy('q',self.db,foreign)
        self.assertEqual(error.exception.status_code,404)
        with self.assertRaises(HTTPException) as error: upsert_grading_policy('q',QuestionGradingPolicyRequest(mode='adaptive'),self.db,foreign)
        self.assertEqual(error.exception.status_code,404)

    def test_http_create_exam_accepts_native_form_and_rejects_missing_fields(self):
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from database import get_db
        from services.auth_dependencies import require_instructor
        from models import Course, Exam
        from routers import exams
        self.db.add(Course(id='c',institution_id='i',teacher_id='teacher',course_code='TEST',title='Synthetic physics'))
        self.db.commit()
        app=FastAPI();app.include_router(exams.router)
        app.dependency_overrides[get_db]=lambda:self.db
        app.dependency_overrides[require_instructor]=lambda:SimpleNamespace(id='teacher',institution_id='i')
        async def exercise():
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                rejected=await client.post('/api/exams',json={})
                self.assertEqual(rejected.status_code,422)
                self.assertEqual({error['loc'][-1] for error in rejected.json()['detail']},{'course_id','title'})
                created=await client.post('/api/exams',json={'course_id':'c','title':'Synthetic grading test','language':'en'})
                self.assertEqual(created.status_code,201,created.text)
                record=self.db.get(Exam,created.json()['id'])
                self.assertEqual((record.course_id,record.title,record.language),('c','Synthetic grading test','en'))
                self.assertEqual(record.institution_id,'i')
        asyncio.run(exercise())

    def test_http_correction_grade_results_review_and_history_contracts(self):
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from database import get_db
        from services.auth_dependencies import require_instructor
        from routers import results, review_resolution, grading
        app=FastAPI()
        for router in [results.router,review_resolution.router,grading.router]:app.include_router(router)
        app.dependency_overrides[get_db]=lambda:self.db
        app.dependency_overrides[require_instructor]=lambda:SimpleNamespace(id='teacher',institution_id='i')
        async def exercise():
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                correction=await client.patch('/api/answer-sources/source/text',json={'text':'Corrected synthetic work','expected_text':'My solution'})
                self.assertEqual(correction.status_code,200,correction.text)
                with patch.dict(os.environ,{'VERIFICATION_ENABLED':'true','GRADING_PROVIDER':'gemini'}),patch('services.grading_service.generate',return_value=json.dumps(self.result())),patch('services.verification_agent.verify',return_value={'status':'checked','summary':'Synthetic verifier','criteria':[]}):
                    process_grading('a',self.db)
                result=await client.get('/api/results/s');self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['answers'][0]['score'],2)
                self.assertNotIn('original_file_path',result.json()['submission'])
                review=await client.post('/api/answers/a/resolve-review',json={'action':'approve','was_review_warranted':False})
                self.assertEqual(review.status_code,200,review.text)
                self.assertEqual(review.json()['answer']['review_status'],'approved')
                result=await client.get('/api/results/s');self.assertEqual(len(result.json()['latest_review_labels']),1)
                history=await client.get('/api/answers/a/review-history');self.assertEqual(len(history.json()),1)
                runs=await client.get('/api/answers/a/grading-runs');self.assertEqual(runs.status_code,200,runs.text)
                self.assertEqual(runs.json()[0]['response_json']['verification']['status'],'checked')
                refused=await client.patch('/api/answer-sources/source/text',json={'text':'Overwrite graded work','expected_text':'Corrected synthetic work'})
                self.assertEqual(refused.status_code,409)
        asyncio.run(exercise())


if __name__=='__main__':unittest.main()
