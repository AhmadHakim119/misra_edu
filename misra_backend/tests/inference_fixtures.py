"""Explicit provider defaults for tests that mock the legacy grading boundary."""
import os
from unittest.mock import patch


def isolate_grading_provider(test_case):
    # Local .env choices must not route synthetic fixtures to another provider.
    # Tests exercising verification or other providers override these explicitly.
    environment = patch.dict(os.environ, {
        "GRADING_PROVIDER": "gemini",
        "GRADING_MODEL": "gemini-2.5-flash",
        "VERIFICATION_ENABLED": "false",
        "MISRA_RETRIEVAL_STRATEGY": "bm25_v1",
    })
    environment.start()
    test_case.addCleanup(environment.stop)
