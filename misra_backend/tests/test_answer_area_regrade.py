"""Versioned answer-area corrections: synthetic originals and mocked providers only."""
import json
import asyncio
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException, Response
from PIL import Image
from pydantic import ValidationError

from models import AnswerSource, GradingRun, ProcessingJob, Submission
from routers.answer_areas import preview_area, get_area_preview, confirm_source_area, regrade_area_answer
from schemas.answer_area_input import AreaPreviewRequest, AreaConfirmRequest, AreaRegradeRequest
from services.answer_area_service import (OPERATION, confirm_area, crop_area, document_hash,
    latest_revision, read_area_job, regrade_corrected_answer, source_signature)
from services.extraction_review_service import build_extraction_review
from services.free_model_gateway import FreeCompletion
from services.grading_package_service import build_grading_package, provider_grading_package
from services.grading_service import process_grading
from services.job_queue_service import job_to_dict
from tests import test_grading_package as fixtures


class AnswerAreaTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool
        with patch.object(fixtures,'create_engine',side_effect=lambda *_:create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)):
            fixtures.GradingPackageTests.setUp(self)
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'synthetic-original.png'
        Image.new('RGB',(800,600),'white').save(self.path)
        self.submission=self.db.get(Submission,'s');self.submission.original_file_path=str(self.path)
        self.source=self.db.get(AnswerSource,'source')
        self.user=SimpleNamespace(id=None,institution_id='i')
        self.box=dict(x=.1,y=.5,width=.8,height=.2)
        self.db.commit()

    tearDown=fixtures.GradingPackageTests.tearDown
    result=fixtures.GradingPackageTests.result

    def preview_job(self, status='completed', **changes):
        data=dict(operation=OPERATION,source_id='source',page_index=0,
            source_signature=source_signature(self.source),document_sha256=document_hash(self.submission),
            base_revision_id=(latest_revision(self.db,self.source,'i') or {}).get('id'),bounding_box=self.box,
            area_preview=dict(text='W = 82 x 3 = 246 J',language='en',legibility='clear'))
        data.update(changes)
        job=ProcessingJob(institution_id='i',submission_id='s',job_type='ocr_submission',status=status,payload=data)
        self.db.add(job);self.db.commit();return job

    def confirm(self,job=None,**changes):
        job=job or self.preview_job()
        data=dict(text='W = 82 × 3 = 246 J',expected_preview_text=job.payload['area_preview']['text'],
            expected_revision_id=job.payload.get('base_revision_id'),complete_answer=True)
        data.update(changes)
        return confirm_area(self.db,self.source,self.submission,job,AreaConfirmRequest(**data),self.user)

    def test_strict_area_schema_and_real_pixel_crop(self):
        image=Image.new('RGB',(800,600),'white')
        self.assertEqual(crop_area(image,self.box).size,(640,120))
        self.assertEqual(image.size,(800,600))
        for box in [dict(x=.9,y=.5,width=.8,height=.2),dict(x=-.1,y=0,width=.2,height=.2)]:
            with self.assertRaises(ValidationError):AreaPreviewRequest(bounding_box=box,expected_text='')
        with self.assertRaisesRegex(ValueError,'larger'):crop_area(image,dict(x=0,y=0,width=.001,height=.001))
        with self.assertRaises(ValidationError):AreaConfirmRequest(text='x',expected_preview_text='x',complete_answer='true')

    def test_read_passes_full_original_and_crop_without_replacing_sources_or_grades(self):
        job=self.preview_job(status='processing',area_preview=None);before=deepcopy(self.source.ocr_segment)
        self.answer.score=1;self.answer.teacher_override_score=.5;self.db.commit()
        with patch('services.answer_area_service.complete',return_value=FreeCompletion(
                json.dumps(dict(text='W = 82 + 3 = 85 J',language='en',legibility='clear')),{})) as provider:
            read_area_job(job,self.db,lambda *args:None)
        contents=provider.call_args.args[0]
        self.assertEqual([contents[2].size,contents[4].size],[(800,600),(640,120)])
        self.assertNotIn('Old key',contents[0]);self.assertEqual(provider.call_args.kwargs['task'],'ocr')
        self.assertEqual(job.payload['area_preview']['text'],'W = 82 + 3 = 85 J')
        self.assertEqual(self.source.extracted_text,'My solution');self.assertEqual(self.source.ocr_segment,before)
        self.assertEqual(float(self.answer.score),1);self.assertEqual(float(self.answer.teacher_override_score),.5)
        self.assertEqual(self.db.query(GradingRun).count(),0)

    def test_saved_preview_is_a_worker_retry_checkpoint(self):
        job=self.preview_job(status='processing')
        with patch('services.answer_area_service.complete') as provider:
            read_area_job(job,self.db,lambda *args:None)
            provider.assert_not_called()

    def test_changed_original_or_text_stops_read_before_provider(self):
        for change in ['text','file']:
            job=self.preview_job()
            if change=='text':self.source.extracted_text='Changed';self.db.commit()
            else:Image.new('RGB',(800,600),'black').save(self.path)
            with patch('services.answer_area_service.complete') as provider:
                with self.assertRaisesRegex(ValueError,'changed'):read_area_job(job,self.db,lambda *args:None)
                provider.assert_not_called()

    def test_confirmation_is_versioned_requires_review_and_is_idempotent(self):
        job=self.preview_job()
        for changes in [dict(complete_answer=False),dict(expected_preview_text='stale'),dict(text=' ')]:
            with self.assertRaises(ValueError):self.confirm(job,**changes)
        revision=self.confirm(job)
        self.assertEqual(revision['revision_number'],1);self.assertEqual(self.confirm(job),revision)
        self.assertEqual(self.source.extracted_text,'My solution');self.assertEqual(self.answer.raw_ocr_text,'My solution')
        self.assertIsNone(self.answer.score)
        with self.assertRaisesRegex(ValueError,'already saved'):self.confirm(job,text='Different')
        newer=self.confirm()
        self.assertEqual(newer['revision_number'],2)
        with self.assertRaisesRegex(ValueError,'newer correction'):self.confirm(job)

    def test_concurrent_preview_cannot_overwrite_newer_confirmation(self):
        first=self.preview_job();stale=self.preview_job();self.confirm(first)
        with self.assertRaisesRegex(ValueError,'Another area correction'):self.confirm(stale)
        self.assertNotIn('area_confirmation',stale.payload)

    def test_mysql_write_paths_use_current_reads_without_locking_display_reads(self):
        from sqlalchemy import event
        from sqlalchemy.dialects import mysql
        self.confirm();statements=[]
        def capture(state):
            sql=str(state.statement.compile(dialect=mysql.dialect()))
            if 'FROM processing_jobs' in sql:statements.append(sql)
        event.listen(self.db,'do_orm_execute',capture)
        try:
            latest_revision(self.db,self.source,'i')
            latest_revision(self.db,self.source,'i',for_update=True)
        finally:event.remove(self.db,'do_orm_execute',capture)
        self.assertEqual(len(statements),2)
        self.assertNotIn('FOR UPDATE',statements[0]);self.assertIn('FOR UPDATE',statements[1])

    def test_package_uses_confirmed_text_and_keeps_full_original_evidence(self):
        revision=self.confirm()
        package,*_=build_grading_package(self.answer,self.q,self.db,'image_text')
        self.assertEqual(package['student_evidence'][0]['text'],revision['text'])
        self.assertEqual(package['original_student_evidence']['combined_ocr'],'My solution')
        self.assertEqual(package['original_student_evidence']['sources'][0]['text'],'My solution')
        images=[item for item in package['student_evidence'] if item['kind']=='student_image']
        self.assertEqual(len(images),2);self.assertEqual(images[0]['id'],'page:0')
        self.assertEqual(images[1]['bounding_box'],self.box)
        projected,*_=provider_grading_package(package)
        encoded=json.dumps(projected)
        for private in [revision['id'],revision['document_sha256'],str(self.path),'confirmed_by']:
            self.assertNotIn(private,encoded)
        self.assertIn('instructor_selected_region',encoded)
        Image.new('RGB',(800,600),'black').save(self.path)
        with self.assertRaisesRegex(ValueError,'original paper changed'):
            build_grading_package(self.answer,self.q,self.db,'image_text')

    def test_effective_revision_disappears_when_original_source_changes(self):
        self.confirm();self.source.extracted_text='New original';self.db.commit()
        self.assertIsNone(latest_revision(self.db,self.source,'i'))
        package,*_=build_grading_package(self.answer,self.q,self.db,'text_only')
        self.assertNotIn('selected_answer_areas',package)

    def test_new_run_preserves_instructor_grade_and_old_snapshots(self):
        with patch('services.grading_service.generate',return_value=json.dumps(self.result())):
            process_grading('a',self.db)
        old=self.db.query(GradingRun).one();old_snapshot=deepcopy(old.response_json);old_text=old.ocr_text_snapshot
        self.answer.review_status='approved';self.db.commit();revision=self.confirm()
        response=self.result(points_earned=0);response['score']=0
        with patch('services.grading_service.generate',return_value=json.dumps(response)) as provider:
            process_grading('a',self.db,mode='image_text',preserve_reviewed_grade=True,require_new_review=True)
        images=[item for item in provider.call_args.kwargs['contents'] if isinstance(item,Image.Image)]
        self.assertEqual([image.size for image in images],[(800,600),(640,120)])
        self.assertEqual(float(self.answer.score),0);self.assertEqual(float(self.answer.teacher_override_score),2)
        self.assertTrue(self.answer.needs_review)
        self.assertEqual(old.response_json,old_snapshot);self.assertEqual(old.ocr_text_snapshot,old_text)
        run=self.db.get(GradingRun,self.answer.grading_raw_response['grading_run_id'])
        self.assertNotEqual(run.id,old.id);self.assertTrue(run.needs_review)
        self.assertEqual(run.ocr_text_snapshot,revision['text']);self.assertEqual(self.answer.raw_ocr_text,'My solution')

    def test_existing_override_is_preserved(self):
        self.confirm();self.answer.score=1;self.answer.teacher_override_score=.5;self.answer.review_status='overridden';self.db.commit()
        with patch('services.grading_service.generate',return_value=json.dumps(self.result())):
            process_grading('a',self.db,mode='image_text',preserve_reviewed_grade=True,require_new_review=True)
        self.assertEqual(float(self.answer.teacher_override_score),.5);self.assertTrue(self.answer.needs_review)

    def test_verifier_receives_full_original_and_selected_crop(self):
        self.confirm()
        with patch.dict('os.environ',{'VERIFICATION_ENABLED':'true'}), \
             patch('services.verification_agent.verify',return_value={'status':'needs_review'}) as verifier, \
             patch('services.grading_service.generate',return_value=json.dumps(self.result())):
            process_grading('a',self.db,mode='image_text',preserve_reviewed_grade=True,require_new_review=True)
        self.assertEqual([image.size for image in verifier.call_args.args[2]],[(800,600),(640,120)])
        self.assertEqual(verifier.call_args.args[0]['student_evidence'][0]['text'],'W = 82 × 3 = 246 J')

    def test_required_course_evidence_is_still_enforced_after_area_confirmation(self):
        self.confirm()
        with patch('services.grading_package_service.retrieve_for_question',side_effect=ValueError('Required course evidence unavailable')), \
             patch('services.grading_service.generate') as provider:
            with self.assertRaisesRegex(ValueError,'Required course evidence'):
                process_grading('a',self.db,mode='image_text',preserve_reviewed_grade=True,require_new_review=True)
            provider.assert_not_called()
        self.assertEqual(self.db.query(GradingRun).count(),0)

    def test_foreign_source_and_preview_are_hidden(self):
        request=AreaPreviewRequest(bounding_box=self.box,expected_text=self.source.extracted_text)
        foreign=SimpleNamespace(id=None,institution_id='other')
        for call in [lambda:preview_area('source',request,self.db,foreign),
                     lambda:get_area_preview('source','missing',self.db,self.user),
                     lambda:regrade_area_answer('a',AreaRegradeRequest(revision_ids=['x'],request_id=uuid4()),self.db,foreign)]:
            with self.assertRaises(HTTPException) as error:call()
            self.assertEqual(error.exception.status_code,404)

    def test_preview_request_retries_reuse_pending_job_and_active_grade_blocks(self):
        request=AreaPreviewRequest(bounding_box=self.box,expected_text=self.source.extracted_text)
        with patch('services.job_queue_service.dispatch_processing_job',side_effect=lambda job,db:job):
            result=preview_area('source',request,self.db,self.user)
            again=preview_area('source',request,self.db,self.user)
        self.assertEqual(result['job']['id'],again['job']['id'])
        job=self.db.get(ProcessingJob,result['job']['id']);job.job_type='grade_submission';job.payload={};self.db.commit()
        with self.assertRaises(HTTPException) as error:preview_area('source',request,self.db,self.user)
        self.assertEqual(error.exception.status_code,409)

    def test_report_exposes_pending_then_confirmed_revision_and_locations(self):
        from routers.results import get_source_locations
        job=self.preview_job()
        source=build_extraction_review('s',self.db)['questions'][0]['sources'][0]
        self.assertEqual(source['pending_area_job_id'],job.id);self.assertIsNone(source['area_revision'])
        self.confirm(job)
        source=build_extraction_review('s',self.db)['questions'][0]['sources'][0]
        self.assertIsNone(source['pending_area_job_id']);self.assertEqual(source['area_revision']['id'],job.id)
        locations=get_source_locations('s',Response(),0,self.db,self.user)
        self.assertEqual(locations['sources']['source']['method'],'instructor_confirmed_area')

    def test_explicit_regrade_pins_current_run_revisions_and_request(self):
        revision=self.confirm();self.answer.score=1;self.answer.grading_raw_response={'grading_run_id':'old'};self.db.commit()
        request=AreaRegradeRequest(expected_run_id='old',revision_ids=[revision['id']],request_id=uuid4())
        with patch('services.job_queue_service.dispatch_processing_job',side_effect=lambda job,db:job), \
             patch('routers.grading._require_verified_mapping') as guard:
            result=regrade_area_answer('a',request,self.db,self.user)
            again=regrade_area_answer('a',request,self.db,self.user)
        self.assertEqual(result['job']['id'],again['job']['id']);guard.assert_called_once_with('s',self.db)
        job=self.db.get(ProcessingJob,result['job']['id'])
        self.assertEqual(job.payload['mode'],'image_text');self.assertEqual(job.payload['revision_ids'],[revision['id']])
        self.assertEqual(float(self.answer.score),1);self.assertEqual(self.db.query(GradingRun).count(),0)

    def test_stale_revision_or_run_rejects_regrade_before_queue(self):
        revision=self.confirm();self.answer.grading_raw_response={'grading_run_id':'old'};self.db.commit()
        for run,revisions in [('wrong',[revision['id']]),('old',['unknown']),('old',[revision['id']]*2)]:
            request=AreaRegradeRequest(expected_run_id=run,revision_ids=revisions,request_id=uuid4())
            with self.assertRaises(HTTPException) as error:regrade_area_answer('a',request,self.db,self.user)
            self.assertEqual(error.exception.status_code,409)

    def test_worker_dispatches_area_read_without_reextracting_the_paper(self):
        from services.job_execution_service import execute_processing_job
        job=self.preview_job(status='queued')
        with patch('services.job_execution_service.SessionLocal',return_value=self.db), \
             patch.object(self.db,'close'),patch('services.answer_area_service.read_area_job') as read, \
             patch('services.job_execution_service.process_submission') as extract:
            execute_processing_job(job.id)
        read.assert_called_once();extract.assert_not_called();self.assertEqual(job.status,'completed')

    def test_worker_dispatches_answer_regrade_without_whole_paper_regrade(self):
        from services.job_execution_service import execute_processing_job
        job=ProcessingJob(institution_id='i',submission_id='s',job_type='grade_submission',status='queued',
            payload={'operation':'regrade_corrected_answer','answer_id':'a'})
        self.db.add(job);self.db.commit()
        with patch('services.job_execution_service.SessionLocal',return_value=self.db), \
             patch.object(self.db,'close'),patch('services.answer_area_service.regrade_corrected_answer') as grade, \
             patch('services.job_execution_service._grade_submission') as whole:
            execute_processing_job(job.id)
        grade.assert_called_once();whole.assert_not_called();self.assertEqual(job.status,'completed')

    def test_worker_regrade_checkpoint_never_creates_duplicate_run(self):
        revision=self.confirm()
        job=ProcessingJob(institution_id='i',submission_id='s',job_type='grade_submission',status='processing',
            payload=dict(operation='regrade_corrected_answer',answer_id='a',revision_ids=[revision['id']],expected_run_id=None))
        self.db.add(job);self.db.commit()
        with patch('services.grading_service.generate',return_value=json.dumps(self.result())) as provider:
            regrade_corrected_answer(job,self.db,lambda *args:None)
            regrade_corrected_answer(job,self.db,lambda *args:None)
        provider.assert_called_once();self.assertEqual(self.db.query(GradingRun).count(),1)
        self.assertEqual(self.submission.status,'needs_review')
        self.assertEqual(job_to_dict(job)['operation'],'regrade_corrected_answer')

    def test_worker_rejects_stale_revisions_before_model_call(self):
        revision=self.confirm();self.confirm()
        job=ProcessingJob(institution_id='i',submission_id='s',job_type='grade_submission',status='processing',
            payload=dict(operation='regrade_corrected_answer',answer_id='a',revision_ids=[revision['id']],expected_run_id=None))
        self.db.add(job);self.db.commit()
        with patch('services.grading_service.generate') as provider:
            with self.assertRaisesRegex(ValueError,'extraction changed'):regrade_corrected_answer(job,self.db,lambda *args:None)
            provider.assert_not_called()

    def test_http_corrected_extraction_regrade_and_history_contracts(self):
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from database import get_db
        from services.auth_dependencies import require_instructor
        from routers import answer_areas, results, grading, review_resolution
        from services.job_execution_service import execute_processing_job
        with patch('services.grading_service.generate',return_value=json.dumps(self.result())):
            process_grading('a',self.db)
        old_run=self.answer.grading_raw_response['grading_run_id']
        self.submission.status='graded';self.db.commit()
        app=FastAPI()
        for router in [answer_areas.router,results.router,grading.router,review_resolution.router]:app.include_router(router)
        app.dependency_overrides[get_db]=lambda:self.db
        app.dependency_overrides[require_instructor]=lambda:self.user
        async def exercise():
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                approved=await client.post('/api/answers/a/resolve-review',json={'action':'approve','grading_run_id':old_run,'was_review_warranted':False})
                self.assertEqual(approved.status_code,200,approved.text)
                with patch('services.job_queue_service.dispatch_processing_job',side_effect=lambda job,db:job):
                    queued=await client.post('/api/answer-sources/source/area-preview',json={'bounding_box':self.box,'expected_text':'My solution'})
                self.assertEqual(queued.status_code,202,queued.text)
                job_id=queued.json()['job']['id']
                job=self.db.get(ProcessingJob,job_id)
                with patch('services.job_execution_service.SessionLocal',return_value=self.db),patch.object(self.db,'close'), \
                     patch('services.answer_area_service.complete',return_value=FreeCompletion(json.dumps({'text':'W = 82 × 3 = 246 J','language':'en','legibility':'clear'}),{})):
                    execute_processing_job(job_id)
                preview=await client.get(f'/api/answer-sources/source/area-preview/{job_id}')
                self.assertEqual(preview.status_code,200,preview.text)
                text=preview.json()['preview']['text']
                confirmed=await client.post(f'/api/answer-sources/source/area-preview/{job_id}/confirm',json={
                    'text':text,'expected_preview_text':text,'expected_revision_id':None,'complete_answer':True})
                self.assertEqual(confirmed.status_code,200,confirmed.text)
                report=(await client.get('/api/submissions/s/extraction-review')).json()
                self.assertEqual(report['questions'][0]['sources'][0]['extracted_text'],'My solution')
                self.assertEqual(report['questions'][0]['sources'][0]['area_revision']['text'],text)
                locations=await client.get('/api/submissions/s/source-locations?page_index=0')
                self.assertEqual(locations.json()['sources']['source']['method'],'instructor_confirmed_area')
                request={'expected_run_id':old_run,'revision_ids':[job_id],'request_id':str(uuid4())}
                with patch('services.job_queue_service.dispatch_processing_job',side_effect=lambda job,db:job):
                    accepted=await client.post('/api/answers/a/regrade-corrected',json=request)
                self.assertEqual(accepted.status_code,202,accepted.text)
                regrade_id=accepted.json()['job']['id']
                blocked=await client.post('/api/answers/a/resolve-review',json={'action':'approve','grading_run_id':old_run,'was_review_warranted':False})
                self.assertEqual(blocked.status_code,409,blocked.text)
                proposal=self.result(points_earned=0);proposal['score']=0
                with patch('services.job_execution_service.SessionLocal',return_value=self.db),patch.object(self.db,'close'), \
                     patch('services.grading_service.generate',return_value=json.dumps(proposal)):
                    execute_processing_job(regrade_id)
                current=await client.get('/api/results/s')
                self.assertEqual(current.status_code,200,current.text)
                answer=current.json()['answers'][0]
                self.assertEqual(answer['score'],0);self.assertEqual(answer['teacher_override_score'],2)
                self.assertTrue(answer['needs_review']);self.assertEqual(answer['raw_ocr_text'],'My solution')
                self.assertEqual(answer['grading_raw_response']['grading_package']['selected_answer_areas'][0]['id'],job_id)
                runs=await client.get('/api/answers/a/grading-runs')
                self.assertEqual(runs.status_code,200,runs.text);self.assertEqual(len(runs.json()),2)
                original=next(run for run in runs.json() if run['id']==old_run)
                self.assertEqual(original['score'],2)
                labels=await client.get('/api/answers/a/review-history')
                self.assertEqual(len(labels.json()),1);self.assertEqual(labels.json()[0]['human_score'],2)
                duplicate=await client.post('/api/answers/a/regrade-corrected',json=request)
                self.assertEqual(duplicate.status_code,202,duplicate.text)
                self.assertEqual(duplicate.json()['job']['id'],regrade_id)
        asyncio.run(exercise())


if __name__=='__main__':unittest.main()
