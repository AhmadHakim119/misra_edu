"""Synthetic literal review cases; no private papers or provider calls."""
import unittest
from services.ocr_text_diff import compare_literal_text, MAX_CHARACTERS, MAX_TOKENS


class LiteralDiffTests(unittest.TestCase):
    def assert_exact_spans(self, left, right, result):
        for operation in result['operations']:
            for key, text in [('left', left), ('right', right)]:
                span = operation[key]
                self.assertEqual(text[span['start']:span['end']], span['text'])

    def test_spelling_repair_is_visible_without_selecting_a_dictionary_word(self):
        result = compare_literal_text('Use CacheBD.', 'Use CacheDB.')
        self.assertEqual(result['status'], 'different_tokens')
        self.assertEqual(result['operations'][0]['left']['text'], 'CacheBD')
        self.assertEqual(result['operations'][0]['right']['text'], 'CacheDB')
        self.assertFalse(result['correct_reading_selected'])
        self.assertFalse(result['can_clear_grading_gate'])

    def test_technical_word_substitution_is_located(self):
        left, right = 'Split the data across devices.', 'Split the model across devices.'
        result = compare_literal_text(left, right)
        self.assertEqual(len(result['operations']), 1)
        self.assertEqual(result['operations'][0]['left']['text'], 'data')
        self.assertEqual(result['operations'][0]['right']['text'], 'model')
        self.assert_exact_spans(left, right, result)

    def test_negation_deletion_and_insertion_have_exact_offsets(self):
        for left, right in [('It does not fit.', 'It does fit.'), ('It fits.', 'It never fits.')]:
            result = compare_literal_text(left, right)
            self.assertEqual(result['status'], 'different_tokens')
            self.assert_exact_spans(left, right, result)
        self.assertEqual(compare_literal_text('not', '')['operations'][0]['operation'], 'delete')
        self.assertEqual(compare_literal_text('', 'not')['operations'][0]['operation'], 'insert')

    def test_arabic_words_and_offsets_are_retained(self):
        left, right = 'لم يتم النسخ', 'تم النسخ'
        result = compare_literal_text(left, right)
        self.assertEqual(result['status'], 'different_tokens')
        self.assert_exact_spans(left, right, result)
        self.assertIn('word', result['operations'][0]['token_kinds'])

    def test_digits_and_signs_are_not_repaired_or_evaluated(self):
        result = compare_literal_text('v = -12.8', 'v = +12.88')
        kinds = {kind for operation in result['operations'] for kind in operation['token_kinds']}
        self.assertEqual(kinds, {'number', 'symbol'})
        self.assertEqual(result['status'], 'different_tokens')

    def test_word_boundaries_are_not_whitespace_equivalents(self):
        result = compare_literal_text('notable', 'not able')
        self.assertEqual(result['status'], 'different_tokens')
        self.assertEqual(result['operations'][0]['right']['text'], 'not able')

    def test_numbers_attached_to_units_keep_numeric_and_word_review_tags(self):
        result = compare_literal_text('size 200GB', 'size 2000GB')
        self.assertEqual(result['operations'][0]['token_kinds'], ['number', 'word'])
        self.assertEqual(result['operations'][0]['left']['text'], '200GB')

    def test_layout_whitespace_is_ignored_but_raw_hashes_are_distinct(self):
        result = compare_literal_text('one\n  two', 'one two')
        self.assertEqual(result['status'], 'same_tokens')
        self.assertEqual(result['operations'], [])
        self.assertNotEqual(result['left_sha256'], result['right_sha256'])
        self.assertFalse(result['can_clear_grading_gate'])

    def test_cancelled_markers_and_case_changes_remain_visible(self):
        left, right = '[crossed-out old] New', 'new'
        result = compare_literal_text(left, right)
        self.assertEqual(result['status'], 'different_tokens')
        self.assert_exact_spans(left, right, result)

    def test_large_region_requires_splitting_without_truncation(self):
        result = compare_literal_text('word ' * (MAX_TOKENS + 1), 'word')
        self.assertEqual(result['status'], 'split_required')
        self.assertEqual(result['operations'], [])
        self.assertFalse(result['can_clear_grading_gate'])

    def test_invalid_or_excessive_input_fails(self):
        for left, right in [(None, ''), ('', []), (True, 'text')]:
            with self.assertRaises(ValueError):
                compare_literal_text(left, right)
        with self.assertRaises(ValueError):
            compare_literal_text('a' * (MAX_CHARACTERS + 1), '')


if __name__ == '__main__':
    unittest.main()
