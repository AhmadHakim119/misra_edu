"""Synthetic metric accounting; no academic data or provider calls."""
from copy import deepcopy
import unittest

from services.evaluation_reliability import summarize_reliability, summarize_replicates, wilson_interval


def observation(i, **changes):
    return dict(answer_id=str(i), status='scored', score=4, max_score=4,
                reference_score=4, needs_review=False) | changes


class ReliabilityTests(unittest.TestCase):
    def test_default_historical_event_is_unchanged(self):
        result = summarize_reliability([observation(1)])
        self.assertEqual(result['event'], 'exact_historical_reference_agreement')
        self.assertIn('Historical labels', result['interpretation'])

    def test_reference_provenance_changes_label_not_metric_accounting(self):
        rows = [observation(1), observation(2, score=3, needs_review=True),
                observation(3, status='abstained', score=None, needs_review=True)]
        before = deepcopy(rows)
        baseline = summarize_reliability(rows)
        events = {
            'instructor_adjudicated': 'exact_instructor_adjudicated_reference_agreement',
            'project_user_adjudicated': 'exact_project_user_adjudicated_reference_agreement',
            'agent_development_audit': 'exact_agent_development_audit_agreement',
        }
        for kind, event in events.items():
            with self.subTest(kind=kind):
                result = summarize_reliability(rows, reference_kind=kind)
                self.assertEqual(result['event'], event)
                for key in baseline.keys() - {'event', 'interpretation'}:
                    self.assertEqual(result[key], baseline[key], key)
        self.assertEqual(rows, before)

    def test_agent_and_project_user_labels_are_not_called_instructor_labels(self):
        agent = summarize_reliability([observation(1)], reference_kind='agent_development_audit')
        user = summarize_reliability([observation(1)], reference_kind='project_user_adjudicated')
        self.assertIn('not independent human adjudication', agent['interpretation'])
        self.assertIn('distinct from instructor adjudication', user['interpretation'])
        self.assertNotIn('instructor_adjudicated', agent['event'])
        self.assertNotIn('instructor_adjudicated', user['event'])

    def test_unknown_reference_kind_rejected_even_for_empty_data(self):
        for kind in [None, '', 'validated_accuracy', 'mixed', [], True]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                summarize_reliability([], reference_kind=kind)

    def test_replicates_preserve_explicit_reference_provenance(self):
        runs = [{'replicate_id': 'one', 'observations': [observation(1)]},
                {'replicate_id': 'two', 'observations': [observation(1, score=3)]}]
        result = summarize_replicates(runs, reference_kind='agent_development_audit')
        self.assertEqual(result['unique_answer_count'], 1)
        self.assertEqual(result['consistently_exact_rate'], 0)
        for report in result['per_replicate'].values():
            self.assertEqual(report['event'], 'exact_agent_development_audit_agreement')

    def test_replicates_reject_unknown_reference_kind_before_reporting(self):
        with self.assertRaises(ValueError):
            summarize_replicates([{'replicate_id': 'one', 'observations': [observation(1)]}],
                                 reference_kind='validated_accuracy')

    def test_failures_stay_in_target_denominator_without_becoming_zero_grades(self):
        rows = [observation(i) for i in range(4)] + [observation(4, status='failed', score=None)]
        before = deepcopy(rows)
        result = summarize_reliability(rows)
        self.assertEqual(result['exact_rate_over_scheduled'], .8)
        self.assertEqual(result['exact_rate_among_scored'], 1)
        self.assertEqual(result['mae_marks_among_scored'], 0)
        self.assertTrue(result['target_met_descriptively'])
        self.assertFalse(result['interval_lower_reaches_target'])
        self.assertEqual(rows, before)

    def test_review_capture_does_not_inflate_exact_agreement(self):
        result = summarize_reliability([observation(1), observation(2, score=2, needs_review=True)])
        self.assertEqual(result['exact_rate_over_scheduled'], .5)
        self.assertEqual(result['disagreement_recall'], 1)
        self.assertEqual(result['review_rate_among_scored'], .5)
        self.assertEqual(result['unflagged_disagreement_count'], 0)
        self.assertFalse(result['target_met_descriptively'])

    def test_empty_and_undefined_rates_are_not_perfect_results(self):
        empty = summarize_reliability([])
        self.assertIsNone(empty['exact_rate_over_scheduled'])
        perfect = summarize_reliability([observation(1, needs_review=True)])
        self.assertIsNone(perfect['disagreement_recall'])
        self.assertIsNone(perfect['unflagged_disagreement_rate'])

    def test_bad_records_cannot_silently_change_denominators(self):
        for rows in [[observation(1), observation(1)], [observation(1, score=float('nan'))],
                     [observation(1, status='missing', score=0)], [observation(1, needs_review=1)],
                     [observation(1, reference_score=5)], [observation(1, score=True)]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                summarize_reliability(rows)

    def test_wilson_bounds_and_small_sample_uncertainty(self):
        interval = wilson_interval(5, 7)
        self.assertAlmostEqual(interval['lower'], .35893445)
        self.assertAlmostEqual(interval['upper'], .91778108)
        self.assertIsNone(wilson_interval(0, 0))
        with self.assertRaises(ValueError):
            wilson_interval(8, 7)

    def test_repeats_do_not_pool_samples_or_choose_the_better_run(self):
        runs=[{'replicate_id':'first','observations':[observation(1),observation(2,score=3)]},
              {'replicate_id':'second','observations':[observation(1),observation(2)]}]
        before=deepcopy(runs)
        result=summarize_replicates(runs)
        self.assertEqual(result['unique_answer_count'],2)
        self.assertEqual(result['consistently_exact_rate'],.5)
        self.assertEqual(result['score_stable_answer_count'],1)
        self.assertFalse(result['target_met_in_every_replicate'])
        self.assertEqual(runs,before)

    def test_failed_repeat_cannot_establish_a_stable_or_exact_grade(self):
        result=summarize_replicates([
            {'replicate_id':'first','observations':[observation(1)]},
            {'replicate_id':'second','observations':[observation(1,status='failed',score=None)]}])
        self.assertEqual(result['consistently_exact_rate'],0)
        self.assertEqual(result['score_stable_answer_count'],0)
        self.assertIsNone(result['answers'][0]['score_range'])
        self.assertEqual(result['per_replicate']['second']['unavailable_count'],1)

    def test_repeat_cohorts_scales_references_and_ids_must_match(self):
        first={'replicate_id':'first','observations':[observation(1)]}
        for second in [first,{'replicate_id':'second','observations':[]},
                       {'replicate_id':'second','observations':[observation(2)]},
                       {'replicate_id':'second','observations':[observation(1,reference_score=3)]},
                       {'replicate_id':'second','observations':[observation(1,max_score=5)]}]:
            with self.subTest(second=second),self.assertRaises(ValueError):
                summarize_replicates([first,second])
        with self.assertRaises(ValueError):summarize_replicates([])

    def test_repeated_wrong_score_is_stable_without_becoming_exact(self):
        result=summarize_replicates([
            {'replicate_id':'first','observations':[observation(1,score=3)]},
            {'replicate_id':'second','observations':[observation(1,score=3)]}])
        self.assertEqual(result['score_stable_answer_count'],1)
        self.assertEqual(result['consistently_exact_answer_count'],0)


if __name__ == '__main__':
    unittest.main()
