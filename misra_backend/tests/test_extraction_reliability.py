"""Synthetic extraction metrics; no private answers or provider calls."""
import unittest

from services.extraction_reliability import summarize_extraction_review


def row(identifier, error, warning, status='reviewed'):
    return {'answer_id': identifier, 'status': status, 'grade_sensitive_error': error,
            'ocr_reported_uncertainty': warning}


class ExtractionReliabilityTests(unittest.TestCase):
    def test_silent_errors_remain_errors_even_when_other_answers_are_flagged(self):
        result = summarize_extraction_review([row('a', True, False), row('b', False, True),
                                             row('c', True, True), row('d', False, False)])
        self.assertEqual(result['grade_sensitive_error_count'], 2)
        self.assertEqual(result['silent_material_error_count'], 1)
        self.assertEqual(result['uncertainty_recall_for_material_error'], .5)
        self.assertEqual(result['uncertainty_precision_for_material_error'], .5)
        self.assertEqual(result['error_free_yield_over_scheduled'], .5)

    def test_unavailable_and_pending_cases_never_become_clean_answers(self):
        result = summarize_extraction_review([row('a', False, False),
            row('b', None, None, 'unavailable'), row('c', None, True, 'needs_adjudication')])
        self.assertEqual(result['scheduled_count'], 3)
        self.assertEqual(result['conclusively_reviewed_count'], 1)
        self.assertEqual(result['unavailable_count'], 1)
        self.assertEqual(result['adjudication_pending_count'], 1)
        self.assertEqual(result['error_free_yield_over_scheduled'], 1 / 3)
        self.assertIsNone(result['uncertainty_recall_for_material_error'])

    def test_undefined_rates_are_null_and_confidence_is_not_fitted(self):
        result = summarize_extraction_review([])
        for key in ['error_rate_among_conclusively_reviewed', 'error_free_yield_over_scheduled',
                    'uncertainty_precision_for_material_error', 'silent_material_error_rate_over_scheduled']:
            self.assertIsNone(result[key])
        self.assertFalse(result['confidence_calibrated'])

    def test_duplicates_unknown_status_and_unchecked_labels_are_rejected(self):
        invalid = [[row('a', False, False), row('a', True, True)], [row('', False, False)],
            [row('a', None, False)], [row('a', 1, True)], [row('a', False, 0)],
            [row('a', False, None, 'unavailable')], [row('a', None, False, 'unavailable')],
            [row('a', None, None, 'needs_adjudication')], [row('a', False, False, 'parsed')]]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                summarize_extraction_review(rows)


if __name__ == '__main__':
    unittest.main()
