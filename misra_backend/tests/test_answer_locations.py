"""Synthetic display localization; no provider calls or live records."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from PIL import Image
from pydantic import ValidationError

from models import AnswerSource, ProcessingJob, Submission, GradingRun
from routers.results import locate_submission_answers, get_source_locations, list_submissions
from services.answer_location_service import (GridLocation, fingerprint, grid_image,
    locate_answers, run_location_job, saved_locations, sources_for_page,
    automatic_locations, record_extraction_completion)
from services.free_model_gateway import FreeCompletion
from services.job_queue_service import job_to_dict
from tests import test_grading_package as fixtures


class AnswerLocationTests(unittest.TestCase):
    setUp = fixtures.GradingPackageTests.setUp
    tearDown = fixtures.GradingPackageTests.tearDown

    def source(self):
        return self.db.get(AnswerSource, 'source')

    def job(self, **changes):
        source = self.source()
        payload = dict(operation='locate_answers', page_index=0,
                       source_fingerprint=fingerprint([source]))
        payload.update(changes)
        job = ProcessingJob(id='location-job', institution_id='i', submission_id='s',
            job_type='ocr_submission', status='queued', payload=payload)
        self.db.add(job); self.db.commit()
        return job

    def completion(self, **changes):
        item = dict(source_id='part_1', found=True, top=28, bottom=31, left=1, right=34)
        item.update(changes)
        return FreeCompletion(json.dumps({'locations': [item]}), {'provider': 'synthetic'})

    def test_grid_boundaries_convert_to_full_original_page_coordinates(self):
        image = Image.new('RGB', (800, 600), 'white')
        with patch('services.answer_location_service.complete', return_value=self.completion()) as call:
            result = locate_answers(image, [self.source()])
        self.assertEqual(result['source']['method'], 'vision_grid')
        self.assertEqual(result['source']['bounding_box'], {'x': .025, 'y': .7, 'width': .825, 'height': .075})
        self.assertEqual(call.call_args.kwargs['task'], 'ocr')
        sent = call.call_args.args[0]
        self.assertNotIn('Old key', sent[0]); self.assertNotIn('Correct logic', sent[0])
        self.assertEqual(sent[1].size, (864, 664))
        self.assertEqual(image.size, (800, 600))

    def test_display_refines_saved_box_without_changing_its_run_or_answer(self):
        from copy import deepcopy
        from PIL import ImageDraw
        image=Image.new('RGB',(800,1000),'white');draw=ImageDraw.Draw(image)
        for x in range(160,560,30):draw.line((x,600,x+6,635),fill='black',width=3)
        location={'status':'located','method':'vision_grid','bounding_box':dict(x=.1,y=.61,width=.7,height=.01)}
        job=self.job(locations={'source':location});job.status='completed';self.db.commit()
        saved=deepcopy(job.payload);text=self.source().extracted_text
        with patch('services.source_location_service.page_source_locations',return_value={'sources':{'source':{'status':'unverified'}}}), \
             patch('services.answer_location_service.page_image',return_value=image), \
             patch('services.answer_location_service.complete') as provider:
            result=get_source_locations('s',Response(),0,self.db,SimpleNamespace(institution_id='i'))
        self.assertEqual(result['sources']['source']['geometry_check'],'vertical_ink_extent_checked')
        self.assertGreater(result['sources']['source']['bounding_box']['height'],.035)
        self.assertEqual(job.payload,saved);self.assertEqual(self.source().extracted_text,text)
        self.assertEqual(self.db.query(ProcessingJob).count(),1);provider.assert_not_called()

    def test_unavailable_display_image_never_reuses_the_coarse_rectangle(self):
        location={'status':'located','method':'vision_grid','bounding_box':dict(x=.1,y=.61,width=.7,height=.01)}
        job=self.job(locations={'source':location});job.status='completed';self.db.commit()
        with patch('services.source_location_service.page_source_locations',return_value={'sources':{}}), \
             patch('services.answer_location_service.page_image',side_effect=OSError('Synthetic unavailable image')):
            result=get_source_locations('s',Response(),0,self.db,SimpleNamespace(institution_id='i'))
        self.assertEqual(result['sources']['source']['status'],'unverified')
        self.assertNotIn('bounding_box',result['sources']['source'])
        self.assertEqual(job.payload['locations']['source'],location)

    def test_missing_duplicate_or_unknown_source_is_rejected(self):
        for locations in [[], [{'source_id': 'unknown', 'found': False}],
                          [{'source_id': 'part_1', 'found': False}]*2]:
            with self.subTest(locations=locations), patch('services.answer_location_service.complete',
                    return_value=FreeCompletion(json.dumps({'locations': locations}), {})):
                with self.assertRaises(ValueError): locate_answers(Image.new('RGB', (80, 60)), [self.source()])

    def test_strict_bounds_and_no_guessed_geometry_when_not_found(self):
        for changes in [dict(top=31,bottom=28), dict(top=.7), dict(right=41),
                        dict(found='true'), dict(found=False), dict(top=None)]:
            with self.subTest(changes=changes), patch('services.answer_location_service.complete', return_value=self.completion(**changes)):
                with self.assertRaises(ValidationError): locate_answers(Image.new('RGB', (80,60)), [self.source()])

    def test_not_found_is_explicit_and_does_not_reuse_old_estimate(self):
        with patch('services.answer_location_service.complete', return_value=FreeCompletion(
                '{"locations":[{"source_id":"part_1","found":false}]}', {})):
            result = locate_answers(Image.new('RGB',(80,60)), [self.source()])
        self.assertEqual(result['source']['reason'], 'answer_not_located')
        self.assertNotIn('bounding_box',result['source'])

    def test_explicit_request_permitted_after_grading_without_touching_grades(self):
        self.answer.score=2; self.answer.teacher_override_score=1; self.db.commit()
        with patch('services.job_queue_service.dispatch_processing_job', side_effect=lambda job,db:job):
            result=locate_submission_answers('s',0,self.db,SimpleNamespace(id=None,institution_id='i'))
            again=locate_submission_answers('s',0,self.db,SimpleNamespace(id=None,institution_id='i'))
        self.assertEqual(result['job']['operation'],'locate_answers')
        self.assertEqual(result['job']['id'],again['job']['id'])
        self.assertEqual(self.answer.score,2); self.assertEqual(self.answer.teacher_override_score,1)
        self.assertEqual(self.db.query(GradingRun).count(),0)

    def test_foreign_missing_pages_and_running_grading_rejected(self):
        for user,page,status in [(SimpleNamespace(institution_id='other'),0,404),
                                 (SimpleNamespace(institution_id='i'),1,404)]:
            with self.assertRaises(HTTPException) as caught:locate_submission_answers('s',page,self.db,user)
            self.assertEqual(caught.exception.status_code,status)
        job=self.job(); job.job_type='grade_submission'; self.db.commit()
        with self.assertRaises(HTTPException) as caught:locate_submission_answers('s',0,self.db,SimpleNamespace(institution_id='i'))
        self.assertEqual(caught.exception.status_code,409)

    def test_worker_saves_separate_result_and_preserves_every_existing_record(self):
        self.answer.score=2; self.answer.teacher_override_score=1;self.db.commit()
        source=self.source(); original=dict(source.ocr_segment);text=source.extracted_text
        job=self.job(); result={'source': {'status':'located','method':'vision_grid',
            'bounding_box':dict(x=.025,y=.7,width=.825,height=.075)}}
        with patch('services.answer_location_service.page_image', return_value=Image.new('RGB',(80,60))), \
             patch('services.answer_location_service.locate_answers', return_value=result):
            run_location_job(job,self.db,lambda *args:None)
        self.assertEqual(job.payload['locations'],result)
        self.assertEqual(self.answer.score,2);self.assertEqual(self.answer.teacher_override_score,1)
        self.assertEqual(source.ocr_segment,original);self.assertEqual(source.extracted_text,text)
        self.assertEqual(self.db.get(Submission,'s').status,'uploaded')

    def test_stale_text_rejected_before_inference_and_saved_result_is_not_reused(self):
        job=self.job();self.source().extracted_text='Changed';self.db.commit()
        with patch('services.answer_location_service.locate_answers') as call:
            with self.assertRaisesRegex(ValueError,'changed'):run_location_job(job,self.db,lambda *args:None)
            call.assert_not_called()
        job.status='completed';job.payload={**job.payload,'locations':{'source':{'status':'located'}}};self.db.commit()
        self.assertEqual(saved_locations(self.db,self.db.get(Submission,'s'),0,[self.source()]),{})

    def test_worker_dispatch_uses_localization_and_never_reruns_ocr(self):
        job=self.job()
        from services.job_execution_service import execute_processing_job
        with patch('services.job_execution_service.SessionLocal',return_value=self.db), \
             patch.object(self.db,'close'), patch('services.answer_location_service.run_location_job') as locate, \
             patch('services.job_execution_service.process_submission') as extract:
            execute_processing_job(job.id)
        locate.assert_called_once();extract.assert_not_called();self.assertEqual(job.status,'completed')

    def test_saved_vision_result_does_not_override_unique_native_pdf_match(self):
        job=self.job();job.status='completed';job.payload={**job.payload,'locations':{
            'source':{'status':'unverified','method':'vision_grid','reason':'answer_not_located'}}};self.db.commit()
        native={'status':'located','method':'native_pdf_text','bounding_box':dict(x=.1,y=.6,width=.5,height=.1)}
        with patch('services.source_location_service.page_source_locations',return_value={'page_index':0,'sources':{'source':native}}):
            report=get_source_locations('s',Response(),0,self.db,SimpleNamespace(institution_id='i'))
        self.assertEqual(report['sources']['source'],native)
        with patch('services.source_location_service.page_source_locations',return_value={'page_index':0,'sources':{'source':{'status':'unverified'}}}):
            report=get_source_locations('s',Response(),0,self.db,SimpleNamespace(institution_id='i'))
        self.assertEqual(report['sources']['source']['reason'],'answer_not_located')

    def test_job_public_record_discloses_operation_but_not_transcription(self):
        result=job_to_dict(self.job())
        self.assertEqual(result['operation'],'locate_answers');self.assertEqual(result['page_index'],0)
        self.assertNotIn('My solution',json.dumps(result,default=str))

    def test_location_task_failure_is_not_presented_as_failed_extraction(self):
        job=self.job();job.status='failed';self.db.commit()
        report={'submission':{'id':'s'},'readiness':{},'questions':[], 'grading_scope':{'kind':'all'}}
        with patch('routers.results.build_extraction_review',return_value=report):
            items=list_submissions(None,self.db,SimpleNamespace(institution_id='i'))
        self.assertIsNone(items[0]['latest_ocr_job'])

    def test_text_changed_during_inference_does_not_publish_stale_location(self):
        job=self.job()
        def changed(*args):
            self.source().extracted_text='Changed during location';self.db.commit()
            return {'source':{'status':'located'}}
        with patch('services.answer_location_service.page_image',return_value=Image.new('RGB',(80,60))), \
             patch('services.answer_location_service.locate_answers',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed while'):run_location_job(job,self.db,lambda *args:None)
        self.assertNotIn('locations',job.payload)

    def test_automatic_requests_reuse_completed_and_failed_attempts(self):
        job=self.job()
        for status in ['completed','failed']:
            job.status=status;self.db.commit()
            with patch('services.job_queue_service.dispatch_processing_job') as dispatch:
                result=locate_submission_answers('s',0,self.db,SimpleNamespace(institution_id='i'),automatic=True)
            self.assertEqual(result['job']['id'],job.id);self.assertTrue(result['reused'])
            dispatch.assert_not_called()

    def test_automatic_requests_wait_for_other_paper_work(self):
        job=self.job();job.job_type='grade_submission';job.payload={};self.db.commit()
        result=locate_submission_answers('s',0,self.db,SimpleNamespace(institution_id='i'),automatic=True)
        self.assertEqual(result['waiting_for']['id'],job.id)

    def test_extraction_localizes_once_and_reuses_checkpoint_after_refresh(self):
        job=self.job();job.payload={};self.db.commit()
        submission=self.db.get(Submission,'s')
        record_extraction_completion(job.id,submission,self.db);self.db.commit()
        result={'source':{'status':'located','method':'vision_grid',
            'bounding_box':dict(x=.025,y=.7,width=.825,height=.075)}}
        with patch('services.answer_location_service.page_image',return_value=Image.new('RGB',(80,60))), \
             patch('services.source_location_service.page_source_locations',return_value={'sources':{}}), \
             patch('services.answer_location_service.locate_answers',return_value=result) as locate:
            automatic_locations(job,self.db,lambda *args:None)
            automatic_locations(job,self.db,lambda *args:None)
        self.assertEqual(locate.call_count,1)
        self.assertEqual(saved_locations(self.db,submission,0,[self.source()]),result)
        with patch('services.job_queue_service.dispatch_processing_job') as dispatch:
            reused=locate_submission_answers('s',0,self.db,SimpleNamespace(institution_id='i'),automatic=True)
        self.assertTrue(reused['reused']);self.assertEqual(reused['job']['status'],'completed')
        dispatch.assert_not_called()

    def test_automatic_location_failure_preserves_extraction_and_is_not_repeated(self):
        job=self.job();job.payload={};submission=self.db.get(Submission,'s');submission.status='extracted'
        self.answer.score=2;self.answer.teacher_override_score=1;self.db.commit()
        record_extraction_completion(job.id,submission,self.db);self.db.commit()
        with patch('services.source_location_service.page_source_locations',return_value={'sources':{}}), \
             patch('services.answer_location_service.page_image',side_effect=ValueError('Synthetic render failure')) as render:
            automatic_locations(job,self.db,lambda *args:None)
            automatic_locations(job,self.db,lambda *args:None)
        self.assertEqual(render.call_count,1)
        self.assertEqual(submission.status,'extracted');self.assertEqual(self.answer.score,2)
        self.assertEqual(self.answer.teacher_override_score,1)
        self.assertEqual(saved_locations(self.db,submission,0,[self.source()])['source']['reason'],
                         'automatic_location_unavailable')

    def test_exact_native_text_needs_no_extra_model_call(self):
        job=self.job();job.payload={};submission=self.db.get(Submission,'s');self.db.commit()
        record_extraction_completion(job.id,submission,self.db);self.db.commit()
        native={'source':{'status':'located','method':'native_pdf_text',
            'bounding_box':dict(x=.1,y=.6,width=.5,height=.1)}}
        with patch('services.source_location_service.page_source_locations',return_value={'sources':native}), \
             patch('services.answer_location_service.locate_answers') as locate:
            automatic_locations(job,self.db,lambda *args:None)
        locate.assert_not_called();self.assertEqual(saved_locations(self.db,submission,0,[self.source()]),native)

    def test_worker_retry_does_not_repeat_checkpointed_extraction(self):
        from services.job_execution_service import execute_processing_job
        job=self.job();job.payload={'extracted_submission_ids':['s']};self.db.commit()
        with patch('services.job_execution_service.SessionLocal',return_value=self.db), \
             patch.object(self.db,'close'), patch('services.job_execution_service.process_submission') as extract, \
             patch('services.answer_location_service.automatic_locations') as locate:
            execute_processing_job(job.id)
        extract.assert_not_called();locate.assert_called_once();self.assertEqual(job.status,'completed')

    def test_actual_extraction_commits_its_resume_marker_with_new_sources(self):
        import tempfile
        from pathlib import Path
        from services.ocr_service import OCRPageResult, OCRSegment, process_submission
        job=self.job();job.payload={};self.db.commit()
        page=OCRPageResult(page_language='en',identity_legibility='not_found',segments=[
            OCRSegment(question_number='1',text='Synthetic answer',language='en',legibility='clear',has_math=False)])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.png';Image.new('RGB',(80,60),'white').save(path)
            self.db.get(Submission,'s').original_file_path=str(path);self.db.commit()
            with patch('services.ocr_service.extract_page',return_value=page):
                process_submission('s',self.db,processing_job_id=job.id)
        self.assertEqual(job.payload['extracted_submission_ids'],['s'])
        self.assertEqual(self.db.get(Submission,'s').status,'extracted')
        self.assertEqual(self.db.query(AnswerSource).one().extracted_text,'Synthetic answer')

    def test_batch_worker_localizes_each_newly_extracted_paper(self):
        from models import Answer
        from services.job_execution_service import execute_processing_job
        job=self.job();job.job_type='ocr_batch';job.submission_id=None;job.batch_id='batch';job.payload={}
        first=self.db.get(Submission,'s');first.batch_id='batch'
        second=Submission(id='s2',institution_id='i',exam_id='e',batch_id='batch',original_file_path='synthetic.png',page_count=1)
        self.db.add_all([second,Answer(id='a2',institution_id='i',submission_id='s2',question_id='q',raw_ocr_text='Second answer'),
            AnswerSource(id='source2',answer_id='a2',page_index=0,segment_index=0,extracted_text='Second answer',ocr_segment={})]);self.db.commit()
        def extracted(*args,**kwargs):
            self.assertEqual(kwargs['processing_job_id'],job.id)
            for submission in [first,second]:
                submission.status='extracted';record_extraction_completion(job.id,submission,self.db)
            self.db.commit()
        def locations(image,sources):
            return {source.id:{'status':'unverified','method':'vision_grid','reason':'answer_not_located'} for source in sources}
        with patch('services.job_execution_service.SessionLocal',return_value=self.db),patch.object(self.db,'close'), \
             patch('services.job_execution_service.process_batch',side_effect=extracted), \
             patch('services.source_location_service.page_source_locations',return_value={'sources':{}}), \
             patch('services.answer_location_service.page_image',return_value=Image.new('RGB',(80,60))), \
             patch('services.answer_location_service.locate_answers',side_effect=locations) as locate:
            execute_processing_job(job.id)
        self.assertEqual(locate.call_count,2);self.assertEqual(job.status,'completed')
        self.assertEqual(set(job.payload['automatic_locations']),{'s','s2'})
