"""Offline exact-agreement target and review diagnostics; never changes grades.

The default event is historical agreement. Other reference kinds must be declared
explicitly; an agent audit never becomes instructor validation. Failed/missing
requests stay in the target denominator.
Use separate reports for reused development cases and genuinely held-out cases.
"""
import math

from services.benchmark_metrics import EPSILON, number


REFERENCE_EVENTS = {
    'historical_teacher': 'exact_historical_reference_agreement',
    'instructor_adjudicated': 'exact_instructor_adjudicated_reference_agreement',
    'project_user_adjudicated': 'exact_project_user_adjudicated_reference_agreement',
    'agent_development_audit': 'exact_agent_development_audit_agreement',
}


def _reference_event(reference_kind):
    if not isinstance(reference_kind, str) or reference_kind not in REFERENCE_EVENTS:
        raise ValueError('Declare a supported reference-grade provenance.')
    return REFERENCE_EVENTS[reference_kind]


def wilson_interval(successes, count):
    """Descriptive 95% binomial interval; correlated samples need group analysis."""
    if type(count) is not int or type(successes) is not int or not 0 <= successes <= count:
        raise ValueError('Invalid success count.')
    if not count:
        return None
    z = 1.959963984540054
    rate = successes / count
    denominator = 1 + z*z/count
    center = (rate + z*z/(2*count)) / denominator
    radius = z * math.sqrt(rate*(1-rate)/count + z*z/(4*count*count)) / denominator
    return {'lower':max(0.0, center-radius), 'upper':min(1.0, center+radius),
            'method':'Wilson 95%; descriptive, assumes independent observations'}


def summarize_reliability(observations, *, target=.8, reference_kind='historical_teacher'):
    """One record per prescheduled answer, including failures and missing runs.

    Caller selects the cohort before evaluation. needs_review is the recorded
    operational flag, not a fitted confidence threshold or a success label.
    reference_kind describes the supplied labels; it neither approves nor checks
    them. The historical default preserves existing callers and saved meanings.
    """
    event = _reference_event(reference_kind)
    target = number(target, 'target')
    if not 0 < target <= 1:
        raise ValueError('Target must be in (0, 1].')
    ids, scored, unavailable = set(), [], 0
    for row in observations:
        identity = row.get('answer_id')
        if not isinstance(identity, str) or not identity.strip() or identity in ids:
            raise ValueError('Every scheduled answer needs a unique identifier.')
        ids.add(identity)
        maximum = number(row.get('max_score'), 'max_score')
        reference = number(row.get('reference_score'), 'reference_score')
        if maximum <= 0 or not 0 <= reference <= maximum:
            raise ValueError('Invalid reference scale.')
        if type(row.get('needs_review')) is not bool:
            raise ValueError('Record the actual review flag.')
        if row.get('status') not in {'scored','failed','missing','abstained'}:
            raise ValueError('Unknown evaluation status.')
        if row['status'] != 'scored':
            if row.get('score') is not None:
                raise ValueError('Unavailable runs cannot have numeric scores.')
            unavailable += 1
            continue
        score = number(row.get('score'), 'score')
        if not 0 <= score <= maximum:
            raise ValueError('Score is outside the reference scale.')
        scored.append((score-reference, maximum, row['needs_review']))
    count, valid = len(ids), len(scored)
    exact = sum(abs(error) <= EPSILON for error, _, _ in scored)
    errors = valid-exact
    flagged = sum(flag for _, _, flag in scored)
    captured = sum(abs(error) > EPSILON and flag for error, _, flag in scored)
    unflagged = valid-flagged
    rate = exact/count if count else None
    interval = wilson_interval(exact, count)
    interpretation = (
        'Flagging a disagreement does not make its grade correct. Historical labels may differ from the approved guide. This report never authorizes automatic finalization.'
        if reference_kind == 'historical_teacher' else
        'Agreement with the declared reference grades, not instructor satisfaction or automatic finalization. '
        + ('Agent audit labels are development evidence, not independent human adjudication.'
           if reference_kind == 'agent_development_audit' else
           'Project-user adjudication is distinct from instructor adjudication.'
           if reference_kind == 'project_user_adjudicated' else
           'Instructor adjudication applies only to the supplied labels; it does not establish reliability on other answers.')
    )
    return {'event':event, 'target':target,
        'scheduled_count':count, 'scored_count':valid, 'unavailable_count':unavailable,
        'exact_count':exact, 'exact_rate_over_scheduled':rate,
        'exact_rate_among_scored':exact/valid if valid else None,
        'target_met_descriptively':rate >= target if count else None,
        'interval_95':interval,
        'interval_lower_reaches_target':interval['lower'] >= target if interval else None,
        'mae_marks_among_scored':sum(abs(e) for e, _, _ in scored)/valid if valid else None,
        'normalized_mae_among_scored':sum(abs(e)/m for e, m, _ in scored)/valid if valid else None,
        'bias_marks_among_scored':sum(e for e, _, _ in scored)/valid if valid else None,
        'review_count_among_scored':flagged, 'review_rate_among_scored':flagged/valid if valid else None,
        'review_or_unavailable_rate':(flagged+unavailable)/count if count else None,
        'disagreement_count':errors, 'disagreements_flagged':captured,
        'disagreement_recall':captured/errors if errors else None,
        'review_precision_for_disagreement':captured/flagged if flagged else None,
        'unflagged_scored_count':unflagged, 'unflagged_disagreement_count':errors-captured,
        'unflagged_disagreement_rate':(errors-captured)/unflagged if unflagged else None,
        'confidence_calibrated':False,
        'interpretation':interpretation}


def summarize_replicates(replicates, *, target=.8, reference_kind='historical_teacher'):
    """Compare prescheduled repeats without pooling correlated answer copies.

    Each repeat must contain the same answers, reference scores and score scales.
    A failed repeat cannot establish a stable or consistently exact grade. Repeats
    characterize variation; they do not multiply the independent sample size.
    """
    _reference_event(reference_kind)
    indexed, summaries = {}, {}
    baseline = None
    for run in replicates:
        identifier = run.get('replicate_id')
        if not isinstance(identifier, str) or not identifier.strip() or identifier in indexed:
            raise ValueError('Require unique, nonempty replicate identifiers.')
        rows = run.get('observations')
        if not isinstance(rows, list) or not rows:
            raise ValueError('Each repeat needs the same nonempty scheduled cohort.')
        summaries[identifier] = summarize_reliability(rows, target=target, reference_kind=reference_kind)
        cohort = {row['answer_id']:(number(row['reference_score'], 'reference_score'),
                                   number(row['max_score'], 'max_score')) for row in rows}
        if baseline is not None and cohort != baseline:
            raise ValueError('Repeat cohorts, reference scores and scales must match.')
        baseline = cohort
        indexed[identifier] = {row['answer_id']:row for row in rows}
    if not indexed:
        raise ValueError('At least one prescheduled repeat is required.')
    answers = []
    for identifier, (reference, _) in baseline.items():
        rows = [run[identifier] for run in indexed.values()]
        complete = all(row['status']=='scored' for row in rows)
        scores = [number(row['score'], 'score') for row in rows] if complete else []
        answers.append({'answer_id':identifier, 'all_repeats_scored':complete,
            'score_range':{'minimum':min(scores),'maximum':max(scores)} if complete else None,
            'score_stable':complete and max(scores)-min(scores)<=EPSILON,
            'exact_in_every_repeat':complete and all(abs(score-reference)<=EPSILON for score in scores)})
    count = len(answers)
    exact = sum(row['exact_in_every_repeat'] for row in answers)
    return {'per_replicate':summaries, 'replicate_count':len(indexed),
        'unique_answer_count':count, 'independent_sample_size_not_multiplied':True,
        'score_stable_answer_count':sum(row['score_stable'] for row in answers),
        'consistently_exact_answer_count':exact, 'consistently_exact_rate':exact/count,
        'target_met_in_every_replicate':all(r['target_met_descriptively'] for r in summaries.values()),
        'answers':answers,
        'interpretation':'Repeated outputs are correlated observations of the same answers, not a larger held-out cohort. No best-repeat or higher-score selection is applied.'}
