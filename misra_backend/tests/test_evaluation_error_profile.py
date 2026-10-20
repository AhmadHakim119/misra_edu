import unittest
from copy import deepcopy

from services.evaluation_error_profile import summarize_error_profile


def row(aid, score, reference, maximum=4, review=False, status='scored'):
    return dict(answer_id=aid, score=score, reference_score=reference,
        max_score=maximum, needs_review=review, status=status)


class ErrorProfileTests(unittest.TestCase):
    def report(self, rows):
        return summarize_error_profile(rows, reference_kind='historical')

    def test_opposing_errors_do_not_disappear_in_zero_bias(self):
        rows=[row('a',3,2,review=True),row('b',1,2)]
        original=deepcopy(rows);r=self.report(rows)
        self.assertEqual(r['normalized_bias_among_scored'],0)
        self.assertEqual(r['normalized_rmse_among_scored'],.25)
        self.assertEqual(r['directions']['above']['count'],1)
        self.assertEqual(r['directions']['below']['count'],1)
        self.assertEqual(r['directions']['above']['review_capture_rate'],1)
        self.assertEqual(r['directions']['below']['review_capture_rate'],0)
        self.assertEqual(r['unflagged_error_count'],1)
        self.assertEqual(r['worst_unflagged_normalized_absolute_error'],.25)
        self.assertEqual(rows,original)

    def test_different_mark_scales_have_comparable_normalized_severity(self):
        r=self.report([row('four',3,2),row('hundred',75,50,100)])
        self.assertEqual(r['normalized_rmse_among_scored'],.25)
        self.assertEqual(r['normalized_absolute_error_distribution'],[
            dict(normalized_absolute_error=.25,count=2,cumulative_count=2,cumulative_rate_among_scored=1)])
        self.assertFalse(r['acceptance_tolerance_fitted'])

    def test_unavailable_attempts_are_coverage_gaps_not_zero_grades(self):
        r=self.report([row('ok',2,2),row('failed',None,4,status='failed',review=True),
            row('abstained',None,3,status='abstained',review=True)])
        self.assertEqual(r['scheduled_count'],3)
        self.assertEqual(r['scored_count'],1)
        self.assertEqual(r['unavailable_count'],2)
        self.assertEqual(r['directions']['below']['count'],0)
        self.assertEqual(r['directions']['exact']['rate_over_scheduled'],1/3)
        self.assertEqual(r['directions']['exact']['rate_among_scored'],1)

    def test_empty_or_entirely_unavailable_profiles_have_no_error_estimate(self):
        for rows in [[],[row('missing',None,2,status='missing',review=True)]]:
            with self.subTest(rows=rows):
                r=self.report(rows)
                self.assertIsNone(r['normalized_rmse_among_scored'])
                self.assertIsNone(r['worst_normalized_absolute_error'])
                self.assertIsNone(r['directions']['above']['rate_among_scored'])
                self.assertEqual(r['normalized_absolute_error_distribution'],[])

    def test_numeric_comparison_precision_matches_primary_exact_metric(self):
        r=self.report([row('same',2+1e-10,2)])
        self.assertEqual(r['directions']['exact']['count'],1)
        self.assertEqual(r['normalized_absolute_error_distribution'][0]['normalized_absolute_error'],0)

    def test_reference_provenance_is_explicit_without_relabeling_correctness(self):
        for kind in ['historical','instructor_adjudicated','project_user_adjudicated','agent_development_audit']:
            r=summarize_error_profile([row('a',3,2)],reference_kind=kind)
            self.assertEqual(r['reference_kind'],kind)
            self.assertEqual(r['event'],'score_difference_against_supplied_references')
        with self.assertRaises(ValueError):summarize_error_profile([],reference_kind='validated_accuracy')

    def test_invalid_or_duplicate_observations_cannot_enter_distribution(self):
        for rows in [[row('a',5,2)],[row('a',None,2)],
                [row('a',2,2),row('a',3,2)],
                [row('a',0,2,status='failed')],
                [row('a',float('nan'),2)]]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):self.report(rows)

    def test_high_raw_confidence_cannot_erase_an_unflagged_disagreement(self):
        r=self.report([{**row('a',4,1),'confidence':100}])
        self.assertEqual(r['unflagged_error_count'],1)
        self.assertEqual(r['worst_normalized_absolute_error'],.75)
        self.assertFalse(r['confidence_calibrated'])


if __name__=='__main__':unittest.main()
