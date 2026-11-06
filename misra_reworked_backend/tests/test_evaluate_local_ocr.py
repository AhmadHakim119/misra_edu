import unittest

from evaluate_local_ocr import OcrReference, edit_distance, evaluate, normalize, transcription_metrics
from local_ocr import Extraction


class OcrEvaluationTests(unittest.TestCase):
    def test_errors_include_negation_operators_case_and_arabic(self):
        self.assertGreater(transcription_metrics("لا تجمع", "تجمع")["wer"], 0)
        self.assertGreater(transcription_metrics("2 + 3", "2 x 3")["cer"], 0)
        self.assertGreater(transcription_metrics("246 J", "246 j")["cer"], 0)
        self.assertEqual(normalize("a\n  b"), "a b")

    def test_identity_and_complete_miss_and_insertions(self):
        self.assertEqual(transcription_metrics("الشغل", "الشغل")["cer"], 0)
        missing = transcription_metrics("abc", "")
        self.assertEqual(missing["cer"], 1)
        self.assertEqual(missing["wer"], 1)
        self.assertGreater(transcription_metrics("a", "a b c")["wer"], 1)
        self.assertEqual(edit_distance("abc", "adc"), 1)
        with self.assertRaises(ValueError):
            transcription_metrics(" ", "a")

    def test_manual_answer_region_excludes_header_even_when_it_has_expected_number(self):
        doc = Extraction.model_validate({"source_sha256": "a"*64, "config_sha256": "b"*64,
            "engine": "paddle", "pages": [{"number": 1, "width": 100, "height": 100,
                "image_sha256": "c"*64, "image": "pages/page-1.png", "issues": []}],
            "spans": [{"id": "p1_s1", "page": 1, "text": "246 J", "engine_confidence": 0.99,
                       "bbox": {"x0": 1,"y0": 1,"x1": 50,"y1": 10}},
                      {"id": "p1_s2", "page": 1, "text": "85 J", "engine_confidence": 0.99,
                       "bbox": {"x0": 1,"y0": 60,"x1": 50,"y1": 80}}], "review_reasons": []})
        ref = OcrReference(id="example", source_sha256="a"*64, kind="synthetic", reference_text="85 J", page=1,
                           region=[0.,0.5,1.,1.], literal_probes=["246", "85"])
        result = evaluate(doc, ref)
        self.assertEqual(result["selected_span_ids"], ["p1_s2"])
        self.assertFalse(result["literal_probe_presence"]["246"])
        self.assertTrue(result["literal_probe_presence"]["85"])
        self.assertTrue(result["needs_transcription_review"])
        with self.assertRaises(ValueError):
            evaluate(doc, ref.model_copy(update={"source_sha256": "f"*64}))


if __name__ == "__main__":
    unittest.main()
