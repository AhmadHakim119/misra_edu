from services.grading_service import _compute_final_confidence, GradingResult, CriterionScore


class FakeAnswer:
    """Minimal stand-in for a real Answer row — only needs the one attribute
    _compute_final_confidence actually reads."""
    def __init__(self, ocr_legibility):
        self.ocr_legibility = ocr_legibility


def run_case(label, ocr_legibility, llm_confidence, score, max_score):
    fake_answer = FakeAnswer(ocr_legibility=ocr_legibility)
    fake_result = GradingResult(
        score=score,
        max_score=max_score,
        feedback="test feedback",
        reasoning="test reasoning",
        criteria_scores=[
            CriterionScore(criterion_id="test", max_points=max_score, points_earned=score, feedback="test")
        ],
        llm_confidence=llm_confidence
    )
    confidence = _compute_final_confidence(fake_answer, fake_result)
    needs_review = confidence < 70
    print(f"{label}: final_confidence={confidence}, needs_review={needs_review}")


# Case 1: everything good — should stay high, matches your real test results so far
run_case("Clean answer", ocr_legibility="clear", llm_confidence=98, score=2.0, max_score=2.0)

# Case 2: illegible OCR + low LLM confidence + boundary-risk score — should drop hard
run_case("Worst case", ocr_legibility="illegible", llm_confidence=30, score=1.0, max_score=2.0)

# Case 3: partial legibility only, everything else fine — isolates the OCR signal's real weight
run_case("Partial OCR only", ocr_legibility="partial", llm_confidence=95, score=2.0, max_score=2.0)

# Case 4: boundary-risk score only, everything else fine — isolates the boundary signal's real weight
run_case("Boundary risk only", ocr_legibility="clear", llm_confidence=95, score=1.0, max_score=2.0)