"""Synthetic comparison/routing evaluation; no papers or model calls."""
import json
from pathlib import Path
import tempfile
import unittest

from comparison_pilot import agreement_metrics, run_experiment
from semantic_comparison import (
    ReferenceSet, StressCase, active_text, cosine, fit_threshold, full_levels,
    routes, routing_metrics, validate_references, validate_vectors,
)
from test_rubric_pilot import fixture


def examples():
    guide, first, raw = fixture()
    first.segments[0].text = "6 * 4 = 24"
    second = first.model_copy(deep=True)
    second.answer_id = "other"
    second.source_sha256 = "b" * 64
    second.segments[0].text = "6 + 4 = 10"
    refs = ReferenceSet.model_validate({
        "split": "calibration", "provenance": "INSTRUCTOR_ONLY_SENTINEL",
        "independent_blind_labels": False,
        "references": [
            {"answer_id": "example", "criterion_levels": {"setup": "full", "calculation": "full"}},
            {"answer_id": "other", "criterion_levels": {"setup": "zero", "calculation": "zero"}},
        ],
    })
    return guide, [first, second], refs, raw


class SemanticComparisonTests(unittest.TestCase):
    def test_crossed_out_work_is_excluded_from_comparison_without_mutation(self):
        _, answers, _, _ = examples()
        before = answers[0].model_dump()
        self.assertEqual(active_text(answers[0]), "6 * 4 = 24")
        self.assertEqual(answers[0].model_dump(), before)

    def test_nonfinite_zero_and_misaligned_embeddings_are_rejected(self):
        for vectors in ([[0, 0]], [[1, float("nan")]], [[True, 1]], [[1], [1, 2]], []):
            with self.subTest(vectors=vectors), self.assertRaises(ValueError):
                validate_vectors({"model": "qwen-embed", "embeddings": vectors}, "qwen-embed", 1)
        with self.assertRaises(ValueError):
            cosine([0, 0], [1, 0])

    def test_low_similarity_refers_to_qwen_and_never_assigns_a_zero_grade(self):
        self.assertEqual(routes({"a": 0.2, "b": 0.95}, 0.9), {"a": "qwen", "b": "comparison"})
        self.assertEqual(routes({"a": 0.95}, 0.9, {"a": False}), {"a": "qwen"})

    def test_observed_candidate_errors_are_counted_even_with_high_similarity(self):
        guide, _, refs, _ = examples()
        metrics = routing_metrics(guide, {"example": 0.95, "other": 0.97}, refs, 0.9)
        self.assertEqual(metrics["coverage"], 1)
        self.assertEqual(metrics["error_among_comparison_resolved"], 0.5)
        self.assertEqual(metrics["routing_recall"], 0)
        self.assertIsNone(metrics["routing_precision"])

    def test_empty_accepted_set_is_undefined_error_rate_not_zero_error_claim(self):
        guide, _, refs, _ = examples()
        metrics = routing_metrics(guide, {"example": 0.95, "other": 0.8}, refs, None)
        self.assertEqual(metrics["coverage"], 0)
        self.assertIsNone(metrics["error_among_comparison_resolved"])
        self.assertEqual(metrics["routing_recall"], 1)

    def test_threshold_fit_cannot_use_test_labels(self):
        guide, _, refs, _ = examples()
        refs.split = "test"
        with self.assertRaisesRegex(ValueError, "Test labels"):
            fit_threshold(guide, {"example": 0.95, "other": 0.8}, refs)

    def test_overlap_in_similarity_can_force_zero_coverage_in_calibration(self):
        guide, _, refs, _ = examples()
        policy = fit_threshold(guide, {"example": 0.9, "other": 0.95}, refs)
        self.assertIsNone(policy["threshold"])

    def test_reference_labels_must_match_the_actual_guide(self):
        guide, answers, refs, _ = examples()
        refs.references[1].criterion_levels["calculation"] = "invented"
        with self.assertRaises(ValueError):
            validate_references(guide, answers, refs)

    def test_grade_failures_remain_unscored_in_metrics(self):
        guide, answers, refs, _ = examples()
        results = [{"answer_id": "example", "score": None}, {"answer_id": "other", "score": None}]
        metrics = agreement_metrics(guide, answers, refs, results)
        self.assertEqual(metrics["unscored"], 2)
        self.assertIsNone(metrics["mae_among_scored"])
        self.assertEqual(metrics["exact_match_yield"], 0)

    def test_local_experiment_reports_unsafe_stress_matches_and_actual_fallback_calls(self):
        guide, answers, refs, _ = examples()
        stress = [StressCase(id="contradiction", text="The product is not 24.",
                             expected_safe_full_credit=False, rationale="Constructed contradiction.")]
        calls = []
        def transport(route, payload=None):
            if route == "/api/tags":
                return {"models": [{"name": "qwen-embed:tiny", "digest": "c" * 64},
                                   {"name": "qwen-grade:tiny", "digest": "d" * 64}]}
            if route == "/api/version":
                return {"version": "mock"}
            self.assertNotIn("INSTRUCTOR_ONLY_SENTINEL", json.dumps(payload))
            calls.append((route, payload))
            if route == "/api/embed":
                self.assertNotIn("99", json.dumps(payload))
                # A false answer can have the same embedding as a correct one.
                return {"model": "qwen-embed:tiny", "embeddings": [[1, 0], [1, 0], [0, 1], [1, 0]]}
            text = payload["messages"][1]["content"]
            wrong = "6 + 4 = 10" in text
            quote = "6 + 4 = 10" if wrong else "6 * 4 = 24"
            proposal = {"feedback": "Synthetic check.", "criteria": [
                {"criterion_id": cid, "level_id": "zero" if wrong else level,
                 "evidence": [{"segment_id": "s1", "quote": quote}],
                 "explanation": "Synthetic rule check.", "needs_review": False}
                for cid, level in full_levels(guide).items()]}
            return {"model": "qwen-grade:tiny", "done": True, "done_reason": "stop",
                    "message": {"content": json.dumps(proposal)}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            report = run_experiment(guide, answers, refs, stress, root, "qwen-embed:tiny", "qwen-grade:tiny",
                                    fit_calibration=True, diagnostic_draft=True, transport=transport)
            self.assertEqual(report["qwen_only"]["grading_calls"], 2)
            self.assertEqual(report["comparison_first"]["grading_calls"], 1)
            self.assertEqual(report["routing_metrics"]["coverage"], 0.5)
            self.assertEqual(report["stress_diagnostic"]["unsafe_full_credit_candidates"], 1)
            self.assertIsNone(report["instructor_review_time_ms"])
            self.assertIsNone(report["independent_test_metrics"])
            self.assertEqual(len([c for c in calls if c[0] == "/api/chat"]), 3)
            self.assertEqual(report["comparison_first"]["metrics"]["criterion_agreement_among_scored"], 1)
            policy = json.loads((root / "routing-policy.json").read_text())
            refs.split = "test"
            with self.assertRaisesRegex(ValueError, "cannot be relabeled"):
                run_experiment(guide, answers, refs, stress, Path(directory) / "invalid-test",
                                "qwen-embed:tiny", "qwen-grade:tiny", policy=policy,
                                diagnostic_draft=True, transport=transport)
            self.assertEqual(len([c for c in calls if c[0] == "/api/chat"]), 3)


if __name__ == "__main__":
    unittest.main()
