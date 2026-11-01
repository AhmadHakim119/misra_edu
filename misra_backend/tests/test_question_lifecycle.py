"""Synthetic removal/restore, current scope and immutable-history regressions."""
from copy import deepcopy
import unittest
from fastapi import HTTPException
from models import Answer, AnswerSource, Exam, GradingRun, ProcessingJob, Question, RubricVersion, Submission
from routers.questions import question_removal_preview, change_question_lifecycle, list_exam_questions
from routers.results import exclude_extracted_source
from schemas.question_lifecycle import QuestionLifecycleRequest
from schemas.source_mapping_input import SourceExclusionRequest
from services.extraction_review_service import build_extraction_review
from services.assessment_readiness_service import assessment_readiness
from services.grade_export_service import build_grade_export
from services.rubric_version_service import get_effective_rubric
from tests import test_course_materials as fixtures


class QuestionLifecycleTests(unittest.TestCase):
    setUp=fixtures.CourseMaterialTests.setUp
    tearDown=fixtures.CourseMaterialTests.tearDown

    def change(self, action='remove', token=None):
        preview=question_removal_preview('q',action,self.db,self.user)
        return change_question_lifecycle('q',QuestionLifecycleRequest(action=action,
            review_token=token or preview['review_token'],confirm_reviewed=True),self.db,self.user)

    def another_question(self):
        other=Question(id='keep',institution_id='i',exam_id='e',question_number='2',question_text='Another question',
            max_score=2,rubric_json=deepcopy(self.rubric),order_index=1)
        self.db.add(other);self.db.commit();return other

    def test_remove_keeps_records_and_updates_current_counts_and_totals(self):
        self.another_question();before=deepcopy(self.db.get(RubricVersion,'r').rubric_json)
        preview=question_removal_preview('q','remove',self.db,self.user)
        self.assertEqual(preview['previous_total_marks'],4);self.assertEqual(preview['revised_total_marks'],2)
        self.change()
        self.assertIsNotNone(self.db.get(Question,'q'));self.assertIsNotNone(self.db.get(AnswerSource,'seg'))
        self.assertEqual(self.db.get(RubricVersion,'r').rubric_json,before)
        report=build_extraction_review('s',self.db)
        self.assertEqual([row['question']['id'] for row in report['questions']],['keep'])
        self.assertEqual(report['readiness']['missing_question_numbers'],['2'])
        self.assertEqual([q['id'] for q in report['removed_questions']],['q'])
        self.assertEqual(assessment_readiness(self.db,'e')['question_count'],1)
        self.assertEqual(build_grade_export('e','i',self.db).rows[0]['max_score'],2)
        self.assertEqual([q.id for q in list_exam_questions('e',self.db,self.user)],['keep'])
        with self.assertRaisesRegex(ValueError,'removed'):get_effective_rubric(self.q,self.db)

    def test_restore_reinstates_prior_authority_without_changing_other_drafts(self):
        other=self.another_question();draft=RubricVersion(id='pending',question_id=other.id,version_number=1,
            status='draft',rubric_json=deepcopy(self.rubric));self.db.add(draft);self.db.commit()
        self.change();self.change('restore')
        self.assertEqual(len(list_exam_questions('e',self.db,self.user)),2)
        self.assertEqual(self.db.get(RubricVersion,'pending').status,'draft')
        self.assertEqual(get_effective_rubric(self.q,self.db)[0]['criteria'],self.rubric['criteria'])

    def test_saved_grade_override_and_run_are_not_deleted_or_recalculated(self):
        self.another_question();answer=self.db.get(Answer,'a');answer.score=1;answer.teacher_override_score=1.5;answer.review_status='approved'
        run=GradingRun(id='historical',answer_id='a',rubric_version_id='r',mode='text_only',model_name='synthetic',
            prompt_version='test',ocr_text_snapshot='Original',rubric_snapshot=deepcopy(self.rubric),score=1,max_score=2,
            feedback='Old',reasoning='Old',criteria_scores=[],llm_confidence=40,final_confidence=40,needs_review=False,response_json={'old':True})
        self.db.add(run);self.db.commit();self.change();self.db.refresh(answer);self.db.refresh(run)
        self.assertEqual(float(answer.score),1);self.assertEqual(float(answer.teacher_override_score),1.5)
        self.assertEqual(run.response_json,{'old':True});self.assertTrue(answer.needs_review)

    def test_stale_preview_cross_institution_and_active_jobs_are_rejected(self):
        preview=question_removal_preview('q','remove',self.db,self.user)
        self.q.question_text='Changed after preview';self.db.commit()
        with self.assertRaises(HTTPException) as e:self.change(token=preview['review_token'])
        self.assertEqual(e.exception.status_code,409)
        with self.assertRaises(HTTPException) as e:question_removal_preview('q','remove',self.db,self.other)
        self.assertEqual(e.exception.status_code,404)
        self.db.add(ProcessingJob(id='active',institution_id='i',requested_by='u',job_type='grade_submission',status='queued',submission_id='s',payload={}))
        self.db.commit()
        with self.assertRaises(HTTPException) as e:question_removal_preview('q','remove',self.db,self.user)
        self.assertEqual(e.exception.status_code,409)

    def test_remove_one_source_keeps_exam_question_and_records_exclusion(self):
        self.db.get(Submission,'s').status='extracted';self.db.commit()
        source=build_extraction_review('s',self.db)['questions'][0]['sources'][0]
        report=exclude_extracted_source('seg',SourceExclusionRequest(review_token=source['removal_token'],confirm_reviewed=True),self.db,self.user)
        self.assertIsNotNone(self.db.get(Question,'q'));self.assertEqual(len(report['questions']),1)
        self.assertEqual(report['readiness']['missing_question_numbers'],['1'])
        self.assertEqual(report['excluded_segments'][0]['former_source_id'],'seg')
        self.assertEqual(report['excluded_segments'][0]['text'],'W = mgh')

    def test_stale_source_and_graded_source_cannot_be_excluded(self):
        source=build_extraction_review('s',self.db)['questions'][0]['sources'][0]
        self.db.get(AnswerSource,'seg').extracted_text='Changed';self.db.commit()
        with self.assertRaises(HTTPException) as e:exclude_extracted_source('seg',SourceExclusionRequest(review_token=source['removal_token'],confirm_reviewed=True),self.db,self.user)
        self.assertEqual(e.exception.status_code,409);self.assertIsNotNone(self.db.get(AnswerSource,'seg'))
        self.db.get(Answer,'a').score=0;self.db.commit()
        with self.assertRaises(HTTPException) as e:exclude_extracted_source('seg',SourceExclusionRequest(review_token=source['removal_token'],confirm_reviewed=True),self.db,self.user)
        self.assertEqual(e.exception.status_code,409)

    def test_restoration_never_approves_an_unapproved_original(self):
        self.q.active_rubric_version_id=None;self.db.get(RubricVersion,'r').status='draft';self.db.commit()
        self.change();self.change('restore')
        self.assertIsNone(self.q.active_rubric_version_id)
        self.assertEqual(self.db.get(RubricVersion,'r').status,'draft')
        with self.assertRaisesRegex(ValueError,'no approved rubric'):get_effective_rubric(self.q,self.db)

    def test_restore_number_conflict_and_missing_confirmation_change_nothing(self):
        preview=question_removal_preview('q','remove',self.db,self.user)
        with self.assertRaises(HTTPException) as e:change_question_lifecycle('q',QuestionLifecycleRequest(action='remove',review_token=preview['review_token'],confirm_reviewed=False),self.db,self.user)
        self.assertEqual(e.exception.status_code,422);self.assertEqual(self.q.active_rubric_version_id,'r')
        self.change();other=self.another_question();other.question_number='1';self.db.commit()
        with self.assertRaises(HTTPException) as e:question_removal_preview('q','restore',self.db,self.user)
        self.assertEqual(e.exception.status_code,409)

    def test_late_failure_rolls_back_question_scope_and_versions(self):
        from unittest.mock import patch
        preview=question_removal_preview('q','remove',self.db,self.user)
        with patch('services.question_lifecycle_service.record_audit_event',side_effect=RuntimeError('Synthetic audit failure')):
            with self.assertRaises(RuntimeError):change_question_lifecycle('q',QuestionLifecycleRequest(action='remove',review_token=preview['review_token'],confirm_reviewed=True),self.db,self.user)
        self.db.refresh(self.q);self.assertEqual(self.q.active_rubric_version_id,'r')
        self.assertEqual(self.db.query(RubricVersion).filter_by(question_id='q').count(),1)

    def test_source_exclusion_is_institution_scoped(self):
        source=build_extraction_review('s',self.db)['questions'][0]['sources'][0]
        with self.assertRaises(HTTPException) as e:exclude_extracted_source('seg',SourceExclusionRequest(review_token=source['removal_token'],confirm_reviewed=True),self.db,self.other)
        self.assertEqual(e.exception.status_code,404);self.assertIsNotNone(self.db.get(AnswerSource,'seg'))

    def test_catalog_uses_the_active_question_count_and_review_queue(self):
        from routers.exams import list_exams
        self.another_question();self.db.get(Answer,'a').score=1;self.db.commit();self.change()
        catalog=list_exams(self.db,self.user)
        row=next(row for row in catalog if row['id']=='e')
        self.assertEqual(row['question_count'],1);self.assertEqual(row['review_count'],0)

    def test_removed_question_blocks_current_grades_decisions_and_corrected_regrades(self):
        import asyncio
        from uuid import uuid4
        from unittest.mock import patch
        from routers.grading import grading_endpoint
        from routers.answer_areas import regrade_area_answer
        from routers.review_resolution import resolve_review
        from schemas.grading_input import GradeRequest
        from schemas.answer_area_input import AreaRegradeRequest
        from schemas.review_input import ReviewResolutionRequest
        from services.review_state_service import review_token
        answer=self.db.get(Answer,'a');answer.score=1;answer.max_score=2;self.db.commit();self.change()
        with patch('routers.grading.process_grading_with_policy') as provider:
            with self.assertRaises(HTTPException) as e:asyncio.run(grading_endpoint('a',GradeRequest(mode='auto'),self.db,self.user))
            self.assertEqual(e.exception.status_code,409);provider.assert_not_called()
        with self.assertRaises(HTTPException) as e:regrade_area_answer('a',AreaRegradeRequest(revision_ids=['revision'],request_id=uuid4()),self.db,self.user)
        self.assertEqual(e.exception.status_code,409)
        with self.assertRaises(HTTPException) as e:resolve_review('a',ReviewResolutionRequest(action='approve',was_review_warranted=True,expected_review_token=review_token(answer)),self.db,self.user)
        self.assertEqual(e.exception.status_code,409);self.assertEqual(float(answer.score),1)
