"""Synthetic approval, retrieval and ingestion tests. No live provider/database."""
import asyncio
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
from fastapi import HTTPException
from pydantic import ValidationError
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile
from database import Base
from models import (Institution, User, Course, Exam, Question, RubricVersion, Submission, Answer,
                    AnswerSource, GradingRun, MaterialVersion, MaterialPage, MaterialChunk, ProcessingJob)
from routers import course_materials as api
from schemas.course_materials import MaterialTextRequest, MaterialApprovalRequest, MaterialScopeRequest, MaterialPageEdit
from services import course_material_service as service
from services.material_retrieval_service import retrieve_for_question, provider_sources, bm25_scores
from services.grading_package_service import build_grading_package, provider_grading_package, validate_evidence_references
from services.grading_service import GradingResult, process_grading
from scripts.upgrade_course_materials import upgrade


class CourseMaterialTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(id="u", institution_id="i", email="test@example.edu", hashed_password="unused", role="teacher")
        self.other = User(id="v", institution_id="j", email="other@example.edu", hashed_password="unused", role="teacher")
        self.rubric = {"max_score":2,"criteria":[{"id":"work","description":"Calculate work against gravity","points":2}]}
        self.q = Question(id="q", institution_id="i", exam_id="e", question_number="1", question_text="Calculate work lifting a mass",
                          max_score=2, rubric_json=deepcopy(self.rubric), order_index=0, active_rubric_version_id="r")
        self.db.add_all([Institution(id="i",name="Test"), Institution(id="j",name="Other"), self.user,self.other,
            Course(id="c",institution_id="i",teacher_id="u",course_code="TEST",title="Synthetic physics"),
            Course(id="c2",institution_id="i",teacher_id="u",course_code="OTHER",title="Other course"),
            Exam(id="e",institution_id="i",course_id="c",title="Synthetic exam"),self.q,
            RubricVersion(id="r",question_id="q",version_number=1,status="approved",rubric_json=deepcopy(self.rubric)),
            Submission(id="s",institution_id="i",exam_id="e",original_file_path="synthetic-missing.png",page_count=1),
            Answer(id="a",institution_id="i",submission_id="s",question_id="q",raw_ocr_text="W = mgh",ocr_legibility="clear"),
            AnswerSource(id="seg",answer_id="a",page_index=0,segment_index=0,extracted_text="W = mgh",ocr_segment={})])
        self.db.commit()
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.directory_patch = patch.object(service,"MATERIAL_DIR",self.directory)
        self.directory_patch.start()

    def tearDown(self):
        self.directory_patch.stop()
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def material(self, text="The work against gravity when lifting a mass is W = mgh.", course="c", approved=True):
        material = api.create_text(course, MaterialTextRequest(title="Synthetic chapter",text=text),self.db,self.user)
        version = self.db.get(MaterialVersion,material["versions"][0]["id"])
        if approved:
            api.approve_version(material["id"],version.id,MaterialApprovalRequest(page_indices=[0],confirm_content_reviewed=True),self.db,self.user)
        return material, version

    def scope(self, version, **kwargs):
        request = MaterialScopeRequest(**({"mode":"required","bindings":[{"version_id":version.id,"page_indices":[0]}]} | kwargs))
        draft = api.create_scope("q",request,self.db,self.user)
        api.approve_scope("q",draft["id"],self.db,self.user)
        return draft

    def result(self, refs):
        return {"score":2,"max_score":2,"feedback":"Correct","reasoning":"Meets criterion","llm_confidence":95,
            "criteria_scores":[{"criterion_id":"work","max_points":2,"points_earned":2,"feedback":"Correct work",
                "evidence_refs":["student:segment:1"],"reference_refs":refs,"policy_applied":[],"uncertainties":[]}]}

    def test_approval_versions_and_immutable_pages(self):
        material, version = self.material(approved=False)
        self.assertEqual(retrieve_for_question(self.db,self.q,self.rubric)["status"],"not_configured")
        self.scope_rejected(version)
        api.approve_version(material["id"],version.id,MaterialApprovalRequest(page_indices=[0],confirm_content_reviewed=True),self.db,self.user)
        page = self.db.query(MaterialPage).one()
        with self.assertRaises(HTTPException) as error:
            api.edit_page(material["id"],version.id,0,MaterialPageEdit(text="Changed",expected_text_sha256=page.text_sha256),self.db,self.user)
        self.assertEqual(error.exception.status_code,409)
        with self.assertRaises(ValueError): service.replace_page(self.db,version,0,"Changed",origin="test")
        next_version = service.new_version(self.db,self.db.get(service.CourseMaterial,material["id"]),self.user,
            media_type="text/plain",document_sha256=service.text_hash("New work"),page_count=1)
        service.replace_page(self.db,next_version,0,"New work",origin="instructor_text")
        next_version.ingestion_status = "ready"
        service.approve_material(self.db,next_version,MaterialApprovalRequest(page_indices=[0],confirm_content_reviewed=True),self.user)
        self.db.commit()
        self.assertEqual(version.status,"superseded")
        service.verify_approved_version(self.db,version)  # Explicit pinned versions remain usable.

    def scope_rejected(self, version):
        with self.assertRaises(HTTPException):
            api.create_scope("q",MaterialScopeRequest(bindings=[{"version_id":version.id,"page_indices":[0]}]),self.db,self.user)

    def test_draft_page_edit_optimistic_lock(self):
        material,version = self.material(approved=False)
        page = self.db.query(MaterialPage).one()
        original = page.text_sha256
        edit = MaterialPageEdit(text="Work W = mgh, checked against page",printed_page_label="196",expected_text_sha256=original)
        api.edit_page(material["id"],version.id,0,edit,self.db,self.user)
        with self.assertRaises(HTTPException) as error:
            api.edit_page(material["id"],version.id,0,edit,self.db,self.user)
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(page.printed_page_label,"196")
        self.assertEqual(page.origin,"instructor_corrected")

    def test_cross_institution_and_course_boundaries(self):
        material,version = self.material()
        for call in [lambda:api.list_materials("c",self.db,self.other),
                     lambda:api.get_pages(material["id"],version.id,0,10,self.db,self.other),
                     lambda:api.list_scopes("q",self.db,self.other)]:
            with self.assertRaises(HTTPException) as error: call()
            self.assertEqual(error.exception.status_code,404)
        _,other_course_version = self.material(course="c2")
        self.scope_rejected(other_course_version)
        self.assertEqual(self.db.query(Submission).count(),1)  # Reference creation never creates student work.

    def test_scoped_retrieval_aliases_and_snapshot(self):
        _,version = self.material()
        self.material(text="Unrelated secret source mentioning gravity. Must not retrieve.",course="c2")
        self.scope(version)
        context = retrieve_for_question(self.db,self.q,self.rubric)
        self.assertEqual(context["status"],"retrieved")
        self.assertEqual(len(context["passages"]),1)
        self.assertNotIn("Unrelated secret",json.dumps(context))
        safe,aliases = provider_sources(context)
        self.assertNotIn(version.id,json.dumps(safe))
        self.assertEqual(list(aliases),["instructor:source:1"])
        self.assertNotIn("W = mgh",context["queries"][0]["query"])  # Query is not constructed from student text.
        with patch("services.grading_service.generate",return_value=json.dumps(self.result(["instructor:source:1"]))):
            process_grading("a",self.db)
        run = self.db.query(GradingRun).one()
        snapshot = deepcopy(run.response_json["grading_package"])
        self.assertEqual(run.criteria_scores[0]["reference_refs"],[context["passages"][0]["id"]])
        self.q.question_text = "Changed task"
        self.db.commit()
        self.assertEqual(self.db.query(GradingRun).one().response_json["grading_package"],snapshot)

    def test_missing_required_source_citation_fails_without_saving_a_grade(self):
        _,version = self.material()
        self.scope(version)
        with patch("services.grading_service.generate",return_value=json.dumps(self.result([]))) as generate:
            with self.assertRaisesRegex(ValueError,'No grade was saved'):
                process_grading("a",self.db)
        self.assertEqual(generate.call_count,2)  # one bounded citation correction
        self.assertEqual(self.db.query(GradingRun).count(),0)
        self.assertIsNone(self.db.get(Answer,'a').score)

    def test_tampered_page_and_scope_fail_before_inference(self):
        _,version = self.material()
        self.scope(version)
        page = self.db.query(MaterialPage).one()
        page.text += " Changed"
        self.db.flush()
        with patch("services.grading_service.generate") as generate:
            with self.assertRaisesRegex(ValueError,"integrity"):
                process_grading("a",self.db)
            generate.assert_not_called()
        self.db.rollback()
        scope = self.db.query(service.QuestionMaterialScopeVersion).one()
        scope.mode = "optional"
        self.db.flush()
        with self.assertRaisesRegex(ValueError,"scope changed"):
            retrieve_for_question(self.db,self.q,self.rubric)

    def test_exact_passage_and_required_empty_retrieval(self):
        _,version = self.material(text="zyxwvu, an intentionally nonmatching passage")
        self.scope(version)
        with self.assertRaisesRegex(ValueError,"lacks relevant context"):
            retrieve_for_question(self.db,self.q,self.rubric)
        chunk = self.db.query(MaterialChunk).filter_by(version_id=version.id).one()
        self.scope(version,bindings=[{"version_id":version.id,"page_indices":[0],"chunk_ids":[chunk.id],"criterion_id":"work"}])
        context = retrieve_for_question(self.db,self.q,self.rubric)
        self.assertEqual(context["passages"][0]["selection"],"exact_link")

    def test_invented_or_wrong_criterion_citations_rejected(self):
        _,version = self.material()
        self.scope(version)
        package,*_ = build_grading_package(self.db.get(Answer,"a"),self.q,self.db,"text_only")
        safe,aliases,*_ = provider_grading_package(package)
        result = GradingResult(**self.result(["material:invented"]))
        result.criteria_scores[0].evidence_refs = ["source:seg"]
        with self.assertRaises(ValueError): validate_evidence_references(result,package)
        result.criteria_scores[0].reference_refs = [package["course_references"]["passages"][0]["id"]]
        package["course_references"]["passages"][0]["criterion_ids"] = ["another"]
        with self.assertRaises(ValueError): validate_evidence_references(result,package)

    def upload_pdf(self):
        stream = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100,height=100)
        writer.write(stream)
        stream.seek(0)
        with patch.object(api,"dispatch_processing_job"):
            result = asyncio.run(api.upload_material("c",UploadFile(filename="chapter.pdf",file=stream),"Chapter",self.db,self.user))
        version = self.db.get(MaterialVersion,result["versions"][0]["id"])
        return version,self.db.get(ProcessingJob,version.processing_job_id)

    def test_ingestion_retry_idempotent_and_blank_page_not_approved(self):
        version,job = self.upload_pdf()
        service.ingest_material_job(job,self.db,lambda *args:None)
        self.db.commit()
        self.assertEqual(version.ingestion_status,"needs_transcription")
        with self.assertRaises(ValueError):
            service.approve_material(self.db,version,MaterialApprovalRequest(page_indices=[0],confirm_content_reviewed=True),self.user)
        service.ingest_material_job(job,self.db,lambda *args:None)
        self.assertEqual(self.db.query(MaterialPage).filter_by(version_id=version.id).count(),1)
        self.assertEqual(self.db.query(MaterialChunk).filter_by(version_id=version.id).count(),0)
        job.payload = dict(job.payload,course_id="c2")
        with self.assertRaisesRegex(ValueError,"does not match"):
            service.ingest_material_job(job,self.db,lambda *args:None)

    def test_invalid_pdf_cleanup_and_missing_document(self):
        with self.assertRaises(HTTPException):
            asyncio.run(api.upload_material("c",UploadFile(filename="bad.pdf",file=io.BytesIO(b"%PDF-broken")),None,self.db,self.user))
        self.assertEqual(list(self.directory.iterdir()),[])
        self.assertEqual(self.db.query(ProcessingJob).count(),0)
        version,job = self.upload_pdf()
        Path(version.original_file_path).unlink()
        with self.assertRaisesRegex(ValueError,"missing"):
            service.ingest_material_job(job,self.db,lambda *args:None)

    def test_contract_confirmation_and_page_indices(self):
        for payload in [{"page_indices":[0]}, {"page_indices":[True],"confirm_content_reviewed":True},
                        {"page_indices":[0,0],"confirm_content_reviewed":True}]:
            with self.assertRaises(ValidationError): MaterialApprovalRequest(**payload)
        with self.assertRaises(ValidationError): MaterialScopeRequest(mode="disabled",bindings=[{"version_id":"v","page_indices":[0]}])
        with self.assertRaises(ValidationError): MaterialTextRequest(title="  ",text="hello")

    def test_schema_upgrade_idempotent(self):
        upgrade(self.engine)
        upgrade(self.engine)
        self.assertTrue(service.schema_available(self.db))

    def test_partial_schema_never_silently_disables_retrieval(self):
        self.db.close()
        MaterialChunk.__table__.drop(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        with self.assertRaisesRegex(ValueError,"schema is incomplete"):
            retrieve_for_question(self.db,self.db.get(Question,"q"),self.rubric)

    def test_wrong_tenant_job_and_changed_document_are_rejected(self):
        version,job = self.upload_pdf()
        job.institution_id = "j"
        with self.assertRaisesRegex(ValueError,"workspace"):
            service.ingest_material_job(job,self.db,lambda *args:None)
        job.institution_id = "i"
        Path(version.original_file_path).write_bytes(b"synthetic tampering")
        with self.assertRaisesRegex(ValueError,"changed"):
            service.ingest_material_job(job,self.db,lambda *args:None)

    def test_durable_worker_completes_material_job_without_provider_or_submission(self):
        from services.job_execution_service import execute_processing_job
        from routers.jobs import _workspace_job
        version,job = self.upload_pdf()
        # Use a fresh isolated session just as the actual worker does.
        factory = sessionmaker(bind=self.engine)
        with patch("services.job_execution_service.SessionLocal",factory),patch("services.gemini_client.generate") as generate:
            execute_processing_job(job.id)
            generate.assert_not_called()
        self.db.expire_all()
        self.assertEqual(self.db.get(ProcessingJob,job.id).status,"completed")
        self.assertEqual(self.db.get(MaterialVersion,version.id).ingestion_status,"needs_transcription")
        context = _workspace_job(self.db.get(ProcessingJob,job.id),self.db)
        self.assertEqual(context["course_id"],"c")
        self.assertEqual(context["material_title"],"Chapter")
        self.assertNotIn("original_file_path",context)
        self.assertEqual(self.db.query(Submission).count(),1)

    def test_bm25_unicode_and_empty_inputs(self):
        self.assertEqual(bm25_scores([],"work"),[])
        scores = bm25_scores(["الطاقة الشغل","unrelated"],"الشغل")
        self.assertGreater(scores[0],scores[1])


if __name__ == "__main__": unittest.main()
