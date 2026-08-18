import os
import unittest
from unittest.mock import MagicMock, patch


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from routers.exams import _run_submission_in_background  # noqa: E402


class BackgroundUploadTests(unittest.TestCase):
    @patch("routers.exams.process_submission")
    @patch("routers.exams.SessionLocal")
    def test_background_submission_uses_and_closes_its_own_session(
        self,
        session_factory,
        process_submission,
    ):
        db = MagicMock()
        session_factory.return_value = db

        _run_submission_in_background("submission-1")

        process_submission.assert_called_once_with("submission-1", db)
        db.close.assert_called_once_with()

    @patch("routers.exams.logger")
    @patch("routers.exams.process_submission", side_effect=RuntimeError("OCR failed"))
    @patch("routers.exams.SessionLocal")
    def test_background_submission_logs_failure_and_still_closes_session(
        self,
        session_factory,
        process_submission,
        logger,
    ):
        db = MagicMock()
        session_factory.return_value = db

        _run_submission_in_background("submission-2")

        process_submission.assert_called_once_with("submission-2", db)
        logger.exception.assert_called_once()
        db.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
