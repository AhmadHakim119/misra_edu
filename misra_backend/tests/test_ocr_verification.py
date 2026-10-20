from copy import deepcopy
import unittest

from services.ocr_verification import arithmetic_warning, compare_regions, critical_tokens, grading_gate, literal_form


class OCRVerificationTests(unittest.TestCase):
    def setUp(self):
        self.region = {'region_id': 'line-1', 'page_index': 0, 'page_sha256': 'a'*64,
                       'crop_sha256': 'b'*64,
                       'bounding_box': {'x': .1, 'y': .2, 'width': .5, 'height': .1}}

    def reading(self, text='v = 12.8 m/s', reader='gemini', family=None, **changes):
        return {'region_id': 'line-1', 'crop_sha256': 'b'*64, 'reader_id': reader,
                'reader_family': family or reader, 'status': 'read', 'text': text,
                'uncertainties': [], 'blind_to_other_readings_and_key': True, **changes}

    def compare(self, left, right=None):
        return compare_regions([self.region], [left] + ([right] if right else []))

    def test_sign_decimal_digit_and_exponent_disagreements_block(self):
        for left, right in [('x-2', 'x+2'), ('14', '1.4'), ('12.8', '12.88'),
                            ('5.9', '-5.4'), ('v^2', 'v2'), ('x\u00b2', 'x2')]:
            with self.subTest(left=left):
                rows = self.compare(self.reading(left), self.reading(right, reader='paddle'))
                self.assertIn('critical_symbol_disagreement', rows[0]['review_reasons'])
                gate = grading_gate(rows)
                self.assertEqual(gate['status'], 'blocked_for_extraction_review')
                self.assertEqual(gate['extraction_revision'], [])
                self.assertEqual(rows[0]['alternatives'][0]['text'], left)

    def test_same_family_and_nonblind_reader_do_not_establish_independence(self):
        for other in [self.reading(reader='gemini-run-2', family='gemini'),
                      self.reading(reader='paddle', blind_to_other_readings_and_key=False)]:
            rows = self.compare(self.reading(), other)
            self.assertIn('insufficient_independent_readers', rows[0]['review_reasons'])

    def test_agreement_screen_does_not_claim_accuracy(self):
        rows = self.compare(self.reading(), self.reading('v=12.8 m/s', reader='paddle'))
        gate = grading_gate(rows)
        self.assertEqual(gate['status'], 'ready_for_diagnostic_grading')
        self.assertFalse(gate['agreement_proves_accuracy'])
        self.assertEqual(gate['extraction_revision'][0]['text'], 'v = 12.8 m/s')

    def test_shared_reader_error_cannot_clear_a_source_ambiguity(self):
        self.region['source_warnings'] = ['Overwritten final digit needs instructor inspection']
        rows = self.compare(self.reading('12.88'), self.reading('12.88', reader='paddle'))
        self.assertIn('source_visual_ambiguity', rows[0]['review_reasons'])
        self.assertEqual(grading_gate(rows)['pending_region_ids'], ['line-1'])

    def test_uncertainty_and_missing_reader_block_even_when_text_matches(self):
        rows = self.compare(self.reading(uncertainties=['decimal unclear']), self.reading(reader='paddle'))
        self.assertIn('reported_uncertainty', rows[0]['review_reasons'])
        self.assertEqual(grading_gate(rows)['pending_region_ids'], ['line-1'])
        rows = self.compare(self.reading(), self.reading(reader='paddle', status='failed', text=''))
        self.assertIn('reader_unavailable_or_illegible', rows[0]['review_reasons'])
        self.assertEqual(grading_gate(self.compare(self.reading()))['pending_region_ids'], ['line-1'])

    def test_current_instructor_revision_preserves_raw_and_unreadable_blocks(self):
        rows = self.compare(self.reading(), self.reading('12.88', reader='paddle'))
        original = deepcopy(rows)
        decision = {'region_id': 'line-1', 'evidence_digest': rows[0]['evidence_digest'],
                    'actor_id': 'synthetic-instructor', 'actor_role': 'instructor',
                    'action': 'confirm', 'text': '12.8', 'reason': 'Checked original crop'}
        self.assertEqual(grading_gate(rows, [decision])['extraction_revision'][0]['text'], '12.8')
        self.assertEqual(original, rows)
        self.assertEqual(grading_gate(rows, [{**decision, 'action': 'unreadable'}])['pending_region_ids'], ['line-1'])
        with self.assertRaises(ValueError):
            grading_gate(rows, [{**decision, 'evidence_digest': 'f'*64}])
        with self.assertRaises(ValueError):
            grading_gate(rows, [{**decision, 'actor_role': 'agent'}])

    def test_fail_closed_on_stale_or_tampered_locations_and_comparisons(self):
        with self.assertRaises(ValueError):
            self.compare(self.reading(crop_sha256='c'*64))
        with self.assertRaises(ValueError):
            self.compare(self.reading(), self.reading())
        with self.assertRaises(ValueError):
            compare_regions([{**self.region, 'bounding_box': {'x': .9, 'y': 0, 'width': .2, 'height': 1}}], [])
        with self.assertRaises(ValueError):
            compare_regions([self.region, self.region], [])
        with self.assertRaises(ValueError):
            self.compare(self.reading(blind_to_other_readings_and_key='true'))
        rows = self.compare(self.reading(), self.reading('wrong', reader='paddle'))
        rows[0]['review_reasons'] = []
        rows[0]['requires_review'] = False
        with self.assertRaises(ValueError):
            grading_gate(rows)

    def test_token_inventory_keeps_pm_and_digit_structure(self):
        self.assertEqual(critical_tokens(r'v=\pm 12.88^2'), ['=', r'\pm', '12.88', '^', '2'])

    def test_explicit_notation_equivalence_does_not_inflate_disagreement(self):
        for a,b in [('v₀²', 'v_0^2'), ('½mv²', r'\frac{1}{2}mv^{2}'),
                    ('9.81×2.7', r'9.81\times 2.7')]:
            with self.subTest(a=a):
                self.assertEqual(literal_form(a), literal_form(b))
                self.assertEqual(critical_tokens(a), critical_tokens(b))
                self.assertFalse(self.compare(self.reading(a), self.reading(b,reader='paddle'))[0]['requires_review'])
        # Radical scope and a missing decimal are never normalized into agreement.
        self.assertNotEqual(literal_form(r'\sqrt{x}+1'), literal_form(r'\sqrt{x+1}'))
        self.assertNotEqual(literal_form('196'), literal_form('1.96'))
        self.assertNotEqual(literal_form('V'), literal_form('v'))
        self.assertNotEqual(literal_form('x/½'), literal_form('x/1/2'))
        self.assertEqual(literal_form(r'\rightarrow'), r'\rightarrow')

    def test_numeric_warning_never_repairs_student_mistake(self):
        text = 'v=sqrt(4)=-2 m/s'
        self.assertEqual(arithmetic_warning(text), 'explicit_numeric_equality_inconsistent')
        rows = self.compare(self.reading(text), self.reading(text, reader='paddle'))
        self.assertIn('numeric_consistency_warning_not_proof_of_ocr_error', rows[0]['review_reasons'])
        self.assertEqual(rows[0]['alternatives'][0]['text'], text)
        self.assertEqual(grading_gate(rows)['status'], 'blocked_for_extraction_review')
        self.assertEqual(arithmetic_warning('v=sqrt(-4)=2'), 'explicit_numeric_expression_undefined')
        self.assertIsNone(arithmetic_warning('v=sqrt(2)=1.41 m/s'))

    def test_script_scope_cannot_disappear_next_to_another_digit(self):
        for a,b in [(r'x^{1}2','x^12'), (r'x_{1}2','x_12'),
                    ('x¹2','x^12'), ('x₁2','x_12'),
                    (r'x^{1} 2','x^12'), ('x¹ 2','x^12')]:
            with self.subTest(a=a):
                self.assertNotEqual(literal_form(a),literal_form(b))
                rows=self.compare(self.reading(a),self.reading(b,reader='paddle'))
                self.assertEqual(grading_gate(rows)['status'],'blocked_for_extraction_review')
        self.assertEqual(literal_form('x¹2'),literal_form(r'x^{1}2'))
        self.assertEqual(literal_form('x¹²'),literal_form(r'x^{12}'))
        self.assertEqual(literal_form('x₁₂'),literal_form(r'x_{12}'))

    def test_numeric_screen_is_bounded_and_does_not_execute_student_code(self):
        for text in ["__import__('os').system('bad')=0", 'v=x+2=3', 'v=10**999999999=1',
                     'v=sqrt(x)=1', 'v=[1]*999999999=1', 'v=1e999=1', 'v='+('1+'*2000)+'1=2']:
            with self.subTest(text=text[:30]):
                self.assertIsNone(arithmetic_warning(text))


if __name__ == '__main__':
    unittest.main()
