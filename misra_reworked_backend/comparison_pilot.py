"""Private, local comparison-first experiment with a fresh Qwen-only baseline."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from time import perf_counter

import rubric_pilot as grading
from semantic_comparison import (
    VERSION, ReferenceSet, StressCase, active_text, cosine, fit_threshold,
    reference_score, routes, routing_metrics, similarity_proposal, threshold_curve,
    validate_references, validate_vectors,
)


EMBED_OPTIONS = {"num_ctx": 4096, "num_gpu": 0}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def installed_model(tags, name):
    if not name.startswith("qwen") or "cloud" in name.lower() or "/" in name:
        raise ValueError("Only explicitly installed local Qwen models are supported.")
    matches = [m for m in tags.get("models", []) if m.get("name") == name]
    if len(matches) != 1 or not matches[0].get("digest") or matches[0].get("remote_host"):
        raise ValueError("Requested local model is absent; no download/fallback was attempted.")
    return matches[0]


def agreement_metrics(guide, answers, references, results):
    """Preserve failures and distinguish total agreement from criterion agreement."""
    validate_references(guide, answers, references)
    by_id = {r["answer_id"]: r for r in results}
    if len(by_id) != len(results) or set(by_id) != {a.answer_id for a in answers}:
        raise ValueError("Results must cover every scheduled answer exactly once.")
    errors, exact, criterion_matches, compared = [], 0, 0, 0
    for ref in references.references:
        result = by_id[ref.answer_id]
        score = result.get("score")
        if score is None:
            continue
        expected = reference_score(guide, ref)
        errors.append(abs(score - expected))
        exact += score == expected
        selected = {c["criterion_id"]: c["level_id"] for c in result["criteria"]}
        compared += len(ref.criterion_levels)
        criterion_matches += sum(selected.get(cid) == level for cid, level in ref.criterion_levels.items())
    return {"scheduled": len(answers), "scored": len(errors), "unscored": len(answers) - len(errors),
            "exact_total_matches": exact,
            "exact_match_yield": exact / len(answers),
            "exact_agreement_among_scored": exact / len(errors) if errors else None,
            "mae_among_scored": sum(errors) / len(errors) if errors else None,
            "criterion_matches": criterion_matches, "criteria_compared": compared,
            "criterion_agreement_among_scored": criterion_matches / compared if compared else None,
            "reference_split": references.split,
            "independent_blind_labels": references.independent_blind_labels}


def run_experiment(guide, answers, references, stress_cases, output, embedding_model, grading_model,
                   *, fit_calibration=False, policy=None, diagnostic_draft=False,
                   transport=grading.local_request):
    if guide.approval_status != "approved" and not diagnostic_draft:
        raise ValueError("Draft guide requires an explicit diagnostic experiment.")
    validate_references(guide, answers, references)
    if bool(fit_calibration) == (policy is not None):
        raise ValueError("Fit a calibration policy OR supply a frozen policy.")
    if fit_calibration and references.split != "calibration":
        raise ValueError("Test labels must not fit the routing policy.")
    stress_ids = [s.id for s in stress_cases]
    if len(stress_ids) != len(set(stress_ids)) or set(stress_ids) & {a.answer_id for a in answers}:
        raise ValueError("Stress cases need distinct IDs, separate from paper IDs.")
    tags = transport("/api/tags")
    embedding_identity = installed_model(tags, embedding_model)
    grading_identity = installed_model(tags, grading_model)
    guide_hash = grading.digest(guide.model_dump())
    if policy is not None:
        if (policy.get("guide_sha256") != guide_hash
                or policy.get("embedding_digest") != embedding_identity["digest"]
                or policy.get("algorithm_version") != VERSION):
            raise ValueError("Frozen policy does not match this guide, embedding model or comparator.")
        if references.split == "test" and (
                set(policy.get("fit_answer_ids", [])) & {a.answer_id for a in answers}
                or set(policy.get("fit_source_sha256", [])) & {a.source_sha256 for a in answers}):
            raise ValueError("Calibration papers cannot be relabeled as unseen test papers.")
    output.mkdir(parents=True, exist_ok=False)
    inputs = [guide.model_answer, *[active_text(a) or "[NO ACTIVE EVIDENCE]" for a in answers],
              *[s.text for s in stress_cases]]
    embed_request = {"model": embedding_model, "input": inputs, "truncate": False,
                     "keep_alive": "5m", "options": EMBED_OPTIONS.copy()}
    grading.save_new(output / "protocol.json", {
        "created_at": datetime.now(timezone.utc).isoformat(), "algorithm_version": VERSION,
        "guide": guide.model_dump(), "answers": [a.model_dump() for a in answers],
        "embedding_model": embedding_identity, "grading_model": grading_identity,
        "ollama_version": transport("/api/version"),
        "runner_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "comparator_source_sha256": hashlib.sha256(Path(__file__).with_name("semantic_comparison.py").read_bytes()).hexdigest(),
        "embedding_options": EMBED_OPTIONS, "grading_options": grading.OPTIONS,
        "execution_order": ["embed", "qwen_only", "comparison_first"],
        "purpose": "one-question development diagnostic; not independent accuracy validation",
        "labels_in_model_inputs": False, "automatic_retries": 0,
    })
    # Labels and stress-case expectations never enter either inference request.
    grading.save_new(output / "reference-labels.json", references.model_dump())
    grading.save_new(output / "stress-cases.json", [s.model_dump() for s in stress_cases])
    grading.save_new(output / "embedding-request.json", embed_request)
    started = perf_counter()
    response = transport("/api/embed", embed_request)
    embedding_ms = (perf_counter() - started) * 1000
    grading.save_new(output / "embedding-response.json", response)
    vectors = validate_vectors(response, embedding_model, len(inputs))
    scores = {a.answer_id: cosine(vectors[0], vectors[i + 1]) for i, a in enumerate(answers)}
    eligible = {a.answer_id: bool(active_text(a).strip()) for a in answers}
    if fit_calibration:
        policy = {**fit_threshold(guide, scores, references, eligible), "algorithm_version": VERSION,
                  "guide_sha256": guide_hash, "embedding_digest": embedding_identity["digest"],
                  "fit_source_sha256": sorted({a.source_sha256 for a in answers})}
    grading.save_new(output / "routing-policy.json", policy)
    decisions = routes(scores, policy["threshold"], eligible)
    routing = [{"answer_id": a.answer_id, "cosine": scores[a.answer_id], "route": decisions[a.answer_id]}
               for a in answers]
    grading.save_new(output / "routing-decisions.json", routing)
    curve = (threshold_curve(guide, scores, references, eligible) if references.split == "calibration" else
             [{"threshold": policy["threshold"], **routing_metrics(guide, scores, references, policy["threshold"], eligible)}])
    grading.save_new(output / "threshold-curve.json", curve)
    stress_rows = []
    for i, case in enumerate(stress_cases):
        similarity = cosine(vectors[0], vectors[1 + len(answers) + i])
        route = routes({case.id: similarity}, policy["threshold"])[case.id]
        stress_rows.append({**case.model_dump(), "cosine": similarity, "route": route,
                            "unsafe_full_credit_candidate": route == "comparison" and not case.expected_safe_full_credit,
                            "unnecessary_fallback": route == "qwen" and case.expected_safe_full_credit})
    grading.save_new(output / "stress-results.json", stress_rows)
    # Freeze the threshold before running either fresh grading arm.
    started = perf_counter()
    baseline = grading.run_pilot(guide, answers, output / "qwen-only", grading_model,
                                 diagnostic_draft=diagnostic_draft, transport=transport)
    baseline_ms = (perf_counter() - started) * 1000
    started = perf_counter()
    referred = [a for a in answers if decisions[a.answer_id] == "qwen"]
    fallback = (grading.run_pilot(guide, referred, output / "qwen-fallback", grading_model,
                                diagnostic_draft=diagnostic_draft, transport=transport)
                if referred else {"results": []})
    fallback_results = {r["answer_id"]: r for r in fallback["results"]}
    hybrid_results = []
    for answer in answers:
        result = (similarity_proposal(guide, answer, scores[answer.answer_id])
                  if decisions[answer.answer_id] == "comparison" else
                  {**fallback_results[answer.answer_id], "decision_source": "qwen_fallback"})
        hybrid_results.append(result)
    hybrid_ms = (perf_counter() - started) * 1000
    grading.save_new(output / "hybrid-results.json", hybrid_results)
    baseline_calls = sum(bool(r.get("inference_requested", r["status"] == "failed")) for r in baseline["results"])
    hybrid_calls = sum(bool(r.get("inference_requested", r["status"] == "failed")) for r in fallback["results"])
    report = {
        "algorithm_version": VERSION, "policy": policy,
        "routing": routing,
        "routing_metrics": routing_metrics(guide, scores, references, policy["threshold"], eligible),
        "qwen_only": {"metrics": agreement_metrics(guide, answers, references, baseline["results"]),
                      "grading_calls": baseline_calls, "observed_elapsed_ms": round(baseline_ms)},
        "comparison_first": {"metrics": agreement_metrics(guide, answers, references, hybrid_results),
                             "embedding_calls": 1, "grading_calls": hybrid_calls,
                             "embedding_stage_ms": round(embedding_ms), "grading_stage_ms": round(hybrid_ms),
                             "observed_stage_sum_ms": round(embedding_ms + hybrid_ms)},
        "stress_diagnostic": {"reference_kind": "developer-constructed expectations, not instructor labels",
                              "case_count": len(stress_rows),
                              "unsafe_full_credit_candidates": sum(r["unsafe_full_credit_candidate"] for r in stress_rows),
                              "unnecessary_fallbacks": sum(r["unnecessary_fallback"] for r in stress_rows)},
        "ocr_time_ms": None, "instructor_review_time_ms": None, "energy_or_money_savings": None,
        "independent_test_metrics": None if references.split == "calibration" else "See explicitly marked reference metrics.",
        "limitations": [
            "Whole-answer similarity proposes full credit only; low similarity never assigns zero.",
            "A threshold fitted and measured on these same two papers is calibration evidence only.",
            "Stress cases test failure modes, not representative grading accuracy.",
            "Serial execution, model loading and prompt caches confound the observed timing comparison.",
            "OCR, rubric setup and instructor review time were not measured.",
            "No final grade or guide approval is automatic.",
        ],
    }
    grading.save_new(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("guide", "answers", "references", "stress-cases", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--embedding-model", default="qwen3-embedding:0.6b")
    parser.add_argument("--grading-model", default="qwen3:4b-instruct")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--fit-calibration", action="store_true")
    choice.add_argument("--policy", type=Path)
    parser.add_argument("--diagnostic-draft", action="store_true")
    args = parser.parse_args()
    private_root = Path(__file__).resolve().parents[1] / "private"
    if not args.output.resolve().is_relative_to(private_root.resolve()):
        parser.error("Comparison output must stay under the ignored private/ directory.")
    guide = grading.Guide.model_validate(read_json(args.guide))
    answers = [grading.Answer.model_validate(a) for a in read_json(args.answers)]
    references = ReferenceSet.model_validate(read_json(args.references))
    stress = [StressCase.model_validate(s) for s in read_json(args.stress_cases)]
    report = run_experiment(guide, answers, references, stress, args.output,
                            args.embedding_model, args.grading_model,
                            fit_calibration=args.fit_calibration,
                            policy=read_json(args.policy) if args.policy else None,
                            diagnostic_draft=args.diagnostic_draft)
    print(json.dumps({"output": str(args.output.resolve()), "routing": report["routing"],
                      "routing_metrics": report["routing_metrics"], "stress": report["stress_diagnostic"]}))


if __name__ == "__main__":
    main()
