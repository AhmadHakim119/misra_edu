"""Atomic guide approval and content-bound review; synthetic isolated records."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from fastapi import HTTPException
from models import RubricVersion, AnswerKeyVersion, AssessmentMaterialScopeVersion
from routers.rubric_versions import (review_assessment_guide, approve_assessment_guide,
    AssessmentGuideApprovalRequest)
from schemas.course_materials import AssessmentMaterialScopeRequest
from services.assessment_source_service import save_default
from services.assessment_guide_service import review_guide
from services.rubric_version_service import create_rubric_version
from tests import test_course_materials as fixtures


class AssessmentGuideTests(unittest.TestCase):
    setUp = fixtures.CourseMaterialTests.setUp
    tearDown = fixtures.CourseMaterialTests.tearDown
    material = fixtures.CourseMaterialTests.material

    def draft(self):
        rubric = {**deepcopy(self.rubric), 'schema_version':2}
        rubric['criteria'][0]['title']='Work calculation'
        return create_rubric_version(question=self.q, rubric_json=rubric, source='manual',
            change_summary='Synthetic draft', db=self.db)

    def approve(self, token):
        return approve_assessment_guide('e', AssessmentGuideApprovalRequest(
            review_token=token, confirm_reviewed=True), self.db, self.user)

    def test_single_approval_activates_rubric_key_and_sources(self):
        from models import Exam
        draft = self.draft()
        key = AnswerKeyVersion(question_id='q', version_number=1, mode='reference',
            reference_text='W = mgh', acceptable_answers=[], document_refs=[], status='draft')
        self.db.add(key); self.db.commit()
        _, material = self.material()
        scope = save_default(self.db, self.db.get(Exam,'e'), AssessmentMaterialScopeRequest(
            mode='required', bindings=[{'version_id':material.id,'page_indices':[0]}]),self.user)
        self.db.commit()
        reviewed = review_assessment_guide('e',self.db,self.user)
        self.assertTrue(reviewed['can_approve']); self.assertEqual(reviewed['pending_count'],3)
        approved = self.approve(reviewed['review_token'])
        self.assertEqual(len(approved['approved_version_ids']),3)
        self.assertEqual(self.db.get(RubricVersion,draft.id).status,'approved')
        self.assertEqual(self.db.get(AnswerKeyVersion,key.id).status,'approved')
        self.assertEqual(self.db.get(AssessmentMaterialScopeVersion,scope.id).status,'approved')
        self.assertEqual(self.q.active_rubric_version_id,draft.id)
        self.assertEqual(reviewed['questions'][0]['source_references'][0]['title'],'Synthetic chapter')

    def correction(self, number='p6.1', text='Corrected printed question'):
        from services.question_definition_service import current_definition
        draft=self.draft();value=deepcopy(draft.rubric_json)
        value['question_definition']=dict(question_number=number,question_text=text,
            language='en',previous=current_definition(self.q))
        from services.rubric_version_service import update_rubric_version
        return update_rubric_version(version=draft,rubric_json=value,change_summary='Correct import',db=self.db)

    def test_question_correction_is_reviewed_and_applied_without_rewriting_history(self):
        from models import Answer, GradingRun
        before=(self.q.question_number,self.q.question_text)
        approved=deepcopy(self.db.get(RubricVersion,'r').rubric_json)
        answer=self.db.get(Answer,'a');answer.score=1;answer.teacher_override_score=1.5;answer.review_status='approved'
        snapshot={'question':{'number':before[0],'text':before[1]}}
        run=GradingRun(id='definition-history',answer_id='a',rubric_version_id='r',mode='text_only',model_name='synthetic',
            prompt_version='test',ocr_text_snapshot='Original work',rubric_snapshot=approved,score=1,max_score=2,
            feedback='Original',reasoning='Original',criteria_scores=[],llm_confidence=40,final_confidence=40,
            needs_review=False,response_json=deepcopy(snapshot))
        self.db.add(run);self.db.commit()
        draft=self.correction();self.assertEqual((self.q.question_number,self.q.question_text),before)
        review=review_assessment_guide('e',self.db,self.user)
        self.assertEqual(review['questions'][0]['question_number'],'p6.1')
        self.assertEqual(review['questions'][0]['current_question_number'],before[0])
        self.approve(review['review_token']);self.db.refresh(self.q)
        self.assertEqual(self.q.question_text,'Corrected printed question')
        self.assertEqual(self.q.question_number,'p6.1')
        self.assertEqual(self.db.get(RubricVersion,'r').rubric_json,approved)
        self.assertEqual(draft.rubric_json['question_definition']['previous']['question_text'],before[1])
        self.db.refresh(answer);self.db.refresh(run)
        self.assertEqual(run.response_json,snapshot);self.assertEqual(float(run.score),1)
        self.assertEqual(float(answer.score),1);self.assertEqual(float(answer.teacher_override_score),1.5)
        self.assertTrue(answer.needs_review)
        from services.rubric_version_service import get_effective_rubric
        effective,_=get_effective_rubric(self.q,self.db)
        self.assertNotIn('question_definition',effective)
        self.assertEqual(effective['criteria'],draft.rubric_json['criteria'])

    def test_another_correction_can_follow_an_approved_correction(self):
        self.correction();self.approve(review_assessment_guide('e',self.db,self.user)['review_token'])
        from routers.rubric_versions import reopen_assessment_guide
        review=review_assessment_guide('e',self.db,self.user)
        reopen_assessment_guide('e',AssessmentGuideApprovalRequest(review_token=review['review_token'],confirm_reviewed=True),self.db,self.user)
        draft=self.db.query(RubricVersion).filter_by(question_id='q',status='draft').one()
        value=deepcopy(draft.rubric_json);value['question_definition']['question_text']='Second wording correction'
        from services.rubric_version_service import update_rubric_version
        update_rubric_version(version=draft,rubric_json=value,change_summary='Second correction',db=self.db)
        review=review_assessment_guide('e',self.db,self.user);self.assertTrue(review['can_approve'],review['errors'])
        self.approve(review['review_token']);self.assertEqual(self.q.question_text,'Second wording correction')

    def test_question_correction_blocks_individual_approval_and_stale_definition(self):
        from services.rubric_version_service import approve_rubric_version
        draft=self.correction()
        with self.assertRaisesRegex(ValueError,'whole-guide'):
            approve_rubric_version(version=draft,db=self.db)
        self.q.question_text='Changed by a different editor';self.db.commit()
        review=review_assessment_guide('e',self.db,self.user)
        self.assertFalse(review['can_approve'])
        self.assertTrue(any('changed after' in e for e in review['errors']))

    def test_duplicate_proposed_question_numbers_block_whole_approval(self):
        from models import Question
        self.db.add(Question(id='collision',institution_id='i',exam_id='e',question_number='P6.1',
            question_text='Other question',max_score=2,rubric_json=self.rubric,order_index=2,language='en'))
        self.db.commit();self.correction()
        review=review_assessment_guide('e',self.db,self.user)
        self.assertFalse(review['can_approve'])
        self.assertTrue(any('used more than once' in e for e in review['errors']))

    def test_whole_approval_can_renumber_a_cycle_atomically(self):
        from models import Question
        from services.question_definition_service import current_definition
        other=Question(id='second',institution_id='i',exam_id='e',question_number='p6.1',
            question_text='Other question',max_score=2,rubric_json=self.rubric,order_index=2,language='en')
        self.db.add(other);self.db.commit();original=self.q.question_number
        first=self.correction()
        value=deepcopy(first.rubric_json)
        value['question_definition']=dict(question_number=original,question_text=other.question_text,
            language='en',previous=current_definition(other))
        create_rubric_version(question=other,rubric_json=value,source='manual',change_summary='Number swap',db=self.db)
        review=review_assessment_guide('e',self.db,self.user);self.assertTrue(review['can_approve'],review['errors'])
        self.approve(review['review_token'])
        self.assertEqual(self.q.question_number,'p6.1');self.assertEqual(other.question_number,original)

    def test_same_draft_edit_invalidates_review(self):
        draft=self.draft(); review=review_assessment_guide('e',self.db,self.user)
        updated=deepcopy(draft.rubric_json);updated['criteria'][0]['description']='Changed credit rule'
        draft.rubric_json=updated;self.db.commit()
        with self.assertRaises(HTTPException) as error:self.approve(review['review_token'])
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(self.db.get(RubricVersion,draft.id).status,'draft')

    def test_draft_total_correction_is_reviewed_before_changing_current_marks(self):
        draft=self.draft()
        self.q.max_score=8
        changed=deepcopy(draft.rubric_json)
        changed['max_score']=4
        changed['criteria'][0]['points']=4
        draft.rubric_json=changed
        self.db.commit()
        review=review_assessment_guide('e',self.db,self.user)
        self.assertTrue(review['can_approve'],review['errors'])
        self.assertEqual(review['total_marks'],4)
        row=review['questions'][0]
        self.assertEqual(row['max_score'],4)
        self.assertEqual(row['current_max_score'],8)
        self.assertTrue(any('8' in w and '4' in w for w in row['warnings']))
        self.db.refresh(self.q)
        self.assertEqual(float(self.q.max_score),8)
        self.assertEqual(self.q.active_rubric_version_id,'r')
        self.approve(review['review_token'])
        self.db.refresh(self.q)
        self.assertEqual(float(self.q.max_score),4)
        self.assertEqual(self.q.active_rubric_version_id,draft.id)
        self.assertEqual(self.db.get(RubricVersion,'r').rubric_json,self.rubric)

    def test_review_of_changed_draft_total_does_not_rewrite_previous_grade(self):
        from models import Answer, GradingRun
        draft=self.draft()
        updated=deepcopy(draft.rubric_json)
        updated['max_score']=4;updated['criteria'][0]['points']=4
        draft.rubric_json=updated
        answer=self.db.get(Answer,'a');answer.score=1;answer.review_status='approved'
        run=GradingRun(id='old-total',answer_id='a',rubric_version_id='r',mode='text_only',model_name='synthetic',
            prompt_version='test',ocr_text_snapshot='W=mgh',rubric_snapshot={'max_score':2},score=1,max_score=2,
            feedback='old',reasoning='old',criteria_scores=[],llm_confidence=40,final_confidence=40,needs_review=False,response_json={})
        self.db.add(run);self.db.commit()
        reviewed=review_assessment_guide('e',self.db,self.user)
        self.approve(reviewed['review_token'])
        self.db.refresh(run);self.db.refresh(answer)
        self.assertEqual(float(run.max_score),2)
        self.assertEqual(run.rubric_snapshot,{'max_score':2})
        self.assertEqual(float(answer.score),1)
        self.assertTrue(answer.needs_review)
        self.assertEqual(answer.review_status,'pending')

    def test_approved_total_mismatch_still_blocks_guide(self):
        self.q.max_score=8;self.db.commit()
        reviewed=review_assessment_guide('e',self.db,self.user)
        self.assertFalse(reviewed['can_approve'])
        self.assertTrue(any('marks do not match' in e for e in reviewed['errors']))

    def test_failure_late_in_approval_rolls_back_every_version(self):
        draft=self.draft()
        key=AnswerKeyVersion(question_id='q',version_number=1,mode='reference',reference_text='W=mgh',status='draft',acceptable_answers=[],document_refs=[])
        self.db.add(key);self.db.commit();review=review_assessment_guide('e',self.db,self.user)
        with patch('services.answer_key_service.approve_key',side_effect=ValueError('Synthetic late rejection')):
            with self.assertRaises(HTTPException):self.approve(review['review_token'])
        self.assertEqual(self.db.get(RubricVersion,draft.id).status,'draft')
        self.assertEqual(self.db.get(RubricVersion,'r').status,'approved')
        self.assertEqual(self.q.active_rubric_version_id,'r')

    def test_invalid_marks_and_unchecked_sources_cannot_approve(self):
        draft=self.draft();bad=deepcopy(draft.rubric_json);bad['criteria'][0]['points']=1;draft.rubric_json=bad;self.db.commit()
        review=review_assessment_guide('e',self.db,self.user)
        self.assertFalse(review['can_approve'])
        with self.assertRaises(HTTPException):self.approve(review['review_token'])
        self.assertEqual(draft.status,'draft')

    def test_cross_institution_and_missing_confirmation(self):
        for endpoint in (review_assessment_guide,):
            with self.assertRaises(HTTPException) as error:endpoint('e',self.db,self.other)
            self.assertEqual(error.exception.status_code,404)
        review=review_assessment_guide('e',self.db,self.user)
        with self.assertRaises(HTTPException) as error:
            approve_assessment_guide('e',AssessmentGuideApprovalRequest(review_token=review['review_token'],confirm_reviewed=False),self.db,self.user)
        self.assertEqual(error.exception.status_code,422)

    def test_legacy_assessment_still_reviews_without_rewriting(self):
        original=deepcopy(self.q.rubric_json)
        review=review_assessment_guide('e',self.db,self.user)
        self.assertTrue(review['can_approve']);self.assertEqual(review['pending_count'],0)
        self.assertEqual(self.q.rubric_json,original)

    def test_multiple_questions_publish_together_without_rewriting_history(self):
        from models import Question, GradingRun
        draft=self.draft()
        second=Question(id='q2',institution_id='i',exam_id='e',question_number='2',question_text='Calculate work',
            max_score=2,rubric_json=deepcopy(draft.rubric_json),order_index=1)
        run=GradingRun(id='old-run',answer_id='a',rubric_version_id='r',mode='text_only',model_name='synthetic',
            prompt_version='test',ocr_text_snapshot='W=mgh',rubric_snapshot={'old':'immutable'},score=1,max_score=2,
            feedback='old',reasoning='old',criteria_scores=[],llm_confidence=40,final_confidence=40,needs_review=True,response_json={})
        self.db.add_all([second,run]);self.db.commit()
        second_draft=create_rubric_version(question=second,rubric_json=deepcopy(draft.rubric_json),source='manual',change_summary='test',db=self.db)
        review=review_assessment_guide('e',self.db,self.user)
        self.assertEqual(len(review['questions']),2)
        approved=self.approve(review['review_token'])
        self.assertEqual(set(approved['approved_version_ids']),{draft.id,second_draft.id})
        self.assertEqual(self.db.get(GradingRun,'old-run').rubric_snapshot,{'old':'immutable'})
        self.assertEqual(float(self.db.get(GradingRun,'old-run').score),1)

    def test_corrupt_or_unchecked_source_blocks_entire_guide(self):
        from models import Exam
        draft=self.draft();_,material=self.material()
        scope=save_default(self.db,self.db.get(Exam,'e'),AssessmentMaterialScopeRequest(mode='required',bindings=[{'version_id':material.id,'page_indices':[0]}]),self.user)
        material.approved_page_indices=[];self.db.commit()
        review=review_assessment_guide('e',self.db,self.user)
        self.assertFalse(review['can_approve'])
        with self.assertRaises(HTTPException):self.approve(review['review_token'])
        self.assertEqual(self.db.get(RubricVersion,draft.id).status,'draft')
        self.assertEqual(self.db.get(AssessmentMaterialScopeVersion,scope.id).status,'draft')

    def test_rubric_ai_draft_uses_checked_pages_without_publishing_sources(self):
        import json
        from models import Exam
        from routers.rubric_versions import suggest_existing_question_rubric_version
        from schemas.rubric_input import ExistingQuestionRubricSuggestionRequest
        draft=self.draft();_,material=self.material()
        scope=save_default(self.db,self.db.get(Exam,'e'),AssessmentMaterialScopeRequest(mode='required',bindings=[{'version_id':material.id,'page_indices':[0]}]),self.user)
        self.db.commit()
        with patch('services.rubric_service.generate',return_value=json.dumps(draft.rubric_json)) as generate:
            result=suggest_existing_question_rubric_version('q',ExistingQuestionRubricSuggestionRequest(),self.db,self.user)
        prompt=generate.call_args.kwargs['contents']
        self.assertIn('COURSE REFERENCE EVIDENCE',prompt)
        self.assertIn('Synthetic chapter',prompt)
        self.assertIn('W = mgh',prompt)
        self.assertEqual(result['rubric_version'].status,'draft')
        self.assertEqual(self.db.get(AssessmentMaterialScopeVersion,scope.id).status,'draft')
        self.assertEqual(self.q.active_rubric_version_id,'r')
