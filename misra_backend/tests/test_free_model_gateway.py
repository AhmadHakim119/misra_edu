import json
import unittest
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
