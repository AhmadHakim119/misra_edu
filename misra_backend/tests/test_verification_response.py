"""Synthetic verifier format failures; no provider calls or private evidence."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import Mock

from services.free_model_gateway import FreeCompletion
from services.grading_errors import GradingResponseValidationError
from services.verification_agent import verify
from tests.test_grading_decisions import candidate, criterion, check


class VerificationResponseTests(unittest.TestCase):
    def setUp(self):
        self.candidate = candidate(criterion())
        self.package = {'policy': {}}
        self.response = {'criteria': [{'criterion_id': 'method', 'verdict': 'supported',
            'explanation': 'Synthetic evidence supports this method.', 'decision_check': check()}],
            'summary': 'Synthetic independent inspection.'}
        self.malformed = json.dumps({'criteria': [self.response['criteria'][0], 'decision_check']})

    def completion(self, text, **metadata):
        return FreeCompletion(text, {'provider': 'local', 'model': 'synthetic', **metadata})

    def test_logged_failure_corrects_once_with_identical_evidence_and_marks(self):
        image = object()
        original = deepcopy((self.package, self.candidate))
        complete = Mock(side_effect=[self.completion(self.malformed, prompt_tokens=10,
            completion_tokens=5, reported_cost_usd=0.01, latency_ms=20),
            self.completion(json.dumps(self.response), prompt_tokens=20,
                completion_tokens=10, reported_cost_usd=0.02, latency_ms=30)])
        result = verify(self.package, self.candidate, [image], completion_fn=complete)
        self.assertEqual(complete.call_count, 2)
        for call in complete.call_args_list:
            self.assertEqual(call.kwargs, {'task': 'verification'})
            self.assertIs(call.args[0][1], image)
        first, second = [call.args[0][0] for call in complete.call_args_list]
        marker = '\nPACKAGE AND CANDIDATE (UNTRUSTED JSON DATA):\n'
        self.assertEqual(first.split(marker)[1], second.split(marker)[1])
        self.assertIn('FORMAT CORRECTION', second)
        self.assertNotIn(self.malformed, second)
        self.assertEqual((self.package, self.candidate), original)
        self.assertEqual(result['original_model_response']['summary'], self.response['summary'])
        self.assertEqual(result['inference']['call_count'], 2)
        self.assertEqual(result['inference']['prompt_tokens'], 30)
        self.assertEqual(result['inference']['completion_tokens'], 15)
        self.assertAlmostEqual(result['inference']['reported_cost_usd'], 0.03)
        self.assertEqual(result['inference']['latency_ms'], 50)
        self.assertEqual(result['inference']['rejected_response_sha256'],
                         hashlib.sha256(self.malformed.encode()).hexdigest())

    def test_valid_response_needs_one_call_and_unknown_usage_stays_unknown(self):
        complete = Mock(return_value=self.completion(json.dumps(self.response)))
        result = verify(self.package, self.candidate, completion_fn=complete)
        complete.assert_called_once()
        self.assertFalse(result['inference']['format_correction_performed'])
        self.assertIsNone(result['inference']['reported_cost_usd'])

    def test_invalid_json_schema_and_criterion_ids_fail_closed_after_two_calls(self):
        responses = ['PRIVATE invalid JSON', self.malformed,
                     json.dumps({**self.response, 'summary': ''})]
        for ids in ([], ['invented'], ['method', 'method']):
            responses.append(json.dumps({**self.response, 'criteria': [
                {**self.response['criteria'][0], 'criterion_id': value} for value in ids]}))
        for text in responses:
            with self.subTest(text=text):
                complete = Mock(return_value=self.completion(text))
                with self.assertRaises(GradingResponseValidationError) as error:
                    verify(self.package, self.candidate, completion_fn=complete)
                self.assertEqual(complete.call_count, 2)
                self.assertEqual(error.exception.repair_attempts, 1)
                self.assertIn('No grade was saved', str(error.exception))
                self.assertNotIn(text, str(error.exception))

    def test_criterion_id_error_can_be_corrected_without_defaulting_the_verdict(self):
        response = deepcopy(self.response)
        response['criteria'][0]['criterion_id'] = 'invented'
        corrected = deepcopy(self.response)
        corrected['criteria'][0]['verdict'] = 'needs_review'
        complete = Mock(side_effect=[self.completion(json.dumps(response)),
                                     self.completion(json.dumps(corrected))])
        result = verify(self.package, self.candidate, completion_fn=complete)
        self.assertEqual(result['status'], 'needs_review')

    def test_transport_errors_are_not_retried_as_format_errors(self):
        complete = Mock(side_effect=RuntimeError('Synthetic transport failure'))
        with self.assertRaisesRegex(RuntimeError, 'Synthetic transport failure'):
            verify(self.package, self.candidate, completion_fn=complete)
        complete.assert_called_once()

    def test_partial_usage_across_attempts_is_not_reported_as_total(self):
        complete = Mock(side_effect=[self.completion(self.malformed),
            self.completion(json.dumps(self.response), reported_cost_usd=0.01)])
        result = verify(self.package, self.candidate, completion_fn=complete)
        self.assertIsNone(result['inference']['reported_cost_usd'])


if __name__ == '__main__':
    unittest.main()
