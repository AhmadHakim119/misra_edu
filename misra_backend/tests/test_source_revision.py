from copy import deepcopy
import json
import unittest
from unittest.mock import Mock
from services.free_model_gateway import FreeCompletion
from services.grading_service import GradingResult
from services.source_revision_service import reconsider_with_sources, revision_eligible
from tests import test_source_consultation as fixtures
from tests.test_grading_decisions import check


class SourceRevisionTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.SourceConsultationTests()
        fixture.setUp()
        self.package = fixture.package
        self.consultation = {'status': 'needs_review', 'course_references': fixture.context,
            'page_inspection': {'status': 'provided_to_verifier'}, 'criteria': [
                {'criterion_id': 'c1', 'verdict': 'needs_review', 'explanation': 'The valid method was missed.',
                 'evidence_refs': ['source:one'], 'reference_refs': ['material:one']}]}
        self.initial = GradingResult(score=0, max_score=1, feedback='Initial proposal', reasoning='Initial',
            llm_confidence=80, criteria_scores=[{'criterion_id': 'c1', 'max_points': 1, 'points_earned': 0,
            'feedback': 'Initial', 'evidence_refs': ['source:one'], 'reference_refs': ['material:one']}])

    def response(self, score=1, **changes):
        value = self.initial.model_dump()
        value.update(score=score, **changes)
        value['criteria_scores'][0].update(points_earned=score,
            evidence_refs=['student:segment:1'], reference_refs=['instructor:source:1'],
            decision_check=check(criterion_kind='other', method_status='not_assessed'))
        return FreeCompletion(json.dumps(value), {'provider': 'mock', 'model': 'fixed'})

    def verifier(self, *args, **kwargs):
        return FreeCompletion(json.dumps({'criteria': [{'criterion_id': 'c1', 'verdict': 'supported',
            'explanation': 'The corrected mark matches the approved criterion.',
            'decision_check': check(criterion_kind='other', method_status='not_assessed')}], 'summary': 'Checked.'}), {})

    def test_one_revision_preserves_initial_proposal_and_requires_fresh_verification(self):
        before = self.initial.model_dump()
        assessment = Mock(return_value=self.response())
        verifier = Mock(side_effect=self.verifier)
        revised, package, record, check = reconsider_with_sources(self.initial, self.package,
            self.consultation, assessment_fn=assessment, verification_fn=verifier)
        self.assertEqual(revised.score, 1)
        self.assertEqual(self.initial.model_dump(), before)
        self.assertEqual(record['initial_proposal']['score'], 0)
        self.assertTrue(record['score_changed'])
        self.assertTrue(record['instructor_review_required'])
        self.assertEqual(assessment.call_count, 1)
        self.assertEqual(verifier.call_count, 1)
        self.assertEqual(check['status'], 'checked')
        self.assertEqual(package['rubric'], self.package['rubric'])
        self.assertEqual(package['policy'], self.package['policy'])

    def test_no_revision_when_page_is_ambiguous_missing_or_no_academic_concern(self):
        for status in ('needs_review', 'unavailable'):
            consultation = {**self.consultation, 'page_inspection': {'status': status}}
            assessment = Mock()
            result, _, record, checked = reconsider_with_sources(self.initial, self.package,
                consultation, assessment_fn=assessment)
            self.assertIs(result, self.initial)
            assessment.assert_not_called()
            self.assertEqual(record['status'], 'not_eligible')
        consultation = deepcopy(self.consultation)
        consultation['criteria'][0]['verdict'] = 'supported'
        self.assertFalse(revision_eligible(consultation))

    def test_research_checked_text_opt_in_is_explicit_and_never_allows_conflicting_page(self):
        consultation = {**self.consultation, 'page_inspection': {'status': 'unavailable'}}
        self.assertTrue(revision_eligible(consultation, checked_transcription=True))
        consultation['page_inspection']['status'] = 'needs_review'
        self.assertFalse(revision_eligible(consultation, checked_transcription=True))

    def test_invalid_revision_keeps_original_and_never_retries(self):
        bad = json.loads(self.response().text)
        bad['criteria_scores'][0]['criterion_id'] = 'invented'
        assessment = Mock(return_value=FreeCompletion(json.dumps(bad), {}))
        verifier = Mock()
        result, _, record, checked = reconsider_with_sources(self.initial, self.package,
            self.consultation, assessment_fn=assessment, verification_fn=verifier)
        self.assertIs(result, self.initial)
        self.assertEqual(record['status'], 'unavailable')
        assessment.assert_called_once()
        verifier.assert_not_called()
        self.assertIsNone(checked)

    def test_revision_may_lower_a_proposal_and_does_not_choose_the_higher_score(self):
        self.initial.score = 1
        self.initial.criteria_scores[0].points_earned = 1
        revised, _, record, _ = reconsider_with_sources(self.initial, self.package,
            self.consultation, assessment_fn=lambda _: self.response(0), verification_fn=self.verifier)
        self.assertEqual(revised.score, 0)
        self.assertEqual(record['initial_proposal']['score'], 1)
        self.assertTrue(record['score_changed'])

    def test_verification_failure_does_not_replace_a_valid_initial_proposal(self):
        result, _, record, checked = reconsider_with_sources(self.initial, self.package,
            self.consultation, assessment_fn=lambda _: self.response(), verification_fn=Mock(side_effect=ValueError('bad')))
        self.assertIs(result, self.initial)
        self.assertEqual(record['status'], 'unavailable')
        self.assertIn('original_response', record)
