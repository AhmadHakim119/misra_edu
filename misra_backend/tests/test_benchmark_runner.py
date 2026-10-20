"""Synthetic research runs only; never send real data or call a provider."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.benchmark_runner import (approved_inputs,file_hash,fixed_input_hash,
    grading_package,research_configuration,run_batch,run_case,validate_cases)
from services.free_model_gateway import FreeCompletion


class ResearchRunnerTests(unittest.TestCase):
    def fixture(self,root):
        text='Work is force times distance. A perpendicular force does zero work.'
        guide={'policy':{'equivalent_methods':'Accept equivalent valid methods.'},'questions':[{
            'id':'synthetic-q1','exam_version':'synthetic','number':'1','text':'Find work from force and distance.',
            'max_score':1,'score_step':1,'answer_key':'W=F*d','criteria':[{'id':'method','title':'Work method',
                'description':'Use force times distance.','full_credit_conditions':'Correct work method.',
                'points':1,'scoring_type':'binary','partial_credit_allowed':False}]}]}
        source={'pages':[{'material_version_id':'v1','document_sha256':'a'*64,'pdf_page':1,'chunks':[{
            'id':'chunk1','material_version_id':'v1','title':'Synthetic work lesson','page_index':0,
            'printed_page_label':'1','text':text,'text_sha256':hashlib.sha256(text.encode()).hexdigest()}]}]}
        for name,value in [('guide.json',guide),('sources.json',source)]:
            (root/name).write_text(json.dumps(value),encoding='utf-8')
        approval={'guide':{'approved':True,'sha256':file_hash(root/'guide.json')},
            'source_pages':{'checked':True,'approved':True,'sha256':file_hash(root/'sources.json')}}
        (root/'approval.json').write_text(json.dumps(approval),encoding='utf-8')
        inputs=approved_inputs(root/'guide.json',root/'sources.json',root/'approval.json')
        case={'answer_id':'a1','paper_id':'p1','group_id':'g1','exam_version':'synthetic',
            'question_id':'synthetic-q1','split':'development','student_text':'UNIQUE_STUDENT_TOKEN W=F*d',
            'transcription_checked':True,'student_work_preserved':True,'teacher_marks_absent':True,
            'group_checked':True,'review_provenance':'Synthetic fixture.'}
        return inputs,case

    def responder(self,contents,**kwargs):
        if kwargs.get('task')=='verification':
            return FreeCompletion(json.dumps({'criteria':[{'criterion_id':'method','verdict':'supported',
                'explanation':'The synthetic evidence supports the criterion.'}],'summary':'Synthetic verification.'}),{})
        package=json.loads(contents.split('GRADING PACKAGE JSON:\n',1)[1])
        allowed=package['citation_contract']['criteria'][0]
        return FreeCompletion(json.dumps({'score':1,'max_score':1,'feedback':'Correct synthetic method.',
            'reasoning':'Synthetic work relation.','llm_confidence':80,'criteria_scores':[{
                'criterion_id':'method','max_points':1,'points_earned':1,'feedback':'Synthetic method shown.',
                'evidence_refs':['student:segment:1'],'reference_refs':allowed['reference_refs'],
                'policy_applied':[],'uncertainties':[]}]}),{'provider':'mock','reported_cost_usd':0})

    def test_guide_and_source_approvals_are_separate_exact_hash_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            p=root/'approval.json';approval=json.loads(p.read_text());approval['source_pages']['checked']=False
            p.write_text(json.dumps(approval))
            with self.assertRaisesRegex(ValueError,'source verification'):
                approved_inputs(root/'guide.json',root/'sources.json',p)
            self.fixture(root);(root/'guide.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'exact research guide'):
                approved_inputs(root/'guide.json',root/'sources.json',p)

    def test_cases_reject_reference_labels_unreviewed_work_and_group_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs,case=self.fixture(Path(directory));validate_cases([case],inputs)
            for field,value in [('reference_score',1),('student_name','fictional'),('teacher_marks_absent',False)]:
                changed={**case,field:value}
                with self.subTest(field=field),self.assertRaises(ValueError):validate_cases([changed],inputs)
            other={**case,'answer_id':'a2','paper_id':'p2','split':'test'}
            with self.assertRaisesRegex(ValueError,'crosses'):validate_cases([case,other],inputs)

    def test_paired_inputs_same_query_never_uses_student_text(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs,case=self.fixture(Path(directory))
            left=grading_package(case,inputs,'no_rag');right=grading_package(case,inputs,'bm25')
            for field in ('question','rubric','policy','answer_key','student_evidence'):
                self.assertEqual(left[field],right[field])
            self.assertEqual(left['course_references']['mode'],'disabled')
            self.assertEqual(right['course_references']['mode'],'required')
            self.assertNotIn('UNIQUE_STUDENT_TOKEN',json.dumps(right['course_references']['queries']))
            changed={**case,'student_text':'A changed extraction'}
            self.assertNotEqual(fixed_input_hash(case,inputs),fixed_input_hash(changed,inputs))

    def test_neural_research_arm_is_explicit_and_preserves_fixed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs,case=self.fixture(Path(directory))
            baseline=grading_package(case,inputs,'bm25')
            for strategy in ['neural_hybrid_v1','dense_v1','dense_rerank_v1']:
                with self.subTest(strategy=strategy),patch('services.neural_retrieval_service.rank_passages',return_value=([1],[{'reranker_logit':3}])) as rank, \
                     patch('services.benchmark_runner.bm25_scores',side_effect=AssertionError('Research dense arm must not run BM25')):
                    neural=grading_package(case,inputs,'bm25',retrieval_strategy=strategy)
                self.assertEqual(baseline['course_references']['strategy'],'bm25_v1')
                self.assertEqual(neural['course_references']['strategy'],strategy)
                self.assertEqual(rank.call_args.kwargs['strategy'],strategy)
                self.assertNotIn('UNIQUE_STUDENT_TOKEN',str(rank.call_args))
                for field in ('question','rubric','policy','answer_key','student_evidence'):
                    self.assertEqual(baseline[field],neural[field])

    def test_real_contract_mock_round_trip_saves_both_agents_and_resumes_without_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inputs,case=self.fixture(root);calls=[]
            def transport(contents,**kwargs):
                calls.append(kwargs['task']);return self.responder(contents,**kwargs)
            results=run_batch([case],inputs,'synthetic/model:free',root/'runs',transport=transport)
            self.assertEqual(len(results),2);self.assertTrue(all(r['status']=='scored' for r in results))
            self.assertEqual(calls.count('grading'),2);self.assertEqual(calls.count('verification'),2)
            self.assertEqual(results,run_batch([case],inputs,'synthetic/model:free',root/'runs',transport=transport))
            self.assertEqual(len(calls),4)
            self.assertEqual(len(list((root/'runs'/'runs').glob('*/verification-response.json'))),2)
            changed={**case,'student_text':'Different evidence'}
            with self.assertRaisesRegex(ValueError,'Frozen batch changed'):
                run_batch([changed],inputs,'synthetic/model:free',root/'runs',transport=transport)

    def test_bad_citations_fail_and_do_not_get_a_best_of_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inputs,case=self.fixture(root);calls=[]
            def transport(contents,**kwargs):
                calls.append(1);response=self.responder(contents,**kwargs)
                data=json.loads(response.text);data['criteria_scores'][0]['reference_refs']=['invented-source']
                return FreeCompletion(json.dumps(data),{})
            config=research_configuration('synthetic/model:free')
            result=run_case(case,inputs,'bm25',config,root/'attempt',transport=transport)
            self.assertEqual(result['status'],'failed');self.assertIsNone(result['score'])
            self.assertTrue(result['hard_review_required']);self.assertEqual(len(calls),1)
            self.assertEqual(result,run_case(case,inputs,'bm25',config,root/'attempt',transport=transport))
            self.assertEqual(len(calls),1)

    def test_interrupted_attempt_is_preserved_and_never_repeated_automatically(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inputs,case=self.fixture(root)
            def interrupted(*args,**kwargs):raise KeyboardInterrupt()
            config=research_configuration('synthetic/model:free')
            with self.assertRaises(KeyboardInterrupt):run_case(case,inputs,'no_rag',config,root/'attempt',transport=interrupted)
            with self.assertRaisesRegex(ValueError,'interrupted attempt'):
                run_case(case,inputs,'no_rag',config,root/'attempt',transport=self.responder)
            self.assertTrue((root/'attempt'/'provider-package.json').is_file())

    def test_missing_required_context_fails_before_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inputs,case=self.fixture(root);inputs['chunks']=[]
            def transport(*args,**kwargs):self.fail('No inference may occur without required sources.')
            result=run_case(case,inputs,'bm25',research_configuration('synthetic/model:free'),root/'attempt',transport=transport)
            self.assertEqual(result['status'],'failed');self.assertIsNone(result['score'])
            self.assertEqual(len(result['retrieval_snapshot_sha256']),64)

    def test_paid_or_automatic_model_routing_is_rejected(self):
        for model in ('paid/model','openrouter/free','openrouter/auto:free'):
            with self.subTest(model=model),self.assertRaises(ValueError):research_configuration(model)


if __name__=='__main__':unittest.main()
