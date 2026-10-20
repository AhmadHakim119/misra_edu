"""Descriptive score-error direction and severity; no grades or fitted cutoffs.

Above/below a historical reference is not necessarily over/under grading: the
historical marking rule can differ from the approved guide. Callers must name
the reference provenance. Repeated or reused answers remain correlated.
"""
import math

from services.benchmark_metrics import EPSILON
from services.evaluation_reliability import summarize_reliability

VERSION = '2026-10-19.error-profile.v1'
REFERENCE_KINDS = frozenset({
    'historical', 'instructor_adjudicated', 'project_user_adjudicated',
    'agent_development_audit',
})


def summarize_error_profile(observations, *, reference_kind):
    """Keep opposing score errors visible even when their mean bias cancels.

    Errors are normalized by each answer's maximum, allowing descriptive
    comparison across score scales. The empirical distribution contains every
    observed error level; it does not select a favorable acceptance tolerance.
    Unavailable attempts stay in coverage but never become numeric errors.
    """
    if reference_kind not in REFERENCE_KINDS:
        raise ValueError('Declare the provenance of the supplied reference grades.')
    rows = list(observations)
    coverage = summarize_reliability(rows)
    groups = {key: {'count': 0, 'flagged_count': 0} for key in ('above', 'below', 'exact')}
    normalized = []
    unflagged_errors = []
    for row in rows:
        if row['status'] != 'scored':
            continue
        error = float(row['score']) - float(row['reference_score'])
        if abs(error) <= EPSILON:
            error = 0.0
        relative = error / float(row['max_score'])
        direction = 'above' if error > 0 else 'below' if error < 0 else 'exact'
        groups[direction]['count'] += 1
        groups[direction]['flagged_count'] += int(row['needs_review'])
        normalized.append(relative)
        if error and not row['needs_review']:
            unflagged_errors.append(abs(relative))
    valid = len(normalized)
    count = coverage['scheduled_count']
    for values in groups.values():
        values['rate_among_scored'] = values['count']/valid if valid else None
        values['rate_over_scheduled'] = values['count']/count if count else None
        values['review_capture_rate'] = values['flagged_count']/values['count'] if values['count'] else None
    distribution = []
    cumulative = 0
    for level in sorted(set(map(abs, normalized))):
        at_level = sum(abs(value) == level for value in normalized)
        cumulative += at_level
        distribution.append({'normalized_absolute_error': level, 'count': at_level,
            'cumulative_count': cumulative, 'cumulative_rate_among_scored': cumulative/valid})
    return {'version': VERSION, 'event': 'score_difference_against_supplied_references',
        'reference_kind': reference_kind, 'scheduled_count': count,
        'scored_count': valid, 'unavailable_count': coverage['unavailable_count'],
        'directions': groups,
        'normalized_bias_among_scored': sum(normalized)/valid if valid else None,
        'normalized_rmse_among_scored': math.sqrt(sum(v*v for v in normalized)/valid) if valid else None,
        'worst_normalized_absolute_error': max(map(abs, normalized)) if valid else None,
        'unflagged_error_count': len(unflagged_errors),
        'worst_unflagged_normalized_absolute_error': max(unflagged_errors) if unflagged_errors else None,
        'normalized_absolute_error_distribution': distribution,
        'acceptance_tolerance_fitted': False, 'confidence_calibrated': False,
        'interpretation': 'Descriptive reference differences, not correctness labels or instructor satisfaction. '
            'Unavailable attempts have no numeric error. No tolerance, confidence threshold, mark or reference was changed.'}
