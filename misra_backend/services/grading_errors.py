"""Safe grading-contract failures, without raw responses or private paper text."""


class CitationValidationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class GradingResponseValidationError(ValueError):
    def __init__(self, code: str, reason: str, repair_attempts: int = 0):
        self.code = code
        self.repair_attempts = repair_attempts
        super().__init__(
            f"AI grading response failed validation: {reason} "
            "No grade was saved for this answer. Earlier completed answers are retained. "
            "Review the saved paper or retry grading; do not re-upload it."
        )
