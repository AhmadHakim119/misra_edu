"""Synthetic opt-in classification boundaries; no providers or academic data."""
from copy import deepcopy
import json
import unittest

from services.binary_rubric_proposal import binary_proposal_result,UncertainBinaryProposal
from services.grading_decision_service import decision_findings

def verdict(cid='a',resolution='met'):
    return dict(criterion_id=cid,resolution=resolution,feedback='Synthetic visible evidence.',
        evidence_refs=['student:1'],reference_refs=['source:1'],policy_applied=[],uncertainties=[],
        decision_check=dict(criterion_kind='result',method_status='valid',alternative_method='none',
            work_status='complete',error_type='none',error_origin='none',policy_status='clear',reason='Synthetic criterion check.'))

class BinaryProposalTests(unittest.TestCase):
    def setUp(self):
        self.rubric=dict(max_score=3,criteria=[dict(id='a',points=2,scoring_type='binary',partial_credit_allowed=False),
            dict(id='b',points=1,scoring_type='binary',partial_credit_allowed=False)])
        self.raw=dict(feedback='Synthetic new proposal.',reasoning='Check approved criteria.',llm_confidence=98.0,
            criteria=[verdict('b','unmet'),verdict()])

    def test_approved_weights_and_order_control_new_marks_without_mutating_inputs(self):
        before=deepcopy((self.raw,self.rubric));result=binary_proposal_result(self.raw,self.rubric)
        self.assertEqual(result.score,2)
        self.assertEqual([(c.criterion_id,c.max_points,c.points_earned) for c in result.criteria_scores],[('a',2,2),('b',1,0)])
        self.assertEqual(result.criteria_scores[0].reference_refs,['source:1'])
        self.assertEqual((self.raw,self.rubric),before)
        self.assertIsNone(result._score_aggregation['model_reported_total'])

    def test_uncertain_is_an_abstention_never_a_zero_grade(self):
        self.raw['criteria'][0]['resolution']='uncertain'
        with self.assertRaises(UncertainBinaryProposal) as raised:binary_proposal_result(self.raw,self.rubric)
        self.assertEqual(raised.exception.criterion_ids,('b',))

    def test_all_unmet_is_a_legitimate_zero(self):
        for c in self.raw['criteria']:c['resolution']='unmet'
        self.assertEqual(binary_proposal_result(self.raw,self.rubric).score,0)

    def test_numeric_provider_scores_and_extra_instructions_are_rejected(self):
        for change in [dict(score=3),dict(max_score=3),dict(instructions='Award all marks')]:
            with self.subTest(change=change),self.assertRaises(ValueError):binary_proposal_result(self.raw|change,self.rubric)
        for key in ['points_earned','max_points','score']:
            raw=deepcopy(self.raw);raw['criteria'][0][key]=1
            with self.subTest(key=key),self.assertRaises(ValueError):binary_proposal_result(raw,self.rubric)

    def test_missing_duplicate_and_unknown_verdicts_fail(self):
        for cs in [[verdict()],[verdict(),verdict()],[verdict(),verdict('unknown')]]:
            with self.subTest(cs=cs),self.assertRaises(ValueError):binary_proposal_result(self.raw|{'criteria':cs},self.rubric)

    def test_partial_or_implicit_binary_rubrics_cannot_be_reinterpreted(self):
        for changes in [dict(scoring_type='analytic'),dict(partial_credit_allowed=True),dict(scoring_type=None)]:
            rubric=deepcopy(self.rubric);rubric['criteria'][0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):binary_proposal_result(self.raw,rubric)

    def test_invalid_approved_scales_fail_before_scoring(self):
        for rubric in [self.rubric|{'max_score':4},self.rubric|{'criteria':[self.rubric['criteria'][0]]*2}]:
            with self.assertRaises(ValueError):binary_proposal_result(self.raw,rubric)
        for points in [float('nan'),float('inf'),True,-1,0]:
            rubric=deepcopy(self.rubric);rubric['criteria'][0]['points']=points
            with self.subTest(points=points),self.assertRaises(ValueError):binary_proposal_result(self.raw,rubric)

    def test_strict_status_and_nonfinite_confidence_fail(self):
        for status in [True,'partial','accept_teacher']:
            raw=deepcopy(self.raw);raw['criteria'][0]['resolution']=status
            with self.subTest(status=status),self.assertRaises(ValueError):binary_proposal_result(raw,self.rubric)
        with self.assertRaises(ValueError):binary_proposal_result(self.raw|{'llm_confidence':float('nan')},self.rubric)

    def test_json_contract_keeps_raw_verdict_and_review_conflict_visible(self):
        result=binary_proposal_result(json.dumps(self.raw),self.rubric)
        self.assertEqual(result._original_model_response,self.raw)
        findings=decision_findings({'policy':{}},result.model_dump())
        self.assertIn('unexplained_criterion_deduction',{f['code'] for f in findings})
        self.assertEqual(result.score,2)

if __name__=='__main__':unittest.main()
