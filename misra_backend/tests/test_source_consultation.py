"""Synthetic bounded source/page consultation checks; no external inference."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
from services.free_model_gateway import FreeCompletion
from services.source_consultation_service import (trigger_reasons, prepare_consultation_context,
    inspect_original_pages, consult_sources, merge_verification)


class SourceConsultationTests(unittest.TestCase):
    def setUp(self):
        self.context = {'strategy': 'hybrid_rrf_v1', 'mode': 'required', 'status': 'retrieved',
            'scope_version_id': 'scope', 'scope_sha256': 'a' * 64,
            'passages': [{'id': 'material:one', 'title': 'Work', 'page_index': 0,
                'printed_page_label': '1', 'text': 'Work is force times displacement.',
                'criterion_ids': ['c1']}]}
        self.package = {'schema_version': 1, 'question': {'text': 'Calculate work', 'max_score': 1},
            'rubric': {'max_score': 1, 'criteria': [{'id': 'c1', 'points': 1}]},
            'policy': {}, 'answer_key': {'mode': 'reference', 'reference_id': 'key:one',
                'reference_text': 'W=Fd', 'document_refs': []},
            'student_evidence': [{'id': 'source:one', 'kind': 'ocr_segment', 'page_index': 0,
                'segment_index': 0, 'text': 'W=82×3=246 J'}], 'course_references': self.context}
        self.candidate = {'score': 1, 'max_score': 1, 'criteria_scores': [{'criterion_id': 'c1',
            'points_earned': 1, 'evidence_refs': ['source:one'], 'reference_refs': ['material:one']}]}
        self.finding = {'criteria': [{'criterion_id': 'c1', 'verdict': 'supported',
            'explanation': 'Force times displacement supports the method.',
            'evidence_refs': ['student:segment:1'], 'reference_refs': ['instructor:source:1']}],
            'summary': 'The cited work and course concept agree.'}

    def response(self, value):
        return FreeCompletion(json.dumps(value), {'provider': 'mock'})

    def test_neural_consultation_preserves_strategy_and_never_falls_back(self):
        for strategy in ['neural_hybrid_v1','bm25_rerank_v1','dense_v1','dense_rerank_v1']:
            baseline={**self.context,'strategy':strategy}
            with self.subTest(strategy=strategy),patch('services.source_consultation_service.retrieve_for_question',return_value=baseline) as retrieve:
                self.assertEqual(prepare_consultation_context(None,'question','rubric',baseline),baseline)
                self.assertEqual(retrieve.call_args.kwargs,{'strategy':strategy,'hits_per_criterion':4})
            with patch('services.source_consultation_service.retrieve_for_question',side_effect=ValueError('Neural model unavailable')) as retrieve:
                with self.assertRaisesRegex(ValueError,'Neural model unavailable'):
                    prepare_consultation_context(None,'question','rubric',baseline)
                self.assertEqual(retrieve.call_count,1)

    def test_only_uncertain_proposals_trigger_and_reasons_accumulate(self):
        value = SimpleNamespace(llm_confidence=99, criteria_scores=[SimpleNamespace(uncertainties=[])],
                                _score_aggregation={}, _provider_metadata={})
        self.assertEqual(trigger_reasons(value, {'status': 'checked'}), [])
        value.llm_confidence = 80
        value.criteria_scores[0].uncertainties = ['Unclear unit']
        value._score_aggregation = {'discrepancy': True}
        value._provider_metadata = {'citation_correction_performed': True}
        self.assertEqual(len(trigger_reasons(value, {'status': 'needs_review'})), 5)

    def test_scope_and_approval_are_pinned_no_student_query(self):
        with patch('services.source_consultation_service.retrieve_for_question', return_value=self.context) as retrieve:
            context = prepare_consultation_context(None, 'question', 'rubric', self.context)
        self.assertEqual(context, self.context)
        self.assertEqual(retrieve.call_args.kwargs, {'strategy': 'hybrid_rrf_v1', 'hits_per_criterion': 4})
        changed = {**self.context, 'scope_version_id': 'other'}
        with patch('services.source_consultation_service.retrieve_for_question', return_value=changed), self.assertRaisesRegex(ValueError, 'scope changed'):
            prepare_consultation_context(None, None, None, self.context)

    def test_confident_method_conflict_triggers_same_bounded_source_check(self):
        value = SimpleNamespace(llm_confidence=100, criteria_scores=[SimpleNamespace(uncertainties=[])],
            _score_aggregation={}, _provider_metadata={}, _decision_review=[{
                'criterion_id': 'c1', 'code': 'valid_method_credit_withheld', 'message': 'Check method.'}])
        self.assertEqual(trigger_reasons(value, {'status': 'checked'}), ['valid_method_credit_withheld'])

    def test_disabled_scope_is_never_overridden(self):
        with patch('services.source_consultation_service.retrieve_for_question') as retrieve:
            self.assertIsNone(prepare_consultation_context(None, None, None, {'mode': 'disabled'}))
            retrieve.assert_not_called()

    def test_coverage_fallback_revalidates_scope_and_never_swallows_integrity_failure(self):
        error = ValueError('Approved-source retrieval lacks relevant context for the configured criteria.')
        with patch('services.source_consultation_service.retrieve_for_question', side_effect=[error, deepcopy(self.context)]) as retrieve:
            result = prepare_consultation_context(None, None, None, self.context)
        self.assertEqual(retrieve.call_count, 2)
        self.assertIn('consultation_retrieval_fallback', result)
        with patch('services.source_consultation_service.retrieve_for_question', side_effect=ValueError('integrity failure')) as retrieve:
            with self.assertRaisesRegex(ValueError, 'integrity'):
                prepare_consultation_context(None, None, None, self.context)
            self.assertEqual(retrieve.call_count, 1)

    def test_source_check_is_one_call_preserves_proposal_and_restores_citations(self):
        original = deepcopy(self.candidate)
        image = Image.new('RGB', (10, 10))
        calls = []
        def complete(contents, **kwargs):
            calls.append((contents, kwargs))
            return self.response(self.finding)
        result = consult_sources(self.package, self.candidate, self.context,
            reasons=['low_model_confidence'], images=[image], completion_fn=complete)
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0][1], image)
        self.assertEqual(result['status'], 'checked')
        self.assertFalse(result['score_changed'])
        self.assertEqual(result['criteria'][0]['reference_refs'], ['material:one'])
        self.assertEqual(self.candidate, original)
        self.assertNotIn('source:one', calls[0][0][0])

    def test_original_page_reread_is_separate_and_never_replaces_extraction(self):
        calls = []
        original = deepcopy(self.package)
        def complete(contents, *, task):
            calls.append(task)
            if task == 'ocr':
                return self.response({'observations': [{'evidence_ref': 'student:segment:1',
                    'observed_text': 'W=82+3=85 J', 'ambiguous': False,
                    'explanation': 'The visible operator is plus.'}]})
            return self.response(self.finding)
        result = consult_sources(self.package, self.candidate, self.context,
            reasons=['criterion_uncertainty'], page_loader=lambda: ([Image.new('RGB', (10, 10))], [0]),
            completion_fn=complete)
        self.assertEqual(calls, ['ocr', 'verification'])
        self.assertEqual(result['page_inspection']['status'], 'needs_review')
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(self.package, original)

    def test_missing_page_is_explicit_and_still_flags_review(self):
        def missing():
            raise FileNotFoundError('private path must not leak')
        result = consult_sources(self.package, self.candidate, self.context,
            reasons=['low_model_confidence'], page_loader=missing,
            completion_fn=lambda *a, **k: self.response(self.finding))
        self.assertEqual(result['page_inspection']['status'], 'unavailable')
        self.assertEqual(result['status'], 'needs_review')
        self.assertNotIn('private path', json.dumps(result))

    def test_model_cannot_change_scores_or_invent_criteria_or_citations(self):
        variants = []
        for field, value in [('criterion_id', 'invented'), ('evidence_refs', ['invented']),
                             ('reference_refs', ['instructor:answer_key']),
                             ('reference_refs', ['instructor:source:99'])]:
            response = deepcopy(self.finding)
            response['criteria'][0][field] = value
            variants.append(response)
        variants.append({**self.finding, 'score': 999})
        variants.append({**self.finding, 'criteria': self.finding['criteria'] * 2})
        for response in variants:
            with self.subTest(response=response):
                result = consult_sources(self.package, self.candidate, self.context,
                    reasons=['low_model_confidence'], completion_fn=lambda *a, **k: self.response(response))
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(self.candidate['score'], 1)

    def test_page_check_rejects_invented_or_missing_segments(self):
        from services.grading_package_service import provider_grading_package
        safe, *_ = provider_grading_package(self.package)
        for observations in ([], [{'evidence_ref': 'invented', 'observed_text': 'secret',
                                  'ambiguous': False, 'explanation': 'Wrong segment'}]):
            result = inspect_original_pages(safe, lambda: ([Image.new('RGB', (10, 10))], [0]),
                completion_fn=lambda *a, **k: self.response({'observations': observations}))
            self.assertEqual(result['status'], 'unavailable')

    def test_page_formatting_difference_is_not_a_conflict(self):
        from services.grading_package_service import provider_grading_package
        safe, *_ = provider_grading_package(self.package)
        response = {'observations': [{'evidence_ref': 'student:segment:1',
            'observed_text': 'W = 82 × 3 = 246 J', 'ambiguous': False, 'explanation': 'Checked'}]}
        result = inspect_original_pages(safe, lambda: ([Image.new('RGB', (10, 10))], [0]),
            completion_fn=lambda *a, **k: self.response(response))
        self.assertEqual(result['status'], 'checked')

    def test_confirmed_regions_are_sent_without_private_area_ids(self):
        self.package['selected_answer_areas'] = [{'id': 'private-area-id', 'source_id': 'one',
            'page_index': 0, 'bounding_box': {'x': .1, 'y': .2, 'width': .5, 'height': .2}}]
        sent = []
        def complete(contents, *, task):
            sent.append((contents, task))
            if task == 'ocr':
                return self.response({'observations': [{'evidence_ref': 'student:segment:1',
                    'observed_text': 'W=82×3=246 J', 'ambiguous': False, 'explanation': 'Checked region'}]})
            return self.response(self.finding)
        result = consult_sources(self.package, self.candidate, self.context,
            reasons=['criterion_uncertainty'], page_loader=lambda: ([Image.new('RGB', (10, 10))], [0]),
            completion_fn=complete)
        self.assertEqual(result['status'], 'checked')
        self.assertIn('confirmed_regions', sent[0][0][0])
        self.assertIn('student:segment:1', sent[0][0][0])
        for contents, _ in sent:
            self.assertNotIn('private-area-id', contents[0])

    def test_secondary_success_cannot_erase_initial_flag(self):
        initial = {'status': 'needs_review', 'summary': 'Uncertain work', 'criteria': [
            {'criterion_id': 'c1', 'verdict': 'needs_review', 'explanation': 'Original concern'}]}
        original = deepcopy(initial)
        merged = merge_verification(initial, {'status': 'checked', **self.finding})
        self.assertEqual(merged['status'], 'needs_review')
        self.assertEqual(merged['criteria'][0]['verdict'], 'needs_review')
        self.assertEqual(initial, original)
        self.assertEqual(merged['initial_check'], original)

    def test_numeric_trace_uses_provider_aliases_and_preserves_local_candidate(self):
        self.candidate['criteria_scores'][0]['numeric_check'] = {
            'student': {'ref': 'source:one', 'quote': '246'},
            'target': {'ref': 'key:one', 'quote': '246'},
            'basis': 'reference', 'depends_on': []}
        before = deepcopy(self.candidate)
        seen = []
        def complete(contents, **kwargs):
            seen.append(contents[0])
            return self.response(self.finding)
        consult_sources(self.package, self.candidate, self.context, reasons=['criterion_uncertainty'], completion_fn=complete)
        self.assertEqual(self.candidate, before)
        self.assertNotIn('source:one', seen[0])
        self.assertNotIn('key:one', seen[0])
        self.assertIn('student:segment:1', seen[0])
        self.assertIn('instructor:answer_key', seen[0])
