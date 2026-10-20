import unittest
from services.review_policy_service import review_decision


class ReviewPolicyTests(unittest.TestCase):
    def decision(self, **changes):
        values = dict(confidence=99, model_confidence=98, legibility='clear',
                      verification_status='checked')
        return review_decision(**(values | changes))

    def test_high_blended_confidence_cannot_hide_uncertain_model(self):
        value = self.decision(confidence=85, model_confidence=70)
        self.assertTrue(value['needs_review'])
        self.assertIn('low_model_confidence', value['reasons'])
        self.assertEqual(value['basis'], 'heuristic_uncalibrated')
        self.assertFalse(value['automatic_finalization'])

    def test_exact_threshold_is_not_below(self):
        self.assertFalse(self.decision(confidence=70, model_confidence=95)['needs_review'])
        self.assertTrue(self.decision(confidence=69.9)['needs_review'])
        self.assertTrue(self.decision(model_confidence=94.9)['needs_review'])

    def test_missing_nan_and_boolean_signals_fail_closed(self):
        for value in (None, float('nan'), float('inf'), True, -1, 101):
            for field in ('confidence', 'model_confidence'):
                with self.subTest(field=field, value=value):
                    self.assertTrue(self.decision(**{field: value})['needs_review'])

    def test_hard_gates_survive_high_confidence(self):
        for changes, reason in [
            ({'legibility': 'partial'}, 'extraction_legibility_uncertain'),
            ({'legibility': None}, 'extraction_legibility_uncertain'),
            ({'verification_status': 'needs_review'}, 'verification_flagged'),
            ({'verification_status': 'not_run'}, 'verification_unavailable'),
            ({'aggregate_discrepancy': True}, 'model_total_discrepancy'),
            ({'require_new_review': True}, 'corrected_extraction_review_required'),
        ]:
            with self.subTest(changes=changes):
                result = self.decision(**changes)
                self.assertTrue(result['needs_review'])
                self.assertIn(reason, result['reasons'])

    def test_bad_configuration_is_rejected(self):
        for value in (True, None, -1, 101, float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.decision(model_threshold=value)
