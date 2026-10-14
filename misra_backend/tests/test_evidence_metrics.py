import unittest
from unittest.mock import patch
from services.evaluation_service import _summary
from services.text_quality_metrics import text_metrics
import test_review_reasons as review_fixtures
from services.evaluation_service import build_evaluation_report
from models import ReviewLabel


class NumericAndTextMetricTests(unittest.TestCase):
    def test_normalized_error_bias_rmse_and_unknown_maximum(self):
        result = _summary([{"absolute_error":1,"signed_error":-1,"max_score":2},
            {"absolute_error":2,"signed_error":2,"max_score":10},{"absolute_error":0,"signed_error":0}])
        self.assertEqual(result["normalized_mae"],.35)
        self.assertEqual(result["normalized_label_count"],2)
        self.assertAlmostEqual(result["rmse"],1.291,places=3)
        self.assertEqual(result["mean_signed_error"],.3333)
        self.assertIsNone(_summary([])["normalized_mae"])

    def test_transcription_and_overlap_scores_are_separate(self):
        same = text_metrics("الشغل = mgh","الشغل = mgh")
        self.assertEqual(same["character_error_rate"],0)
        self.assertEqual(same["word_error_rate"],0)
        self.assertEqual(same["rouge_l"]["f1"],1)
        error = text_metrics("W = mgh","W = mg")
        self.assertAlmostEqual(error["character_error_rate"],1/7)
        self.assertAlmostEqual(error["word_error_rate"],1/3)
        self.assertIsNone(text_metrics("","text")["character_error_rate"])
        self.assertEqual(text_metrics("abc","xxxxxxxxx")["character_error_rate"],3)

    def test_large_text_comparison_rejected_instead_of_unbounded_cpu(self):
        with self.assertRaises(ValueError): text_metrics("a"*3000,"b"*3000)


class SavedEvidenceMetricTests(unittest.TestCase):
    setUp = review_fixtures.ReviewReasonTests.setUp
    tearDown = review_fixtures.ReviewReasonTests.tearDown

    def test_saved_metrics_use_historical_max_and_report_unknown_cost(self):
        self.run.latency_ms = 1200
        self.run.response_json = {"grading_package":{"student_evidence":[{"id":"source:1","kind":"ocr_segment"}],
            "answer_key":{"reference_id":"key:1","mode":"reference"},"policy":{},"course_references":{"passages":[]}}}
        self.run.criteria_scores = [{"criterion_id":"c","points_earned":2,"max_points":3,"evidence_refs":["source:1"],"reference_refs":["key:invented"]}]
        self.db.add(ReviewLabel(answer_id=self.answer.id,grading_run_id=self.run.id,ai_score_snapshot=2,human_score=3,
            was_review_warranted=True,review_reason_codes=["unsupported_deduction","evidence_citation_error"]))
        self.question.max_score = 100  # Must not rescale historical predictions.
        self.db.commit()
        report = build_evaluation_report(self.db,institution_id="institution-1")
        self.assertEqual(report["overall"]["normalized_mae"],.3333)
        self.assertEqual(report["instructor_error_annotations"]["unsupported_deduction_count"],1)
        diagnostic = report["saved_run_diagnostics"]
        self.assertEqual(diagnostic["student_citation_coverage"],1)
        self.assertEqual(diagnostic["invalid_reference_count"],1)
        self.assertEqual(diagnostic["performance"][0]["median_latency_ms"],1200)
        self.assertIsNone(diagnostic["performance"][0]["reported_cost_usd"])
        self.assertEqual(build_evaluation_report(self.db,institution_id="other")["saved_run_diagnostics"]["run_count"],0)

    def test_combined_text_plus_tracked_segment_is_a_valid_citation(self):
        self.run.response_json = {"grading_package":{"student_evidence":[{"id":"source:1","kind":"ocr_segment"},
            {"id":"answer:text","kind":"combined_ocr"}],"answer_key":{"reference_id":"key:1","mode":"reference"},"policy":{}},
            "inference":{"provider":"openrouter_free","reported_cost_usd":0}}
        self.run.criteria_scores = [{"criterion_id":"c","evidence_refs":["answer:text","source:1"],"reference_refs":["key:1"]}]
        self.db.commit()
        diagnostic = build_evaluation_report(self.db,institution_id="institution-1")["saved_run_diagnostics"]
        self.assertEqual(diagnostic["invalid_reference_count"],0)
        self.assertEqual(diagnostic["student_citation_coverage"],1)
        self.assertEqual(diagnostic["performance"][0]["reported_cost_usd"],0)


if __name__ == "__main__": unittest.main()
