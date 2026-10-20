import unittest
from services.benchmark_metrics import snapshot_hash
from services.review_metrics_service import review_operating_metrics


class ReviewMetricsTests(unittest.TestCase):
    def fixture(self):
        refs = [{'answer_id': str(i), 'paper_id': str(i), 'group_id': str(i),
                 'exam_version': 'synthetic', 'question_id': 'q', 'split': 'test',
                 'max_score': 2, 'score_step': 1, 'reference_score': 2,
                 'independent_reference': True, 'label_checked': True,
                 'input_reviewed': True, 'guide_checked': True, 'group_checked': True,
                 'fixed_inputs_sha256': snapshot_hash(i)} for i in range(7)]
        preds = [{'answer_id': ref['answer_id'], 'condition': 'no_rag',
                  'run_id': ref['answer_id'], 'fixed_inputs_sha256': ref['fixed_inputs_sha256'],
                  'system_sha256': snapshot_hash('system'), 'comparison_sha256': snapshot_hash('common'),
                  'retrieval_snapshot_sha256': None, 'status': 'scored', 'score': 2,
                  'confidence': 97, 'hard_review_required': False} for ref in refs[:6]]
        preds[0].update(score=1, confidence=90)  # caught error
        preds[1].update(score=1, confidence=99)  # missed error
        preds[2].update(confidence=80)  # reviewed exact
        preds[4].update(status='failed', score=None)
        preds[5].update(status='abstained', score=None)
        return refs, preds

    def test_confusion_workload_risk_and_coverage_have_explicit_denominators(self):
        refs, preds = self.fixture()
        result = review_operating_metrics(refs, preds, condition='no_rag', split='test', threshold=95)
        self.assertEqual(result['counts']['scored'], 4)
        self.assertEqual(result['counts']['unavailable'], 3)
        self.assertEqual(result['disagreement_recall'], .5)
        self.assertEqual(result['disagreement_precision'], .5)
        self.assertEqual(result['review_rate_over_expected'], 5 / 7)
        self.assertEqual(result['unflagged_disagreement_rate'], .5)
        self.assertEqual(result['exact_yield_over_expected'], 2 / 7)
        self.assertEqual(result['exact_agreement_among_scored'], .5)

    def test_missing_confidence_and_hard_gates_are_reviewed_at_any_threshold(self):
        refs, preds = self.fixture()
        preds[0]['confidence'] = None
        preds[1]['hard_review_required'] = True
        result = review_operating_metrics(refs, preds, condition='no_rag', split='test', threshold=0)
        self.assertEqual(result['counts']['missing_confidence'], 1)
        self.assertEqual(result['disagreement_recall'], 1)
        self.assertEqual(result['unflagged_disagreement_rate'], 0)

    def test_empty_rates_are_undefined_not_perfect(self):
        result = review_operating_metrics([], [], condition='bm25', split='test', threshold=97)
        self.assertIsNone(result['disagreement_recall'])
        self.assertIsNone(result['review_rate_over_expected'])
        self.assertIsNone(result['unflagged_disagreement_rate'])

    def test_failed_grades_cannot_be_recast_as_zero_and_invalid_thresholds_fail(self):
        refs, preds = self.fixture()
        preds[4]['score'] = 0
        with self.assertRaises(ValueError):
            review_operating_metrics(refs, preds, condition='no_rag', split='test', threshold=95)
        for threshold in (True, float('nan'), float('inf'), -1, 102):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                review_operating_metrics([], [], condition='no_rag', split='test', threshold=threshold)
