"""One offline scorecard assembled from the existing metric implementations."""
from collections import defaultdict

from services.benchmark_metrics import confidence_diagnostics, number, quadratic_kappa
from services.evaluation_criteria import summarize_criteria
from services.evaluation_error_profile import summarize_error_profile
from services.evaluation_review import review_risk_coverage
from services.evaluation_reliability import REFERENCE_EVENTS
from services.evaluation_transfer import summarize_transfer

VERSION = 'offline-scorecard.v1'


def build_scorecard(rows, *, reference_kind, target=.8, review_risk_threshold=.25,
                    bootstrap_samples=2000, seed=171):
    rows = [dict(row) for row in rows]
    if not isinstance(reference_kind, str) or reference_kind not in REFERENCE_EVENTS:
        raise ValueError('Declare reference-grade provenance.')
    for row in rows:
        for name in ('max_score', 'score_step', 'reference_score'):
            row[name] = number(row.get(name), name)
        if row.get('status') == 'scored':
            row['score'] = number(row.get('score'), 'score')
        if row.get('confidence') is not None:
            row['confidence'] = number(row['confidence'], 'confidence')
    if any(r['reference_kind'] != reference_kind for r in rows):
        raise ValueError('Produce separate scorecards for different reference provenance.')
    transfer = summarize_transfer(rows, target=target, bootstrap_samples=bootstrap_samples, seed=seed)
    groups = defaultdict(list)
    for row in rows:
        if row['status'] == 'scored':
            groups[(row['subject_id'], row['question_id'])].append((row, row))
    scored_pairs = [pair for values in groups.values() for pair in values]
    for _, prediction in scored_pairs:
        confidence = prediction.get('confidence')
        if confidence is not None:
            if not 0 <= number(confidence, 'confidence') <= 100:
                raise ValueError('Confidence must be in [0, 100] or null.')
    overall = transfer['overall']
    return dict(metric_version=VERSION,
        headline=dict(name='exact_grade_agreement', reference_kind=reference_kind,
            exact_count=overall['exact_count'], scheduled_count=overall['scheduled_count'],
            rate=overall['exact_rate_over_scheduled'],
            rate_among_scored=overall['exact_rate_among_scored'], interval_95=overall['interval_95'],
            target=target, target_met_descriptively=overall['target_met_descriptively']),
        reliability=overall, transfer=transfer,
        error_profile=summarize_error_profile(rows,
            reference_kind='historical' if reference_kind=='historical_teacher' else reference_kind),
        criterion_errors=summarize_criteria(rows),
        review=review_risk_coverage(rows, threshold=review_risk_threshold, reference_kind=reference_kind),
        raw_confidence_diagnostics=confidence_diagnostics(scored_pairs),
        per_question_qwk=[dict(subject_id=s, question_id=q, scored_count=len(values),
                               qwk=quadratic_kappa(values)) for (s, q), values in sorted(groups.items())],
        unmeasured=dict(instructor_acceptance='Requires observed instructor decisions and correction time.',
            ocr_fidelity='Requires checked transcription/image comparisons; grade agreement does not measure OCR.',
            evidence_support='Citation presence alone does not establish semantic support.'),
        interpretation='Exact grade agreement is the headline; tolerance, QWK, repeat consistency and review '
            'capture are different metrics. This offline report fits no thresholds and changes no grades.')
