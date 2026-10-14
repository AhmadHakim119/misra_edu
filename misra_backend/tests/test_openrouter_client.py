import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from services.openrouter_client import OpenRouterError, complete_json


class _Response:
    def __init__(self, payload):
        self.stream = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self.stream

    def __exit__(self, *_args):
        self.stream.close()


class OpenRouterClientTests(unittest.TestCase):
    def test_explicit_free_slug_required_before_network_call(self):
        with patch("services.openrouter_client.urllib.request.urlopen") as call:
            with self.assertRaisesRegex(ValueError, "explicit :free"):
                complete_json(model="nvidia/paid", prompt="synthetic", api_key="test-secret")
            call.assert_not_called()

    def test_parses_completion_and_usage_without_persisting_secret(self):
        payload = {"model": "nvidia/test:free", "choices": [{"message": {"content": '{"score": 2}'}}],
                   "usage": {"prompt_tokens": 12, "completion_tokens": 5}}
        with patch("services.openrouter_client.urllib.request.urlopen", return_value=_Response(payload)) as call:
            result = complete_json(model="nvidia/test:free", prompt="synthetic", api_key="test-secret")
        request = call.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertEqual(json.loads(request.data)["reasoning"], {"enabled": False})
        self.assertEqual(result.text, '{"score": 2}')
        self.assertEqual(result.prompt_tokens, 12)
        self.assertEqual(result.completion_tokens, 5)
        self.assertNotIn("test-secret", repr(result))

    def test_http_error_does_not_expose_provider_body_or_key(self):
        error = HTTPError("https://openrouter.ai/api/v1/chat/completions", 429,
                          "limit; test-secret", {}, io.BytesIO(b"private prompt; test-secret"))
        with patch("services.openrouter_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(OpenRouterError) as raised:
                complete_json(model="nvidia/test:free", prompt="synthetic", api_key="test-secret")
        self.assertIn("HTTP 429", str(raised.exception))
        self.assertNotIn("test-secret", str(raised.exception))
        self.assertNotIn("private prompt", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
