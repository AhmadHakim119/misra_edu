"""Synthetic source-generation contracts; no live provider, Redis or private files."""
import json
import os
import unittest
from copy import deepcopy
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
from database import Base
from models import (Institution, User, Course, Exam, Question, RubricVersion, AnswerKeyVersion,
                    QuestionMaterialScopeVersion, MaterialVersion, MaterialPage, ProcessingJob, Submission)
from routers import course_materials as material_api, exam_setup as setup_api
from schemas.course_materials import MaterialTextRequest, MaterialApprovalRequest
from schemas.source_question_drafts import SourceQuestionDraftRequest
from services.exam_setup_service import ConfirmImport, extract_setup_documents
from services.free_model_gateway import FreeCompletion
from services.source_question_draft_service import generate_source_questions


class SourceQuestionDraftTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://"); Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(id="u", institution_id="i", email="test@example.edu", hashed_password="unused", role="teacher")
        self.other = User(id="other", institution_id="j", email="other@example.edu", hashed_password="unused", role="teacher")
        self.db.add_all([Institution(id="i",name="Test"), Institution(id="j",name="Other"), self.user,self.other,
            Course(id="c",institution_id="i",teacher_id="u",course_code="TEST",title="Synthetic physics"),
            Course(id="c2",institution_id="i",teacher_id="u",course_code="OTHER",title="Other course"),
            Exam(id="e",institution_id="i",course_id="c",title="Synthetic exam")]); self.db.commit()
        created = material_api.create_text("c", MaterialTextRequest(title="Synthetic energy chapter",
            text="The work done against gravity is W = mgh. Work is measured in joules."), self.db,self.user)
        self.version_id = created["versions"][0]["id"]
        material_api.approve_version(created["id"],self.version_id,
            MaterialApprovalRequest(page_indices=[0],confirm_content_reviewed=True),self.db,self.user)
        self.request = SourceQuestionDraftRequest(bindings=[dict(version_id=self.version_id,page_indices=[0])],
                                                   topic="Work against gravity",count=1,points_per_question=2)

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def queue(self, user=None):
        with patch("routers.exam_setup.dispatch_processing_job"):
            data = setup_api.draft_source_questions("e",self.request,self.db,user or self.user)
        return self.db.get(ProcessingJob,data["job"]["id"])

    def proposal(self):
        citation = dict(source_ref="source:1",quote="W = mgh")
        return dict(questions=[dict(question_text="Calculate the work lifting a 2 kg mass through 3 m. Use g = 10 m/s².",
            answer_mode="reference",answer_key="W = mgh = 2 × 10 × 3 = 60 J.",
            criteria=[dict(title="Method",description="Use W = mgh",points=1,citations=[citation]),
                      dict(title="Result",description="Calculate 60 J including units",points=1,citations=[citation])],
            citations=[citation])],warnings=[])

    def generate(self, job=None, output=None):
        job = job or self.queue()
        response = FreeCompletion(json.dumps(output or self.proposal()),dict(provider="synthetic-free",reported_cost_usd=0,latency_ms=3))
        with patch("services.source_question_draft_service.complete_free",return_value=response) as provider:
            extract_setup_documents(job,self.db,lambda *args:self.db.commit())
        job.status = "completed"; self.db.commit()
        return job, provider

    def reviewed(self, job, **changes):
        raw = job.payload["draft_questions"][0]
        values = {key:raw[key] for key in ("source_draft_id","question_number","question_text","max_score","marking_guide","answer_key")}
        return ConfirmImport(questions=[{**values,**changes}])

    def test_request_is_durable_deduplicated_and_not_a_submission(self):
        first = self.queue(); second = self.queue()
        self.assertEqual(first.id,second.id)
        self.assertEqual(self.db.query(Submission).count(),0)
        self.assertEqual(self.db.query(Question).count(),0)
        self.assertNotIn("original_file_path",json.dumps(setup_api.public_import(first),default=str))

    def test_source_generation_is_not_available_across_institutions(self):
        with self.assertRaises(HTTPException) as error: self.queue(self.other)
        self.assertEqual(error.exception.status_code,404)

    def test_draft_or_foreign_course_material_is_rejected_before_queueing(self):
        version = self.db.get(MaterialVersion,self.version_id)
        version.status = "draft"; self.db.commit()
        with self.assertRaises(HTTPException): self.queue()
        self.assertEqual(self.db.query(ProcessingJob).count(),0)
        version.status = "approved"
        from models import CourseMaterial
        self.db.get(CourseMaterial,version.material_id).course_id = "c2"; self.db.commit()
        with self.assertRaises(HTTPException): self.queue()

    def test_generation_saves_traceable_drafts_without_creating_questions(self):
        job, provider = self.generate()
        provider.assert_called_once()
        self.assertEqual(self.db.query(Question).count(),0)
        payload = job.payload
        self.assertEqual(payload["source_package"]["passages"][0]["version_id"],self.version_id)
        self.assertEqual(payload["draft_questions"][0]["citations"][0]["quote"],"W = mgh")
        self.assertEqual(len(payload["draft_snapshot_sha256"]),64)
        with patch("services.source_question_draft_service.complete_free") as retry:
            generate_source_questions(job,self.db,lambda *args:None)
            retry.assert_not_called()

    def test_confirmation_creates_separate_unapproved_foundations_and_is_idempotent(self):
        job,_ = self.generate()
        request = self.reviewed(job)
        first = setup_api.confirm("e",job.id,request,self.db,self.user)
        second = setup_api.confirm("e",job.id,request,self.db,self.user)
        self.assertEqual(first["question_ids"],second["question_ids"])
        self.assertEqual(self.db.query(Question).count(),1)
        self.assertEqual(self.db.query(Question).one().language,"en")
        self.assertEqual(self.db.query(RubricVersion).one().status,"draft")
        self.assertEqual(len(self.db.query(RubricVersion).one().rubric_json["criteria"]),2)
        self.assertEqual(self.db.query(AnswerKeyVersion).one().status,"draft")
        scope = self.db.query(QuestionMaterialScopeVersion).one()
        self.assertEqual(scope.status,"draft")
        self.assertEqual(scope.bindings[0]["version_id"],self.version_id)
        self.assertEqual(job.payload["imported_source_drafts"][0]["question_id"],first["question_ids"][0])
        self.assertEqual(job.payload["imported_source_drafts"][0]["source_draft_id"],request.questions[0].source_draft_id)

    def test_unknown_draft_id_cannot_import_arbitrary_questions(self):
        job,_ = self.generate()
        with self.assertRaises(HTTPException):
            setup_api.confirm("e",job.id,self.reviewed(job,source_draft_id="invented"),self.db,self.user)
        self.assertEqual(self.db.query(Question).count(),0)

    def test_wrong_scores_count_or_citations_save_no_proposals(self):
        for scenario in ("scores","quote","source","count"):
            with self.subTest(scenario=scenario):
                job = self.queue()
                output = self.proposal()
                if scenario == "scores": output["questions"][0]["criteria"][0]["points"] = 2
                if scenario == "quote": output["questions"][0]["citations"][0]["quote"] = "Fabricated quotation"
                if scenario == "source": output["questions"][0]["citations"][0]["source_ref"] = "unknown"
                if scenario == "count": output["questions"].append(deepcopy(output["questions"][0]))
                with self.assertRaises(ValueError): self.generate(job,output)
                self.db.rollback(); self.db.refresh(job)
                self.assertFalse(job.payload.get("draft_questions"))
                self.assertEqual(self.db.query(Question).count(),0)

    def test_changed_approved_content_is_rejected_on_execution(self):
        job = self.queue()
        page = self.db.query(MaterialPage).one(); page.text = "Unexpected replacement"; self.db.commit()
        with patch("services.source_question_draft_service.complete_free") as provider:
            with self.assertRaises(ValueError): generate_source_questions(job,self.db,lambda *args:None)
            provider.assert_not_called()

    def test_changed_snapshot_is_rejected_before_confirmation(self):
        job,_ = self.generate()
        payload = deepcopy(job.payload); payload["draft_questions"][0]["answer_key"] = "Changed"
        job.payload = payload; self.db.commit()
        with self.assertRaises(HTTPException):
            setup_api.confirm("e",job.id,self.reviewed(job),self.db,self.user)
        self.assertEqual(self.db.query(Question).count(),0)

    def test_reviewed_marking_changes_are_not_silently_replaced_by_model_criteria(self):
        job,_ = self.generate()
        setup_api.confirm("e",job.id,self.reviewed(job,marking_guide="Instructor revised criterion",max_score=3),self.db,self.user)
        rubric = self.db.query(RubricVersion).one().rubric_json
        self.assertEqual(rubric["max_score"],3)
        self.assertEqual(len(rubric["criteria"]),1)
        self.assertEqual(rubric["criteria"][0]["description"],"Instructor revised criterion")

    def test_source_request_marks_do_not_round_silently_in_database(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SourceQuestionDraftRequest(**{**self.request.model_dump(),"points_per_question":2.005})
