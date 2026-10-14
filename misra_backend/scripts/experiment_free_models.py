"""Compare free OpenRouter grading models using invented answers only.

No database access, uploaded papers, official grades, or Gemini calls. This is
an API smoke test, not a measurement of academic grading accuracy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from services.grading_service import (  # noqa: E402
    GRADING_PROMPT,
    GradingResult,
    _validate_grading_against_rubric,
)
from services.grading_package_service import validate_evidence_references  # noqa: E402
from services.openrouter_client import OpenRouterError, complete_json  # noqa: E402


DEFAULT_MODELS = (
    "nvidia/nemotron-3-super-120b-a12b:free",
)


def _case(name: str, question: str, answer: str, criterion: dict,
          reference: str, policy: dict, expected_score: float) -> dict:
    rubric = {"schema_version": 2, "max_score": float(criterion["points"]),
              "criteria": [criterion], "policy": policy}
    package = {
        "schema_version": 1,
        "question": {"number": "1", "text": question,
                     "max_score": float(criterion["points"])},
        "rubric": rubric,
        "policy": policy,
        "answer_key": {"reference_id": "instructor:answer_key", "version": 1,
                       "mode": "reference", "reference_text": reference,
                       "alternatives": [], "document_refs": [],
                       "is_legacy_fallback": False},
        "routing": {"selected_mode": "text_only"},
        "definition_consistency": {"blocking_errors": [], "advisories": []},
        "student_evidence": [
            {"id": "student:combined:1", "kind": "combined_ocr", "text": answer},
            {"id": "student:segment:1", "kind": "ocr_segment", "page_index": 0,
             "segment_index": 0, "text": answer},
        ],
    }
    return {"name": name, "package": package, "expected_score": expected_score}


def synthetic_cases() -> list[dict]:
    """Three distinct, clearly labeled examples for contract and behavior checks."""
    return [
        _case(
            "correct_sql_handwritten_notation",
            "Write a query listing each course name in ascending order.",
            "SELECT courseName FROM COURSES ORDER BY courseName ASC;",
            {"id": "ordering", "title": "Correct ordered query", "points": 2,
             "description": "Select course names and order them ascending.",
             "scoring_type": "scaled", "partial_credit_allowed": True},
            "SELECT courseName FROM COURSES ORDER BY courseName ASC;",
            {"handwritten_syntax_policy": "accept_unambiguous",
             "grading_approach": "balanced"},
            2.0,
        ),
        _case(
            "wrong_math_result",
            "Find 7 × 8. Award one point for the correct multiplication setup and one for the result.",
            "7 × 8 = 54",
            {"id": "multiplication", "title": "Multiplication setup and result", "points": 2,
             "description": "One point for setting up 7 × 8; one for the correct answer 56.",
             "scoring_type": "scaled", "partial_credit_allowed": True},
            "7 × 8 = 56. A correct setup with an arithmetic slip earns one point.",
            {"arithmetic_error_policy": "single_penalty", "method_credit": "partial"},
            1.0,
        ),
        _case(
            "valid_ethics_reasoning",
            "Explain why exposing a classmate's private data without consent is unethical.",
            "It violates their privacy and removes their choice about who sees their information. It may also cause harm.",
            {"id": "privacy_reasoning", "title": "Ethical reasoning", "points": 2,
             "description": "Identify the privacy or autonomy concern and explain a plausible harm.",
             "scoring_type": "scaled", "partial_credit_allowed": True},
            "Valid answers connect unauthorized disclosure to privacy, autonomy, consent, or harm.",
            {"alternative_methods_allowed": True, "grading_approach": "balanced"},
            2.0,
        ),
    ]


def run_experiment(models: tuple[str, ...], cases: list[dict]) -> list[dict]:
    rows = []
    for model in models:
        for case in cases:
            prompt = GRADING_PROMPT + "\nGRADING PACKAGE JSON:\n" + json.dumps(
                case["package"], ensure_ascii=False)
            row = {"model": model, "case": case["name"],
                   "expected_score": case["expected_score"]}
            try:
                completion = complete_json(model=model, prompt=prompt)
                row.update({"latency_ms": completion.latency_ms,
                            "prompt_tokens": completion.prompt_tokens,
                            "completion_tokens": completion.completion_tokens,
                            "returned_model": completion.returned_model})
                parsed = json.loads(completion.text)
                result = GradingResult.model_validate(parsed)
                _validate_grading_against_rubric(result, case["package"]["rubric"])
                validate_evidence_references(result, case["package"])
                row.update({"status": "valid", "score": result.score,
                            "absolute_error": round(abs(result.score - case["expected_score"]), 2),
                            "criterion_feedback": [item.feedback for item in result.criteria_scores]})
            except (OpenRouterError, ValidationError, ValueError, json.JSONDecodeError) as error:
                # Keep errors compact: a provider may echo request content in its message.
                row.update({"status": "invalid", "error_type": type(error).__name__})
                if isinstance(error, OpenRouterError):
                    row["safe_error"] = str(error)
            rows.append(row)
            print(json.dumps({key: row.get(key) for key in
                ("model", "case", "status", "score", "absolute_error", "latency_ms", "error_type", "safe_error")}))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", help="Explicit :free model slug; repeat as needed")
    parser.add_argument("--case", action="append", help="Synthetic case name; repeat as needed")
    args = parser.parse_args()
    models = tuple(args.model or DEFAULT_MODELS)
    if not all(model.endswith(":free") for model in models):
        parser.error("Every experimental model must use an explicit :free slug")
    cases = synthetic_cases()
    if args.case:
        cases = [case for case in cases if case["name"] in args.case]
        if len(cases) != len(set(args.case)):
            parser.error("Unknown or duplicate synthetic case name")
    rows = run_experiment(models, cases)
    for model in models:
        subset = [row for row in rows if row["model"] == model]
        valid = [row for row in subset if row["status"] == "valid"]
        print(json.dumps({"model": model, "valid": len(valid), "attempted": len(subset),
                          "illustrative_mae": round(sum(row["absolute_error"] for row in valid) /
                                                    len(valid), 3) if valid else None,
                          "note": "Synthetic smoke test; not a real grading accuracy estimate."}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
