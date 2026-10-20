"""Offline extraction-fidelity and review-signal metrics, separate from grades.

Labels must come from local comparison with actual student work. JSON validity,
OCR confidence and a matching grade are not fidelity labels. No thresholds fit.
"""


def summarize_extraction_review(rows):
    """One row per prescheduled answer; failures/ambiguities stay in the yield.

    status: reviewed | unavailable | needs_adjudication
    grade_sensitive_error: a checked bool for reviewed rows, otherwise None
    ocr_reported_uncertainty: bool for available outputs, None for unavailable
    """
    seen = set()
    reviewed = []
    unavailable = pending = 0
    for row in rows:
        identifier = row.get('answer_id')
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError('Extraction metrics require unique scheduled answer identifiers.')
        seen.add(identifier)
        status = row.get('status')
        error = row.get('grade_sensitive_error')
        flagged = row.get('ocr_reported_uncertainty')
        if status == 'reviewed':
            if type(error) is not bool or type(flagged) is not bool:
                raise ValueError('Reviewed extraction rows need checked error and uncertainty booleans.')
            reviewed.append((error, flagged))
        elif status in {'unavailable', 'needs_adjudication'}:
            if error is not None:
                raise ValueError('Unavailable or unresolved extraction cannot be labeled error-free.')
            if status == 'unavailable':
                if flagged is not None:
                    raise ValueError('Unavailable extraction has no observed uncertainty signal.')
                unavailable += 1
            else:
                if type(flagged) is not bool:
                    raise ValueError('Unresolved available extraction needs its observed uncertainty signal.')
                pending += 1
        else:
            raise ValueError('Unknown extraction review status.')
    scheduled = len(seen)
    count = len(reviewed)
    errors = sum(error for error, _ in reviewed)
    flagged = sum(flag for _, flag in reviewed)
    captured = sum(error and flag for error, flag in reviewed)
    silent = errors - captured
    ratio = lambda numerator, denominator: numerator / denominator if denominator else None
    return {
        'event': 'locally_reviewed_grade_sensitive_extraction_issue',
        'scheduled_count': scheduled,
        'conclusively_reviewed_count': count,
        'unavailable_count': unavailable,
        'adjudication_pending_count': pending,
        'grade_sensitive_error_count': errors,
        'error_rate_among_conclusively_reviewed': ratio(errors, count),
        'error_free_yield_over_scheduled': ratio(count - errors, scheduled),
        'reported_uncertainty_count_among_reviewed': flagged,
        'reported_uncertainty_rate_among_reviewed': ratio(flagged, count),
        'material_errors_with_reported_uncertainty': captured,
        'uncertainty_recall_for_material_error': ratio(captured, errors),
        'uncertainty_precision_for_material_error': ratio(captured, flagged),
        'silent_material_error_count': silent,
        'silent_material_error_rate_over_scheduled': ratio(silent, scheduled),
        'confidence_calibrated': False,
        'interpretation': 'Counts qualitative extraction issues and presence of an OCR uncertainty flag. '
            'Not character accuracy, grade accuracy or proof a warning identifies the correct glyph. '
            'Unknown/failing rows remain in scheduled yield; no reference grade or confidence fit is used.',
    }
