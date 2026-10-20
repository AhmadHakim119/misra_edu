from copy import deepcopy
import unittest

from services.ocr_verification import compare_regions
from services.ocr_review_triage import compare_critical_views, review_queue


class OCRReviewTriageTests(unittest.TestCase):
    def setUp(self):
        self.parent={'region_id':'line','page_index':0,'page_sha256':'a'*64,'crop_sha256':'b'*64,
                     'bounding_box':{'x':.1,'y':.2,'width':.5,'height':.2},'source_warnings':['Overwritten sign']}
        self.focus={**self.parent,'region_id':'focus','crop_sha256':'c'*64,
                    'bounding_box':{'x':.2,'y':.25,'width':.1,'height':.05},'source_warnings':[]}

    def reading(self,region,text='v=5.9',reader='a',family='family',**changes):
        return {'region_id':region['region_id'],'crop_sha256':region['crop_sha256'],'reader_id':reader,
                'reader_family':family,'status':'read','text':text,'uncertainties':[],
                'blind_to_other_readings_and_key':True,**changes}

    def test_component_reply_is_displayed_without_clearing_full_review(self):
        rows=compare_regions([self.parent],[self.reading(self.parent),self.reading(self.parent,reader='b',family='other')])
        original=deepcopy(rows)
        reply={'region_id':'line','component_id':'operator','evidence_digest':rows[0]['evidence_digest'],
               'actor_role':'project_user','confirmed_component':'+','source_warning_indices_resolved':[0]}
        result=review_queue(rows,[reply])
        self.assertEqual(result['regions'][0]['priority'],'remaining_region_review')
        self.assertEqual(result['regions'][0]['unresolved_source_warnings'],[])
        self.assertEqual(result['regions'][0]['confirmed_components'][0]['confirmed_component'],'+')
        self.assertEqual(result['full_grading_gate']['status'],'blocked_for_extraction_review')
        self.assertEqual(rows,original)
        self.assertFalse(result['component_reviews_are_full_answer_approvals'])

    def test_stale_duplicate_unknown_warning_and_unknown_region_fail_closed(self):
        rows=compare_regions([self.parent],[self.reading(self.parent)])
        reply={'region_id':'line','component_id':'operator','evidence_digest':rows[0]['evidence_digest'],
               'actor_role':'project_user','confirmed_component':'+','source_warning_indices_resolved':[0]}
        for replies in [[{**reply,'evidence_digest':'f'*64}],[reply,reply],
                        [{**reply,'region_id':'missing'}],[{**reply,'source_warning_indices_resolved':[5]}],
                        [{**reply,'source_warning_indices_resolved':[-1]}],
                        [{**reply,'source_warning_indices_resolved':[True]}],
                        [{**reply,'source_warning_indices_resolved':['0']}],
                        [{**reply,'source_warning_indices_resolved':[0.0]}],
                        [{**reply,'actor_role':'model'}]]:
            with self.subTest(replies=replies),self.assertRaises(ValueError):review_queue(rows,replies)

    def test_critical_conflict_stays_high_even_with_a_component_reply(self):
        rows=compare_regions([self.parent],[self.reading(self.parent,'x-2'),self.reading(self.parent,'x+2',reader='b',family='other')])
        result=review_queue(rows)
        self.assertEqual(result['regions'][0]['priority'],'critical_or_uncertain')

    def test_different_sign_decimal_and_extra_digit_detect_cross_view_conflicts(self):
        for before,after in [('v=5.9','-5.9'),('v=1.96+2','196'),('x=0.98','90.98')]:
            with self.subTest(before=before):
                out=compare_critical_views(self.parent,self.reading(self.parent,before),self.focus,self.reading(self.focus,after))
                self.assertEqual(out['status'],'critical_view_conflict')
                self.assertFalse(out['text_repaired'])
                self.assertFalse(out['counts_as_another_independent_reader'])

    def test_repeated_shared_wrong_digits_and_unclear_crop_are_not_verified_accuracy(self):
        left=self.reading(self.parent,'v=12.88')
        out=compare_critical_views(self.parent,left,self.focus,self.reading(self.focus,'12.88'))
        self.assertEqual(out['status'],'no_critical_conflict_observed')
        self.assertIn('matching_subsequence_is_not_accuracy_or_approval',out['reasons'])
        for right in [self.reading(self.focus,'12.88',uncertainties=['overwritten']),self.reading(self.focus,'[unclear]')]:
            self.assertEqual(compare_critical_views(self.parent,left,self.focus,right)['status'],'indeterminate')

    def test_cross_view_rejects_different_page_crop_or_reader_family(self):
        left,right=self.reading(self.parent),self.reading(self.focus)
        for region,reading in [({**self.focus,'page_sha256':'f'*64},right),
                               ({**self.focus,'bounding_box':{'x':.8,'y':.8,'width':.1,'height':.1}},right),
                               (self.focus,{**right,'crop_sha256':'f'*64}),
                               (self.focus,{**right,'reader_family':'different'})]:
            with self.assertRaises(ValueError):compare_critical_views(self.parent,left,region,reading)


if __name__=='__main__':unittest.main()
