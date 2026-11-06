"""Experimental full-credit similarity router. A similarity is not a probability.

Only high-scoring full-credit candidates can bypass Qwen. Low similarity never
becomes zero marks. All outputs remain provisional and instructor-reviewed.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import Field

from rubric_pilot import Answer, Guide, Proposal, StrictModel, score_proposal


VERSION = "semantic-comparison-v1"


class Reference(StrictModel):
    answer_id: str = Field(min_length=1)
    criterion_levels: dict[str, str]


class ReferenceSet(StrictModel):
    split: Literal["calibration", "test"]
    provenance: str = Field(min_length=1)
    independent_blind_labels: bool
    references: list[Reference] = Field(min_length=1)


class StressCase(StrictModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=20000)
    expected_safe_full_credit: bool
    rationale: str = Field(min_length=1)


def active_text(answer: Answer) -> str:
    return "\n".join(s.text for s in answer.segments if not s.crossed_out)


def validate_vectors(response, model, expected_count):
    if response.get("model") != model:
        raise ValueError("Embedding response used a different model.")
    vectors = response.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise ValueError("Embedding response is missing input vectors.")
    dimension = None
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise ValueError("Embedding vectors must be nonempty arrays.")
        if dimension is None:
            dimension = len(vector)
        if len(vector) != dimension or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
            raise ValueError("Embedding dimensions or values are invalid.")
        if math.fsum(x * x for x in vector) == 0:
            raise ValueError("Zero vectors cannot establish similarity.")
    return vectors


def cosine(left, right):
    if len(left) != len(right) or not left:
        raise ValueError("Require equally sized nonempty vectors.")
    for vector in (left, right):
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
            raise ValueError("Vector values must be finite numbers.")
    numerator = math.fsum(x * y for x, y in zip(left, right))
    denominator = math.sqrt(math.fsum(x * x for x in left)) * math.sqrt(math.fsum(y * y for y in right))
    if not denominator or not math.isfinite(denominator):
        raise ValueError("Cannot compare zero or invalid vectors.")
    return max(-1.0, min(1.0, numerator / denominator))


def full_levels(guide: Guide):
    return {c.id: next(level.id for level in c.levels if level.points == c.max_points)
            for c in guide.criteria}


def validate_references(guide, answers, references):
    ids = [r.answer_id for r in references.references]
    if len(ids) != len(set(ids)) or set(ids) != {a.answer_id for a in answers}:
        raise ValueError("References must identify each supplied answer exactly once.")
    allowed = {c.id: {level.id for level in c.levels} for c in guide.criteria}
    for reference in references.references:
        if set(reference.criterion_levels) != set(allowed):
            raise ValueError("Reference labels must cover the rubric criteria exactly.")
        if any(level not in allowed[cid] for cid, level in reference.criterion_levels.items()):
            raise ValueError("Reference level does not belong to its criterion.")


def reference_score(guide, reference):
    return math.fsum(next(level.points for level in c.levels
                          if level.id == reference.criterion_levels[c.id]) for c in guide.criteria)


def validate_scores(scores):
    if not scores or any(type(v) not in (int, float) or not math.isfinite(v) or not -1 <= v <= 1
                         for v in scores.values()):
        raise ValueError("Require finite cosine scores between -1 and 1.")


def routes(scores, threshold, eligible=None):
    validate_scores(scores)
    if threshold is not None and (type(threshold) not in (int, float)
                                  or not math.isfinite(threshold) or not -1 <= threshold <= 1):
        raise ValueError("Threshold must be null or a finite value between -1 and 1.")
    if eligible is not None and set(eligible) != set(scores):
        raise ValueError("Eligibility must cover every score exactly.")
    return {aid: "comparison" if threshold is not None and score >= threshold
            and (eligible is None or eligible[aid]) else "qwen" for aid, score in scores.items()}


def routing_metrics(guide, scores, references, threshold, eligible=None):
    if set(scores) != {r.answer_id for r in references.references}:
        raise ValueError("Scores and references must cover the same answers.")
    decisions = routes(scores, threshold, eligible)
    full = full_levels(guide)
    wrong = {r.answer_id for r in references.references if r.criterion_levels != full}
    accepted = {aid for aid, route in decisions.items() if route == "comparison"}
    referred = set(scores) - accepted
    missed = accepted & wrong
    caught = referred & wrong
    total = len(scores)
    precision = len(caught) / len(referred) if referred else None
    recall = len(caught) / len(wrong) if wrong else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and precision + recall else
          0.0 if precision is not None and recall is not None else None)
    return {
        "label_split": references.split, "sample_count": total,
        "independent_blind_labels": references.independent_blind_labels,
        "positive_definition": "A full-credit candidate disagrees with at least one instructor criterion level.",
        "comparison_resolved": len(accepted), "qwen_referred": len(referred),
        "coverage": len(accepted) / total,
        "comparison_errors": len(missed),
        "error_among_comparison_resolved": len(missed) / len(accepted) if accepted else None,
        "candidate_errors_caught": len(caught), "candidate_errors_total": len(wrong),
        "routing_precision": precision, "routing_recall": recall, "routing_f1": f1,
        "interpretation": "Routing is tested against full-credit candidate errors, not all possible Qwen errors.",
    }


def fit_threshold(guide, scores, references, eligible=None):
    """Fit only on calibration data. Never choose a threshold from test labels."""
    if references.split != "calibration":
        raise ValueError("Test labels cannot fit a routing threshold.")
    validate_scores(scores)
    choices = [None, *sorted(set(scores.values()))]
    acceptable = []
    for threshold in choices:
        metrics = routing_metrics(guide, scores, references, threshold, eligible)
        if metrics["comparison_errors"] == 0:
            acceptable.append((metrics["comparison_resolved"], threshold))
    _, threshold = max(acceptable, key=lambda item: (item[0], -2 if item[1] is None else item[1]))
    return {
        "threshold": threshold,
        "fit_answer_ids": sorted(scores), "fit_sample_count": len(scores),
        "objective": "Maximum calibration coverage with zero observed full-credit candidate errors.",
        "validation_status": "unvalidated; calibration fit is not test performance or a correctness guarantee",
    }


def threshold_curve(guide, scores, references, eligible=None):
    return [{"threshold": threshold, **routing_metrics(guide, scores, references, threshold, eligible)}
            for threshold in [None, *sorted(set(scores.values()))]]


def similarity_proposal(guide, answer, similarity):
    evidence = [{"segment_id": s.id, "quote": s.text} for s in answer.segments if not s.crossed_out]
    if not evidence:
        raise ValueError("Similarity cannot resolve an answer without active evidence.")
    # Quotes locate the evidence, not independently establish each criterion's
    # academic support. This intentionally simple baseline is tested for errors.
    full = full_levels(guide)
    proposal = Proposal.model_validate({
        "criteria": [{"criterion_id": c.id, "level_id": full[c.id], "evidence": evidence,
                      "explanation": "Experimental full-credit candidate from whole-answer similarity; criterion support awaits instructor review.",
                      "needs_review": False} for c in guide.criteria],
        "feedback": "Provisional full-credit similarity match. Instructor confirmation is required.",
    })
    result = score_proposal(guide, answer, proposal)
    result.update(decision_source="semantic_comparison", cosine_similarity=similarity)
    return result
