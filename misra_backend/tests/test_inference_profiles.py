"""Hybrid UI profile contracts: synthetic data, mocked transports, no inference."""
import asyncio
from copy import deepcopy
import io
import json
import os
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, MockTransport
from PIL import Image
from services.inference_profiles import (
    FULL_LOCAL_PROFILE, LOCAL_MODEL, LOCAL_PROFILE, TEXT_ONLY_IMAGE_ERROR, VISION_MODEL, VISION_PROFILE, active_profile, install_profile_middleware, local_profile,
    loopback_url, profile_scope, validate_snapshot,
)
from services.inference_service import complete, configuration, generate_setup, verification_enabled
from services.free_model_gateway import FreeCompletion
from services.openrouter_client import OpenRouterError


class InferenceProfileTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'LOCAL_AI_BASE_URL': 'http://127.0.0.1:11434/v1',
            'MISRA_AI_PROVIDER': 'gemini', 'GRADING_PROVIDER': 'gemini', 'GRADING_MODEL': 'gemini-2.5-flash',
            'VERIFICATION_ENABLED': 'false'})
        env.start(); self.addCleanup(env.stop)

    def test_task_routing_and_verification_are_scoped_and_restored(self):
        original = dict(os.environ)
        with profile_scope(local_profile()):
            self.assertEqual(configuration('ocr'), {'provider': 'gemini', 'model': 'gemini-2.5-flash'})
            for task in ('setup', 'grading', 'verification'):
                self.assertEqual(configuration(task), {'provider': 'local', 'model': 'qwen3:4b-instruct'})
            self.assertTrue(verification_enabled())
        self.assertEqual(configuration('grading')['provider'], 'gemini')
        self.assertFalse(verification_enabled())
        self.assertEqual(dict(os.environ), original)

    def test_ollama_connection_cancels_before_a_response_arrives(self):
        from services.grading_control import GradingStopped, grading_checkpoint
        from services.inference_service import _cancellable_ollama_chat

        async def exercise():
            started = asyncio.Event()
            closed = asyncio.Event()

            async def waiting_server(request):
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    closed.set()

            def checkpoint(**kwargs):
                if started.is_set():
                    raise GradingStopped()

            token = grading_checkpoint.set(checkpoint)
            try:
                with patch('httpx.AsyncClient', side_effect=lambda **options: AsyncClient(
                    transport=MockTransport(waiting_server), **options)):
                    with self.assertRaises(GradingStopped):
                        await asyncio.wait_for(_cancellable_ollama_chat('http://127.0.0.1/api/chat', {}, 900, check_interval=.01), 1)
                self.assertTrue(closed.is_set())
            finally:
                grading_checkpoint.reset(token)

        asyncio.run(exercise())

    def test_concurrent_requests_cannot_change_each_others_provider(self):
        async def worker(profile):
            with profile_scope(profile):
                await asyncio.sleep(0)
                return configuration('grading')['provider']
        async def exercise():
            return await asyncio.gather(worker(local_profile()), worker(None))
        self.assertEqual(asyncio.run(exercise()), ['local', 'gemini'])
        self.assertIsNone(active_profile())

    def test_snapshot_is_independent_of_changed_worker_environment(self):
        snapshot = local_profile()
        with patch.dict(os.environ, {'LOCAL_AI_BASE_URL': 'http://example.invalid/v1'}):
            with profile_scope(snapshot):
                returned = active_profile(); returned['tasks']['grading']['model'] = 'changed'
                self.assertEqual(configuration('grading')['model'], 'qwen3:4b-instruct')
                self.assertEqual(active_profile()['local_base_url'], 'http://127.0.0.1:11434')

    def test_altered_profiles_and_remote_urls_are_rejected(self):
        for key, value in [('verification_enabled', False), ('max_output_tokens', 1), ('version', 2)]:
            snapshot = local_profile(); snapshot[key] = value
            with self.assertRaises(ValueError): validate_snapshot(snapshot)
        for url in ['https://example.com/v1', 'http://localhost:11434/v1?key=private',
                    'http://user:pass@127.0.0.1', 'http://127.0.0.1:11434/other', 'http://127.0.0.1:bad']:
            with self.assertRaises(ValueError): loopback_url(url)

    def test_native_ollama_json_and_recorded_metadata(self):
        result = {'model': 'qwen3:4b-instruct', 'done': True, 'done_reason': 'stop',
            'message': {'content': '{"synthetic":true}'}, 'prompt_eval_count': 10, 'eval_count': 5}
        with profile_scope(local_profile()), patch('services.inference_service._ollama_json', return_value=result) as send:
            out = complete('Synthetic input', task='grading')
        self.assertEqual(out.text, '{"synthetic":true}')
        body = send.call_args.kwargs['body']
        self.assertEqual(body['options']['num_ctx'], 32768)
        self.assertEqual(body['format'], 'json'); self.assertFalse(body['stream'])
        self.assertEqual(out.metadata['inference_profile'], LOCAL_PROFILE)
        self.assertEqual(out.metadata['prompt_tokens'], 10)

    def test_local_images_and_oversized_inputs_fail_before_transport(self):
        for contents in [['Synthetic evidence', Image.new('RGB', (2, 2))], 'x' * 24000]:
            with profile_scope(local_profile()), patch('services.inference_service._ollama_json') as send, \
                    patch('services.inference_service.gemini_generate') as hosted:
                with self.assertRaises(ValueError): complete(contents)
                send.assert_not_called(); hosted.assert_not_called()

    def test_vision_profile_sends_images_for_grading_and_verification_to_pinned_ollama(self):
        response = {'model': VISION_MODEL, 'done': True, 'done_reason': 'stop', 'message': {'content': '{}'}}
        snapshot = local_profile(VISION_PROFILE)
        self.assertEqual(snapshot['tasks']['ocr']['provider'], 'gemini')
        self.assertEqual(snapshot['tasks']['setup'], local_profile()['tasks']['setup'])
        with profile_scope(snapshot), patch.dict(os.environ, {'LOCAL_AI_BASE_URL': 'http://localhost:9999/v1'}), \
                patch('services.inference_service.urllib.request.build_opener') as make_opener, \
                patch('services.inference_service.gemini_generate') as hosted:
            send = make_opener.return_value.open
            for task in ('grading', 'verification'):
                send.return_value = io.BytesIO(json.dumps(response).encode())
                out = complete(['Synthetic rubric', Image.new('RGB', (2, 2))], task=task)
                request = send.call_args.args[0]
                body = json.loads(request.data)
                self.assertEqual(request.full_url, 'http://127.0.0.1:11434/api/chat')
                self.assertEqual(body['model'], VISION_MODEL)
                self.assertTrue(body['messages'][0]['images'][0].startswith('iVBORw0KGgo'))
                self.assertEqual(body['options']['num_ctx'], 16384)
                self.assertEqual(body['options']['num_predict'], snapshot['max_output_tokens'])
                self.assertFalse(body['truncate'])
                self.assertFalse(body['shift'])
                self.assertEqual(out.metadata['image_count'], 1)
                self.assertEqual(out.metadata['context_tokens'], body['options']['num_ctx'])
                self.assertEqual(out.metadata['inference_profile'], VISION_PROFILE)
            # This fits in tokens, but its byte length exceeded the old guard.
            long_prompt = 'Approved criterion and synthetic evidence.\n' * 750
            for task in ('grading', 'verification'):
                send.return_value = io.BytesIO(json.dumps(response).encode())
                complete([long_prompt, Image.new('RGB', (2, 2))], task=task)
                body = json.loads(send.call_args.args[0].data)
                self.assertEqual(body['options']['num_ctx'], snapshot['context_tokens'])
                self.assertEqual(body['messages'][0]['content'], long_prompt)
                self.assertEqual(len(body['messages'][0]['images']), 1)
                self.assertFalse(body['truncate'])
                self.assertFalse(body['shift'])
            hosted.assert_not_called()

    def test_vision_assessment_and_verifier_send_their_response_schemas(self):
        from services.grading_service import GradingResult, _assessment_completion
        from services.verification_agent import VerificationResult, verify

        def response(content):
            return {'model': VISION_MODEL, 'done': True, 'done_reason': 'stop',
                    'message': {'content': json.dumps(content)}}

        image = Image.new('RGB', (2, 2))
        with profile_scope(local_profile(VISION_PROFILE)), \
                patch('services.inference_service._ollama_json') as send:
            send.return_value = response({})
            _assessment_completion(['Synthetic question', image], ['custom_instructions'])
            expected = GradingResult.model_json_schema()
            expected['$defs']['CriterionScore']['properties']['policy_applied']['items']['enum'] = ['custom_instructions']
            self.assertEqual(send.call_args.kwargs['body']['format'], expected)
            send.return_value = response({'criteria': [{'criterion_id': 'method', 'verdict': 'needs_review',
                'explanation': 'Check the method.'}], 'summary': 'Review required.'})
            verify({}, {'criteria_scores': [{'criterion_id': 'method', 'points_earned': 0, 'max_points': 1}]}, [image])
            self.assertEqual(send.call_args.kwargs['body']['format'], VerificationResult.model_json_schema())

    def test_text_assessment_sends_policy_citation_constraints_to_ollama(self):
        from services.grading_service import _assessment_completion

        response = {'model': 'qwen3:4b-instruct', 'done': True, 'done_reason': 'stop',
                    'message': {'content': '{}'}}
        with profile_scope(local_profile(FULL_LOCAL_PROFILE)), \
                patch('services.inference_service._ollama_json', return_value=response) as send:
            _assessment_completion('Synthetic question', ['units_policy'])
            schema = send.call_args.kwargs['body']['format']
            policy = schema['$defs']['CriterionScore']['properties']['policy_applied']
            self.assertEqual(policy['items']['enum'], ['units_policy'])

            _assessment_completion('Synthetic question without policy fields', [])
            schema = send.call_args.kwargs['body']['format']
            policy = schema['$defs']['CriterionScore']['properties']['policy_applied']
            self.assertEqual(policy['maxItems'], 0)

    def test_incomplete_mismatched_and_tool_responses_do_not_fallback(self):
        base = {'model': 'qwen3:4b-instruct', 'done': True, 'done_reason': 'stop', 'message': {'content': '{}'}}
        failures = [{**base, 'model': 'other'}, {**base, 'done': False}, {**base, 'done_reason': 'length'},
            {**base, 'message': {'content': '{}', 'tool_calls': [{'name': 'not-allowed'}]}},
            {**base, 'message': {'content': ''}}]
        for result in failures:
            with profile_scope(local_profile()), patch('services.inference_service._ollama_json', return_value=result), \
                    patch('services.inference_service.gemini_generate') as hosted:
                with self.assertRaises(OpenRouterError): complete('Synthetic')
                hosted.assert_not_called()

    def test_setup_images_use_explicit_gemini_reader_but_text_uses_local(self):
        image = Image.new('RGB', (2, 2))
        with profile_scope(local_profile()), patch('services.inference_service.gemini_generate', return_value='{}') as reader, \
                patch('services.inference_service._ollama_completion', return_value=FreeCompletion('{}', {})) as local:
            generate_setup(['Read a synthetic setup page', image], json_mode=True)
            self.assertIs(reader.call_args.args[0][1], image)
            local.assert_not_called()
            generate_setup('Draft a rubric from synthetic checked text', json_mode=True)
            local.assert_called_once()

    def test_exact_rubric_drafting_sends_the_scoring_schema_to_text_qwen(self):
        from services.rubric_service import suggest_rubric

        response = {'model': LOCAL_MODEL, 'done': True, 'done_reason': 'stop',
                    'message': {'content': json.dumps({'criteria': [
                        {'title': 'Method', 'description': 'Shows the force-distance product.', 'points': 2},
                    ]})}}
        with profile_scope(local_profile(FULL_LOCAL_PROFILE)), \
                patch('services.inference_service._ollama_json', return_value=response) as send, \
                patch('services.inference_service.gemini_generate') as gemini, \
                patch('services.inference_service.complete_routed') as hosted:
            rubric = suggest_rubric('Calculate work.', 'Physics', 2, 'en',
                                    answer_key='W = Fd', exact_scoring=True)
        body = send.call_args.kwargs['body']
        self.assertEqual(body['model'], LOCAL_MODEL)
        self.assertEqual(body['format']['required'], ['criteria'])
        self.assertEqual(body['format']['properties']['criteria']['items']['required'],
                         ['title', 'description', 'points'])
        self.assertEqual(rubric.criteria[0].scoring_type, 'binary')
        self.assertEqual(rubric.max_score, 2)
        gemini.assert_not_called()
        hosted.assert_not_called()

    def test_fully_local_profile_routes_all_tasks_without_hosted_calls(self):
        def response(path, body, timeout):
            return {'model': body['model'], 'done': True, 'done_reason': 'stop', 'message': {'content': '{}'}}

        image = Image.new('RGB', (2, 2))
        with profile_scope(local_profile(FULL_LOCAL_PROFILE)), \
                patch('services.inference_service._ollama_json', side_effect=response) as send, \
                patch('services.inference_service.gemini_generate') as gemini, \
                patch('services.inference_service.complete_routed') as hosted:
            for task, contents, expected in (
                ('ocr', ['Read the page', image], VISION_MODEL), ('setup', 'Synthetic guide', LOCAL_MODEL),
                ('grading', 'Synthetic transcription', LOCAL_MODEL), ('grading', ['Synthetic work', image], VISION_MODEL),
                ('verification', 'Synthetic transcription', LOCAL_MODEL), ('verification', ['Synthetic work', image], VISION_MODEL),
            ):
                self.assertEqual(complete(contents, task=task).metadata['model'], expected)
            generate_setup(['Synthetic page', image], json_mode=True)
            self.assertEqual(send.call_args.kwargs['body']['model'], VISION_MODEL)
            gemini.assert_not_called(); hosted.assert_not_called()

    def test_vision_cuda_crash_tries_cpu_once_with_identical_evidence(self):
        err = HTTPError('http://127.0.0.1:11434/api/chat', 500, 'runner failed', {},
                        io.BytesIO(b'{"error":"llama-server process has terminated: exit status 0xc0000409"}'))
        result = {'model': VISION_MODEL, 'done': True, 'done_reason': 'stop', 'message': {'content': '{}'}}
        with profile_scope(local_profile(FULL_LOCAL_PROFILE)), \
                patch('services.inference_service._ollama_json', side_effect=[err, result, result]) as send:
            evidence = ['Synthetic evidence', Image.new('RGB', (2, 2))]
            self.assertTrue(complete(evidence, task='ocr').metadata['cpu_vision'])
            complete(evidence, task='verification')
        first, second, third = (call.kwargs['body'] for call in send.call_args_list)
        self.assertNotIn('num_gpu', first['options'])
        self.assertEqual(second['options']['num_gpu'], 0)
        self.assertEqual(third['options']['num_gpu'], 0)
        self.assertEqual(first['messages'], second['messages'])

    def test_local_status_checks_tags_without_inference(self):
        from routers.inference_profiles import local_status
        with patch('routers.inference_profiles._ollama_json', return_value={'models': [{'name': LOCAL_MODEL}, {'name': VISION_MODEL}]}) as read:
            result = local_status()
        self.assertTrue(result['available']); self.assertFalse(result['inference_started'])
        read.assert_called_once_with('/api/tags')
        with patch('routers.inference_profiles._ollama_json', side_effect=RuntimeError('private diagnostics')):
            failure = local_status()
        self.assertFalse(failure['available']); self.assertNotIn('private diagnostics', failure['message'])

    def test_http_profiles_are_authenticated_and_unknown_profiles_rejected(self):
        from routers.inference_profiles import router
        from services.auth_dependencies import require_instructor
        from fastapi import HTTPException
        app = FastAPI(); install_profile_middleware(app); app.include_router(router)
        def denied(): raise HTTPException(401, 'Sign in')
        async def exercise():
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                app.dependency_overrides[require_instructor] = denied
                self.assertEqual((await client.get('/api/inference-profiles')).status_code, 401)
                app.dependency_overrides[require_instructor] = lambda: SimpleNamespace(id='teacher', institution_id='i')
                response = await client.get('/api/inference-profiles', headers={'X-Misra-Inference-Profile': FULL_LOCAL_PROFILE})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['selected_profile'], FULL_LOCAL_PROFILE)
                catalog = {item['id']: item for item in response.json()['profiles']}
                self.assertEqual(catalog['configured']['tasks']['grading']['provider'], 'gemini')
                self.assertEqual(set(catalog), {FULL_LOCAL_PROFILE, 'configured'})
                self.assertEqual(catalog[FULL_LOCAL_PROFILE]['tasks']['vision_grading']['model'], VISION_MODEL)
                with patch('routers.inference_profiles._ollama_json', return_value={'models': [{'name': VISION_MODEL}, {'name': LOCAL_MODEL}]}):
                    status = await client.get('/api/inference-profiles/local-status', params={'profile_id': VISION_PROFILE})
                self.assertEqual(status.status_code, 200)
                self.assertIn(VISION_MODEL, status.json()['models'])
                self.assertTrue(status.json()['available'])
                self.assertEqual((await client.get('/api/inference-profiles', headers={'X-Misra-Inference-Profile': 'arbitrary'})).status_code, 422)
        asyncio.run(exercise())

    def test_invalid_local_configuration_does_not_block_authentication(self):
        app = FastAPI(); install_profile_middleware(app)
        @app.get('/api/auth/synthetic')
        def authentication(): return {'ok': True}
        async def exercise():
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                with patch.dict(os.environ, {'LOCAL_AI_BASE_URL': 'https://remote.invalid'}):
                    response = await client.get('/api/auth/synthetic', headers={'X-Misra-Inference-Profile': LOCAL_PROFILE})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'ok': True})
        asyncio.run(exercise())


class ProfilePersistenceTests(unittest.TestCase):
    # Reuse the isolated, synthetic grading package database and proposal fixture.
    from tests.test_native_pipeline import NativePipelineTests as _fixture
    setUp = _fixture.setUp
    tearDown = _fixture.tearDown
    result = _fixture.result

    def test_failed_text_only_image_job_requires_fresh_grading(self):
        from models import ProcessingJob
        from services.job_queue_service import retry_processing_job
        job = ProcessingJob(id='text-only-image-error', institution_id='i', requested_by='teacher',
                            submission_id='s', status='failed', job_type='grade_submission', error_message=TEXT_ONLY_IMAGE_ERROR)
        self.db.add(job); self.db.commit()
        with patch('services.job_queue_service.dispatch_processing_job') as dispatch:
            with self.assertRaisesRegex(ValueError, 'Continue with current AI setup'):
                retry_processing_job(job, self.db)
        self.assertEqual(job.status, 'failed')
        dispatch.assert_not_called()

    def test_invalid_saved_profile_exhausts_retry_without_inference(self):
        from models import ProcessingJob
        from services.job_execution_service import execute_processing_job
        snapshot = local_profile(); snapshot['verification_enabled'] = False
        job = ProcessingJob(id='invalid-profile', institution_id='i', requested_by='teacher',
            job_type='grade_submission', submission_id='s', status='queued', attempt_count=0,
            max_attempts=1, progress_total=1, payload={'_inference_profile': snapshot})
        self.db.add(job); self.db.commit()
        with patch('services.job_execution_service.SessionLocal', return_value=self.db), \
                patch('services.job_execution_service._grade_submission') as grade:
            with self.assertRaisesRegex(ValueError, 'altered saved inference profile'):
                execute_processing_job('invalid-profile')
            grade.assert_not_called()
        saved = self.db.get(ProcessingJob, 'invalid-profile')
        self.assertEqual(saved.status, 'failed'); self.assertEqual(saved.attempt_count, 1)
        self.assertIsNone(active_profile())

    def test_profile_jobs_use_versioned_entrypoint_and_old_workers_fail_closed(self):
        from models import ProcessingJob
        from services.inference_profiles import execute_profile_job
        from services.job_queue_service import dispatch_processing_job
        job = ProcessingJob(id='old-worker-profile', institution_id='i', requested_by='teacher',
            job_type='grade_submission', submission_id='s', status='queued', max_attempts=1,
            payload={'_inference_profile': local_profile()})
        self.db.add(job); self.db.commit()
        with patch('services.job_queue_service.queue_for') as queue:
            queue.return_value.enqueue.return_value = SimpleNamespace(id='synthetic-rq')
            dispatch_processing_job(job, self.db)
            self.assertEqual(queue.return_value.enqueue.call_args.args[0], 'services.inference_profiles.execute_profile_job')
        with patch('services.grading_service.PROFILE_SUPPORT_VERSION', 0), \
                patch('database.SessionLocal', return_value=self.db), \
                patch('services.job_execution_service.execute_processing_job') as grade:
            with self.assertRaisesRegex(ValueError, 'Worker restart required'):
                execute_profile_job('old-worker-profile')
            grade.assert_not_called()
        saved = self.db.get(ProcessingJob, 'old-worker-profile')
        self.assertEqual(saved.status, 'failed')
        self.assertIn('No inference was started', saved.error_message)

    def test_queued_profile_persists_and_repeated_acceptance_keeps_original(self):
        from services.job_queue_service import create_processing_job
        with profile_scope(local_profile(VISION_PROFILE)), patch('services.job_queue_service.dispatch_processing_job'):
            job, created = create_processing_job(self.db, institution_id='i', requested_by='teacher',
                job_type='grade_submission', submission_id='s', payload={'mode': 'text_only'})
        snapshot = deepcopy(job.payload)
        self.assertTrue(created); self.assertEqual(snapshot['_inference_profile']['id'], VISION_PROFILE)
        with profile_scope(None), patch('services.job_queue_service.dispatch_processing_job'):
            existing, created = create_processing_job(self.db, institution_id='i', requested_by='teacher',
                job_type='grade_submission', submission_id='s', payload={'mode': 'image_text'})
        self.assertFalse(created); self.assertEqual(existing.id, job.id)
        self.assertEqual(existing.payload, snapshot)

    def test_worker_reloads_snapshot_and_resets_profile(self):
        from models import ProcessingJob
        from services.job_execution_service import execute_processing_job
        job = ProcessingJob(id='profile-job', institution_id='i', requested_by='teacher',
            job_type='grade_submission', submission_id='s', status='queued', attempt_count=0,
            max_attempts=1, progress_total=1, payload={'mode': 'text_only', '_inference_profile': local_profile()})
        self.db.add(job); self.db.commit()
        def check(*args):
            self.assertEqual(configuration('grading')['provider'], 'local')
            self.assertTrue(verification_enabled())
        with patch('services.job_execution_service.SessionLocal', return_value=self.db), \
                patch('services.job_execution_service._grade_submission', side_effect=check) as grade:
            execute_processing_job(job.id)
        grade.assert_called_once(); self.assertIsNone(active_profile())

    def test_grading_uses_local_and_verifier_even_when_process_verifier_disabled(self):
        from models import GradingRun
        from services.grading_service import process_grading
        result = self.result(evidence_refs=['student:segment:1'], reference_refs=['instructor:answer_key'])
        verifier = {'criteria': [{'criterion_id': 'logic', 'verdict': 'supported', 'explanation': 'Synthetic support'}],
                    'summary': 'Synthetic verification'}
        with profile_scope(local_profile()), patch('services.inference_service._ollama_completion', side_effect=[
            FreeCompletion(json.dumps(result), {'provider': 'local', 'model': 'qwen3:4b-instruct'}),
            FreeCompletion(json.dumps(verifier), {'provider': 'local', 'model': 'qwen3:4b-instruct'})]) as local, \
                patch('services.grading_service.generate') as hosted:
            process_grading('a', self.db)
        self.assertEqual(local.call_count, 2); hosted.assert_not_called()
        saved = self.db.query(GradingRun).one().response_json
        self.assertEqual(saved['verification']['inference']['model'], 'qwen3:4b-instruct')
        self.assertTrue(self.answer.needs_review)
        self.assertIn('local_model_evaluation_pending', saved['review_policy']['reasons'])

    def test_visual_grading_fails_without_saving_or_discarding_images(self):
        from models import GradingRun
        from services.grading_service import process_grading
        with profile_scope(local_profile()), patch('services.grading_service._load_answer_source_images',
            return_value=([Image.new('RGB', (2, 2))], [0])), patch('services.inference_service._ollama_json') as send:
            with self.assertRaisesRegex(ValueError, 'Required images cannot be omitted'):
                process_grading('a', self.db, mode='image_text')
        send.assert_not_called(); self.assertEqual(self.db.query(GradingRun).count(), 0)
        self.assertIsNone(self.answer.score)

    def test_fully_local_image_and_text_grading_saves_a_vision_proposal_and_verification(self):
        from models import GradingRun
        from services.grading_service import process_grading

        proposal = self.result(evidence_refs=['student:page:1'], reference_refs=['instructor:answer_key'])
        verifier = {'criteria': [{'criterion_id': 'logic', 'verdict': 'supported',
            'explanation': 'Synthetic support'}], 'summary': 'Synthetic verification'}
        responses = [{'model': VISION_MODEL, 'done': True, 'done_reason': 'stop',
                      'message': {'content': json.dumps(item)}} for item in (proposal, verifier)]
        image = Image.new('RGB', (2, 2))
        with profile_scope(local_profile(FULL_LOCAL_PROFILE)), \
                patch('services.grading_service._load_answer_source_images', return_value=([image], [0])), \
                patch('services.inference_service._ollama_json', side_effect=responses) as send, \
                patch('services.inference_service.complete_routed') as hosted:
            answer = process_grading('a', self.db, mode='image_text')
        grading, verification = [call.kwargs['body'] for call in send.call_args_list]
        self.assertEqual((grading['model'], verification['model']), (VISION_MODEL, VISION_MODEL))
        self.assertEqual(grading['messages'][0]['images'], verification['messages'][0]['images'])
        self.assertEqual(len(grading['messages'][0]['images']), 1)
        self.assertEqual(answer.score, 2)
        self.assertEqual(self.db.query(GradingRun).one().mode, 'image_text')
        hosted.assert_not_called()
