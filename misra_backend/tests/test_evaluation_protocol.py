"""Frozen synthetic imports and immutable private CLI outputs; no model calls."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluation_cli import main, private_directory, scorecard_markdown, write_report
from services.benchmark_metrics import snapshot_hash
from services.evaluation_protocol import evaluate_frozen, file_sha256, freeze_protocol, verify_protocol


class FrozenEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.spec = dict(protocol_id='synthetic-test-v1', purpose='development', data_kind='synthetic',
            prediction_origin='synthetic_fixture', evaluation_split='development',
            reference_kind='agent_development_audit', input_mode='checked_text',
            metric_policy=dict(target=.8, review_risk_threshold=.25, bootstrap_samples=100, seed=171),
            configuration=dict(model_id='synthetic-no-inference', prompt_version='v1',
                verification_version='v1', calculator_version='literal-v1', inference_settings=dict(temperature=0),
                review_risk_signal='synthetic fixture risk',
                retrieval=dict(strategy='bm25_v1', top_k=3)), artifacts=[])
        for role in ('guide', 'source', 'policy', 'prompt', 'implementation'):
            path = self.root/(role+'.json')
            path.write_text(json.dumps(dict(synthetic=True, role=role)), encoding='utf-8')
            self.spec['artifacts'].append(dict(role=role, path=path.name, approval=dict(status='pending' if role in {'guide','source'} else 'not_required')))
        packet = self.root/'answer.json'
        packet.write_text('{"synthetic_answer":"A manufactured answer"}', encoding='utf-8')
        self.cohort = [dict(answer_id='a', subject_id='subject-a', question_id='q', group_id='g',
            split='development', input_mode='checked_text', input_path=packet.name,
            input_sha256=file_sha256(packet), max_score=2, score_step=1, group_checked=True,
            answer_previously_used=False, question_previously_used=False, student_previously_used=False)]
        self.references = [dict(answer_id='a', reference_score=2, label_checked=True,
                                reference_kind='agent_development_audit')]

    def freeze(self):
        return freeze_protocol(self.spec, self.cohort, root=self.root)

    def prediction(self, manifest, **changes):
        return dict(answer_id='a', run_id='r1', status='scored', score=2, needs_review=False,
            hard_review_required=False, review_risk=.1, confidence=None,
            protocol_sha256=manifest['protocol_sha256'], input_sha256=self.cohort[0]['input_sha256']) | changes

    def validation(self):
        self.spec.update(purpose='held_out_validation', evaluation_split='test', data_kind='local_private',
            prediction_origin='saved_model_run', reference_kind='instructor_adjudicated',
            prior_registry_path='registry.json', registry_complete=True)
        (self.root/'registry.json').write_text('[]', encoding='utf-8')
        self.cohort[0]['split'] = 'test'
        self.references[0]['reference_kind'] = 'instructor_adjudicated'
        for a in self.spec['artifacts']:
            if a['role'] in {'guide','source'}:
                a['approval'] = dict(status='approved', approved_by='synthetic-test-reviewer',
                    approved_at='2026-01-01', checked=True, artifact_sha256=file_sha256(self.root/a['path']))

    def test_freeze_then_import_new_labels_and_saved_predictions(self):
        before = deepcopy(self.cohort)
        manifest = self.freeze()
        self.assertNotIn('reference_score', manifest['cohort'][0])
        result = evaluate_frozen(manifest, self.references, [self.prediction(manifest)], root=self.root)
        self.assertEqual(result['headline']['rate'], 1)
        self.assertFalse(result['inference_performed'])
        self.assertEqual(result['pending_approval_roles'], ['guide','source'])
        self.assertEqual(self.cohort, before)

    def test_missing_run_is_retained_without_becoming_zero_grade(self):
        result = evaluate_frozen(self.freeze(), self.references, [], root=self.root)
        self.assertEqual(result['headline']['scheduled_count'], 1)
        self.assertEqual(result['headline']['rate'], 0)
        self.assertIsNone(result['reliability']['mae_marks_among_scored'])

    def test_missing_total_labels_block_instead_of_shrinking_the_cohort(self):
        for refs in ([], [dict(self.references[0], label_checked=False)],
                     [dict(self.references[0], reference_score=None)]):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                evaluate_frozen(self.freeze(), refs, [], root=self.root)

    def test_changed_artifact_registry_input_and_metric_implementation_are_detected(self):
        manifest = self.freeze()
        for filename in ('guide.json', 'answer.json'):
            path = self.root/filename
            original = path.read_bytes()
            path.write_text('changed synthetic artifact', encoding='utf-8')
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                verify_protocol(manifest, root=self.root)
            path.write_bytes(original)
        altered = deepcopy(manifest)
        altered['metric_implementation']['evaluation_review.py'] = snapshot_hash('old metric')
        altered['protocol_sha256'] = snapshot_hash({k:v for k,v in altered.items() if k!='protocol_sha256'})
        with self.assertRaisesRegex(ValueError, 'drift'):
            verify_protocol(altered, root=self.root)
        self.validation()
        frozen = self.freeze()
        (self.root/'registry.json').write_text('[{}]', encoding='utf-8')
        with self.assertRaises(ValueError):
            verify_protocol(frozen, root=self.root)

    def test_manifest_tampering_cannot_retain_the_old_fingerprint(self):
        manifest = self.freeze()
        manifest['spec']['metric_policy']['review_risk_threshold'] = .99
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            verify_protocol(manifest, root=self.root)

    def test_config_input_mismatch_reference_leak_and_duplicate_runs_are_rejected(self):
        manifest = self.freeze()
        for changes in [dict(protocol_sha256=snapshot_hash('another config')),
                        dict(input_sha256=snapshot_hash('another answer')), dict(reference_score=2),
                        dict(student_name='synthetic person'), dict(score=float('nan')),
                        dict(score=.5), dict(needs_review=None), dict(status='failed', score=0)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                evaluate_frozen(manifest, self.references, [self.prediction(manifest, **changes)], root=self.root)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            evaluate_frozen(manifest, self.references, [self.prediction(manifest)]*2, root=self.root)

    def test_reference_revision_is_hashed_separately_without_overwriting_old_runs(self):
        manifest = self.freeze()
        first = evaluate_frozen(manifest, self.references, [self.prediction(manifest)], root=self.root)
        revised = [dict(self.references[0], reference_score=1)]
        second = evaluate_frozen(manifest, revised, [self.prediction(manifest)], root=self.root)
        self.assertNotEqual(first['references_sha256'], second['references_sha256'])
        self.assertEqual(first['protocol_sha256'], second['protocol_sha256'])
        self.assertEqual(second['headline']['rate'], 0)

    def test_historical_labels_cannot_masquerade_as_adjudicated_validation(self):
        self.validation()
        manifest = self.freeze()
        wrong = [dict(self.references[0], reference_kind='historical_teacher')]
        with self.assertRaisesRegex(ValueError, 'provenance'):
            evaluate_frozen(manifest, wrong, [], root=self.root)
        self.spec['reference_kind'] = 'agent_development_audit'
        with self.assertRaisesRegex(ValueError, 'adjudicated'):
            self.freeze()

    def test_pending_guide_or_unchecked_source_blocks_validation_only(self):
        self.assertEqual(self.freeze()['spec']['purpose'], 'development')
        self.validation()
        for role in ('guide', 'source'):
            artifact = next(a for a in self.spec['artifacts'] if a['role']==role)
            original = deepcopy(artifact['approval'])
            artifact['approval']['status'] = 'pending'
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'approval'):
                self.freeze()
            artifact['approval'] = original
        next(a for a in self.spec['artifacts'] if a['role']=='source')['approval']['checked'] = False
        with self.assertRaisesRegex(ValueError, 'checked sources'):
            self.freeze()

    def test_explicit_approval_must_match_the_exact_file(self):
        self.validation()
        self.spec['artifacts'][0]['approval']['artifact_sha256'] = snapshot_hash('wrong')
        with self.assertRaisesRegex(ValueError, 'revision'):
            self.freeze()

    def test_reuse_cannot_be_hidden_by_erasing_marks_or_false_exposure_flags(self):
        self.validation()
        for previous in [dict(answer_id='a', group_id='other', subject_id='subject-a', question_id='q'),
                         dict(answer_id='other', group_id='g', subject_id='subject-a', question_id='q')]:
            (self.root/'registry.json').write_text(json.dumps([previous]), encoding='utf-8')
            with self.subTest(previous=previous), self.assertRaisesRegex(ValueError, 'Held-out'):
                self.freeze()
        (self.root/'registry.json').write_text('[]', encoding='utf-8')
        self.cohort[0]['answer_previously_used'] = True
        with self.assertRaises(ValueError):
            self.freeze()

    def test_student_split_leakage_and_known_question_claim_are_rejected(self):
        self.validation()
        other = dict(self.cohort[0], answer_id='b', split='development', question_previously_used=True)
        self.cohort.append(other)
        with self.assertRaisesRegex(ValueError, 'crosses'):
            self.freeze()
        other['group_id'] = 'another'
        self.cohort[0]['question_previously_used'] = True
        self.freeze()  # Known question is allowed for new-student validation.
        (self.root/'registry.json').write_text(json.dumps([dict(answer_id='old', group_id='old',
            subject_id='different', question_id='different')]), encoding='utf-8')
        self.cohort = self.cohort[:1]
        self.cohort[0]['question_previously_used'] = False
        (self.root/'registry.json').write_text(json.dumps([dict(answer_id='old', group_id='old',
            subject_id='subject-a', question_id='q')]), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Known questions'):
            self.freeze()

    def test_no_registry_or_input_packet_blocks_validation(self):
        self.validation()
        self.spec['registry_complete'] = False
        with self.assertRaisesRegex(ValueError, 'registry'):
            self.freeze()
        self.spec['registry_complete'] = True
        del self.cohort[0]['input_path']
        with self.assertRaisesRegex(ValueError, 'input packet'):
            self.freeze()

    def test_subject_transfer_requires_new_subject_and_frozen_baseline_settings(self):
        self.validation()
        baseline = self.freeze()
        (self.root/'baseline.json').write_text(json.dumps(baseline), encoding='utf-8')
        self.spec.update(purpose='subject_transfer', baseline_protocol_path='baseline.json')
        self.cohort[0].update(subject_id='new-subject', group_id='new-group')
        (self.root/'registry.json').write_text(json.dumps([dict(answer_id='old', group_id='old',
            subject_id='previous-subject', question_id='q')]), encoding='utf-8')
        self.freeze()
        self.spec['configuration']['inference_settings']['temperature'] = .5
        with self.assertRaisesRegex(ValueError, 'frozen'):
            self.freeze()
        self.spec['configuration']['inference_settings']['temperature'] = 0
        self.cohort[0]['subject_id'] = 'previous-subject'
        self.cohort[0]['question_id'] = 'new-q'
        with self.assertRaisesRegex(ValueError, 'hold out the subject'):
            self.freeze()

    def test_subject_transfer_cannot_reuse_baseline_subject_missing_from_registry(self):
        self.validation()
        baseline = self.freeze()
        (self.root/'baseline.json').write_text(json.dumps(baseline), encoding='utf-8')
        self.spec.update(purpose='subject_transfer', baseline_protocol_path='baseline.json')
        self.cohort[0]['group_id'] = 'new-group'
        with self.assertRaisesRegex(ValueError, 'baseline'):
            self.freeze()

    def test_paths_cannot_escape_workspace(self):
        self.spec['artifacts'][0]['path'] = '../outside.json'
        with self.assertRaisesRegex(ValueError, 'workspace'):
            self.freeze()

    def test_cli_freeze_report_are_private_exclusive_and_network_free(self):
        for name, content in [('spec', self.spec), ('cohort', self.cohort)]:
            (self.root/(name+'.json')).write_text(json.dumps(content), encoding='utf-8')
        frozen_path = self.root/'private'/'frozen.json'
        with patch('socket.socket.connect', side_effect=AssertionError('No network permitted')), redirect_stdout(StringIO()):
            main(['--root', str(self.root), 'freeze', '--spec', str(self.root/'spec.json'),
                  '--cohort', str(self.root/'cohort.json'), '--output', str(frozen_path)])
            manifest = json.loads(frozen_path.read_text(encoding='utf-8'))
            for name, content in [('labels', self.references), ('predictions', [self.prediction(manifest)])]:
                (self.root/(name+'.json')).write_text(json.dumps(content), encoding='utf-8')
            args = ['--root', str(self.root), 'report', '--manifest', str(frozen_path),
                '--references', str(self.root/'labels.json'), '--predictions', str(self.root/'predictions.json'),
                '--output', str(self.root/'private'/'report-v1')]
            main(args)
            output = self.root/'private'/'report-v1'/'scorecard.json'
            first = output.read_bytes()
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                main(args)
            self.assertEqual(output.read_bytes(), first)
        report = json.loads(first)
        self.assertIn('Synthetic software demonstration only', scorecard_markdown(report))
        self.assertTrue((output.parent/'scorecard.md').is_file())
        with self.assertRaises(ValueError):
            private_directory(self.root, self.root/'docs'/'public-report')


if __name__ == '__main__':
    unittest.main()
