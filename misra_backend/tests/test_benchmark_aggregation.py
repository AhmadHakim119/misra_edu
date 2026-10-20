"""Synthetic section rules only; no real paper marks or live policies."""
import unittest

from services.benchmark_aggregation import aggregate_section


class SectionAggregationTests(unittest.TestCase):
    def test_eight_available_marks_capped_at_six(self):
        maxima={str(index):1 for index in range(8)}
        for correct,expected in [(8,6),(7,6),(6,6),(5,5),(0,0)]:
            scores={key:int(int(key)<correct) for key in maxima}
            with self.subTest(correct=correct):
                result=aggregate_section(scores,maxima,cap=6)
                self.assertEqual(result['score'],expected)
                self.assertEqual(result['max_score'],6)
                self.assertEqual(result['uncapped_selected_total'],correct)
                self.assertEqual(result['question_scores'],scores)

    def test_best_n_whole_questions_is_separate_from_sum_cap(self):
        scores={'q1':2,'q2':4,'q3':3};maxima=dict.fromkeys(scores,4)
        best=aggregate_section(scores,maxima,best_n=2)
        capped=aggregate_section(scores,maxima,cap=8)
        self.assertEqual(best['score'],7);self.assertEqual(best['max_score'],8)
        self.assertEqual(best['selected_question_ids'],['q2','q3'])
        self.assertEqual(capped['score'],8)
        self.assertNotEqual(best['rule_sha256'],capped['rule_sha256'])

    def test_failed_or_missing_prediction_never_becomes_zero_or_discarded(self):
        for scores in ({'q1':2},{'q1':2,'q2':None}):
            result=aggregate_section(scores,{'q1':2,'q2':2},best_n=1)
            self.assertEqual(result['status'],'incomplete');self.assertIsNone(result['score'])
            self.assertEqual(result['missing_question_ids'],['q2'])
        self.assertEqual(aggregate_section({'q1':2,'q2':0},{'q1':2,'q2':2},best_n=1)['score'],2)

    def test_invalid_counts_caps_unknown_questions_and_scores_fail(self):
        for options in ({'best_n':True},{'best_n':0},{'best_n':2},{'cap':0},{'cap':3},{'cap':float('nan')}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                aggregate_section({'q1':1},{'q1':2},**options)
        for scores in ({'q1':True},{'q1':3},{'q1':-1},{'q1':float('inf')},{'q2':1}):
            with self.subTest(scores=scores),self.assertRaises(ValueError):
                aggregate_section(scores,{'q1':2})

    def test_ties_are_deterministic_and_inputs_unchanged(self):
        scores={'q2':1,'q1':1};maxima={'q2':2,'q1':2}
        result=aggregate_section(scores,maxima,best_n=1)
        self.assertEqual(result['selected_question_ids'],['q1'])
        self.assertEqual(scores,{'q2':1,'q1':1})
        self.assertEqual(maxima,{'q2':2,'q1':2})


if __name__=='__main__':unittest.main()
