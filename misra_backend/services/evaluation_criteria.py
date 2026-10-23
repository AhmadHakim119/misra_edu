"""Offline criterion comparisons. Missing labels and missing decisions are not zeroes."""
from collections import defaultdict

from services.benchmark_metrics import EPSILON, identifier, number, on_grid


def criterion_pairs(row):
    """Validate rubric scales, known IDs and totals before comparing decisions.

    reference_criteria may be absent when only a total was labelled. A null
    reference_score means unlabelled, while a null/missing prediction is unassessed.
    Both remain visible in coverage. All scores use the declared criterion grid.
    """
    references = row.get('reference_criteria', [])
    predictions = row.get('criteria', [])
    if not isinstance(references, list) or not isinstance(predictions, list):
        raise ValueError('Criterion references and predictions must be arrays.')
    refs, runs = {}, {}
    for item in references:
        cid = identifier(item.get('criterion_id'), 'criterion_id')
        if cid in refs:
            raise ValueError('Duplicate reference criterion.')
        maximum = number(item.get('max_score'), 'criterion max_score')
        step = number(item.get('score_step'), 'criterion score_step')
        if maximum <= 0 or step <= 0 or not on_grid(maximum, step):
            raise ValueError('Invalid criterion score scale.')
        score = item.get('reference_score')
        if score is not None:
            score = number(score, 'criterion reference_score')
            if not 0 <= score <= maximum or not on_grid(score, step):
                raise ValueError('Criterion reference is outside its score grid.')
        refs[cid] = dict(max_score=maximum, score_step=step, reference_score=score)
    for item in predictions:
        cid = identifier(item.get('criterion_id'), 'criterion_id')
        if cid not in refs or cid in runs:
            raise ValueError('Unknown or duplicate predicted criterion; supply rubric scales even for unlabelled criteria.')
        score = item.get('score')
        if score is not None:
            score = number(score, 'criterion score')
            if row['status'] != 'scored':
                raise ValueError('Unavailable answers cannot carry criterion scores.')
            if not 0 <= score <= refs[cid]['max_score'] or not on_grid(score, refs[cid]['score_step']):
                raise ValueError('Criterion prediction is outside its score grid.')
        runs[cid] = score
    if refs:
        if abs(sum(r['max_score'] for r in refs.values()) - row['max_score']) > EPSILON:
            raise ValueError('Criterion maxima must sum to the answer maximum.')
        known_reference = sum(r['reference_score'] for r in refs.values() if r['reference_score'] is not None)
        unlabelled_maximum = sum(r['max_score'] for r in refs.values() if r['reference_score'] is None)
        if not known_reference-EPSILON <= row['reference_score'] <= known_reference+unlabelled_maximum+EPSILON:
            raise ValueError('Partial criterion references are incompatible with the reference total.')
        if all(r['reference_score'] is not None for r in refs.values()):
            if abs(sum(r['reference_score'] for r in refs.values()) - row['reference_score']) > EPSILON:
                raise ValueError('Criterion references do not sum to the reference total.')
        if len(runs) == len(refs) and all(v is not None for v in runs.values()):
            if abs(sum(runs.values()) - row['score']) > EPSILON:
                raise ValueError('Criterion predictions do not sum to the proposed total.')
        elif row['status'] == 'scored':
            known_score = sum(v for v in runs.values() if v is not None)
            unassessed_maximum = sum(ref['max_score'] for cid, ref in refs.items() if runs.get(cid) is None)
            if not known_score-EPSILON <= row['score'] <= known_score+unassessed_maximum+EPSILON:
                raise ValueError('Partial criterion predictions are incompatible with the proposed total.')
    return [(cid, ref, runs.get(cid)) for cid, ref in refs.items()]


def summarize_criteria(rows):
    """Differences against declared labels, never inferred from total agreement."""
    groups, differences, offsetting = defaultdict(list), [], []
    labelled = scheduled = 0
    answers_without_rubric = 0
    for row in rows:
        pairs = criterion_pairs(row)
        answers_without_rubric += not bool(pairs)
        scheduled += len(pairs)
        errors = []
        for cid, ref, prediction in pairs:
            label = ref['reference_score']
            labelled += label is not None
            error = None if label is None or prediction is None else prediction - label
            item = dict(answer_id=row['answer_id'], criterion_id=cid,
                        reference_score=label, score=prediction, error=error,
                        max_score=ref['max_score'])
            groups[(row['subject_id'], row['question_id'], cid)].append(item)
            if error is not None:
                errors.append(error)
                if abs(error) > EPSILON:
                    differences.append(item)
        if (row['status'] == 'scored' and abs(row['score'] - row['reference_score']) <= EPSILON
                and any(e > EPSILON for e in errors) and any(e < -EPSILON for e in errors)):
            offsetting.append(row['answer_id'])

    def summary(items):
        known = [r for r in items if r['reference_score'] is not None]
        compared = [r for r in known if r['error'] is not None]
        exact = sum(abs(r['error']) <= EPSILON for r in compared)
        return dict(scheduled_count=len(items), labelled_count=len(known), comparable_count=len(compared),
            missing_prediction_count=len(known)-len(compared),
            exact_count=exact, exact_rate_over_labelled=exact/len(known) if known else None,
            exact_rate_among_comparable=exact/len(compared) if compared else None,
            above_reference_count=sum(r['error'] > EPSILON for r in compared),
            below_reference_count=sum(r['error'] < -EPSILON for r in compared),
            points_above_reference=sum(max(0, r['error']) for r in compared),
            points_below_reference=sum(max(0, -r['error']) for r in compared),
            normalized_mae=sum(abs(r['error'])/r['max_score'] for r in compared)/len(compared) if compared else None)

    all_items = [r for values in groups.values() for r in values]
    return dict(summary(all_items), unlabelled_count=scheduled-labelled,
        answers_without_criterion_rubric_count=answers_without_rubric,
        total_agreement_with_offsetting_criterion_errors_count=len(offsetting),
        total_agreement_with_offsetting_criterion_errors=offsetting,
        differences=differences,
        per_criterion=[dict(subject_id=s, question_id=q, criterion_id=c, **summary(values))
                       for (s, q, c), values in sorted(groups.items())],
        interpretation='Above/below the supplied criterion reference, not independently established correctness. '
            'False credit and denied credit require adjudicated criterion labels. Missing labels/decisions are never zeroes.')
