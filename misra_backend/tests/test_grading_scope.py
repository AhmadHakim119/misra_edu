import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from models import Answer, AnswerSource, ProcessingJob, Question, ReviewLabel, User
from tests import test_grade_exports as fixtures
from services.grade_export_service import build_grade_export, build_csv, build_export_preflight
from services.grading_package_service import build_grading_package
from services.extraction_review_service import build_extraction_review
from services.evaluation_service import build_evaluation_report
from services.job_execution_service import _grade_submission
from schemas.grading_input import GradeRequest
from schemas.rubric_v2 import RubricPolicy
from routers.grading import grading_endpoint


class GradingScopeTests(unittest.TestCase):
    setUp = fixtures.GradeExportTests.setUp
    tearDown = fixtures.GradeExportTests.tearDown

    def add_external(self):
        question = Question(id="practical", institution_id="institution-1", exam_id="exam-1",
            question_number="2", question_text="Upload your notebook to the LMS", max_score=10,
            rubric_json={"max_score": 10, "criteria": [{"id": "practical", "points": 10, "description": "Externally assessed implementation"}], "policy": {"assessment_scope": "external"}}, order_index=2, language="en")
        answer = Answer(id="external-answer", institution_id="institution-1", submission_id="submission-1",
            question_id=question.id, score=0, max_score=10, needs_review=True, review_status="pending")
        self.db.add_all([question, answer])
        self.db.commit()
        return question, answer

    def test_scope_defaults_and_rejects_unknown_values(self):
        self.assertEqual(RubricPolicy().assessment_scope, "paper")
        with self.assertRaises(ValueError):
            RubricPolicy(assessment_scope="guess")

    def test_catalog_does_not_count_external_review_flags(self):
        from routers.exams import list_exams
        self.add_external()
        user = User(institution_id="institution-1", role="instructor")
        exam = next(item for item in list_exams(self.db, user) if item["id"] == "exam-1")
        self.assertEqual(exam["question_count"], 2)
        self.assertEqual(exam["review_count"], 0)

    def test_external_marks_not_zero_or_full_exam_export(self):
        _, answer = self.add_external()
        export = build_grade_export("exam-1", "institution-1", self.db)
        self.assertEqual(export.rows[0]["score"], 8)
        self.assertEqual(export.rows[0]["max_score"], 10)
        self.assertTrue(export.rows[0]["ready_for_lms"])
        self.assertIn("Paper component only", build_csv(export, "blackboard", "student_number")[0].decode("utf-8-sig"))
        self.assertEqual(build_export_preflight(export, "student_number")["grading_scope"]["external_question_numbers"], ["2"])
        self.assertEqual(self.db.get(Answer, answer.id).score, 0)  # Historical evidence not erased.

    def test_readiness_ignores_external_question_without_source(self):
        self.add_external()
        self.db.add(AnswerSource(id="source", answer_id="answer-1",
            page_index=0, segment_index=0, question_number="1", extracted_text="Synthetic work", ocr_segment={}))
        self.db.commit()
        report = build_extraction_review("submission-1", self.db)
        self.assertEqual(report["readiness"]["expected_question_count"], 1)
        self.assertTrue(report["readiness"]["bulk_grading_allowed"])
        self.assertEqual(len(report["external_questions"]), 1)

    def test_external_is_blocked_at_api_and_package_before_provider(self):
        question, answer = self.add_external()
        user = self.db.get(User, "teacher-1")
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(grading_endpoint(answer.id, GradeRequest(mode="auto"), self.db, user))
        self.assertEqual(caught.exception.status_code, 409)
        with self.assertRaisesRegex(ValueError, "outside MISRA"):
            build_grading_package(answer, question, self.db, "text_only")

    def test_worker_does_not_grade_external_and_counts_only_paper(self):
        self.add_external()
        job = ProcessingJob(id="job", institution_id="institution-1", submission_id="submission-1",
            job_type="grade_submission", payload={"mode": "auto"})
        self.db.add(job)
        self.db.commit()
        with patch("services.job_execution_service.process_grading_with_policy") as grade:
            _grade_submission(job, self.db)
        self.assertEqual(grade.call_count, 1)
        self.assertEqual(grade.call_args.args[0], "answer-1")
        self.assertEqual(job.progress_total, 1)

    def test_evaluation_discloses_external_exclusion_and_never_uses_mutable_criteria(self):
        _, external = self.add_external()
        paper = self.db.get(Answer, "answer-1")
        paper.criteria_scores = [{"criterion_id": "method", "points_earned": 10}]
        self.db.add_all([
            ReviewLabel(id="paper-label", answer_id=paper.id, ai_score_snapshot=8, human_score=9,
                human_criteria_scores=[{"criterion_id": "method", "points_earned": 10}],
                was_review_warranted=True, label_source="test"),
            ReviewLabel(id="external-label", answer_id=external.id, ai_score_snapshot=0, human_score=6,
                was_review_warranted=True, label_source="test")])
        self.db.commit()
        report = build_evaluation_report(self.db, institution_id="institution-1", exam_id="exam-1")
        self.assertEqual(report["overall"]["mae"], 1)
        self.assertEqual(report["unique_answer_count"], 1)
        self.assertEqual(report["excluded_external_labels"][0]["review_label_id"], "external-label")
        self.assertEqual(report["criterion_level"], {})
        self.assertEqual(self.db.query(ReviewLabel).count(), 2)
