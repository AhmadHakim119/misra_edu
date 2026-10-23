"""Check policy arithmetic against located text, without awarding or changing marks.

The model still identifies the quantity and judges the local method. Matching text
and arithmetic cannot establish that either academic judgment is correct.
"""
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.grading_numeric_checks import evaluate_numeric_expression

VERSION = '2026-10-22.policy-arithmetic.v1'


class LocatedNumber(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ref: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=200)


class NumericPolicyCheck(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # Quotes are literal numeric tokens/expressions, without variable names/units.
    student: LocatedNumber
    target: LocatedNumber
    basis: Literal['reference', 'follow_through', 'numeric_penalty_cap']
    depends_on: list[str] = Field(default_factory=list, max_length=20)


POLICY_ARITHMETIC_INSTRUCTIONS = '''
POLICY APPLICATION WORKSHEET (complete before assigning points):
- Separate the visible method from its numerical result. Use the approved partial-
  credit levels; an unfinished final number does not invalidate a sufficient method.
- For a numerical result, return numeric_check alongside decision_check:
  {"student":{"ref":"<student evidence ID>","quote":"<literal number>"},
   "target":{"ref":"<key ID or student evidence ID>","quote":"<literal number or numeric expression>"},
   "basis":"reference|follow_through|numeric_penalty_cap","depends_on":[]}.
  Each quote must occur unchanged in the cited text. Do not invent expressions,
  silently fix transcription, convert units inside a quote, or use course examples
  as the answer key. If an equivalent conversion, image-only number or symbolic
  route cannot be represented literally, return null and explain the limitation.
- reference compares the student's result to the approved key's literal value.
  follow_through compares it to the student's VISIBLE substituted numeric expression,
  with the earlier criterion IDs in depends_on. Independently check the local
  relation and quantity assignment and report method_status=valid only if established.
  A wrong earlier input may qualify; a NEW arithmetic/rounding error does not become
  correct follow-through. Apply the approved tolerance to the local calculation too.
  No relative tolerance is an absolute allowance around zero.
- A numeric_penalty_cap exception compares against the key and identifies the
  criterion IDs where the numerical deduction was actually taken. It requires the
  approved cap, valid relevant methods, and an actual numerical deduction elsewhere.
  Do not award every numerical mark by claiming a cap with no originating deduction.
- Before returning points, sum numerical marks lost across the WHOLE question,
  not the number of criteria. Keep conceptual deductions separate. When a cap is
  explicitly approved, do not exceed its limit or erase an independent conceptual
  error. Never change the error classification just to make the marks pass a check.
- For non-numerical criteria numeric_check is null. These are checkable model
  assertions, not new marking rules. Unverified readings/dependencies need review.
'''


def _number(location, sources):
    text = sources.get(location['ref'])
    quote = location['quote']
    if not isinstance(text, str) or quote not in text:
        return None
    # A substring of a digit string must not stand in for the actual written value.
    start = 0
    while (index := text.find(quote, start)) >= 0:
        end = index + len(quote)
        before = text[:index].rstrip()
        # A separated unary minus is still part of the written number. For an
        # arithmetic subexpression after an operator, quote the full expression.
        if ((index == 0 or text[index - 1] not in '0123456789.eE−-')
                and not before.endswith(('-', '−'))
                and (end == len(text) or text[end] not in '0123456789.eE')):
            result = evaluate_numeric_expression(quote)
            return result.get('value') if result['status'] == 'computed' else None
        start = index + 1
    return None


def _within(actual, expected, percent):
    if expected == 0:
        return actual == 0
    return abs(actual - expected) <= abs(expected) * percent / 100 + 1e-12 * abs(expected)


def policy_arithmetic_audit(package, candidate):
    """Return replayable checks and review findings; inputs remain immutable."""
    findings, comparisons = [], []
    policy = package.get('policy') or {}
    tolerance = policy.get('rounding_tolerance_percent')
    tolerance_valid = (type(tolerance) in (int, float) and math.isfinite(tolerance)
                       and 0 <= tolerance <= 100)
    criteria = candidate['criteria_scores']
    by_id = {c['criterion_id']: c for c in criteria}
    student_text = {e['id']: e.get('text') for e in package.get('student_evidence', [])
                    if e.get('kind') in {'ocr_segment', 'combined_ocr'}}
    key = package.get('answer_key') or {}
    key_text = {key.get('reference_id'): key.get('reference_text')} if key.get('mode') != 'no_fixed_answer' else {}

    def methods_established():
        checks = [c.get('decision_check') or {} for c in criteria]
        return (bool(checks) and any(k.get('method_status') == 'valid' for k in checks)
            and all(k.get('method_status') in {'valid', 'not_assessed'}
                and k.get('work_status') == 'complete'
                and k.get('policy_status') == 'clear'
                and k.get('error_type') not in {'conceptual', 'unclear', 'missing_work'}
                and k.get('error_origin') not in {'physical_relation', 'physical_direction', 'mixed', 'unclear'}
                for k in checks))

    def flag(cid, code, message):
        findings.append(dict(criterion_id=cid, code=code, message=message))

    for c in criteria:
        cid = c['criterion_id']
        check = c.get('decision_check') or {}
        raw = c.get('numeric_check')
        if not raw:
            if (tolerance_valid and check.get('criterion_kind') == 'result'
                    and check.get('error_type') == 'calculation'):
                flag(cid, 'numeric_trace_missing', 'A numerical policy decision lacks a located comparison. Check the written value and its local calculation; no marks were changed.')
            continue
        trace = NumericPolicyCheck.model_validate(raw).model_dump()
        if not re.fullmatch(r'\s*[+−-]?\s*(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?\s*', trace['student']['quote']):
            flag(cid, 'numeric_trace_unverified', 'The student result must be a located literal number, separately from its calculation.')
            continue
        if not tolerance_valid:
            flag(cid, 'numeric_tolerance_unavailable', 'No structured approved numerical tolerance is available. The comparison cannot authorize credit or a deduction.')
            continue
        if (trace['student']['ref'] not in c.get('evidence_refs', [])
                or (trace['basis'] != 'follow_through'
                    and trace['target']['ref'] not in c.get('reference_refs', []))
                or (trace['basis'] == 'follow_through'
                    and trace['target']['ref'] not in c.get('evidence_refs', []))):
            flag(cid, 'numeric_trace_uncited', 'The numerical comparison is not linked to this criterion\'s cited student/key evidence.')
            continue
        actual = _number(trace['student'], student_text)
        targets = student_text if trace['basis'] == 'follow_through' else key_text
        expected = _number(trace['target'], targets)
        if actual is None or expected is None:
            flag(cid, 'numeric_trace_unverified', 'The numerical comparison does not resolve to literal supported arithmetic in the cited student work and approved key. No reading, conversion or expression was invented.')
            continue
        within = _within(actual, expected, tolerance)
        comparisons.append(dict(criterion_id=cid, basis=trace['basis'], student_value=actual,
            target_value=expected, tolerance_percent=tolerance, within_tolerance=within))
        dependencies = trace['depends_on']
        dependency_ok = (bool(dependencies) and len(set(dependencies)) == len(dependencies)
                         and all(d in by_id and d != cid for d in dependencies))
        if trace['basis'] == 'follow_through':
            if (not dependency_ok or check.get('method_status') != 'valid'
                    or check.get('work_status') != 'complete'
                    or not all((by_id.get(d, {}).get('decision_check') or {}).get('criterion_kind') in {'result', 'mixed'} for d in dependencies)):
                flag(cid, 'follow_through_unverified', 'Follow-through needs identified earlier criteria and a complete, valid local method. Arithmetic alone does not establish the quantity dependency.')
            if policy.get('error_carried_forward') not in {'single_penalty'} and policy.get('cross_part_follow_through') != 'allow_prior_error':
                flag(cid, 'follow_through_permission_unverified', 'No structured general follow-through permission is available. Check the specific approved criterion/custom rule before granting this exception.')
            elif dependency_ok and any((by_id[d].get('decision_check') or {}).get('error_type') == 'conceptual'
                     for d in dependencies) and policy.get('cross_part_follow_through') != 'allow_prior_error':
                flag(cid, 'cross_part_permission_unverified', 'The originating result has a conceptual error; explicit structured approval of cross-part follow-through is required to check this exception.')
        cap_credit = trace['basis'] == 'numeric_penalty_cap'
        if cap_credit:
            cap = policy.get('numeric_penalty_cap_points')
            if (type(cap) not in (int, float) or not math.isfinite(cap) or cap < 0
                    or not dependency_ok or not methods_established()
                    or not any(by_id[d]['points_earned'] < by_id[d]['max_points']
                               and (by_id[d].get('decision_check') or {}).get('error_type') == 'calculation'
                               for d in dependencies)):
                cap_credit = False
                flag(cid, 'numeric_cap_credit_unverified', 'A numerical-cap exception needs the approved limit, valid relevant methods and an actual identified numerical deduction. It cannot excuse all wrong results without a penalty.')
        if (check.get('criterion_kind') == 'result'
                and c['points_earned'] == c['max_points'] and not within and not cap_credit):
            flag(cid, 'numeric_credit_outside_tolerance', 'Awarded numerical credit is outside the approved tolerance, including any claimed local follow-through calculation. A new arithmetic/rounding error needs its own policy treatment; no marks were changed.')
        if (within and c['points_earned'] < c['max_points']
                and check.get('criterion_kind') == 'result' and check.get('error_type') == 'calculation'
                and check.get('work_status') == 'complete'):
            flag(cid, 'numeric_deduction_within_tolerance', 'A numerical deduction conflicts with the located result being within approved tolerance. Check other explicit criterion requirements before deciding the mark.')

    # Count lost points, including a multi-point numerical criterion, not rows.
    cap = policy.get('numeric_penalty_cap_points')
    numerical = [c for c in criteria if c['points_earned'] < c['max_points']
                 and (c.get('decision_check') or {}).get('error_type') == 'calculation']
    lost = math.fsum(c['max_points'] - c['points_earned'] for c in numerical)
    if (type(cap) in (int, float) and math.isfinite(cap) and cap >= 0
            and methods_established() and lost > cap + 1e-9):
        for c in numerical:
            flag(c['criterion_id'], 'numeric_penalty_limit_exceeded',
                 f'Numerical deductions total {lost:g} marks; the approved question limit is {cap:g}. Relevant methods were reported valid. Review the allocation; no marks were changed.')
    # Model-supplied dependencies may be reordered, but cannot be circular.
    edges = {c['criterion_id']: (c.get('numeric_check') or {}).get('depends_on', []) for c in criteria}
    for cid in edges:
        pending, seen = list(edges[cid]), set()
        while pending:
            item = pending.pop()
            if item == cid:
                flag(cid, 'numeric_dependency_cycle', 'The claimed numerical-credit dependencies are circular and cannot establish follow-through or an originating penalty.')
                break
            if item not in seen:
                seen.add(item)
                pending.extend(edges.get(item, []))
    return dict(version=VERSION, comparisons=comparisons, numerical_marks_lost=lost,
                findings=findings, score_changed=False)


def remap_numeric_refs(criterion, aliases):
    """Remap only trace reference fields, never quoted student/key text."""
    trace = criterion.get('numeric_check')
    if trace:
        for side in ('student', 'target'):
            location = trace[side]
            location['ref'] = aliases.get(location['ref'], location['ref'])
