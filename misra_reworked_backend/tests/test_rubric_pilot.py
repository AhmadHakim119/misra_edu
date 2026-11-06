"""Synthetic local-pilot boundaries; no real model, database or student files."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from rubric_pilot import Answer, Guide, Proposal, make_request, run_pilot, score_proposal


def fixture():
    guide = Guide.model_validate({
        "question_id": "synthetic", "question": "Calculate a product.", "assumptions": [],
        "model_answer": "6 * 4 = 24", "approval_status": "draft", "max_points": 3,
        "criteria": [
            {"id": "setup", "title": "Multiplication", "max_points": 1, "levels": [
                {"id": "zero", "description": "No multiplication", "points": 0},
                {"id": "full", "description": "Uses multiplication", "points": 1}]},
            {"id": "calculation", "title": "Calculation", "max_points": 2, "levels": [
                {"id": "zero", "description": "No correct calculation", "points": 0},
                {"id": "partial", "description": "Correct setup, unfinished", "points": 1},
                {"id": "full", "description": "Correct result", "points": 2}]},
        ],
    })
    answer = Answer.model_validate({
        "answer_id": "example", "source_sha256": "a" * 64,
        "transcription_method": "manual_visual",
        "transcription_status": "checked_by_agent_against_page",
        "segments": [{"id": "s1", "text": "6 * 4", "crossed_out": False},
                     {"id": "s2", "text": "99", "crossed_out": True}],
    })
    raw = {"feedback": "Synthetic feedback.", "criteria": [
        {"criterion_id": "setup", "level_id": "full", "explanation": "Multiplication shown.",
         "needs_review": False, "evidence": [{"segment_id": "s1", "quote": "6 * 4"}]},
        {"criterion_id": "calculation", "level_id": "partial", "explanation": "Unfinished.",
         "needs_review": False, "evidence": [{"segment_id": "s1", "quote": "6 * 4"}]},
    ]}
    return guide, answer, raw


class RubricPilotTests(unittest.TestCase):
    def test_partial_levels_are_scored_from_guide_not_provider_numbers(self):
        guide, answer, raw = fixture()
        before = deepcopy(raw)
        result = score_proposal(guide, answer, Proposal.model_validate(raw))
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["instructor_review_status"], "pending")
        self.assertEqual(raw, before)
        for key in ("score", "points", "confidence"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                Proposal.model_validate({**raw, key: 3})

    def test_uncertainty_abstains_instead_of_becoming_zero(self):
        guide, answer, raw = fixture()
        raw["criteria"][1].update(level_id=None, needs_review=True)
        result = score_proposal(guide, answer, Proposal.model_validate(raw))
        self.assertIsNone(result["score"])
        self.assertEqual(result["status"], "needs_review")

    def test_explicit_zero_is_distinct_from_missing_grade(self):
        guide, answer, raw = fixture()
        for row in raw["criteria"]:
            row["level_id"] = "zero"
        self.assertEqual(score_proposal(guide, answer, Proposal.model_validate(raw))["score"], 0)

    def test_missing_duplicate_and_unknown_criteria_fail(self):
        guide, answer, raw = fixture()
        for rows in ([raw["criteria"][0]], [raw["criteria"][0]] * 2,
                     [{**raw["criteria"][0], "criterion_id": "unknown"}, raw["criteria"][1]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                score_proposal(guide, answer, Proposal.model_validate({**raw, "criteria": rows}))

    def test_level_ids_are_bound_to_their_own_criterion(self):
        guide, answer, raw = fixture()
        raw["criteria"][0]["level_id"] = "partial"
        with self.assertRaises(ValueError):
            score_proposal(guide, answer, Proposal.model_validate(raw))

    def test_invented_and_crossed_out_evidence_cannot_support_marks(self):
        guide, answer, raw = fixture()
        for evidence in ({"segment_id": "missing", "quote": "6 * 4"},
                         {"segment_id": "s1", "quote": "24"},
                         {"segment_id": "s2", "quote": "99"}):
            changed = deepcopy(raw)
            changed["criteria"][0]["evidence"] = [evidence]
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                score_proposal(guide, answer, Proposal.model_validate(changed))

    def test_missing_evidence_requests_review_even_when_model_does_not(self):
        guide, answer, raw = fixture()
        raw["criteria"][0]["evidence"] = []
        self.assertEqual(score_proposal(guide, answer, Proposal.model_validate(raw))["status"], "needs_review")

    def test_invalid_scales_and_nonfinite_marks_are_rejected(self):
        guide, _, _ = fixture()
        for points in (4, float("nan"), float("inf"), True):
            changed = guide.model_dump()
            changed["max_points"] = points
            with self.subTest(points=points), self.assertRaises(ValueError):
                Guide.model_validate(changed)

    def test_model_package_contains_evidence_but_not_source_or_reference_labels(self):
        guide, answer, _ = fixture()
        request = make_request(guide, answer, "qwen-test:1")
        prompt = json.dumps(request)
        self.assertNotIn(answer.source_sha256, prompt)
        self.assertNotIn("transcription_status", prompt)
        self.assertNotIn("reference_score", prompt)
        self.assertIn("6 * 4", prompt)

    def test_cancelled_work_is_absent_from_request_but_original_answer_is_preserved(self):
        guide, answer, _ = fixture()
        before = answer.model_dump()
        request = make_request(guide, answer, "qwen-test:1")
        data = request["messages"][1]["content"].split("DATA PACKAGE:\n", 1)[1].split("\nRESPONSE SCHEMA:\n", 1)[0]
        package = json.loads(data)
        self.assertEqual(package["student_evidence"], [{"id": "s1", "text": "6 * 4"}])
        self.assertEqual(answer.model_dump(), before)
        self.assertTrue(answer.segments[1].crossed_out)

    def test_all_crossed_out_work_requires_review_without_inference_or_zero_grade(self):
        guide, answer, _ = fixture()
        for segment in answer.segments:
            segment.crossed_out = True
        def fake(route, payload=None):
            if route == "/api/tags":
                return {"models": [{"name": "qwen-test:1", "digest": "b" * 64}]}
            if route == "/api/version":
                return {"version": "mock"}
            self.fail("No inference may be requested without active evidence.")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "attempt"
            summary = run_pilot(guide, [answer], output, "qwen-test:1",
                                diagnostic_draft=True, transport=fake)
            result = summary["results"][0]
            self.assertEqual(result["status"], "needs_review")
            self.assertIsNone(result["score"])
            self.assertFalse(result["inference_requested"])
            snapshot = json.loads((output / "input-snapshot.json").read_text())
            self.assertEqual(snapshot["answers"][0], answer.model_dump())
            self.assertEqual(len(snapshot["runner_source_sha256"]), 64)

    def test_run_saves_raw_output_and_keeps_instructor_reference_pending(self):
        guide, answer, raw = fixture()
        calls = []
        def fake(route, payload=None):
            if route == "/api/tags":
                return {"models": [{"name": "qwen-test:1", "digest": "b" * 64}]}
            if route == "/api/version":
                return {"version": "mock"}
            calls.append(payload)
            return {"model": "qwen-test:1", "done": True, "done_reason": "stop",
                    "message": {"content": json.dumps(raw)}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "attempt"
            with self.assertRaises(ValueError):
                run_pilot(guide, [answer], output, "qwen-test:1", transport=fake)
            result = run_pilot(guide, [answer], output, "qwen-test:1", diagnostic_draft=True, transport=fake)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["results"][0]["score"], 2)
            self.assertIsNone(result["grading_accuracy"])
            self.assertTrue((output / "example" / "raw-response.json").is_file())
            with self.assertRaises(FileExistsError):
                run_pilot(guide, [answer], output, "qwen-test:1", diagnostic_draft=True, transport=fake)
            self.assertEqual(len(calls), 1)

    def test_truncation_and_transport_failures_are_saved_without_retry(self):
        guide, answer, raw = fixture()
        for failure in ("transport", "truncation", "schema"):
            calls = []
            def fake(route, payload=None):
                if route == "/api/tags":
                    return {"models": [{"name": "qwen-test:1", "digest": "b" * 64}]}
                if route == "/api/version":
                    return {"version": "mock"}
                calls.append(payload)
                if failure == "transport":
                    raise TimeoutError()
                return {"model": "qwen-test:1", "done": True,
                        "done_reason": "length" if failure == "truncation" else "stop",
                        "message": {"content": "{}" if failure == "schema" else json.dumps(raw)}}
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                result = run_pilot(guide, [answer], Path(directory) / "attempt", "qwen-test:1",
                                   diagnostic_draft=True, transport=fake)
                self.assertEqual(len(calls), 1)
                self.assertEqual(result["results"][0]["status"], "failed")
                self.assertIsNone(result["results"][0]["score"])


if __name__ == "__main__":
    unittest.main()
