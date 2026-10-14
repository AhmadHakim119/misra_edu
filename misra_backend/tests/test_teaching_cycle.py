"""Synthetic lecture-to-assessment and descriptive feedback boundaries."""
import unittest
from copy import deepcopy

from fastapi import HTTPException
from models import Answer, Exam
from schemas.course_materials import MaterialScopeRequest, AssessmentMaterialScopeRequest
from schemas.source_question_drafts import SourceQuestionDraftRequest
from services.grading_package_service import build_grading_package, validate_evidence_references
from services.grading_service import GradingResult
from services.material_retrieval_service import retrieve_for_question
from services.learning_insights_service import learning_insights
from routers.results import assessment_learning_insights
import tests.test_course_materials as fixtures


class TeachingCycleTests(unittest.TestCase):
    setUp = fixtures.CourseMaterialTests.setUp
    tearDown = fixtures.CourseMaterialTests.tearDown
    material = fixtures.CourseMaterialTests.material
    scope = fixtures.CourseMaterialTests.scope

    def test_fourteen_chapters_fit_explicit_assessment_and_generation_scope(self):
        bindings = [{'version_id': 'v'+str(n), 'page_indices':[0]} for n in range(14)]
        self.assertEqual(len(AssessmentMaterialScopeRequest(mode='required',bindings=bindings).bindings),14)
        self.assertEqual(len(SourceQuestionDraftRequest(bindings=bindings,topic='Work').bindings),14)

    def test_required_source_citation_cannot_be_replaced_by_key(self):
        _, version = self.material()
        self.scope(version)
        pack, _, _, _ = build_grading_package(self.db.get(Answer,'a'),self.q,self.db,'text_only')
        pack['answer_key']['mode'] = 'reference'
        value = GradingResult.model_validate(dict(score=2,max_score=2,feedback='Correct',reasoning='Work',llm_confidence=95,
            criteria_scores=[dict(criterion_id='work',max_points=2,points_earned=2,feedback='Correct',
                evidence_refs=['source:seg'],reference_refs=[pack['answer_key']['reference_id']],policy_applied=[],uncertainties=[])]))
        with self.assertRaisesRegex(ValueError,'must cite an approved course passage'):
            validate_evidence_references(value,pack)
        value.criteria_scores[0].reference_refs.append(pack['course_references']['passages'][0]['id'])
        validate_evidence_references(value,pack)

    def test_required_unbound_criterion_stops_before_provider(self):
        _, version = self.material()
        rubric = deepcopy(self.rubric)
        rubric['criteria'].append({'id':'unbound','description':'Explain horizontal work','points':1})
        self.scope(version,bindings=[{'version_id':version.id,'page_indices':[0],'criterion_id':'work'}])
        with self.assertRaisesRegex(ValueError,'lacks relevant context'):
            retrieve_for_question(self.db,self.q,rubric)

    def graded_answer(self):
        _, version = self.material()
        self.scope(version)
        answer = self.db.get(Answer,'a')
        package, _, _, _ = build_grading_package(answer,self.q,self.db,'text_only')
        answer.score, answer.max_score = 1, 2
        answer.needs_review = True
        answer.grading_raw_response = {'grading_package':package}
        answer.criteria_scores = [dict(criterion_id='work',points_earned=1,max_points=2,
            reference_refs=[package['course_references']['passages'][0]['id']])]
        self.db.commit()
        return answer

    def test_feedback_counts_recorded_marks_not_ungraded_zero(self):
        data = learning_insights(self.db,self.db.get(Exam,'e'))
        self.assertEqual(data['questions'][0]['graded_count'],0)
        self.assertIsNone(data['questions'][0]['average_percent'])
        self.graded_answer()
        data = learning_insights(self.db,self.db.get(Exam,'e'))
        q = data['questions'][0]
        self.assertEqual(q['average_percent'],50)
        self.assertEqual(q['awaiting_review_count'],1)
        self.assertEqual(q['course_grounded_count'],1)
        self.assertEqual(q['criteria'][0]['partial_credit_count'],1)
        self.assertEqual(q['criteria'][0]['source_pages'][0]['title'],'Synthetic chapter')
        self.assertEqual(data['confidence_status'],'uncalibrated')

    def test_total_override_does_not_fake_criterion_improvement(self):
        answer = self.graded_answer()
        answer.teacher_override_score, answer.review_status = 2,'overridden'
        self.db.commit()
        q = learning_insights(self.db,self.db.get(Exam,'e'))['questions'][0]
        self.assertEqual(q['average_percent'],100)
        self.assertEqual(q['criteria'],[])
        self.assertEqual(q['criterion_override_excluded_count'],1)
        self.assertEqual(q['awaiting_review_count'],0)

    def test_external_work_excluded_and_tenant_access_denied(self):
        self.q.rubric_json = {'policy':{'assessment_scope':'external'}}
        self.db.commit()
        self.assertEqual(learning_insights(self.db,self.db.get(Exam,'e'))['questions'],[])
        with self.assertRaises(HTTPException) as error:
            assessment_learning_insights('e',self.db,self.other)
        self.assertEqual(error.exception.status_code,404)


if __name__ == '__main__':
    unittest.main()
