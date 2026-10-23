"""Synthetic calculator/trust regressions; no private examples or provider calls."""
from copy import deepcopy
import unittest
from services.grading_numeric_checks import evaluate_numeric_expression as calc, numeric_context, MAX_CHECKS
from services.grading_package_service import provider_grading_package


class NumericChecksTests(unittest.TestCase):
    def test_signed_product_and_radical_are_literal(self):
        result = calc('sqrt(20^2+2(-9.8)(2-5))')
        self.assertEqual(result['status'],'computed')
        self.assertAlmostEqual(result['value'],458.8**.5)
        self.assertAlmostEqual(calc('2(-9.8)(2-5)')['value'],58.8)

    def test_different_signs_are_not_normalized_to_each_other(self):
        self.assertAlmostEqual(calc('20²+2(9.8)(2-5)')['value'],341.2)
        self.assertAlmostEqual(calc('20²+2(−9.8)(2-5)')['value'],458.8)

    def test_domains_do_not_become_zero_or_consistent(self):
        for text in ['sqrt(-4)','3/0']:
            with self.subTest(text=text):
                self.assertEqual(calc(text),{'status':'domain_error'})

    def test_algebra_and_ambiguous_notation_stay_unchecked(self):
        for text in ['v0^2+2*a*d','2,7','2 7','1.5(2)x','sqrt{4}','sin(3)','True','',None]:
            with self.subTest(text=text):
                self.assertEqual(calc(text),{'status':'unsupported'})

    def test_executable_constructs_cannot_run(self):
        for text in ['__import__("os").getcwd()','sqrt.__class__','(1).__class__',
                     'sqrt(x=4)','[1][0]','1; print(1)','1 if True else 0']:
            with self.subTest(text=text):
                self.assertEqual(calc(text),{'status':'unsupported'})

    def test_bounds_cover_input_exponents_nonfinite_and_large_intermediates(self):
        for text in ['1'*201,'2^999','1e999','1e9*1e9','sqrt(1e10)']:
            with self.subTest(text=text):
                self.assertEqual(calc(text),{'status':'limit_exceeded'})

    def test_precedence_and_numeric_juxtaposition(self):
        for text, expected in [('-2^2',-4),('(-2)^2',4),('(2)(3)',6),('2(3+4)',14),
                               ('sqrt(16)/2',2),('1.2e2 / 3',40),('8 m/s',8)]:
            with self.subTest(text=text):
                self.assertEqual(calc(text)['value'],expected)

    def test_location_raw_text_and_distinct_lines_are_preserved(self):
        evidence = [{'id':'student:segment:1','kind':'ocr_segment',
                     'text':'v = sqrt(20^2+2(-9.8)(2-5)); v = 19.2 m/s'}]
        original = deepcopy(evidence)
        context = numeric_context(evidence)
        self.assertEqual(evidence,original)
        self.assertEqual(len(context['checks']),2)
        self.assertFalse(context['coverage_limited'])
        for row in context['checks']:
            span = row['text_span']
            self.assertEqual(row['literal_expression'],evidence[0]['text'][span['start']:span['end']])
        self.assertNotEqual(context['checks'][0]['value'],context['checks'][1]['value'])
        self.assertNotIn('score',context)
        self.assertNotIn('consistent',context)

    def test_unsupported_expression_is_reported(self):
        context = numeric_context([{'id':'student:segment:1','kind':'ocr_segment','text':'a=x+3'}])
        self.assertEqual(context['checks'][0]['status'],'unsupported')
        self.assertNotIn('value',context['checks'][0])

    def test_next_assignment_prose_label_is_outside_expression_span(self):
        text = 'u = sqrt(25). Final student u: u = 4 m/s'
        context = numeric_context([{'id':'student:segment:1','kind':'ocr_segment','text':text}])
        self.assertEqual(context['checks'][0]['literal_expression'],'sqrt(25)')
        self.assertEqual(context['checks'][0]['value'],5)
        span = context['checks'][0]['text_span']
        self.assertEqual(text[span['start']:span['end']],'sqrt(25)')
        self.assertEqual(context['checks'][1]['value'],4)
        unchecked = numeric_context([{'id':'student:segment:1','kind':'ocr_segment','text':'u=2 x'}])
        self.assertEqual(unchecked['checks'][0]['status'],'unsupported')

    def test_bounded_coverage_and_segment_preference(self):
        context = numeric_context([
            {'id':'student:combined:1','kind':'combined_ocr','text':'x=999'},
            {'id':'student:segment:1','kind':'ocr_segment','text':'a=1;'*40}])
        self.assertTrue(context['coverage_limited'])
        self.assertEqual(len(context['checks']),MAX_CHECKS)
        self.assertEqual({c['evidence_ref'] for c in context['checks']},{'student:segment:1'})

    def test_provider_recomputes_context_without_changing_rules_or_retrieval(self):
        package = {'question':{'text':'Synthetic task','max_score':2},
            'rubric':{'max_score':2,'criteria':[{'id':'result','points':2}]},'policy':{},
            'answer_key':{'mode':'reference','reference_id':'key:private','reference_text':'Separate key'},
            'student_evidence':[{'id':'private-source-id','kind':'ocr_segment','text':'x=2(3)',
                                 'numeric_checks':{'value':999,'score':2}}],
            'course_references':{'mode':'required','strategy':'synthetic','status':'retrieved','passages':[]},
            'numeric_checks':{'value':999,'score':2}}
        original = deepcopy(package)
        safe, _, _ = provider_grading_package(package)
        self.assertEqual(package,original)
        self.assertEqual(safe['numeric_checks']['checks'][0]['value'],6)
        self.assertEqual(safe['numeric_checks']['checks'][0]['evidence_ref'],'student:segment:1')
        self.assertEqual(safe['policy'],{})
        scoring_rubric = deepcopy(safe['rubric'])
        for criterion in scoring_rubric['criteria']:
            hints = criterion.pop('citation_requirements')
            self.assertTrue(hints['course_reference_required'])
            self.assertFalse(hints['answer_key_alone_sufficient'])
        self.assertEqual(scoring_rubric,original['rubric'])
        self.assertEqual(safe['course_references']['mode'],'required')
        self.assertNotIn('numeric_checks',safe['student_evidence'][0])
        self.assertNotIn('score',safe['numeric_checks'])


if __name__ == '__main__':
    unittest.main()
