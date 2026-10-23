"""Offline selective-review curves; risk is a ranking signal, not a probability."""
from services.benchmark_metrics import EPSILON, number
from services.evaluation_reliability import summarize_reliability


def review_risk_coverage(rows, *, threshold, reference_kind):
    rows = list(rows)
    summarize_reliability(rows, reference_kind=reference_kind)
    threshold = number(threshold, 'review_risk_threshold')
    if not 0 <= threshold <= 1:
        raise ValueError('Review risk threshold must be in [0, 1].')
    for row in rows:
        if type(row.get('hard_review_required')) is not bool:
            raise ValueError('Declare deterministic hard review gates.')
        if row['hard_review_required'] and not row['needs_review']:
            raise ValueError('A hard gate cannot have needs_review=false.')
        risk = row.get('review_risk')
        if risk is not None and not 0 <= number(risk, 'review_risk') <= 1:
            raise ValueError('Review risk must be in [0, 1] or null.')
    eligible = [r for r in rows if r['status'] == 'scored'
                and not r['hard_review_required'] and r.get('review_risk') is not None]
    scored = [r for r in rows if r['status'] == 'scored']
    total_errors = sum(abs(r['score'] - r['reference_score']) > EPSILON for r in scored)

    def point(cutoff):
        retained = [r for r in eligible if cutoff is not None and float(r['review_risk']) <= cutoff]
        errors = [abs(r['score'] - r['reference_score'])/r['max_score'] for r in retained]
        wrong = sum(e > EPSILON/r['max_score'] for e, r in zip(errors, retained))
        reviewed_scored = len(scored)-len(retained)
        captured = total_errors-wrong
        return dict(threshold=cutoff, retained_count=len(retained),
            coverage_over_scheduled=len(retained)/len(rows) if rows else None,
            coverage_among_scored=len(retained)/len(scored) if scored else None,
            retained_disagreement_count=wrong, retained_disagreement_rate=wrong/len(retained) if retained else None,
            retained_normalized_mae=sum(errors)/len(errors) if errors else None,
            worst_retained_normalized_error=max(errors) if errors else None,
            review_or_unavailable_count=len(rows)-len(retained),
            review_or_unavailable_rate=(len(rows)-len(retained))/len(rows) if rows else None,
            review_precision_for_disagreement=captured/reviewed_scored if reviewed_scored else None,
            disagreement_recall=captured/total_errors if total_errors else None)

    cutoffs = sorted({float(r['review_risk']) for r in eligible})
    return dict(risk_direction='larger_requires_more_review', risk_is_calibrated_probability=False,
        missing_risk_scored_count=sum(r.get('review_risk') is None for r in scored),
        hard_gate_scored_count=sum(r['hard_review_required'] for r in scored),
        operating_point=point(threshold), curve=[point(None)]+[point(t) for t in cutoffs],
        threshold_selected_from_this_report=False,
        interpretation='Threshold was declared before reporting. Ties enter together. Hard gates, unavailable '
            'runs and missing risk cannot be retained. Curves are descriptive; retained means proposed without '
            'additional review in this simulation, never permission to finalize grades.')
