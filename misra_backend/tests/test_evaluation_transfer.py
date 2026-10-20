"""Synthetic cross-subject accounting, without inference or academic data."""
from copy import deepcopy
import unittest

from services.evaluation_transfer import summarize_transfer


def row(i, **changes):
    return dict(answer_id=str(i), subject_id='subject-a', question_id='q1',
        group_id=f'g{i}', group_checked=True, answer_previously_used=False,
        question_previously_used=False, student_previously_used=False,
        input_mode='checked_text', reference_kind='historical_teacher',
        status='scored', score=4, reference_score=4, max_score=4,
        score_step=1, needs_review=False) | changes


class TransferMetricsTests(unittest.TestCase):
    def test_large_easy_question_cannot_hide_small_failing_question(self):
        rows=[row(i) for i in range(9)]+[row(9,question_id='q2',score=2)]
        before=deepcopy(rows);r=summarize_transfer(rows)
        self.assertEqual(r['overall']['exact_rate_over_scheduled'],.9)
        self.assertEqual(r['question_macro_exact_yield'],.5)
        self.assertFalse(r['all_questions_reach_target_descriptively'])
        self.assertEqual(rows,before)

    def test_new_question_does_not_make_reused_student_held_out(self):
        r=summarize_transfer([row(1,student_previously_used=True)])
        self.assertEqual(list(r['exposure_groups']),['new_answer_reused_student_new_question'])
        self.assertFalse(r['confidence_calibrated'])

    def test_reused_answers_remain_regression_evidence(self):
        r=summarize_transfer([row(1,answer_previously_used=True,student_previously_used=True,question_previously_used=True)])
        self.assertEqual(list(r['exposure_groups']),['reused_answer_regression'])

    def test_subject_macro_and_normalized_error_work_on_different_scales(self):
        rows=[row(i) for i in range(3)]+[row(4,subject_id='subject-b',max_score=100,score_step=5,reference_score=100,score=90)]
        r=summarize_transfer(rows)
        self.assertEqual(r['subject_macro_exact_yield'],.5)
        self.assertEqual(r['overall']['normalized_mae_among_scored'],.025)

    def test_missing_attempt_is_no_success_and_no_zero_grade(self):
        r=summarize_transfer([row(1),row(2,status='missing',score=None),row(3,score=3,needs_review=True)])
        self.assertEqual(r['overall']['exact_rate_over_scheduled'],1/3)
        self.assertEqual(r['within_one_score_step_yield'],2/3)
        self.assertEqual(r['overall']['mae_marks_among_scored'],.5)

    def test_stage_mixing_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize_transfer([row(1),row(2,input_mode='raw_ocr')])

    def test_historical_and_adjudicated_references_are_visible(self):
        r=summarize_transfer([row(1),row(2,reference_kind='instructor_adjudicated')])
        self.assertEqual(set(r['reference_kinds']),{'historical_teacher','instructor_adjudicated'})
        self.assertEqual(r['overall']['event'],'exact_mixed_reference_agreement')
        self.assertEqual(r['reference_kinds']['instructor_adjudicated']['event'],
            'exact_instructor_adjudicated_reference_agreement')

    def test_reused_answer_cannot_be_reported_as_a_new_question_or_student(self):
        for changes in [dict(answer_previously_used=True),dict(answer_previously_used=True,
                question_previously_used=True),dict(answer_previously_used=True,student_previously_used=True)]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                summarize_transfer([row(1,**changes)])

    def test_same_question_exposure_cannot_vary_between_answers(self):
        with self.assertRaises(ValueError):
            summarize_transfer([row(1),row(2,question_previously_used=True)])

    def test_exposure_and_group_checks_are_required(self):
        for change in [dict(group_checked=False),dict(student_previously_used=None),
                       dict(question_previously_used=1),dict(answer_previously_used=None)]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                summarize_transfer([row(1,**change)])

    def test_grid_and_question_scale_inconsistency_is_rejected(self):
        for rows in [[row(1,score=3.5)],[row(1,score_step=3)],
                     [row(1),row(2,max_score=5)],
                     [row(1,group_id='same'),row(2,group_id='same',student_previously_used=True)]]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):summarize_transfer(rows)

    def test_student_cluster_bootstrap_retains_within_student_correlation(self):
        rows=[row(i,group_id='g0' if i<4 else 'g1',question_id=f'q{i%4}',score=4 if i<4 else 2) for i in range(8)]
        a=summarize_transfer(rows,seed=22);b=summarize_transfer(rows,seed=22)
        self.assertEqual(a['student_cluster_bootstrap'],b['student_cluster_bootstrap'])
        self.assertEqual(a['student_cluster_bootstrap']['cluster_count'],2)
        self.assertEqual(a['student_cluster_bootstrap']['interval_95'],dict(lower=0,upper=1))
        self.assertEqual(a['question_cluster_bootstrap']['cluster_count'],4)

    def test_empty_or_one_cluster_does_not_create_perfect_interval(self):
        r=summarize_transfer([])
        self.assertIsNone(r['overall']['exact_rate_over_scheduled'])
        self.assertIsNone(r['all_questions_reach_target_descriptively'])
        self.assertIsNone(r['student_cluster_bootstrap']['interval_95'])
        self.assertIsNone(summarize_transfer([row(1)])['question_cluster_bootstrap']['interval_95'])

    def test_bootstrap_protocol_is_bounded(self):
        for changes in [dict(bootstrap_samples=True),dict(bootstrap_samples=99),dict(seed=False)]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                summarize_transfer([row(1)],**changes)


if __name__=='__main__':unittest.main()
