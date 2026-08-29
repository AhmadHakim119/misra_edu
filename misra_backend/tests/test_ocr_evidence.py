import os
import unittest

from pydantic import ValidationError

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from services.ocr_service import OCRSegment


class OcrEvidenceTests(unittest.TestCase):
    def test_segment_accepts_normalized_evidence_box(self):
        segment = OCRSegment(
            question_number="2",
            text="SELECT * FROM COURSES",
            language="en",
            legibility="clear",
            has_math=False,
            bounding_box={"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.3},
        )
        self.assertEqual(segment.bounding_box.x, 0.1)

    def test_segment_rejects_box_outside_page(self):
        with self.assertRaises(ValidationError):
            OCRSegment(
                question_number="2",
                text="answer",
                language="en",
                legibility="clear",
                has_math=False,
                bounding_box={"x": 0.8, "y": 0.2, "width": 0.3, "height": 0.3},
            )


if __name__ == "__main__":
    unittest.main()
