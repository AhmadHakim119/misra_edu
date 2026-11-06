"""Synthetic offline OCR boundaries, without model calls, student papers or database."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import local_ocr as ocr
from rubric_pilot import Answer, Proposal, make_request, score_proposal
from test_rubric_pilot import fixture


class OcrTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.guard = patch.object(ocr, "PRIVATE_ROOT", self.root)
        self.guard.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.guard.stop)
        self.image = self.root / "synthetic.png"
        Image.new("RGB", (160, 80), "white").save(self.image)
        self.config = ocr.OcrConfig(engine="paddle", language="ar+en",
                                    detection_model_dir="synthetic", recognition_model_dir="synthetic")

    def fake_backend(self, config):
        class Fake:
            def recognize(inner, image, page, width, height):
                return {"rec_texts": ["لا تجمع 2 + 3"], "rec_scores": [0.99],
                        "rec_polys": [[[2,2],[90,2],[90,30],[2,30]]]}
        return Fake()

    def run_fixture(self):
        output = self.root / "run"
        doc = ocr.extract(self.image, self.config, output, backend_factory=self.fake_backend)
        return doc, output

    def test_preserves_source_pages_raw_and_unknown_cancellation(self):
        doc, out = self.run_fixture()
        self.assertEqual(ocr.file_hash(self.image), ocr.file_hash(out / "original.png"))
        self.assertEqual(doc.status, "needs_transcription_review")
        self.assertEqual(doc.spans[0].cancellation, "unknown")
        self.assertEqual(doc.spans[0].role, "unassigned")
        self.assertTrue((out / "raw-page-1.json").exists())
        self.assertFalse(json.loads((out / "run.json").read_text())["grading_requested"])
        self.assertEqual(doc.spans[0].text, "لا تجمع 2 + 3")

    def test_ocr_draft_cannot_be_a_grading_answer(self):
        doc, _ = self.run_fixture()
        with self.assertRaises(ValueError):
            Answer.model_validate(doc.model_dump())

    def test_no_overwrite_or_outputs_outside_private(self):
        self.run_fixture()
        with self.assertRaises(FileExistsError):
            self.run_fixture()
        with self.assertRaises(ValueError):
            ocr.private_path(self.root.parent / "public-output")

    def test_failure_persists_none_score_not_zero(self):
        def fail(config):
            raise RuntimeError("synthetic failure")
        with self.assertRaises(RuntimeError):
            ocr.extract(self.image, self.config, self.root / "fail", backend_factory=fail)
        failure = json.loads((self.root / "fail/failure.json").read_text())
        self.assertIsNone(failure["score"])
        self.assertTrue((self.root / "fail/pages/page-1.png").exists())

    def test_empty_detection_requires_review(self):
        class Empty:
            def recognize(inner, *args):
                return {"rec_texts": [], "rec_scores": [], "rec_polys": []}
        doc = ocr.extract(self.image, self.config, self.root / "empty", backend_factory=lambda c: Empty())
        self.assertEqual(doc.status, "needs_transcription_review")
        self.assertTrue(doc.pages[0].issues)

    def test_malformed_engine_output_is_saved_before_validation_failure(self):
        class Bad:
            def recognize(inner, *args):
                return {"rec_texts": ["untrusted output"], "rec_scores": [], "rec_polys": []}
        with self.assertRaises(ValueError):
            ocr.extract(self.image, self.config, self.root / "bad", backend_factory=lambda c: Bad())
        self.assertTrue((self.root / "bad/raw-page-1.json").exists())
        self.assertFalse((self.root / "bad/extraction.json").exists())

    def test_network_connections_are_disabled_and_restored(self):
        original = socket.create_connection
        with ocr.offline_python(), self.assertRaises(RuntimeError):
            socket.create_connection(("example.com", 443))
        self.assertIs(socket.create_connection, original)

    def test_paddle_rejects_mismatched_lengths_invalid_scores_and_geometry(self):
        good = {"rec_texts": ["2 + 3"], "rec_scores": [0.99],
                "rec_polys": [[[1, 2], [30, 2], [30, 20], [1, 20]]]}
        self.assertEqual(ocr.parse_paddle(good, 1, 160, 80)[0].text, "2 + 3")
        for change in ({"rec_scores": []}, {"rec_scores": [float("nan")]},
                       {"rec_scores": [1.1]}, {"rec_polys": [[[1, 2], [900, 2], [900, 20], [1, 20]]]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ocr.parse_paddle({**good, **change}, 1, 160, 80)

    def test_tesseract_keeps_arabic_negation_and_operator(self):
        header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        text = header + "5\t1\t1\t1\t1\t1\t1\t2\t20\t18\t90\tلا\n"
        text += "5\t1\t1\t1\t1\t2\t25\t2\t10\t18\t95\t+\n"
        spans = ocr.parse_tesseract(text, 1, 160, 80)
        self.assertEqual([s.text for s in spans], ["لا", "+"])
        with self.assertRaises(ValueError):
            ocr.parse_tesseract(text.replace("\t90\t", "\tNaN\t"), 1, 160, 80)

    def review_fixture(self, out):
        path = out / "extraction.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        return {"extraction_sha256": ocr.file_hash(path), "source_sha256": doc["source_sha256"],
                "answer_id": "synthetic", "question_id": "synthetic", "reviewer": "Synthetic instructor",
                "answer_region_and_completeness_checked": True,
                "excludes_identity_question_and_teacher_marks": True,
                "segments": [{"id": "s1", "page": 1, "bbox": {"x0": 2,"y0": 2,"x1": 90,"y1": 30},
                              "source_span_ids": ["p1_s1"], "text": "2 + 3", "crossed_out": False,
                              "checked_against_page": True}]}

    def export(self, out, review):
        review_path = self.root / "review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        return ocr.export_reviewed(out / "extraction.json", review_path, self.root / "reviewed")

    def test_reviewed_export_keeps_provenance_and_never_approves_grade(self):
        _, out = self.run_fixture()
        review = self.review_fixture(out)
        answer = self.export(out, review)
        self.assertEqual(answer.transcription_method, "local_ocr")
        self.assertIsNotNone(answer.extraction_provenance)
        guide, _, _ = fixture()
        payload = make_request(guide, answer, "qwen-test")
        self.assertNotIn("Synthetic instructor", json.dumps(payload))
        self.assertNotIn("extraction_sha256", json.dumps(payload))
        self.assertEqual(json.loads((out / "extraction.json").read_text())["status"], "needs_transcription_review")

    def test_unchecked_cancelled_unknown_stale_or_wrong_refs_rejected(self):
        _, out = self.run_fixture()
        good = self.review_fixture(out)
        cases = []
        for key, value in (("checked_against_page", False), ("crossed_out", None),
                           ("source_span_ids", ["p99_s1"]), ("page", 2)):
            case = deepcopy(good)
            case["segments"][0][key] = value
            cases.append(case)
        for key, value in (("extraction_sha256", "f"*64), ("source_sha256", "f"*64),
                           ("answer_region_and_completeness_checked", False),
                           ("excludes_identity_question_and_teacher_marks", False)):
            cases.append({**good, key: value})
        for review in cases:
            with self.subTest(review=review), self.assertRaises(ValueError):
                self.export(out, review)

    def test_tampered_page_cannot_be_exported(self):
        _, out = self.run_fixture()
        review = self.review_fixture(out)
        (out / "pages/page-1.png").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.export(out, review)

    def test_review_template_cannot_self_approve(self):
        _, out = self.run_fixture()
        path = self.root / "template.json"
        ocr.review_template(out / "extraction.json", path, "synthetic", "synthetic")
        template = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsNone(template["segments"][0]["crossed_out"])
        with self.assertRaises(ValueError):
            ocr.export_reviewed(out / "extraction.json", path, self.root / "exported")

    def test_crossed_out_review_stays_filtered_from_qwen(self):
        _, out = self.run_fixture()
        review = self.review_fixture(out)
        review["segments"][0]["crossed_out"] = True
        answer = self.export(out, review)
        guide, _, _ = fixture()
        payload = make_request(guide, answer, "qwen-test")
        self.assertNotIn('"text": "2 + 3"', json.dumps(payload))

    def test_wrong_question_is_rejected_before_grading(self):
        _, out = self.run_fixture()
        review = self.review_fixture(out)
        review["question_id"] = "other-question"
        answer = self.export(out, review)
        guide, _, raw = fixture()
        with self.assertRaises(ValueError):
            make_request(guide, answer, "qwen-test")
        with self.assertRaises(ValueError):
            score_proposal(guide, answer, Proposal.model_validate(raw))


if __name__ == "__main__":
    unittest.main()
