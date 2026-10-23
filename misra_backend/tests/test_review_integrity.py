"""Applied decisions and stale writes, using only an isolated synthetic database."""
import unittest

from fastapi import HTTPException
from models import Answer, AuditLog, ReviewLabel
from routers.review_resolution import resolve_review, reopen_review
from schemas.public_results import AnswerRecord
from schemas.review_input import ReviewResolutionRequest, ReopenReviewRequest
from services.review_state_service import latest_operational_label, review_token
from tests import test_course_materials as fixtures


class ReviewIntegrityTests(unittest.TestCase):
    tearDown = fixtures.CourseMaterialTests.tearDown

    def setUp(self):
        fixtures.CourseMaterialTests.setUp(self)
        self.answer = self.db.get(Answer, 'a')
        self.answer.score = 1
        self.answer.max_score = 2
        self.answer.criteria_scores = [dict(criterion_id='work', points_earned=1, max_points=2)]
        self.db.commit()

    def request(self, score, **kwargs):
        return ReviewResolutionRequest(action='override', human_score=score,
            human_criteria_scores=[dict(criterion_id='work', points_earned=score, max_points=2)],
            was_review_warranted=True, review_reason_codes=['method_credit'], **kwargs)

    def save(self, score):
        return resolve_review('a', self.request(score, expected_review_token=review_token(self.answer)),
                              self.db, self.user)['review_label']

    def test_evaluation_only_label_cannot_replace_applied_criteria(self):
        applied = self.save(2)
        token = review_token(self.answer)
        evaluation = resolve_review('a', self.request(0, apply_as_current=False), self.db, self.user)['review_label']
        self.assertEqual(float(self.answer.teacher_override_score), 2)
        self.assertEqual(latest_operational_label(self.db, self.answer).id, applied.id)
        self.assertEqual(review_token(self.answer), token)
        self.assertNotEqual(applied.id, evaluation.id)
        self.assertEqual(self.db.query(ReviewLabel).count(), 2)
        # Pre-pointer records with explicit audit provenance remain recoverable.
        self.answer.grading_raw_response = {}
        self.db.commit()
        self.assertEqual(latest_operational_label(self.db, self.answer).id, applied.id)

    def test_ambiguous_legacy_label_is_not_presented_as_applied(self):
        self.db.add(ReviewLabel(answer_id='a', ai_score_snapshot=1, human_score=0,
                               was_review_warranted=True))
        self.db.commit()
        self.assertIsNone(latest_operational_label(self.db, self.answer))

    def test_stale_save_is_rejected_without_a_label_or_audit_write(self):
        stale = self.request(0, expected_review_token=review_token(self.answer))
        applied = self.save(2)
        counts = (self.db.query(ReviewLabel).count(), self.db.query(AuditLog).count())
        with self.assertRaises(HTTPException) as error:
            resolve_review('a', stale, self.db, self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(float(self.answer.teacher_override_score), 2)
        self.assertEqual(latest_operational_label(self.db, self.answer).id, applied.id)
        self.assertEqual(counts, (self.db.query(ReviewLabel).count(), self.db.query(AuditLog).count()))
        self.save(0)  # A refreshed decision can be saved.

    def test_same_score_same_timestamp_still_invalidates_token(self):
        self.save(2)
        token, reviewed_at = review_token(self.answer), self.answer.reviewed_at
        self.save(2)
        self.answer.reviewed_at = reviewed_at
        self.db.commit()
        self.assertNotEqual(review_token(self.answer), token)

    def test_missing_token_rejected_and_public_token_matches_database(self):
        self.assertEqual(AnswerRecord.model_validate(self.answer).review_token, review_token(self.answer))
        with self.assertRaises(HTTPException) as error:
            resolve_review('a', self.request(2), self.db, self.user)
        self.assertEqual(error.exception.status_code, 409)

    def test_reopen_invalidates_previously_loaded_decision(self):
        applied = self.save(2)
        stale = self.request(0, expected_review_token=review_token(self.answer))
        reopen_review('a', ReopenReviewRequest(expected_reviewed_at=self.answer.reviewed_at,
            expected_label_id=applied.id, reason='Check the original'), self.db, self.user)
        with self.assertRaises(HTTPException) as error:
            resolve_review('a', stale, self.db, self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.answer.review_status, 'pending')
