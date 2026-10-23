"""Prospective review routing. Heuristic signals are not accuracy probabilities."""
import math

REVIEW_POLICY_VERSION = '2026-10-23.v4'


def review_decision(*, confidence, model_confidence, legibility, verification_status,
                    aggregate_discrepancy=False, require_new_review=False, decision_findings=(),
                    blended_threshold=70.0, model_threshold=95.0):
    """Do not let clear OCR compensate for uncertain assessment or an absent verifier.

    The raw floor is a conservative operational heuristic, NOT the DeepSeek
    research calibrator. That calibrator used a different signal and population.
    Thresholds only prioritize review; they never finalize an instructor grade.
    """
    def valid(value):
        return (isinstance(value, (float, int)) and not isinstance(value, bool)
                and math.isfinite(value) and 0 <= value <= 100)

    if not valid(blended_threshold) or not valid(model_threshold):
        raise ValueError('Review thresholds must be finite values between 0 and 100.')
    reasons = []
    for value, threshold, missing, low in (
        (confidence, blended_threshold, 'confidence_unavailable', 'low_blended_confidence'),
        (model_confidence, model_threshold, 'model_confidence_unavailable', 'low_model_confidence'),
    ):
        if not valid(value):
            reasons.append(missing)
        elif value < threshold:
            reasons.append(low)
    if legibility != 'clear':
        reasons.append('extraction_legibility_uncertain')
    if verification_status != 'checked':
        reasons.append('verification_flagged' if verification_status == 'needs_review'
                       else 'verification_unavailable')
    if aggregate_discrepancy:
        reasons.append('model_total_discrepancy')
    if require_new_review:
        reasons.append('corrected_extraction_review_required')
    reasons.extend(dict.fromkeys(f['code'] for f in decision_findings))
    return {'version': REVIEW_POLICY_VERSION, 'basis': 'heuristic_uncalibrated',
            'hard_gate_reasons': [r for r in reasons if r not in {'low_blended_confidence','low_model_confidence'}],
            'confidence_only_review': bool(reasons) and all(r in {'low_blended_confidence','low_model_confidence'} for r in reasons),
            'thresholds': {'blended_below': blended_threshold, 'model_below': model_threshold},
            'signals': {'blended_confidence': confidence, 'model_confidence': model_confidence,
                        'legibility': legibility, 'verification_status': verification_status},
            'criterion_findings': list(decision_findings),
            'needs_review': bool(reasons), 'reasons': reasons,
            'automatic_finalization': False}
