"""Source-default precedence and historical integrity; isolated synthetic database."""
from copy import deepcopy
from unittest.mock import patch
import json
import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from models import AssessmentMaterialScopeVersion, QuestionMaterialScopeVersion, GradingRun
from schemas.course_materials import AssessmentMaterialScopeRequest, MaterialScopeRequest
from routers import course_materials as api
from services.material_retrieval_service import retrieve_for_question
from services.grading_service import process_grading
from scripts.upgrade_assessment_sources import upgrade
from tests import test_course_materials as fixtures


class AssessmentSourceTests(unittest.TestCase):
    setUp = fixtures.CourseMaterialTests.setUp
    tearDown = fixtures.CourseMaterialTests.tearDown
    material = fixtures.CourseMaterialTests.material
    scope = fixtures.CourseMaterialTests.scope
    result = fixtures.CourseMaterialTests.result

    def default(self, version=None, mode="required", approved=True):
        bindings = [{"version_id": version.id, "page_indices": [0]}] if version else []
        row = api.create_assessment_scope("e", AssessmentMaterialScopeRequest(mode=mode, bindings=bindings), self.db, self.user)
        if approved:
            api.approve_assessment_scope("e", row["id"], self.db, self.user)
        return row

    def test_default_draft_not_used_and_approved_inherited(self):
        _, version = self.material()
        draft = self.default(version, approved=False)
        self.assertEqual(retrieve_for_question(self.db, self.q, self.rubric)["status"], "not_configured")
        api.approve_assessment_scope("e", draft["id"], self.db, self.user)
        context = retrieve_for_question(self.db, self.q, self.rubric)
        self.assertEqual(context["scope_origin"], "assessment")
        self.assertEqual(context["scope_version_id"], draft["id"])
        self.assertEqual(context["status"], "retrieved")
        self.assertEqual(api.get_effective_scope("q", self.db, self.user)["origin"], "assessment")

    def test_pending_chapter_selection_is_draft_only_until_source_review(self):
        from schemas.course_materials import MaterialApprovalRequest
        from services.assessment_guide_service import review_guide
        from models import Exam
        _,active=self.material();old=self.default(active)
        material,pending=self.material(approved=False)
        binding={'version_id':pending.id,'page_indices':[0]}
        with self.assertRaises(HTTPException):
            api.create_assessment_scope('e',AssessmentMaterialScopeRequest(bindings=[binding]),self.db,self.user)
        draft=api.create_assessment_scope('e',AssessmentMaterialScopeRequest(bindings=[binding],allow_pending_sources=True),self.db,self.user)
        self.assertEqual(draft['status'],'draft')
        self.assertEqual(retrieve_for_question(self.db,self.q,self.rubric)['scope_version_id'],old['id'])
        with self.assertRaises(HTTPException):api.approve_assessment_scope('e',draft['id'],self.db,self.user)
        self.assertEqual(pending.status,'draft');self.assertEqual(pending.approved_page_indices,[])
        review=review_guide(self.db,self.db.get(Exam,'e'))
        self.assertFalse(review['can_approve']);self.assertTrue(any('source' in e.lower() for e in review['errors']))
        api.approve_version(material['id'],pending.id,MaterialApprovalRequest(page_indices=[0],confirm_content_reviewed=True),self.db,self.user)
        api.approve_assessment_scope('e',draft['id'],self.db,self.user)
        self.assertEqual(retrieve_for_question(self.db,self.q,self.rubric)['scope_version_id'],draft['id'])

    def test_pending_chapter_selection_checks_ownership_page_bounds_and_reading_state(self):
        _,version=self.material(approved=False)
        for binding in [{'version_id':version.id,'page_indices':[1]},{'version_id':'missing','page_indices':[0]}]:
            with self.assertRaises(HTTPException):
                api.create_assessment_scope('e',AssessmentMaterialScopeRequest(bindings=[binding],allow_pending_sources=True),self.db,self.user)
        _,foreign=self.material(course='c2',approved=False)
        with self.assertRaises(HTTPException):
            api.create_assessment_scope('e',AssessmentMaterialScopeRequest(bindings=[{'version_id':foreign.id,'page_indices':[0]}],allow_pending_sources=True),self.db,self.user)
        version.ingestion_status='queued';self.db.commit()
        with self.assertRaises(HTTPException):
            api.create_assessment_scope('e',AssessmentMaterialScopeRequest(bindings=[{'version_id':version.id,'page_indices':[0]}],allow_pending_sources=True),self.db,self.user)
        self.assertEqual(self.db.query(AssessmentMaterialScopeVersion).count(),0)

    def test_exception_disable_and_return_to_inherit(self):
        _, version = self.material()
        self.default(version)
        _, alternative = self.material(text="Work against gravity is force times lifting distance.")
        override = self.scope(alternative)
        self.assertEqual(retrieve_for_question(self.db, self.q, self.rubric)["scope_version_id"], override["id"])
        self.scope(alternative, mode="disabled", bindings=[])
        self.assertEqual(retrieve_for_question(self.db, self.q, self.rubric)["status"], "disabled")
        draft = api.create_scope("q", MaterialScopeRequest(mode="inherit"), self.db, self.user)
        api.approve_scope("q", draft["id"], self.db, self.user)
        context = retrieve_for_question(self.db, self.q, self.rubric)
        self.assertEqual(context["scope_origin"], "assessment")
        self.assertEqual(context["question_scope_version_id"], draft["id"])
        self.assertEqual(context["passages"][0]["material_version_id"], version.id)

    def test_unapproved_exception_does_not_shadow_default(self):
        _, version = self.material()
        self.default(version)
        api.create_scope("q", MaterialScopeRequest(mode="disabled"), self.db, self.user)
        self.assertEqual(retrieve_for_question(self.db, self.q, self.rubric)["scope_origin"], "assessment")

    def test_scope_tampering_is_rejected(self):
        _, version = self.material()
        row = self.default(version)
        scope = self.db.get(AssessmentMaterialScopeVersion, row["id"])
        scope.mode = "optional"
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "default changed"):
            retrieve_for_question(self.db, self.q, self.rubric)

    def test_cross_institution_and_course(self):
        _, version = self.material()
        row = self.default(version)
        for call in [lambda: api.list_assessment_scopes("e", self.db, self.other),
                     lambda: api.approve_assessment_scope("e", row["id"], self.db, self.other),
                     lambda: api.get_effective_scope("q", self.db, self.other)]:
            with self.assertRaises(HTTPException) as error:
                call()
            self.assertEqual(error.exception.status_code, 404)
        _, foreign = self.material(course="c2")
        with self.assertRaises(HTTPException) as error:
            self.default(foreign)
        self.assertEqual(error.exception.status_code, 422)

    def test_no_criterion_ids_in_defaults_or_inherit_bindings(self):
        with self.assertRaises(ValidationError):
            AssessmentMaterialScopeRequest(mode="inherit")
        with self.assertRaises(ValidationError):
            AssessmentMaterialScopeRequest(bindings=[{"version_id": "v", "page_indices": [0], "criterion_id": "work"}])
        with self.assertRaises(ValidationError):
            MaterialScopeRequest(mode="inherit", bindings=[{"version_id": "v", "page_indices": [0]}])

    def test_new_default_does_not_change_saved_run(self):
        _, version = self.material()
        first = self.default(version)
        with patch("services.grading_service.generate", return_value=json.dumps(self.result(["instructor:source:1"]))):
            process_grading("a", self.db)
        run = self.db.query(GradingRun).one()
        snapshot = deepcopy(run.response_json["grading_package"])
        self.assertEqual(snapshot["course_references"]["scope_version_id"], first["id"])
        self.default(mode="disabled")
        self.db.refresh(run)
        self.assertEqual(run.response_json["grading_package"], snapshot)
        self.assertEqual(retrieve_for_question(self.db, self.q, self.rubric)["status"], "disabled")

    def test_additive_upgrade_missing_table_legacy_and_idempotent(self):
        AssessmentMaterialScopeVersion.__table__.drop(self.engine)
        _, version = self.material()
        self.scope(version)
        self.assertEqual(retrieve_for_question(self.db, self.q, self.rubric)["scope_origin"], "question")
        with self.assertRaises(HTTPException) as error:
            api.list_assessment_scopes("e", self.db, self.user)
        self.assertEqual(error.exception.status_code, 503)
        upgrade(self.engine)
        upgrade(self.engine)
        self.assertEqual(len(api.list_assessment_scopes("e", self.db, self.user)["versions"]), 0)


if __name__ == "__main__":
    unittest.main()
