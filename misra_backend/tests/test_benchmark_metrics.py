"""Synthetic benchmark validation, paired effects and held-out calibration."""
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchmark_cli import main, prepare, private_output, read_records
from services.benchmark_metrics import (MetricPolicy, build_benchmark_report, calibrated_probability,
    confidence_diagnostics, fit_calibration, quadratic_kappa, snapshot_hash, validate_inputs)


class BenchmarkTests(unittest.TestCase):
    def reference(self,index,split='test',maximum=2,step=1,human=2,question='q'):
        return {'answer_id':f'a{index}','paper_id':f'p{index}','group_id':f'g{index}',
            'exam_version':'synthetic','question_id':question,'split':split,'max_score':maximum,
            'score_step':step,'reference_score':human,'independent_reference':True,
            'label_checked':True,'input_reviewed':True,'guide_checked':True,'group_checked':True,
            'fixed_inputs_sha256':snapshot_hash({'answer':index})}

    def prediction(self,ref,condition='bm25',score=2,confidence=80,status='scored',hard=False):
        return {'answer_id':ref['answer_id'],'condition':condition,'run_id':f'{ref["answer_id"]}-{condition}',
            'status':status,'score':score,'confidence':confidence,'hard_review_required':hard,
            'fixed_inputs_sha256':ref['fixed_inputs_sha256'],'system_sha256':snapshot_hash(condition),
            'comparison_sha256':snapshot_hash('fixed model/prompt/verification/settings'),
            'retrieval_snapshot_sha256':snapshot_hash('approved passages') if condition=='bm25' else None}

    def calibration_data(self):
        refs=[self.reference(1,'calibration'),self.reference(2,'calibration'),self.reference(3),self.reference(4)]
        predictions=[self.prediction(ref,score=0 if i%2==0 else 2,confidence=20 if i%2==0 else 80) for i,ref in enumerate(refs)]
        policy=MetricPolicy(min_fit_answers=2,min_fit_groups=2,bootstrap_samples=200)
        return refs,predictions,policy

    def test_known_mae_normalized_error_and_bias_on_mixed_scales(self):
        refs=[self.reference(1),self.reference(2,maximum=10,human=5,question='q2')]
        predictions=[self.prediction(refs[0],score=1),self.prediction(refs[1],score=7)]
        result=build_benchmark_report(refs,predictions)['splits']['test']['conditions']['bm25']
        self.assertEqual(result['mae'],1.5);self.assertAlmostEqual(result['rmse'],2.5**.5)
        self.assertAlmostEqual(result['normalized_mae'],.35);self.assertAlmostEqual(result['normalized_bias'],-.15)
        self.assertEqual(len(result['per_question']),2)

    def test_tolerance_is_in_score_steps_and_never_changes_exact_agreement(self):
        refs=[self.reference(1,step=.5,human=0),self.reference(2,maximum=10,step=2,human=4,question='q2')]
        predictions=[self.prediction(refs[0],score=1),self.prediction(refs[1],score=6)]
        result=build_benchmark_report(refs,predictions)['splits']['test']['conditions']['bm25']
        self.assertEqual(result['exact_agreement'],0);self.assertEqual(result['tolerance_agreement'],.5)

    def test_failed_missing_and_abstained_runs_are_not_zero_grades(self):
        refs=[self.reference(i) for i in range(4)]
        predictions=[self.prediction(refs[0]),self.prediction(refs[1],score=None,status='failed'),
                     self.prediction(refs[2],score=None,status='abstained')]
        metrics=build_benchmark_report(refs,predictions)['splits']['test']['conditions']['bm25']
        self.assertEqual(metrics['status_counts'],{'scored':1,'failed':1,'abstained':1,'missing':1})
        self.assertEqual(metrics['mae'],0);self.assertEqual(metrics['scoring_coverage'],.25)
        self.assertEqual(metrics['exact_agreement_over_all_expected'],.25)
        predictions[1]['score']=0
        with self.assertRaisesRegex(ValueError,'must not carry'):validate_inputs(refs,predictions)

    def test_unverified_labels_redactions_guides_and_groups_cannot_enter_reports(self):
        for field in ('independent_reference','label_checked','input_reviewed','guide_checked','group_checked'):
            ref=self.reference(1);ref[field]=False
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,field):
                build_benchmark_report([ref],[])

    def test_nan_boolean_invalid_scale_and_off_grid_predictions_rejected(self):
        for field,value in [('reference_score',float('nan')),('max_score',True),('score_step',0),('reference_score',3)]:
            ref=self.reference(1);ref[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):validate_inputs([ref],[])
        ref=self.reference(1)
        for value in (.2,float('inf'),True,-1,3):
            with self.subTest(score=value),self.assertRaises(ValueError):validate_inputs([ref],[self.prediction(ref,score=value)])

    def test_repeated_runs_are_not_silently_cherry_picked(self):
        ref=self.reference(1)
        with self.assertRaisesRegex(ValueError,'Multiple runs'):
            validate_inputs([ref],[self.prediction(ref),self.prediction(ref,score=1)])
        with self.assertRaisesRegex(ValueError,'Duplicate reference'):
            validate_inputs([ref,deepcopy(ref)],[])

    def test_one_student_cannot_cross_splits_even_with_different_papers(self):
        refs=[self.reference(1,'calibration'),self.reference(2)];refs[1]['group_id']=refs[0]['group_id']
        with self.assertRaisesRegex(ValueError,'crosses'):validate_inputs(refs,[])

    def test_frozen_inputs_model_drift_and_teacher_mark_leakage_rejected(self):
        refs=[self.reference(1),self.reference(2)]
        original=[self.prediction(refs[0]),self.prediction(refs[1])]
        for field,value in [('fixed_inputs_sha256',snapshot_hash('different')),('system_sha256',snapshot_hash('different')),
                            ('comparison_sha256',snapshot_hash('different')),('reference_score',2)]:
            predictions=deepcopy(original);predictions[1][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_inputs(refs,predictions)

    def test_raw_reliability_brier_ece_and_confidence_zero_are_preserved(self):
        refs,predictions,_=self.calibration_data()
        rows=[(ref,prediction) for ref,prediction in zip(refs,predictions)]
        result=confidence_diagnostics(rows)
        self.assertAlmostEqual(result['brier_score'],.04);self.assertAlmostEqual(result['ece'],.2)
        predictions[0]['confidence']=0;predictions[1]['confidence']=None
        result=confidence_diagnostics(rows)
        self.assertEqual(result['observation_count'],3);self.assertEqual(result['missing_confidence_count'],1)

    def test_paired_bm25_effect_uses_shared_answers_and_group_bootstrap(self):
        refs=[self.reference(1),self.reference(2,human=0)]
        predictions=[self.prediction(refs[0],'no_rag',score=1),self.prediction(refs[0],score=2),
                     self.prediction(refs[1],'no_rag',score=2),self.prediction(refs[1],score=1)]
        policy=MetricPolicy(bootstrap_samples=200)
        result=build_benchmark_report(refs,predictions,policy)['splits']['test']['paired_bm25']
        self.assertEqual(result['normalized_mae_improvement'],.5)
        self.assertEqual(result['paired_scored_count'],2);self.assertEqual(result['interval_95']['lower'],.5)
        self.assertEqual(result,build_benchmark_report(refs,predictions,policy)['splits']['test']['paired_bm25'])
        predictions[-1]['score']=None;predictions[-1]['status']='failed'
        result=build_benchmark_report(refs,predictions,policy)['splits']['test']['paired_bm25']
        self.assertEqual(result['paired_scored_count'],1);self.assertEqual(result['unpaired_or_unscored_count'],1)
        self.assertIsNone(result['interval_95'])

    def test_quadratic_kappa_is_per_scale_and_constant_scores_are_undefined(self):
        refs=[self.reference(i,human=i) for i in range(3)]
        self.assertEqual(quadratic_kappa([(ref,self.prediction(ref,score=i)) for i,ref in enumerate(refs)]),1)
        self.assertAlmostEqual(quadratic_kappa([(ref,self.prediction(ref,score=2-i)) for i,ref in enumerate(refs)]),-1)
        self.assertIsNone(quadratic_kappa([(refs[0],self.prediction(refs[0],score=0))]))

    def test_fit_refuses_small_pilot_without_claiming_calibrated_confidence(self):
        refs,predictions,_=self.calibration_data()
        fitted=fit_calibration(refs,predictions,'bm25')
        self.assertEqual(fitted['status'],'insufficient_data');self.assertEqual(fitted['knots'],[])
        self.assertIsNone(fitted['review_threshold'])

    def test_isotonic_fit_uses_only_calibration_and_reports_held_out_results(self):
        refs,predictions,policy=self.calibration_data();original=deepcopy(predictions)
        fit=fit_calibration(refs,predictions,'bm25',policy)
        self.assertEqual(fit['status'],'fitted_unvalidated');self.assertEqual(fit['fit_answer_ids'],['a1','a2'])
        self.assertAlmostEqual(calibrated_probability(50,fit),.5)
        report=build_benchmark_report(refs,predictions,policy,fit)
        metrics=report['splits']['test']['conditions']['bm25']
        self.assertEqual(metrics['calibrated_confidence']['brier_score'],0)
        self.assertEqual(metrics['held_out_review_threshold']['error_recall'],1)
        self.assertEqual(metrics['held_out_review_threshold']['review_rate_among_scored'],.5)
        self.assertEqual(original,predictions)
        refs[-1]['reference_score']=1
        self.assertEqual(fit_calibration(refs,predictions,'bm25',policy),fit)

    def test_pava_pools_nonmonotone_confidence_and_constant_confidence_is_insufficient(self):
        refs,predictions,policy=self.calibration_data()
        predictions[0]['score']=2;predictions[1]['score']=0
        fit=fit_calibration(refs,predictions,'bm25',policy)
        self.assertEqual([k['probability'] for k in fit['knots']],[.5,.5])
        predictions[1]['confidence']=20
        self.assertEqual(fit_calibration(refs,predictions,'bm25',policy)['status'],'insufficient_data')

    def test_calibration_cannot_be_reused_after_fitting_labels_or_policy_change(self):
        refs,predictions,policy=self.calibration_data();fit=fit_calibration(refs,predictions,'bm25',policy)
        refs[0]['reference_score']=0
        with self.assertRaisesRegex(ValueError,'data/policy changed'):build_benchmark_report(refs,predictions,policy,fit)

    def test_hard_review_gates_are_never_bypassed(self):
        refs,predictions,policy=self.calibration_data();fit=fit_calibration(refs,predictions,'bm25',policy)
        predictions[-1]['hard_review_required']=True
        metrics=build_benchmark_report(refs,predictions,policy,fit)['splits']['test']['conditions']['bm25']
        self.assertEqual(metrics['held_out_review_threshold']['flagged_count'],2)

    def test_failed_missing_calibration_units_remain_in_frozen_cohort(self):
        refs,predictions,policy=self.calibration_data()
        failed=self.reference(10,'calibration');missing=self.reference(11,'calibration')
        refs.extend([failed,missing])
        predictions.append(self.prediction(failed,score=None,status='failed'))
        fit=fit_calibration(refs,predictions,'bm25',policy)
        self.assertEqual(fit['answer_count'],2)
        build_benchmark_report(refs,predictions,policy,fit)
        with self.assertRaisesRegex(ValueError,'cohort changed'):
            build_benchmark_report(refs[:-1],predictions,policy,fit)
        changed=deepcopy(predictions);changed[-1]['status']='abstained'
        with self.assertRaisesRegex(ValueError,'cohort changed'):
            build_benchmark_report(refs,changed,policy,fit)

    def test_edited_fit_cannot_replace_mapping_or_threshold_after_test_results(self):
        refs,predictions,policy=self.calibration_data()
        fit=fit_calibration(refs,predictions,'bm25',policy)
        for key,value in [('review_threshold',{'raw_confidence_below':0}),
                          ('knots',[{'x':.2,'probability':.9},{'x':.8,'probability':1}])]:
            changed=deepcopy(fit);changed[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'differs from the frozen fit'):
                build_benchmark_report(refs,predictions,policy,changed)

    def test_invalid_knots_and_missing_data_do_not_produce_fake_zero_metrics(self):
        refs,predictions,policy=self.calibration_data();fit=fit_calibration(refs,predictions,'bm25',policy)
        fit['knots'][0]['probability']=float('nan')
        with self.assertRaises(ValueError):calibrated_probability(20,fit)
        empty=build_benchmark_report([],[])['splits']['test']['conditions']['bm25']
        self.assertIsNone(empty['mae']);self.assertIsNone(empty['exact_agreement']);self.assertIsNone(empty['confidence']['brier_score'])


class PrivatePreparationTests(unittest.TestCase):
    def test_fit_report_cli_round_trip_is_private_offline_and_refuses_overwrite(self):
        refs,predictions,policy=BenchmarkTests().calibration_data()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);private=root/'private';private.mkdir()
            files={'calibration-references.json':[ref for ref in refs if ref['split']=='calibration'],
                'calibration-predictions.json':[run for run in predictions if run['answer_id'] in ('a1','a2')],
                'all-references.json':refs,'all-predictions.json':predictions,'policy.json':policy.__dict__}
            for name,value in files.items():(private/name).write_text(json.dumps(value),encoding='utf-8')
            fit=private/'fit.json';report=private/'report.json'
            fit_args=['benchmark_cli.py','--root',str(root),'fit','--references',str(private/'calibration-references.json'),
                '--predictions',str(private/'calibration-predictions.json'),'--policy',str(private/'policy.json'),
                '--condition','bm25','--output',str(fit)]
            report_args=['benchmark_cli.py','--root',str(root),'report','--references',str(private/'all-references.json'),
                '--predictions',str(private/'all-predictions.json'),'--policy',str(private/'policy.json'),
                '--calibration',str(fit),'--output',str(report)]
            for arguments in (fit_args,report_args):
                with patch('sys.argv',arguments),redirect_stdout(StringIO()):main()
            result=json.loads(report.read_text())
            self.assertEqual(result['confidence_status'],'uncalibrated_operational_scores')
            self.assertEqual(result['splits']['test']['reference_count'],2)
            self.assertEqual(result['splits']['test']['conditions']['bm25']['held_out_review_threshold']['error_recall'],1)
            self.assertEqual(result['input_file_sha256']['references'],hashlib.sha256((private/'all-references.json').read_bytes()).hexdigest())
            before=report.read_bytes()
            with patch('sys.argv',report_args),redirect_stderr(StringIO()),self.assertRaises(SystemExit) as error:main()
            self.assertEqual(error.exception.code,2);self.assertEqual(report.read_bytes(),before)

    def test_preparation_has_candidate_boundaries_no_scores_and_no_silent_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for year in ('F23','F24','F25'):
                folder=root/f'GPHY171_01_Final Exam_{year}';folder.mkdir()
                (folder/'key_AK.pdf').write_bytes(f'synthetic key {year}'.encode())
                (folder/'bundle.pdf').write_bytes(f'synthetic bundle {year}'.encode())
            with patch('pypdf.PdfReader',side_effect=lambda path:SimpleNamespace(pages=[None]*(11 if '_AK' in path.name else 22))):
                result=prepare(root,root/'private'/'pilot')
            self.assertEqual(result['candidate_paper_count'],6);self.assertEqual(result['candidate_part_label_count'],28)
            output=root/'private'/'pilot'
            inventory=json.loads((output/'prepared-inventory.json').read_text())
            self.assertTrue(all(not row['boundary_checked'] for row in inventory['papers']))
            labels=read_records(output/'reference-template.csv')
            self.assertTrue(all(row['reference_score'] is None and not row['label_checked'] and not row['input_reviewed'] for row in labels))
            with self.assertRaisesRegex(ValueError,'already exists'):prepare(root,output)
            with self.assertRaisesRegex(ValueError,'private/'):private_output(root,root/'docs'/'leak.json')

    def test_csv_does_not_treat_false_or_blank_as_truthy_or_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'labels.csv'
            path.write_text('answer_id,label_checked,reference_score\na1,false,\n',encoding='utf-8')
            self.assertEqual(read_records(path),[{'answer_id':'a1','label_checked':False,'reference_score':None}])


if __name__=='__main__':unittest.main()
