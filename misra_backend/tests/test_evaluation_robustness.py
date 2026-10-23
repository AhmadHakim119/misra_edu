"""Synthetic contrast detector and actual bounded-calculator invariants.

Imported fixture decisions exercise the metric, not an LLM's semantic ability.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from services.evaluation_robustness import summarize_robustness, validate_marking_bank
from services.grading_numeric_checks import evaluate_numeric_expression

BANK_PATH = Path(__file__).resolve().parents[2]/'evaluation/synthetic/marking-bank-v1.json'


class MarkingRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.bank = json.loads(BANK_PATH.read_text(encoding='utf-8'))
        self.predictions = [dict(answer_id=e['answer_id'], status='scored',
            score=sum(e['proposed_criterion_scores'].values()),
            criteria=[dict(criterion_id=c, score=s) for c, s in e['proposed_criterion_scores'].items()])
            for e in self.bank['examples']]

    def report(self):
        return summarize_robustness(self.bank, self.predictions, prediction_origin='synthetic_fixture')

    def change(self, aid, scores):
        r = next(r for r in self.predictions if r['answer_id']==aid)
        r['criteria'] = [dict(criterion_id=c, score=s) for c, s in scores.items()]
        r['score'] = sum(scores.values())

    def test_bank_covers_all_requested_categories_and_requires_approval(self):
        validate_marking_bank(self.bank)
        categories = {e['category'] for e in self.bank['examples']}
        self.assertTrue({'full_credit', 'partial_credit', 'no_credit', 'alternative_method', 'follow_through'} <= categories)
        self.assertEqual(self.bank['approval_status'], 'requires_instructor_approval')
        self.assertEqual(len(self.bank['examples']), 13)
        self.assertEqual(self.report()['matching_pair_count'], 5)
        self.assertIn('do not establish model robustness', self.report()['interpretation'])

    def test_equivalent_notation_and_paraphrases_must_preserve_criteria(self):
        self.change('syn-notation', dict(acceleration_method=0, acceleration_result=1, force_method=1, force_result=1))
        self.change('syn-paraphrase', dict(availability=1, mechanism=0))
        result = self.report()
        for kind in ('equivalent_notation', 'paraphrase'):
            self.assertEqual(result['by_kind'][kind]['matching_pair_count'], 0)

    def test_changed_sign_cannot_be_treated_as_equivalent(self):
        self.change('syn-sign', dict(acceleration_method=1, acceleration_result=1, force_method=1, force_result=1))
        report = self.report()
        self.assertEqual(report['by_kind']['changed_sign']['matching_pair_count'], 0)
        pair = next(r for r in report['pairs'] if r['kind']=='changed_sign')
        self.assertEqual(pair['observed_changed_criterion_ids'], [])
        self.assertEqual(pair['expected_changed_criterion_ids'], ['acceleration_result'])

    def test_negation_keyword_overlap_and_correct_numbers_with_wrong_reasoning_are_detected(self):
        self.change('syn-negation', dict(availability=1, mechanism=1))
        self.change('syn-reasoning', dict(acceleration_method=1, acceleration_result=1, force_method=1, force_result=1))
        report = self.report()
        self.assertEqual(report['by_kind']['negation']['matching_pair_count'], 0)
        self.assertEqual(report['by_kind']['incorrect_reasoning']['matching_pair_count'], 0)

    def test_equal_total_with_wrong_criterion_allocation_still_fails(self):
        self.change('syn-reasoning', dict(acceleration_method=1, acceleration_result=0, force_method=1, force_result=0))
        self.assertEqual(self.report()['by_kind']['incorrect_reasoning']['matching_pair_count'], 0)

    def test_missing_or_incomplete_decisions_do_not_shrink_pair_denominator(self):
        self.predictions = [r for r in self.predictions if r['answer_id']!='syn-full']
        report = self.report()
        self.assertEqual(report['scheduled_pair_count'], 5)
        self.assertEqual(report['complete_pair_count'], 2)
        self.assertEqual(report['matching_rate_over_scheduled'], .4)
        self.predictions[0]['criteria'][0]['score'] = None
        self.assertLessEqual(self.report()['complete_pair_count'], 2)

    def test_unknown_duplicate_nonfinite_and_inconsistent_inputs_rejected(self):
        for mutate in [lambda p: p.append(deepcopy(p[0])),
                       lambda p: p[0].update(answer_id='unknown'),
                       lambda p: p[0]['criteria'][0].update(score=True),
                       lambda p: p[0]['criteria'][0].update(score=float('nan')),
                       lambda p: p[0].update(score=0),
                       lambda p: p[0].update(status='failed')]:
            original = deepcopy(self.predictions)
            mutate(self.predictions)
            with self.assertRaises(ValueError):
                self.report()
            self.predictions = original

    def test_bank_approval_and_pair_expectations_cannot_change_silently(self):
        self.bank['approval_status'] = 'approved'
        with self.assertRaisesRegex(ValueError, 'pending'):
            validate_marking_bank(self.bank)
        self.bank['approval_status'] = 'requires_instructor_approval'
        self.bank['robustness_pairs'][0]['changed_criterion_ids'] = ['force_method']
        with self.assertRaisesRegex(ValueError, 'declared changed'):
            validate_marking_bank(self.bank)

    def test_actual_calculator_equivalent_notation_is_stable(self):
        for expression in ['(12-0)/3', '12÷3', '12/3', '2²', '2**2']:
            with self.subTest(expression=expression):
                result = evaluate_numeric_expression(expression)
                self.assertEqual(result['status'], 'computed')
                self.assertEqual(result['value'], 4)

    def test_actual_calculator_preserves_changed_sign_and_checks_follow_through(self):
        self.assertEqual(evaluate_numeric_expression('2(−4)')['value'], -8)
        self.assertEqual(evaluate_numeric_expression('2(4)')['value'], 8)
        self.assertEqual(evaluate_numeric_expression('2(5)')['value'], 10)
        self.assertNotEqual(evaluate_numeric_expression('2(5)')['value'], 7)

    def test_calculator_does_not_claim_to_validate_prose_or_physical_reasoning(self):
        for expression in ['force is mass divided by acceleration', 'F = m/a', 'not available', '__import__("os")']:
            with self.subTest(expression=expression):
                self.assertNotEqual(evaluate_numeric_expression(expression)['status'], 'computed')


if __name__ == '__main__':
    unittest.main()
