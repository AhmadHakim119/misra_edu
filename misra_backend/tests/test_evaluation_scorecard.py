"""Synthetic accounting tests. No inference or private academic records."""
from copy import deepcopy
import unittest

from services.evaluation_criteria import summarize_criteria
from services.evaluation_review import review_risk_coverage
from services.evaluation_scorecard import build_scorecard


def row(aid='a', **changes):
    return dict(answer_id=aid, subject_id='synthetic', question_id='q', group_id='g'+aid,
        group_checked=True, answer_previously_used=False, question_previously_used=False,
        student_previously_used=False, input_mode='checked_text', reference_kind='instructor_adjudicated',
        status='scored', score=2, reference_score=2, max_score=2, score_step=1,
        needs_review=False, hard_review_required=False, review_risk=.1,
        reference_criteria=[dict(criterion_id='method', max_score=1, score_step=1, reference_score=1),
                            dict(criterion_id='result', max_score=1, score_step=1, reference_score=1)],
        criteria=[dict(criterion_id='method', score=1), dict(criterion_id='result', score=1)]) | changes


def scores(method, result):
    return [dict(criterion_id='method', score=method), dict(criterion_id='result', score=result)]


class CriterionErrorTests(unittest.TestCase):
    def test_matching_total_can_hide_false_credit_and_denied_credit(self):
        r = row(score=1, reference_score=1, criteria=scores(0, 1))
        r['reference_criteria'][1]['reference_score'] = 0
        before = deepcopy(r)
        report = summarize_criteria([r])
        self.assertEqual(report['exact_count'], 0)
        self.assertEqual(report['above_reference_count'], 1)
        self.assertEqual(report['below_reference_count'], 1)
        self.assertEqual(report['points_above_reference'], 1)
        self.assertEqual(report['points_below_reference'], 1)
        self.assertEqual(report['total_agreement_with_offsetting_criterion_errors'], ['a'])
        self.assertEqual(r, before)

    def test_missing_decision_and_missing_label_are_distinct_from_zero(self):
        r = row(criteria=scores(0, None), score=0, reference_score=1)
        r['reference_criteria'][0]['reference_score'] = None
        result = summarize_criteria([r])
        self.assertEqual(result['labelled_count'], 1)
        self.assertEqual(result['unlabelled_count'], 1)
        self.assertEqual(result['comparable_count'], 0)
        self.assertEqual(result['missing_prediction_count'], 1)
        self.assertIsNone(result['exact_rate_among_comparable'])
        self.assertEqual(result['exact_rate_over_labelled'], 0)

    def test_unavailable_answer_retains_all_labelled_criteria(self):
        result = summarize_criteria([row(status='failed', score=None, criteria=[])])
        self.assertEqual(result['missing_prediction_count'], 2)
        self.assertEqual(result['exact_rate_over_labelled'], 0)

    def test_total_labels_alone_cannot_establish_criterion_agreement(self):
        result = summarize_criteria([row(reference_criteria=[], criteria=[])])
        self.assertEqual(result['answers_without_criterion_rubric_count'], 1)
        self.assertIsNone(result['exact_rate_over_labelled'])

    def test_same_criterion_id_in_different_questions_is_not_merged(self):
        result = summarize_criteria([row(), row('b', question_id='q2')])
        self.assertEqual(len(result['per_criterion']), 4)

    def test_partial_labels_and_decisions_must_still_be_compatible_with_totals(self):
        r = row(reference_score=0)
        r['reference_criteria'][0]['reference_score'] = None
        with self.assertRaisesRegex(ValueError, 'Partial criterion references'):
            summarize_criteria([r])
        with self.assertRaisesRegex(ValueError, 'Partial criterion predictions'):
            summarize_criteria([row(score=0, criteria=scores(1, None))])

    def test_empty_scorecard_does_not_turn_no_evidence_into_success(self):
        result = build_scorecard([], reference_kind='instructor_adjudicated', bootstrap_samples=100)
        self.assertIsNone(result['headline']['rate'])
        self.assertIsNone(result['criterion_errors']['exact_rate_over_labelled'])
        self.assertEqual(result['transfer']['overall']['event'], 'exact_reference_agreement')

    def test_invalid_criterion_scores_ids_and_totals_fail_closed(self):
        cases = [row(criteria=scores(True, 1)), row(criteria=scores(float('nan'), 1)),
                 row(criteria=scores(.5, 1), score=1.5), row(criteria=scores(2, 0)),
                 row(criteria=scores(1, 0)), row(reference_score=1),
                 row(criteria=[dict(criterion_id='invented', score=0)]),
                 row(criteria=scores(1, 1)+scores(1, 1)),
                 row(status='failed', score=None), row(reference_criteria=[], criteria=scores(1, 1))]
        wrong_maximum = row()
        wrong_maximum['reference_criteria'][0]['max_score'] = 2
        cases.append(wrong_maximum)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                summarize_criteria([case])


class ReviewCurveTests(unittest.TestCase):
    def report(self, rows, threshold=.25):
        return review_risk_coverage(rows, threshold=threshold, reference_kind='instructor_adjudicated')

    def test_threshold_ties_enter_together_and_hard_gates_never_clear(self):
        rows = [row(), row('b', score=1, criteria=scores(1, 0)),
                row('c', hard_review_required=True, needs_review=True, review_risk=0),
                row('d', score=None, status='missing', criteria=[], needs_review=True),
                row('e', review_risk=None)]
        result = self.report(rows)
        self.assertEqual(len(result['curve']), 2)
        self.assertEqual([p['retained_count'] for p in result['curve']], [0, 2])
        operating = result['operating_point']
        self.assertEqual(operating['coverage_over_scheduled'], .4)
        self.assertEqual(operating['retained_disagreement_rate'], .5)
        self.assertEqual(operating['review_or_unavailable_count'], 3)
        self.assertEqual(operating['disagreement_recall'], 0)
        self.assertEqual(result['missing_risk_scored_count'], 1)

    def test_high_risk_error_is_captured_with_explicit_review_burden(self):
        rows = [row(), row('b', score=0, criteria=scores(0, 0), review_risk=.9, needs_review=True)]
        p = self.report(rows)['operating_point']
        self.assertEqual(p['coverage_over_scheduled'], .5)
        self.assertEqual(p['retained_disagreement_rate'], 0)
        self.assertEqual(p['disagreement_recall'], 1)
        self.assertEqual(p['review_precision_for_disagreement'], 1)
        self.assertEqual(p['review_or_unavailable_rate'], .5)

    def test_empty_retained_set_has_undefined_risk_not_zero_risk(self):
        result = self.report([row(hard_review_required=True, needs_review=True)])
        self.assertIsNone(result['operating_point']['retained_disagreement_rate'])
        self.assertIsNone(self.report([])['operating_point']['coverage_over_scheduled'])

    def test_bad_risk_or_cleared_hard_gate_rejected(self):
        for changes in [dict(review_risk=True), dict(review_risk=-.1), dict(review_risk=float('nan')),
                        dict(review_risk=1.01), dict(hard_review_required=None), dict(hard_review_required=True)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.report([row(**changes)])
        for threshold in (True, -1, float('nan'), 2):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                self.report([row()], threshold)

    def test_looser_threshold_only_increases_coverage_and_keeps_errors_visible(self):
        rows = [row(), row('b', score=0, review_risk=.9)]
        points = self.report(rows)['curve']
        self.assertEqual([p['retained_count'] for p in points], [0, 1, 2])
        self.assertEqual(points[-1]['retained_disagreement_rate'], .5)


class ScorecardTests(unittest.TestCase):
    def test_headline_reuses_exact_scheduled_denominator(self):
        rows = [row(), row('b', status='failed', score=None, criteria=[], needs_review=True)]
        before = deepcopy(rows)
        result = build_scorecard(rows, reference_kind='instructor_adjudicated', bootstrap_samples=100)
        self.assertEqual(result['headline']['rate'], .5)
        self.assertEqual(result['headline']['rate_among_scored'], 1)
        self.assertEqual(result['reliability'], result['transfer']['overall'])
        self.assertEqual(result['criterion_errors']['missing_prediction_count'], 2)
        self.assertIsNone(result['per_question_qwk'][0]['qwk'])
        self.assertEqual(rows, before)

    def test_provenance_and_input_stages_are_not_pooled(self):
        for changes in [dict(reference_kind='historical_teacher'), dict(input_mode='raw_ocr')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_scorecard([row(), row('b', **changes)], reference_kind='instructor_adjudicated')

    def test_confidence_is_diagnostic_not_a_review_override(self):
        r = row(confidence=100, hard_review_required=True, needs_review=True)
        result = build_scorecard([r], reference_kind='instructor_adjudicated', bootstrap_samples=100)
        self.assertFalse(result['reliability']['confidence_calibrated'])
        self.assertEqual(result['review']['operating_point']['retained_count'], 0)
        for value in [True, 101, float('inf')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_scorecard([row(confidence=value)], reference_kind='instructor_adjudicated')

    def test_agent_labels_stay_agent_labels_through_transfer(self):
        result = build_scorecard([row(reference_kind='agent_development_audit')],
                                reference_kind='agent_development_audit', bootstrap_samples=100)
        self.assertEqual(result['headline']['reference_kind'], 'agent_development_audit')
        self.assertIn('agent_development', result['transfer']['overall']['event'])

    def test_qwk_keeps_question_scale_boundaries(self):
        result = build_scorecard([row('a', score=0, criteria=scores(0, 0)),
            row('b', reference_score=0, score=0, reference_criteria=[
                dict(criterion_id='method', max_score=1, score_step=1, reference_score=0),
                dict(criterion_id='result', max_score=1, score_step=1, reference_score=0)], criteria=scores(0, 0))],
                reference_kind='instructor_adjudicated', bootstrap_samples=100)
        self.assertEqual(result['per_question_qwk'][0]['qwk'], 0)
        self.assertEqual(result['headline']['rate'], .5)


if __name__ == '__main__':
    unittest.main()
