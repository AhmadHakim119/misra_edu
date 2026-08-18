from models import Answer


def resolved_review_status(answer: Answer) -> str | None:
    """Recover the authoritative human state, including older inconsistent rows."""
    if answer.teacher_override_score is not None:
        return "overridden"
    if answer.review_status == "approved" or answer.reviewed_at is not None:
        return "approved"
    return None
