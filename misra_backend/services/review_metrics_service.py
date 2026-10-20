"""Supplemental operational metrics; never replace or refit a frozen benchmark."""
from services.benchmark_metrics import CONDITIONS, EPSILON, SPLITS, validate_inputs


def review_operating_metrics(references, predictions, *, condition, split, threshold):
    """Evaluate a previously chosen RAW-confidence threshold, including failures.

    No threshold search occurs here. Failed/missing/abstained runs require review,
    but have no score and therefore cannot be called correct, wrong or caught.
    Review workload is a count of prioritized answers, not measured human effort.
    """
    if condition not in CONDITIONS or split not in SPLITS:
        raise ValueError('Unknown condition or partition.')
    if (type(threshold) not in (int, float) or not 0 <= threshold <= 101):
        raise ValueError('Invalid raw-confidence threshold.')
    refs, runs = validate_inputs(references, predictions)
    selected = [ref for ref in refs.values() if ref['split'] == split]
    counts = dict(expected=len(selected), scored=0, unavailable=0, exact=0,
                  errors=0, flagged_errors=0, flagged_exact=0,
                  unflagged_errors=0, unflagged_exact=0, missing_confidence=0)
    for ref in selected:
        run = runs.get((ref['answer_id'], condition))
        if not run or run['status'] != 'scored':
            counts['unavailable'] += 1
            continue
        counts['scored'] += 1
        error = abs(run['score'] - ref['reference_score']) > EPSILON
        counts['errors' if error else 'exact'] += 1
        confidence = run.get('confidence')
        counts['missing_confidence'] += confidence is None
        flag = run['hard_review_required'] or confidence is None or confidence < threshold
        counts[('flagged_' if flag else 'unflagged_') + ('errors' if error else 'exact')] += 1

    def ratio(top, bottom):
        return top / bottom if bottom else None

    flagged = counts['flagged_errors'] + counts['flagged_exact']
    retained = counts['unflagged_errors'] + counts['unflagged_exact']
    return {'version': 'review_metrics_v2', 'condition': condition, 'split': split,
            'raw_confidence_below': threshold, 'counts': counts,
            'scoring_coverage': ratio(counts['scored'], counts['expected']),
            'exact_agreement_among_scored': ratio(counts['exact'], counts['scored']),
            'exact_yield_over_expected': ratio(counts['exact'], counts['expected']),
            'disagreement_recall': ratio(counts['flagged_errors'], counts['errors']),
            'disagreement_precision': ratio(counts['flagged_errors'], flagged),
            'review_rate_over_expected': ratio(flagged + counts['unavailable'], counts['expected']),
            'unflagged_disagreement_rate': ratio(counts['unflagged_errors'], retained),
            'unflagged_scored_count': retained,
            'interpretation': 'Descriptive priority routing; unflagged does not mean approved. '
                              'No grade accuracy change or measured time saving is implied.'}
