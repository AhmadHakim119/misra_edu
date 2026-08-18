from google import genai
from google.genai import errors, types
import os
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gemini-2.5-flash"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is not set.")

client = genai.Client(api_key=GEMINI_API_KEY)

def _is_transient_error(retry_state):
    exception = retry_state.outcome.exception()
    if isinstance(exception, errors.APIError):
        return exception.code in (429, 500, 503)
    return False

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=_is_transient_error,
    reraise=True
)
def generate(contents, model=DEFAULT_MODEL, json_mode=False):
    config = types.GenerateContentConfig(
        response_mime_type="application/json" if json_mode else "text/plain"
    )
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config
    )
    return response.text