import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from PIL import Image
from services.free_model_gateway import complete_free
from services.openrouter_client import OpenRouterError


class FreeModelGatewayTests(unittest.TestCase):
    model = "synthetic/model:free"

    def catalog(self, **changes):
        entry = {"id":self.model,"pricing":{"prompt":"0","completion":"0","request":"0"},
            "architecture":{"input_modalities":["text","image"]},"supported_parameters":["response_format"]}
        entry.update(changes)
        return {"data":[entry]}

    def response(self, **changes):
        response = {"model":self.model,"choices":[{"finish_reason":"stop","message":{"content":'{"score":2}'}}],
            "usage":{"cost":0,"prompt_tokens":100,"completion_tokens":10}}
        response.update(changes)
        return response

    def http_response(self, payload):
        return io.BytesIO(json.dumps(payload).encode('utf8'))

    def http_error(self, code):
        return urllib.error.HTTPError('https://openrouter.ai/api/v1/chat/completions', code,
            'PRIVATE provider message', {}, io.BytesIO(b'PRIVATE response and credentials'))

    def test_temporary_http_failures_retry_the_identical_free_request(self):
        for code in [500, 502, 503, 504]:
            with self.subTest(code=code), patch('services.free_model_gateway.urllib.request.urlopen',
                    side_effect=[self.http_response(self.catalog()), self.http_error(code),
                                 self.http_response(self.response())]) as request, \
                 patch('services.free_model_gateway.sleep', create=True) as pause:
                result = complete_free('Synthetic', model=self.model, api_key='synthetic-key')
                self.assertEqual(result.text, '{"score":2}')
                self.assertEqual(request.call_count, 3)
                self.assertIs(request.call_args_list[1].args[0], request.call_args_list[2].args[0])
                body = json.loads(request.call_args_list[2].args[0].data)
                self.assertEqual(body['model'], self.model)
                self.assertFalse(body['provider']['allow_fallbacks'])
                self.assertEqual(body['provider']['max_price'], {'prompt':0, 'completion':0})
                pause.assert_called_once_with(2)

    def test_temporary_failure_retries_are_bounded_and_errors_stay_private(self):
        with patch('services.free_model_gateway.urllib.request.urlopen', side_effect=[
                self.http_response(self.catalog()), *[self.http_error(502) for _ in range(3)]]) as request, \
             patch('services.free_model_gateway.sleep', create=True) as pause:
            with self.assertRaises(OpenRouterError) as caught:
                complete_free('Synthetic', model=self.model, api_key='synthetic-key')
        self.assertEqual(request.call_count, 4)  # one catalog + three identical completion attempts
        self.assertEqual([c.args[0] for c in pause.call_args_list], [2, 4])
        self.assertIn('HTTP 502', str(caught.exception))
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertNotIn('synthetic-key', str(caught.exception))

    def test_temporary_error_inside_json_uses_the_same_bounded_retry(self):
        with patch('services.free_model_gateway.urllib.request.urlopen', side_effect=[
                self.http_response(self.catalog()),
                self.http_response({'error':{'code':502, 'message':'PRIVATE'}}),
                self.http_response(self.response())]) as request, \
             patch('services.free_model_gateway.sleep', create=True) as pause:
            self.assertEqual(complete_free('Synthetic', model=self.model, api_key='key').text, '{"score":2}')
        self.assertEqual(request.call_count, 3)
        pause.assert_called_once_with(2)

    def test_auth_credit_quota_and_request_failures_are_not_immediately_retried(self):
        for code in [400, 401, 402, 403, 404, 422, 429]:
            with self.subTest(code=code), patch('services.free_model_gateway.urllib.request.urlopen',
                    side_effect=[self.http_response(self.catalog()), self.http_error(code)]) as request, \
                 patch('services.free_model_gateway.sleep', create=True) as pause:
                with self.assertRaisesRegex(OpenRouterError, f'HTTP {code}'):
                    complete_free('Synthetic', model=self.model, api_key='key')
                self.assertEqual(request.call_count, 2)
                pause.assert_not_called()

    def test_invalid_provider_json_is_not_retried(self):
        with patch('services.free_model_gateway.urllib.request.urlopen', side_effect=[
                self.http_response(self.catalog()), io.BytesIO(b'not JSON PRIVATE')]) as request, \
             patch('services.free_model_gateway.sleep', create=True) as pause:
            with self.assertRaisesRegex(OpenRouterError, 'invalid response JSON'):
                complete_free('Synthetic', model=self.model, api_key='key')
        self.assertEqual(request.call_count, 2)
        pause.assert_not_called()

    def test_json_quota_error_is_not_immediately_retried(self):
        with patch('services.free_model_gateway.urllib.request.urlopen', side_effect=[
                self.http_response(self.catalog()),
                self.http_response({'error':{'code':429, 'message':'PRIVATE'}})]) as request, \
             patch('services.free_model_gateway.sleep', create=True) as pause:
            with self.assertRaisesRegex(OpenRouterError, 'error 429'):
                complete_free('Synthetic', model=self.model, api_key='key')
        self.assertEqual(request.call_count, 2)
        pause.assert_not_called()

    def test_catalog_outage_is_retried_before_any_completion_is_sent(self):
        with patch('services.free_model_gateway.urllib.request.urlopen', side_effect=[
                self.http_error(503), self.http_response(self.catalog()),
                self.http_response(self.response())]) as request, \
             patch('services.free_model_gateway.sleep', create=True) as pause:
            self.assertEqual(complete_free('Synthetic', model=self.model, api_key='key').text, '{"score":2}')
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[0].args, request.call_args_list[1].args)
        self.assertIsInstance(request.call_args_list[2].args[0].data, bytes)
        pause.assert_called_once_with(2)

    def test_free_request_has_no_fallback_and_records_usage(self):
        with patch("services.free_model_gateway._read_json",side_effect=[self.catalog(),self.response()]) as read:
            result = complete_free("Synthetic",model=self.model,api_key="synthetic-key")
        self.assertEqual(result.text,'{"score":2}')
        body = json.loads(read.call_args.args[0].data)
        self.assertFalse(body["provider"]["allow_fallbacks"])
        self.assertEqual(body["provider"]["max_price"],{"prompt":0,"completion":0})
        self.assertEqual(result.metadata["reported_cost_usd"],0)
        self.assertEqual(result.metadata["prompt_tokens"],100)
        self.assertNotIn("synthetic-key",json.dumps(result.metadata))

    def test_paid_model_and_router_rejected_without_network(self):
        with patch("services.free_model_gateway._read_json") as read:
            for model in ["synthetic/paid","openrouter/free:free"]:
                with self.assertRaises(ValueError): complete_free("hello",model=model,api_key="key")
            read.assert_not_called()

    def test_unverified_prices_rejected_before_completion(self):
        for pricing in [{"prompt":"0"},{"prompt":"0","completion":"0.1"},
                        {"prompt":"nan","completion":"0"},{"prompt":"0","completion":"0","image":"1"}]:
            with self.subTest(pricing=pricing),patch("services.free_model_gateway._read_json",return_value=self.catalog(pricing=pricing)) as read:
                with self.assertRaises(OpenRouterError): complete_free("hello",model=self.model,api_key="key")
                self.assertEqual(read.call_count,1)

    def test_vision_never_falls_back_to_text(self):
        image = Image.new("RGB",(20,30),"white")
        with patch("services.free_model_gateway._read_json",return_value=self.catalog(architecture={"input_modalities":["text"]})) as read:
            with self.assertRaisesRegex(ValueError,"text-only fallback"):
                complete_free(["hello",image],model=self.model,api_key="key")
            self.assertEqual(read.call_count,1)
        with patch("services.free_model_gateway._read_json",side_effect=[self.catalog(),self.response()]) as read:
            result = complete_free(["hello",image],model=self.model,api_key="key")
        body = json.loads(read.call_args.args[0].data)
        self.assertEqual(result.metadata["image_count"],1)
        self.assertTrue(body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_truncated_empty_and_nonzero_cost_rejected(self):
        for response in [self.response(choices=[{"finish_reason":"length","message":{"content":"{}"}}]),
                         self.response(choices=[]),self.response(usage={"cost":1}),self.response(usage={"cost":"nan"})]:
            with self.subTest(response=response),patch("services.free_model_gateway._read_json",side_effect=[self.catalog(),response]):
                with self.assertRaises(OpenRouterError): complete_free("hello",model=self.model,api_key="key")

    def test_wrong_model_and_invalid_metadata_rejected(self):
        for response in [self.response(model="synthetic/paid"),self.response(usage=[1,2])]:
            with patch("services.free_model_gateway._read_json",side_effect=[self.catalog(),response]):
                with self.assertRaises(OpenRouterError): complete_free("hello",model=self.model,api_key="key")

    def test_missing_gemini_key_blocks_only_gemini_operation(self):
        from services import gemini_client
        with patch.object(gemini_client,"client",None):
            with self.assertRaisesRegex(RuntimeError,"GEMINI_API_KEY"):
                gemini_client.generate("Synthetic input")
            with patch("services.free_model_gateway._read_json",side_effect=[self.catalog(),self.response()]):
                self.assertEqual(complete_free("hello",model=self.model,api_key="key").text,'{"score":2}')


if __name__ == "__main__": unittest.main()
