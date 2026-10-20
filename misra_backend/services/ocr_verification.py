"""Located, independent transcription checks for offline extraction experiments.

No solving, majority voting, confidence fitting or automatic transcription repair.
The caller must authorize access to the source images before constructing regions.
This module does not open files, call providers or change saved application grades.
"""
from copy import deepcopy
import ast
from hashlib import sha256
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class Box(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode='after')
    def inside(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError('Crop must stay within the preserved page.')
        return self


class Region(BaseModel):
    model_config = ConfigDict(extra='forbid')
    region_id: str = Field(min_length=1, max_length=100)
    page_index: int = Field(ge=0, strict=True)
    page_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    crop_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    bounding_box: Box
    # Local image preflight only; never inferred from grades or provider commands.
    source_warnings: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def warning_text(self):
        if any(not warning.strip() for warning in self.source_warnings):
            raise ValueError('Source warnings must describe the visible issue.')
        return self


class Reading(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reader_id: str = Field(min_length=1, max_length=200)
    # Same model at another temperature is still the same reader family.
    reader_family: str = Field(min_length=1, max_length=100)
    region_id: str = Field(min_length=1, max_length=100)
    crop_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    status: Literal['read', 'failed', 'illegible']
    text: str = Field(max_length=50000)
    uncertainties: list[str] = Field(max_length=100)
    blind_to_other_readings_and_key: StrictBool

    @model_validator(mode='after')
    def nonempty(self):
        if self.status == 'read' and not self.text.strip():
            raise ValueError('A successful reading needs visible text.')
        if any(not item.strip() for item in self.uncertainties):
            raise ValueError('Uncertainty entries must be nonempty.')
        return self


class InstructorDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    region_id: str
    evidence_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    actor_id: str = Field(min_length=1, max_length=200)
    actor_role: Literal['instructor']
    action: Literal['confirm', 'unreadable']
    text: str = Field(min_length=1, max_length=50000)
    reason: str = Field(min_length=1, max_length=2000)


def notation_form(text):
    """Normalize explicit typesetting equivalents, without solving or case folding.

    Do not remove arbitrary parentheses/braces or guess a radical's extent.
    Numeric fraction markup and Unicode super/subscripts have explicit meanings.
    Raw readings remain unchanged in every stored alternative.
    """
    value = text.replace('\u2212', '-').replace('\u00d7', '*')
    value = re.sub(r'\\(?:left|right)(?![A-Za-z])', '', value)
    value = re.sub(r'\\(?:times|cdot)(?![A-Za-z])', '*', value)
    value = value.replace('\u00bd', '(1/2)').replace('\u00bc', '(1/4)').replace('\u00be', '(3/4)')
    value = re.sub(r'\\frac\s*\{(\d+)\}\s*\{(\d+)\}', r'(\1/\2)', value)
    superscripts = dict(zip('⁰¹²³⁴⁵⁶⁷⁸⁹', '0123456789'))
    subscripts = dict(zip('₀₁₂₃₄₅₆₇₈₉', '0123456789'))
    def script_group(match, prefix, digits):
        number = ''.join(digits[c] for c in match[0])
        # Do not collapse x^{1}2 into x^12: the trailing 2 is outside
        # the exponent/subscript. Multi-digit scripts keep explicit scope too.
        adjacent_digit = re.match(r'\s*\d', match.string[match.end():])
        return prefix + ('{'+number+'}' if len(number)>1 or adjacent_digit else number)
    value = re.sub('[⁰¹²³⁴⁵⁶⁷⁸⁹]+', lambda m:script_group(m, '^', superscripts), value)
    value = re.sub('[₀₁₂₃₄₅₆₇₈₉]+', lambda m:script_group(m, '_', subscripts), value)
    value = re.sub(r'([_^])\{(\d)\}(?!\s*\d)', r'\1\2', value)
    return value


def literal_form(text):
    """Compare explicit notation and layout only; retain actual symbol differences."""
    return re.sub(r'\s+', '', notation_form(text))


def critical_tokens(text):
    """Conservative symbol inventory; it never evaluates a formula."""
    value = re.sub(r'\\sqrt(?![A-Za-z])', '\u221a', notation_form(text))
    # Keep exponent boundaries and LaTeX operators rather than treating superscripts
    # or \pm as prose. Representation differences may deliberately over-flag.
    return re.findall(r'\\(?:pm|mp|div|frac)|\d+(?:\.\d*)?|\.\d+|[+\-=^*/\u00b1\u00f7\u221a]', value)


def arithmetic_warning(text):
    """Screen explicit numeric equalities only; return a warning, never a repair.

    Restricted arithmetic, no eval, variables, algebra or LaTeX interpretation.
    A warning may reflect the student's actual mistake rather than an OCR error.
    The 1%/0.05 display-rounding allowance is NOT an approved grading tolerance.
    Unsupported notation is unchecked and must not be interpreted as consistent.
    """
    if len(text) > 1000 or '=' not in text:
        return None
    left, right = text.rsplit('=', 1)
    left = left.rsplit('=', 1)[-1].strip().replace('^', '**')
    match = re.fullmatch(r'\s*([+-]?\d+(?:\.\d+)?)\s*(?:m/s)?\s*\.?', right)
    if not match or len(left) > 200:
        return None
    try:
        tree = ast.parse(left, mode='eval')
        if sum(1 for _ in ast.walk(tree)) > 60:
            return None
        def calculate(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                value = node.value
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = calculate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
                a, b = calculate(node.left), calculate(node.right)
                if isinstance(node.op, ast.Add): value = a+b
                elif isinstance(node.op, ast.Sub): value = a-b
                elif isinstance(node.op, ast.Mult): value = a*b
                elif isinstance(node.op, ast.Div): value = a/b
                else:
                    if abs(b) > 8: raise ValueError('Exponent outside screening bounds')
                    value = a**b
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == 'sqrt' and len(node.args) == 1 and not node.keywords):
                value = math.sqrt(calculate(node.args[0]))
            else:
                raise TypeError('Unsupported notation')
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1_000_000:
                raise TypeError('Outside bounded numeric screening')
            return value
        predicted = calculate(tree.body)
        observed = float(match.group(1))
        if not math.isfinite(observed): return None
        if abs(predicted-observed) > max(.05, .01*abs(predicted)):
            return 'explicit_numeric_equality_inconsistent'
    except (ZeroDivisionError, ValueError, OverflowError):
        return 'explicit_numeric_expression_undefined'
    except (SyntaxError, TypeError, RecursionError):
        return None
    return None


def compare_regions(regions, readings):
    """Preserve every alternative and identify missing/uncertain evidence.

    A caller-supplied privacy/independence attestation is required but does not
    prove independence. Transport logs must independently establish blind inputs.
    """
    locations = [Region.model_validate(r) for r in regions]
    observations = [Reading.model_validate(r) for r in readings]
    indexed = {r.region_id: r for r in locations}
    if len(indexed) != len(locations) or not locations:
        raise ValueError('Require nonempty, unique reviewed regions.')
    grouped = {key: [] for key in indexed}
    seen = set()
    for observation in observations:
        key = (observation.region_id, observation.reader_id)
        if key in seen or observation.region_id not in indexed:
            raise ValueError('Duplicate reading or unknown region.')
        seen.add(key)
        if observation.crop_sha256 != indexed[observation.region_id].crop_sha256:
            raise ValueError('Reading belongs to a different crop.')
        grouped[observation.region_id].append(observation)
    output = []
    for region in locations:
        rows = sorted(grouped[region.region_id], key=lambda r: r.reader_id)
        usable = [r for r in rows if r.status == 'read' and r.blind_to_other_readings_and_key]
        reasons = []
        if region.source_warnings:
            reasons.append('source_visual_ambiguity')
        if len({r.reader_family for r in usable}) < 2:
            reasons.append('insufficient_independent_readers')
        if any(r.status != 'read' for r in rows):
            reasons.append('reader_unavailable_or_illegible')
        if any(not r.blind_to_other_readings_and_key for r in rows):
            reasons.append('reader_not_blind')
        if any(r.uncertainties or '[unclear]' in r.text.lower() for r in rows):
            reasons.append('reported_uncertainty')
        if len({literal_form(r.text) for r in usable}) > 1:
            reasons.append('transcription_disagreement')
        if len({tuple(critical_tokens(r.text)) for r in usable}) > 1:
            reasons.append('critical_symbol_disagreement')
        if any(arithmetic_warning(r.text) for r in usable):
            reasons.append('numeric_consistency_warning_not_proof_of_ocr_error')
        evidence = {'region': region.model_dump(), 'alternatives': [r.model_dump() for r in rows]}
        digest = sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False,
                                   separators=(',', ':')).encode()).hexdigest()
        output.append({**evidence, 'evidence_digest': digest,
                       'review_reasons': reasons, 'requires_review': bool(reasons)})
    return output


def grading_gate(comparisons, decisions=()):
    """No disputed/failed region passes without a current instructor decision.

    Validate decisions in the trusted local review boundary. Do not use provider
    content to construct them. The returned text is a NEW extraction revision;
    alternatives and original OCR are never mutated.
    """
    if not comparisons or len({r['region']['region_id'] for r in comparisons}) != len(comparisons):
        raise ValueError('Require nonempty unique region comparisons.')
    # Recompute from raw evidence: callers cannot remove a reason to bypass review.
    verified = compare_regions([r['region'] for r in comparisons],
                               [a for r in comparisons for a in r['alternatives']])
    if verified != comparisons:
        raise ValueError('Comparison snapshot changed; rebuild review.')
    resolved = {}
    for raw in decisions:
        item = InstructorDecision.model_validate(raw)
        if item.region_id in resolved:
            raise ValueError('Use one current decision per region.')
        resolved[item.region_id] = item
    if set(resolved) - {r['region']['region_id'] for r in comparisons}:
        raise ValueError('Decision refers to an unknown region.')
    pending, text = [], []
    for row in comparisons:
        identifier = row['region']['region_id']
        decision = resolved.get(identifier)
        if decision and decision.evidence_digest != row['evidence_digest']:
            raise ValueError('Stale instructor decision; evidence changed.')
        if decision and decision.action == 'confirm':
            text.append({'region_id': identifier, 'text': decision.text, 'origin': 'instructor_revision'})
        elif row['requires_review'] or decision:
            pending.append(identifier)
        else:
            text.append({'region_id': identifier, 'text': row['alternatives'][0]['text'],
                         'origin': 'independent_reader_agreement'})
    return {'status': 'blocked_for_extraction_review' if pending else 'ready_for_diagnostic_grading',
            'pending_region_ids': pending, 'extraction_revision': [] if pending else deepcopy(text),
            'agreement_proves_accuracy': False}
