"""One explicit guide approval includes selected, readable source drafts."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from fastapi import HTTPException
from models import AnswerKeyVersion, AssessmentMaterialScopeVersion, Exam, MaterialVersion, RubricVersion
from routers.rubric_versions import AssessmentGuideApprovalRequest, approve_assessment_guide, review_assessment_guide
from schemas.course_materials import AssessmentMaterialScopeRequest
from services.assessment_source_service import save_default
from services.course_material_service import replace_page
from services.rubric_version_service import create_rubric_version
from tests import test_course_materials as fixtures


class CombinedGuideSourceTests(unittest.TestCase):
    setUp = fixtures.CourseMaterialTests.setUp
    tearDown = fixtures.CourseMaterialTests.tearDown
    material = fixtures.CourseMaterialTests.material

    def prepare(self):
        _, version = self.material(approved=False)
        scope = save_default(self.db, self.db.get(Exam, 'e'), AssessmentMaterialScopeRequest(
            mode='required', allow_pending_sources=True,
            bindings=[{'version_id':version.id, 'page_indices':[0]}]), self.user)
        rubric = deepcopy(self.rubric)
        rubric['criteria'][0]['title'] = 'Work calculation'
        draft = create_rubric_version(question=self.q, rubric_json=rubric, source='manual',
            change_summary='Synthetic combined approval', db=self.db)
        return version, scope, draft

    def approve(self, token, **kwargs):
        return approve_assessment_guide('e', AssessmentGuideApprovalRequest(
            review_token=token, confirm_reviewed=True, **kwargs), self.db, self.user)

    def test_review_plans_sources_without_approving_them(self):
        version, scope, _ = self.prepare()
        reviewed = review_assessment_guide('e', self.db, self.user)
        self.assertTrue(reviewed['can_approve'], reviewed['errors'])
        self.assertEqual(len(reviewed['source_approvals']), 1)
        plan = reviewed['source_approvals'][0]
        self.assertEqual(plan['version_id'], version.id)
        self.assertEqual(plan['page_indices'], [0])
        self.assertEqual(len(plan['content_sha256']), 64)
        self.assertEqual(version.status, 'draft')
        self.assertEqual(scope.status, 'draft')
        self.assertEqual(version.approved_page_indices, [])

    def test_explicit_combined_approval_publishes_sources_and_guide_once(self):
        version, scope, draft = self.prepare()
        reviewed = review_assessment_guide('e', self.db, self.user)
        with self.assertRaises(HTTPException) as error:
            self.approve(reviewed['review_token'])
        self.assertEqual(error.exception.status_code, 409)
        self.db.refresh(version)
        self.assertEqual(version.status, 'draft')
        result = self.approve(reviewed['review_token'], approve_selected_sources=True)
        for record in (version, scope, draft):
            self.db.refresh(record)
            self.assertEqual(record.status, 'approved')
        self.assertEqual(version.approved_page_indices, [0])
        self.assertEqual(version.approved_by, self.user.id)
        self.assertIn(version.id, result['approved_version_ids'])
        self.assertEqual(self.q.active_rubric_version_id, draft.id)

    def test_source_edit_invalidates_the_reviewed_content(self):
        version, scope, _ = self.prepare()
        reviewed = review_assessment_guide('e', self.db, self.user)
        replace_page(self.db, version, 0, 'Changed course explanation.', origin='instructor_corrected')
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            self.approve(reviewed['review_token'], approve_selected_sources=True)
        self.assertEqual(error.exception.status_code, 409)
        self.db.refresh(version); self.db.refresh(scope)
        self.assertEqual(version.status, 'draft')
        self.assertEqual(scope.status, 'draft')

    def test_late_guide_failure_rolls_back_source_approval(self):
        version, scope, draft = self.prepare()
        self.db.add(AnswerKeyVersion(question_id='q', version_number=1, mode='reference',
            reference_text='W = mgh', acceptable_answers=[], document_refs=[], status='draft'))
        self.db.commit()
        reviewed = review_assessment_guide('e', self.db, self.user)
        with patch('services.answer_key_service.approve_key', side_effect=ValueError('Synthetic late rejection')):
            with self.assertRaises(HTTPException):
                self.approve(reviewed['review_token'], approve_selected_sources=True)
        for record in (version, scope, draft):
            self.db.refresh(record)
            self.assertEqual(record.status, 'draft')
        self.assertEqual(version.approved_page_indices, [])
        self.assertEqual(self.q.active_rubric_version_id, 'r')

    def test_unreadable_pages_and_incomplete_ingestion_remain_blocked(self):
        version, _, _ = self.prepare()
        for ingestion, text in [('needs_transcription', ''), ('processing', 'Some readable text')]:
            with self.subTest(ingestion=ingestion):
                version.ingestion_status = ingestion
                replace_page(self.db, version, 0, text, origin='instructor_corrected')
                self.db.commit()
                reviewed = review_assessment_guide('e', self.db, self.user)
                self.assertFalse(reviewed['can_approve'])
                with self.assertRaises(HTTPException):
                    self.approve(reviewed['review_token'], approve_selected_sources=True)
                self.db.refresh(version)
                self.assertEqual(version.status, 'draft')

    def test_other_course_source_cannot_be_bundled(self):
        version, scope, _ = self.prepare()
        _, foreign = self.material(course='c2', approved=False)
        scope.bindings = [{'version_id':foreign.id, 'page_indices':[0]}]
        self.db.commit()
        reviewed = review_assessment_guide('e', self.db, self.user)
        self.assertFalse(reviewed['can_approve'])
        with self.assertRaises(HTTPException):
            self.approve(reviewed['review_token'], approve_selected_sources=True)
        self.db.refresh(foreign); self.db.refresh(version)
        self.assertEqual(foreign.status, 'draft')
        self.assertEqual(version.status, 'draft')
