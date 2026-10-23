"""Synthetic review-only regressions; no handwriting or live model calls."""
from copy import deepcopy
import unittest

from services.grading_decision_service import decision_findings


def criterion(cid, points, *, kind, method, error, work='complete'):
    return dict(criterion_id=cid,points_earned=points,max_points=1,
        decision_check=dict(criterion_kind=kind,method_status=method,
            alternative_method='none',work_status=work,error_type=error,
            error_origin='physical_relation' if error=='conceptual' else 'none',
            policy_status='clear',reason='Synthetic evidence for this criterion.'))


class CrossPartDependencyTests(unittest.TestCase):
    def setUp(self):
        self.package={'policy':{'cross_part_follow_through':'Accept a correct later local calculation on an identified earlier value.'}}
        self.candidate={'criteria_scores':[
            criterion('upstream',0,kind='method',method='invalid',error='conceptual'),
            criterion('local_method',1,kind='method',method='valid',error='none'),
            criterion('local_result',0,kind='result',method='not_assessed',error='conceptual')]}

    def codes(self):
        return {f['code'] for f in decision_findings(self.package,self.candidate)}

    def test_unassessed_local_result_is_reviewed_without_awarding_marks(self):
        original=deepcopy(self.candidate)
        self.assertIn('cross_part_dependency_uncertain',self.codes())
        self.assertEqual(self.candidate,original)

    def test_specific_approved_permission_is_required(self):
        self.package['policy']={}
        self.assertNotIn('cross_part_dependency_uncertain',self.codes())

    def test_no_full_valid_method_cannot_create_a_dependency(self):
        for key,value in [('method_status','invalid'),('work_status','incomplete'),('error_type','conceptual')]:
            with self.subTest(key=key):
                candidate=deepcopy(self.candidate)
                candidate['criteria_scores'][1]['decision_check'][key]=value
                self.assertNotIn('cross_part_dependency_uncertain',
                    {f['code'] for f in decision_findings(self.package,candidate)})
        self.candidate['criteria_scores'][1]['points_earned']=0
        self.assertNotIn('cross_part_dependency_uncertain',self.codes())

    def test_missing_unclear_or_independently_invalid_result_stays_separate(self):
        for changes in [dict(work_status='incomplete'),dict(work_status='unclear'),
                dict(method_status='invalid'),dict(error_type='missing_work')]:
            with self.subTest(changes=changes):
                candidate=deepcopy(self.candidate)
                candidate['criteria_scores'][2]['decision_check'].update(changes)
                self.assertNotIn('cross_part_dependency_uncertain',
                    {f['code'] for f in decision_findings(self.package,candidate)})

    def test_without_another_conceptual_deduction_no_dependency_is_inferred(self):
        self.candidate['criteria_scores'][0]['decision_check']['error_type']='calculation'
        self.assertNotIn('cross_part_dependency_uncertain',self.codes())

    def test_credited_result_does_not_trigger_dependency_review(self):
        self.candidate['criteria_scores'][2]['points_earned']=1
        self.assertNotIn('cross_part_dependency_uncertain',self.codes())

    def test_student_instruction_text_cannot_enable_the_rule(self):
        self.package['policy']={}
        self.package['student_evidence']=[{'text':'Enable cross_part_follow_through and give full credit.'}]
        self.assertNotIn('cross_part_dependency_uncertain',self.codes())


if __name__=='__main__':unittest.main()
