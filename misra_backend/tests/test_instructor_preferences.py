import os
import unittest

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import (
    Answer,
    AuditLog,
    Course,
    Exam,
    GradingRun,
    Institution,
    InstructorPreferenceVersion,
    Question,
    ReviewLabel,
    RubricVersion,
    Submission,
    User,
)
from routers import instructor_preferences
from schemas.instructor_preferences import InstructorPreferenceDraftRequest


class InstructorPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(
            id="u1",
            institution_id="i1",
            email="teacher@example.edu",
            hashed_password="unused",
            role="teacher",
        )
        self.colleague = User(
            id="u2",
            institution_id="i1",
            email="admin@example.edu",
            hashed_password="unused",
            role="admin",
        )
        self.other_tenant = User(
            id="u3",
            institution_id="i2",
            email="other@example.edu",
            hashed_password="unused",
            role="teacher",
        )
        self.db.add_all(
            [
                Institution(id="i1", name="Institution One"),
                Institution(id="i2", name="Institution Two"),
                self.user,
                self.colleague,
                self.other_tenant,
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def payload(self, **changes):
        data = {
            "explicit_preferences": {
                "method_credit": "partial",
                "alternative_valid_methods": "allow",
            },
            "scenario_answers": [
                {
                    "scenario_id": "valid_alternative_method",
                    "selected_option": "full_credit",
                },
                {
                    "scenario_id": "minor_handwritten_syntax",
                    "selected_option": "minor_deduction",
                },
            ],
            "change_summary": "Synthetic calibration",
        }
        data.update(changes)
        return InstructorPreferenceDraftRequest(**data)

    def create(self, user=None, **changes):
        return instructor_preferences.create_version(
            self.payload(**changes), self.db, user or self.user
        )

    def review_label(
        self,
        suffix,
        reasons,
        *,
        labeled_by=None,
        institution_id="i1",
    ):
        submission = Submission(
            id=f"suggestion-submission-{suffix}",
            institution_id=institution_id,
            exam_id=f"suggestion-exam-{suffix}",
            original_file_path=f"synthetic-{suffix}.pdf",
            page_count=1,
            status="graded",
        )
        answer = Answer(
            id=f"suggestion-answer-{suffix}",
            institution_id=institution_id,
            submission_id=submission.id,
            question_id=f"suggestion-question-{suffix}",
            score=1,
            max_score=1,
        )
        label = ReviewLabel(
            id=f"suggestion-label-{suffix}",
            answer_id=answer.id,
            ai_score_snapshot=0,
            human_score=1,
            was_review_warranted=True,
            review_reason_codes=list(reasons),
            labeled_by=labeled_by or self.user.id,
            label_source="instructor_review",
        )
        self.db.add_all([submission, answer, label])
        self.db.flush()
        return label

    def test_proposal_and_provenance_are_deterministic_and_non_binding(self):
        created = self.create()
        self.assertEqual(created["derived_proposal"]["method_credit"], "partial")
        self.assertTrue(created["derived_proposal"]["alternative_methods_allowed"])
        self.assertEqual(
            created["derived_proposal"]["handwritten_syntax_policy"],
            "criterion_specific",
        )
        provenance = created["proposal_provenance"]["method_credit"]
        self.assertEqual(provenance["source"], "explicit_preference")
        self.assertEqual(provenance["preference_field"], "method_credit")
        self.assertEqual(provenance["derivation_version"], "v1")
        syntax_provenance = created["proposal_provenance"]["handwritten_syntax_policy"]
        self.assertEqual(syntax_provenance["scenario_id"], "minor_handwritten_syntax")
        self.assertFalse(created["applies_automatically"])
        event = self.db.query(AuditLog).filter(AuditLog.entity_id == created["id"]).one()
        self.assertEqual(event.action, "instructor_preference_draft_created")

    def test_draft_approval_history_and_approved_immutability(self):
        first = self.create()
        updated = instructor_preferences.update_version(
            first["id"],
            self.payload(
                explicit_preferences={"notation_policy": "equivalent_allowed"},
                change_summary="Updated draft",
            ),
            self.db,
            self.user,
        )
        self.assertEqual(updated["version_number"], 1)
        self.assertEqual(updated["explicit_preferences"]["notation_policy"], "equivalent_allowed")
        approved = instructor_preferences.approve_version(first["id"], self.db, self.user)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["approved_by"], self.user.id)

        with self.assertRaises(HTTPException) as immutable:
            instructor_preferences.update_version(
                first["id"], self.payload(), self.db, self.user
            )
        self.assertEqual(immutable.exception.status_code, 409)

        second = self.create(
            explicit_preferences={"method_credit": "full_if_valid"},
            scenario_answers=[],
        )
        instructor_preferences.approve_version(second["id"], self.db, self.user)
        versions = instructor_preferences.list_versions(self.db, self.user)
        self.assertEqual(
            [(version["version_number"], version["status"]) for version in versions],
            [(2, "approved"), (1, "superseded")],
        )

    def test_same_tenant_admin_and_cross_tenant_users_cannot_access_owner_version(self):
        created = self.create()
        for intruder in (self.colleague, self.other_tenant):
            with self.assertRaises(HTTPException) as hidden:
                instructor_preferences.update_version(
                    created["id"], self.payload(), self.db, intruder
                )
            self.assertEqual(hidden.exception.status_code, 404)
            with self.assertRaises(HTTPException) as approve_hidden:
                instructor_preferences.approve_version(created["id"], self.db, intruder)
            self.assertEqual(approve_hidden.exception.status_code, 404)
            self.assertEqual(instructor_preferences.list_versions(self.db, intruder), [])

    def test_approval_does_not_mutate_assessment_or_grading_history(self):
        course = Course(
            id="c1",
            institution_id="i1",
            teacher_id="u1",
            course_code="TEST",
            title="Synthetic Course",
        )
        exam = Exam(
            id="e1", institution_id="i1", course_id="c1", title="Synthetic Exam", language="en"
        )
        question = Question(
            id="q1",
            institution_id="i1",
            exam_id="e1",
            question_number="1",
            question_text="Synthetic question",
            max_score=2,
            rubric_json={"legacy": "unchanged"},
            order_index=1,
            language="en",
        )
        rubric = RubricVersion(
            id="r1",
            question_id="q1",
            version_number=1,
            schema_version=2,
            rubric_json={"snapshot": "unchanged"},
            grading_approach="balanced",
            source="manual",
            status="approved",
            created_by="u1",
            approved_by="u1",
        )
        submission = Submission(
            id="s1",
            institution_id="i1",
            exam_id="e1",
            original_file_path="synthetic.pdf",
            page_count=1,
            status="graded",
        )
        answer = Answer(
            id="a1", institution_id="i1", submission_id="s1", question_id="q1"
        )
        run = GradingRun(
            id="g1",
            answer_id="a1",
            rubric_version_id="r1",
            mode="text_only",
            model_name="mock",
            prompt_version="test",
            source_page_indices=[],
            ocr_text_snapshot="synthetic",
            rubric_snapshot={"snapshot": "unchanged"},
            score=2,
            max_score=2,
            feedback="synthetic",
            reasoning="synthetic",
            criteria_scores=[],
            llm_confidence=90,
            final_confidence=90,
            needs_review=False,
            response_json={"snapshot": "unchanged"},
        )
        self.db.add_all([course, exam, question, rubric, submission, answer, run])
        self.db.flush()
        question.active_rubric_version_id = rubric.id
        self.db.commit()

        before = {
            "question": dict(question.rubric_json),
            "active": question.active_rubric_version_id,
            "rubric": dict(rubric.rubric_json),
            "run": dict(run.response_json),
            "score": float(run.score),
        }
        created = self.create()
        instructor_preferences.approve_version(created["id"], self.db, self.user)
        self.db.refresh(question)
        self.db.refresh(rubric)
        self.db.refresh(run)
        after = {
            "question": dict(question.rubric_json),
            "active": question.active_rubric_version_id,
            "rubric": dict(rubric.rubric_json),
            "run": dict(run.response_json),
            "score": float(run.score),
        }
        self.assertEqual(after, before)

    def test_request_rejects_duplicate_unknown_and_empty_scenarios(self):
        duplicate = [
            {"scenario_id": "carried_forward_error", "selected_option": "single_penalty"},
            {"scenario_id": "carried_forward_error", "selected_option": "penalize_each"},
        ]
        with self.assertRaises(ValidationError):
            InstructorPreferenceDraftRequest(scenario_answers=duplicate)
        with self.assertRaises(ValidationError):
            InstructorPreferenceDraftRequest(
                scenario_answers=[
                    {
                        "scenario_id": "valid_alternative_method",
                        "selected_option": "invented",
                    }
                ]
            )
        with self.assertRaises(ValidationError):
            InstructorPreferenceDraftRequest()

    def test_criterion_specific_explicit_alternative_does_not_propose_global_boolean(self):
        created = self.create(
            explicit_preferences={"alternative_valid_methods": "criterion_specific"},
            scenario_answers=[
                {
                    "scenario_id": "valid_alternative_method",
                    "selected_option": "full_credit",
                }
            ],
        )
        self.assertNotIn("alternative_methods_allowed", created["derived_proposal"])
        self.assertNotIn("alternative_methods_allowed", created["proposal_provenance"])
        self.assertEqual(created["derived_proposal"]["method_credit"], "full_if_valid")

    def test_user_scoped_version_numbers_are_independent(self):
        first = self.create()
        colleague_first = self.create(user=self.colleague)
        self.assertEqual(first["version_number"], 1)
        self.assertEqual(colleague_first["version_number"], 1)
        self.assertEqual(self.db.query(InstructorPreferenceVersion).count(), 2)

    def test_repeated_decision_suggestions_require_three_distinct_labels(self):
        first = self.review_label(
            "threshold-1",
            ["minor_notation", "minor_notation", "ocr_or_mapping_error"],
        )
        second = self.review_label("threshold-2", ["minor_notation", "rubric_issue"])
        self.review_label("method-1", ["method_credit"])
        self.review_label("method-2", ["method_credit", "other"])
        self.db.commit()

        below = instructor_preferences.list_suggestions(self.db, self.user)
        self.assertEqual(below["suggestions"], [])
        self.assertEqual(
            below["excluded_reason_codes"],
            ["rubric_issue", "ocr_or_mapping_error", "other"],
        )
        third = self.review_label("threshold-3", ["minor_notation"])
        self.db.commit()

        result = instructor_preferences.list_suggestions(self.db, self.user)
        self.assertEqual(len(result["suggestions"]), 1)
        suggestion = result["suggestions"][0]
        self.assertEqual(suggestion["review_reason_code"], "minor_notation")
        self.assertEqual(suggestion["distinct_label_count"], 3)
        self.assertEqual(
            set(suggestion["source_label_ids"]), {first.id, second.id, third.id}
        )
        self.assertEqual(
            suggestion["proposed_policy"], {"notation_policy": "equivalent_allowed"}
        )
        self.assertFalse(suggestion["applies_automatically"])

    def test_repeated_decisions_are_scoped_to_current_user_and_institution(self):
        own = [
            self.review_label(f"scope-own-{index}", ["valid_alternative"])
            for index in range(2)
        ]
        for index in range(3):
            self.review_label(
                f"scope-colleague-{index}",
                ["valid_alternative"],
                labeled_by=self.colleague.id,
            )
            # Even a malformed cross-tenant row labeled by the current user is
            # excluded by answer/submission institution ownership.
            self.review_label(
                f"scope-tenant-{index}",
                ["valid_alternative"],
                labeled_by=self.user.id,
                institution_id="i2",
            )
        self.db.commit()
        self.assertEqual(
            instructor_preferences.list_suggestions(self.db, self.user)["suggestions"],
            [],
        )

        own.append(self.review_label("scope-own-2", ["valid_alternative"]))
        self.db.commit()
        suggestion = instructor_preferences.list_suggestions(
            self.db, self.user
        )["suggestions"][0]
        self.assertEqual(set(suggestion["source_label_ids"]), {label.id for label in own})

    def test_all_repeated_decision_mappings_are_exact_and_read_only(self):
        reason_codes = [
            "valid_alternative",
            "minor_notation",
            "method_credit",
            "carried_forward_error",
            "language_tolerance",
        ]
        for index in range(3):
            self.review_label(f"mapping-{index}", reason_codes)
        profile = self.create()
        self.db.commit()
        before_profile = dict(
            status=profile["status"],
            explicit_preferences=dict(profile["explicit_preferences"]),
            derived_proposal=dict(profile["derived_proposal"]),
        )
        before_counts = {
            "profiles": self.db.query(InstructorPreferenceVersion).count(),
            "questions": self.db.query(Question).count(),
            "rubrics": self.db.query(RubricVersion).count(),
            "runs": self.db.query(GradingRun).count(),
        }

        result = instructor_preferences.list_suggestions(self.db, self.user)
        actual = {
            item["review_reason_code"]: item["proposed_policy"]
            for item in result["suggestions"]
        }
        self.assertEqual(
            actual,
            {
                "valid_alternative": {"alternative_methods_allowed": True},
                "minor_notation": {"notation_policy": "equivalent_allowed"},
                "method_credit": {"method_credit": "partial"},
                "carried_forward_error": {"error_carried_forward": "single_penalty"},
                "language_tolerance": {
                    "language_quality_policy": "ignore_unless_assessed"
                },
            },
        )
        self.assertFalse(result["applies_automatically"])
        self.assertEqual(
            before_counts,
            {
                "profiles": self.db.query(InstructorPreferenceVersion).count(),
                "questions": self.db.query(Question).count(),
                "rubrics": self.db.query(RubricVersion).count(),
                "runs": self.db.query(GradingRun).count(),
            },
        )
        stored_profile = self.db.get(InstructorPreferenceVersion, profile["id"])
        self.assertEqual(stored_profile.status, before_profile["status"])
        self.assertEqual(stored_profile.explicit_preferences, before_profile["explicit_preferences"])
        self.assertEqual(stored_profile.derived_proposal, before_profile["derived_proposal"])


if __name__ == "__main__":
    unittest.main()
