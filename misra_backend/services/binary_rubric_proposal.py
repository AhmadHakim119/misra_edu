"""Opt-in offline binary-criterion classification, without provider/storage calls.

Callers must validate the approved guide, source evidence and citation bindings.
This does not approve a guide, infer a criterion verdict, repair an old score, or
finalize grades. The standard GradingResult contract and live path are unchanged.
"""
import math
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field

from services.benchmark_metrics import number
from services.grading_decision_service import CriterionDecisionCheck
from services.grading_service import GradingResult,_validate_grading_against_rubric

VERSION='2026-10-19.binary-classification.v1'


class BinaryCriterionVerdict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False,strict=True)
    criterion_id: str=Field(min_length=1,max_length=200)
    resolution: Literal['met','unmet','uncertain']
    feedback: str=Field(min_length=1,max_length=10000)
    evidence_refs: list[str]=Field(max_length=100)
    reference_refs: list[str]=Field(max_length=100)
    policy_applied: list[str]=Field(max_length=100)
    uncertainties: list[str]=Field(max_length=100)
    decision_check: CriterionDecisionCheck


class BinaryProposal(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False,strict=True)
    feedback: str=Field(min_length=1,max_length=10000)
    reasoning: str=Field(min_length=1,max_length=10000)
    llm_confidence: float=Field(ge=0,le=100)
    criteria: list[BinaryCriterionVerdict]=Field(min_length=1,max_length=100)


class UncertainBinaryProposal(ValueError):
    """An uncertain verdict has no numeric grade; it is never mapped to zero."""
    def __init__(self,criterion_ids):
        self.criterion_ids=tuple(criterion_ids)
        super().__init__('Uncertain binary criteria require instructor review.')


def binary_proposal_result(raw,rubric):
    """Derive NEW proposal marks from explicit verdicts and approved weights.

    Numeric score/max/points fields from the provider are forbidden. Only explicit
    binary criteria are supported; partial-credit rubrics fail before scoring.
    Citation references remain unchanged for the existing evidence validator.
    Uncertain verdicts abstain for the whole answer, preserving the raw response
    in the caller's immutable attempt rather than manufacturing zero marks.
    """
    proposal=BinaryProposal.model_validate_json(raw) if isinstance(raw,str) else BinaryProposal.model_validate(raw)
    criteria=rubric.get('criteria')
    if not isinstance(criteria,list) or not criteria or len(criteria)>100 or any(not isinstance(c,dict) for c in criteria):
        raise ValueError('Require bounded approved binary criteria.')
    ids=[c.get('id') for c in criteria]
    if any(not isinstance(cid,str) or not cid.strip() for cid in ids) or len(ids)!=len(set(ids)):
        raise ValueError('Approved criteria must have unique IDs.')
    weights={}
    for c in criteria:
        if c.get('scoring_type')!='binary' or c.get('partial_credit_allowed') is not False:
            raise ValueError('Classification scoring requires explicitly approved binary-only criteria.')
        weight=number(c.get('points'),'criterion points')
        if weight<=0:raise ValueError('Criterion weights must be positive.')
        weights[c['id']]=weight
    maximum=number(rubric.get('max_score'),'max_score')
    if maximum<=0 or abs(math.fsum(weights.values())-maximum)>1e-9:
        raise ValueError('Approved criterion weights must sum to the maximum.')
    supplied=[v.criterion_id for v in proposal.criteria]
    if len(supplied)!=len(set(supplied)) or set(supplied)!=set(ids):
        raise ValueError('Return every approved criterion exactly once.')
    uncertain=[v.criterion_id for v in proposal.criteria if v.resolution=='uncertain']
    if uncertain:raise UncertainBinaryProposal(uncertain)
    by_id={v.criterion_id:v for v in proposal.criteria};scores=[]
    for cid in ids:
        verdict=by_id[cid]
        score=verdict.model_dump(exclude={'resolution'})
        score.update(max_points=weights[cid],points_earned=weights[cid] if verdict.resolution=='met' else 0.0)
        scores.append(score)
    result=GradingResult(score=math.fsum(c['points_earned'] for c in scores),max_score=maximum,
        feedback=proposal.feedback,reasoning=proposal.reasoning,llm_confidence=proposal.llm_confidence,criteria_scores=scores)
    _validate_grading_against_rubric(result,rubric)
    result._original_model_response=proposal.model_dump()
    result._score_aggregation=dict(version=VERSION,model_reported_total=None,criterion_total=result.score,
        discrepancy=False,criterion_marks_changed=False,marks_derived_from_explicit_binary_verdicts=True)
    return result
