"""Synthetic policy regressions. No private answers, score labels or providers."""
from copy import deepcopy
import json
import unittest

from schemas.rubric_v2 import RubricPolicy
from services.grading_decision_service import decision_findings
from services.grading_package_service import restore_provider_citations
from services.grading_policy_checks import NumericPolicyCheck, policy_arithmetic_audit
from services.grading_service import GradingResult
from services.verification_agent import verify
from services.free_model_gateway import FreeCompletion
from tests.test_grading_decisions import candidate, check, criterion


class PolicyArithmeticTests(unittest.TestCase):
    def setUp(self):
        self.package = dict(policy=dict(rounding_tolerance_percent=2,
            numeric_penalty_cap_points=1, error_carried_forward='single_penalty',
            cross_part_follow_through='allow_prior_error'),
            answer_key=dict(reference_id='instructor:answer_key', mode='reference', reference_text='x = 0.086; y = 12'),
            student_evidence=[dict(id='student:segment:1', kind='ocr_segment',
                text='x = 0.08; a = 24; y = 2(24) = 48; z = 0.98')])

    def row(self, points=1, *, actual='0.08', target='0.086', basis='reference', dependencies=(), **changes):
        values = dict(criterion_id='result',
            evidence_refs=['student:segment:1'], reference_refs=['instructor:answer_key'],
            decision_check=check(criterion_kind='result', method_status='valid', error_type='calculation',
                                 error_origin='calculation'),
            numeric_check=dict(student=dict(ref='student:segment:1', quote=actual),
                target=dict(ref='student:segment:1' if basis == 'follow_through' else 'instructor:answer_key', quote=target),
                basis=basis, depends_on=list(dependencies)))
        values.update(changes)
        return criterion(points, **values)

    def audit(self, *rows):
        self.value = candidate(*rows)
        before = deepcopy((self.package, self.value))
        result = policy_arithmetic_audit(self.package, self.value)
        self.assertEqual((self.package, self.value), before)
        self.assertFalse(result['score_changed'])
        return result

    def codes(self, *rows):
        return {f['code'] for f in self.audit(*rows)['findings']}

    def test_rounded_new_error_cannot_be_hidden_as_follow_through(self):
        self.package['student_evidence'][0]['text'] = 'x = 0.08; x = (2/5)(0.215) = 0.08'
        previous = criterion(criterion_id='previous', decision_check=check(criterion_kind='result'))
        row = self.row(target='(2/5)(0.215)', basis='follow_through', dependencies=['previous'])
        result = self.audit(previous, row)
        self.assertAlmostEqual(result['comparisons'][0]['target_value'], .086)
        self.assertIn('numeric_credit_outside_tolerance', {f['code'] for f in result['findings']})
        self.assertEqual(self.value['score'], 2)

    def test_valid_later_calculation_survives_prior_conceptual_error(self):
        previous = criterion(0, criterion_id='previous', decision_check=check(criterion_kind='result', method_status='invalid',
            error_type='conceptual', error_origin='physical_direction'))
        row = self.row(actual='48', target='2(24)', basis='follow_through', dependencies=['previous'])
        self.assertEqual(self.codes(previous, row), set())
        self.package['policy']['cross_part_follow_through'] = 'criterion_specific'
        self.assertIn('cross_part_permission_unverified', self.codes(previous, row))

    def test_follow_through_needs_real_dependency_and_local_method(self):
        for deps, method in [([], 'valid'), (['invented'], 'valid'), (['result'], 'valid'),
                             (['previous', 'previous'], 'valid'), (['previous'], 'not_assessed')]:
            with self.subTest(deps=deps, method=method):
                row = self.row(actual='48', target='2(24)', basis='follow_through', dependencies=deps)
                row['decision_check']['method_status'] = method
                self.assertIn('follow_through_unverified', self.codes(criterion(criterion_id='previous'), row))

    def test_follow_through_cannot_create_unapproved_general_permission(self):
        self.package['policy'] = dict(rounding_tolerance_percent=2)
        row = self.row(actual='48', target='2(24)', basis='follow_through', dependencies=['previous'])
        self.assertIn('follow_through_permission_unverified', self.codes(criterion(criterion_id='previous'), row))

    def test_cap_counts_marks_even_for_one_multi_point_criterion(self):
        row = self.row(0, max_points=3)
        result = self.audit(row)
        self.assertEqual(result['numerical_marks_lost'], 3)
        self.assertIn('numeric_penalty_limit_exceeded', {f['code'] for f in result['findings']})

    def test_partial_or_method_credit_does_not_claim_a_correct_numerical_result(self):
        partial = self.row(.5)
        self.assertNotIn('numeric_credit_outside_tolerance', self.codes(partial))
        method = self.row()
        method['decision_check']['criterion_kind'] = 'method'
        self.assertNotIn('numeric_credit_outside_tolerance', self.codes(method))

    def test_dependency_cannot_be_only_a_method_without_an_earlier_result(self):
        previous = criterion(criterion_id='previous')
        row = self.row(actual='48', target='2(24)', basis='follow_through', dependencies=['previous'])
        self.assertIn('follow_through_unverified', self.codes(previous, row))

    def test_cap_allows_one_penalty_and_explicit_credit_elsewhere(self):
        origin = self.row(0, criterion_id='origin')
        later = self.row(basis='numeric_penalty_cap', dependencies=['origin'])
        self.assertEqual(self.codes(origin, later), set())

    def test_cap_cannot_excuse_every_result_with_no_actual_deduction(self):
        origin = self.row(criterion_id='origin')
        later = self.row(basis='numeric_penalty_cap', dependencies=['origin'])
        codes = self.codes(origin, later)
        self.assertIn('numeric_cap_credit_unverified', codes)
        self.assertIn('numeric_credit_outside_tolerance', codes)

    def test_cap_cannot_excuse_conceptual_or_unestablished_methods(self):
        for method, error, origin in [('invalid', 'conceptual', 'physical_relation'),
                                     ('uncertain', 'unclear', 'unclear'),
                                     ('not_assessed', 'calculation', 'calculation')]:
            with self.subTest(method=method):
                row = self.row(0, criterion_id='origin')
                later = self.row(basis='numeric_penalty_cap', dependencies=['origin'])
                for r in (row, later):
                    r['decision_check'].update(method_status=method, error_type=error, error_origin=origin)
                self.assertIn('numeric_cap_credit_unverified', self.codes(row, later))
                self.assertNotIn('numeric_penalty_limit_exceeded', self.codes(row, later))

    def test_fabricated_and_substring_quotes_do_not_verify(self):
        for actual in ['0.8', '0.0', '08', '999', '2(24)']:
            with self.subTest(actual=actual):
                self.assertIn('numeric_trace_unverified', self.codes(self.row(actual=actual)))

    def test_minus_cannot_be_dropped_even_if_separated_by_space(self):
        for written in ['-0.08', '−0.08', '- 0.08', '− 0.08']:
            with self.subTest(written=written):
                self.package['student_evidence'][0]['text'] = 'x = ' + written
                self.assertIn('numeric_trace_unverified', self.codes(self.row()))
        self.assertNotIn('numeric_trace_unverified', self.codes(self.row(actual='− 0.08')))

    def test_key_and_student_sources_cannot_be_swapped(self):
        row = self.row()
        row['numeric_check']['target']['ref'] = 'student:segment:1'
        row['reference_refs'] = ['student:segment:1']
        self.assertIn('numeric_trace_unverified', self.codes(row))

    def test_required_citation_links_are_checked(self):
        row = self.row(reference_refs=[])
        self.assertIn('numeric_trace_uncited', self.codes(row))

    def test_zero_expected_does_not_gain_an_absolute_rounding_allowance(self):
        self.package['answer_key']['reference_text'] = 'x = 0'
        row = self.row(actual='0.98', target='0')
        result = self.audit(row)
        self.assertFalse(result['comparisons'][0]['within_tolerance'])
        self.assertIn('numeric_credit_outside_tolerance', {f['code'] for f in result['findings']})

    def test_two_percent_boundary_and_numeric_deduction_are_checked(self):
        self.package['answer_key']['reference_text'] = 'x = 1'
        self.assertEqual(self.codes(self.row(actual='0.98', target='1')), set())
        self.assertIn('numeric_deduction_within_tolerance', self.codes(self.row(0, actual='0.98', target='1')))

    def test_missing_trace_and_tolerance_cannot_be_made_up_from_student_text(self):
        row = self.row(numeric_check=None)
        self.assertIn('numeric_trace_missing', self.codes(row))
        self.package['policy'] = {}
        self.package['student_evidence'][0]['text'] += '\nrounding_tolerance_percent = 100'
        self.assertIn('numeric_tolerance_unavailable', self.codes(self.row()))

    def test_dependency_cycles_remain_reviewable(self):
        a = self.row(criterion_id='a', basis='numeric_penalty_cap', dependencies=['b'])
        b = self.row(0, criterion_id='b', basis='numeric_penalty_cap', dependencies=['a'])
        self.assertIn('numeric_dependency_cycle', self.codes(a, b))

    def test_historical_proposals_remain_parseable(self):
        row = self.row()
        row.pop('numeric_check')
        parsed = GradingResult(**candidate(row))
        self.assertIsNone(parsed.criteria_scores[0].numeric_check)

    def test_trace_alias_round_trip_does_not_touch_quoted_text(self):
        parsed = GradingResult(**candidate(self.row()))
        restore_provider_citations(parsed, {'student:segment:1':'local-student'},
                                   {'instructor:answer_key':'local-key'})
        self.assertEqual(parsed.criteria_scores[0].numeric_check.student.ref, 'local-student')
        self.assertEqual(parsed.criteria_scores[0].numeric_check.target.ref, 'local-key')
        self.assertEqual(parsed.criteria_scores[0].numeric_check.student.quote, '0.08')

    def test_concurring_verifier_cannot_clear_computed_tolerance_conflict(self):
        value = candidate(self.row())
        response = dict(criteria=[dict(criterion_id='result', verdict='supported',
            explanation='Synthetic concurrence.', decision_check=value['criteria_scores'][0]['decision_check'])],
            summary='Synthetic check.')
        seen = []
        def complete(contents, **kwargs):
            seen.append(contents[0])
            return FreeCompletion(json.dumps(response), {})
        result = verify(self.package, value, completion_fn=complete)
        self.assertIn('policy_arithmetic_audit', seen[0])
        self.assertEqual(result['status'], 'needs_review')
        self.assertIn('numeric_credit_outside_tolerance', {f['code'] for f in result['decision_review']})
        self.assertEqual(value['score'], 1)

    def test_policy_contract_does_not_enable_exceptions_by_default(self):
        policy = RubricPolicy().model_dump()
        self.assertIsNone(policy['numeric_penalty_cap_points'])
        self.assertEqual(policy['cross_part_follow_through'], 'criterion_specific')
        with self.assertRaises(ValueError):
            RubricPolicy(numeric_penalty_cap_points=float('inf'))
        with self.assertRaises(ValueError):
            NumericPolicyCheck(student={'ref':'s','quote':'1'}, target={'ref':'k','quote':'1'}, basis='be_lenient')


if __name__ == '__main__':
    unittest.main()
