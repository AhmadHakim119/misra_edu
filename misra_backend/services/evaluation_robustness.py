"""Compare imported decisions on synthetic contrast pairs; never grade the text.

Unit tests use fixture decisions to test this detector. Empirical robustness needs
actual saved model decisions, with the exact same frozen grader on both sides.
"""
from services.benchmark_metrics import EPSILON, identifier, number

KINDS = {'equivalent_notation', 'paraphrase', 'changed_sign', 'negation', 'incorrect_reasoning'}


def validate_marking_bank(bank):
    if bank.get('data_kind') != 'synthetic' or bank.get('approval_status') != 'requires_instructor_approval':
        raise ValueError('This draft bank must remain explicitly synthetic and pending instructor approval.')
    guides, examples = {}, {}
    for guide in bank['guides']:
        qid = identifier(guide.get('question_id'), 'question_id')
        if qid in guides:
            raise ValueError('Duplicate synthetic guide.')
        criteria = {}
        for item in guide['criteria']:
            cid = identifier(item.get('criterion_id'), 'criterion_id')
            points = number(item.get('max_score'), 'criterion max_score')
            if cid in criteria or points <= 0:
                raise ValueError('Invalid synthetic rubric.')
            criteria[cid] = points
        if abs(sum(criteria.values())-number(guide['max_score'], 'max_score')) > EPSILON:
            raise ValueError('Synthetic criterion maxima must sum to the maximum.')
        guides[qid] = (guide, criteria)
    for example in bank['examples']:
        eid = identifier(example.get('answer_id'), 'answer_id')
        if eid in examples or example.get('question_id') not in guides:
            raise ValueError('Duplicate example or unknown synthetic question.')
        identifier(example.get('student_text'), 'synthetic student_text')
        identifier(example.get('rationale'), 'proposed marking rationale')
        expected = example['proposed_criterion_scores']
        criteria = guides[example['question_id']][1]
        if set(expected) != set(criteria):
            raise ValueError('Each draft example needs every proposed criterion label.')
        if any(not 0 <= number(value, 'proposed criterion score') <= criteria[cid]
               for cid, value in expected.items()):
            raise ValueError('Proposed example marks are outside the rubric.')
        examples[eid] = example
    pairs = set()
    for pair in bank['robustness_pairs']:
        pid = identifier(pair.get('pair_id'), 'pair_id')
        if pid in pairs or pair.get('kind') not in KINDS:
            raise ValueError('Duplicate pair or unknown robustness kind.')
        pairs.add(pid)
        base, variant = examples[pair['baseline']], examples[pair['variant']]
        if base['question_id'] != variant['question_id']:
            raise ValueError('Contrast pairs must use the same question and rubric.')
        changed = {cid for cid, value in base['proposed_criterion_scores'].items()
                   if abs(value-variant['proposed_criterion_scores'][cid]) > EPSILON}
        if changed != set(pair['changed_criterion_ids']):
            raise ValueError('The declared changed criteria differ from the proposed labels.')
        if (pair['kind'] in {'equivalent_notation', 'paraphrase'}) != (not changed):
            raise ValueError('Notation/paraphrase preserve marks; semantic changes must have explicit affected criteria.')
    return guides, examples


def summarize_robustness(bank, predictions, *, prediction_origin):
    guides, examples = validate_marking_bank(bank)
    if prediction_origin not in {'synthetic_fixture', 'saved_model_run'}:
        raise ValueError('Declare whether decisions came from a model or a synthetic fixture.')
    runs, results = {}, []
    for run in predictions:
        aid = run.get('answer_id')
        if aid not in examples or aid in runs:
            raise ValueError('Unknown or repeated robustness answer.')
        status = run.get('status')
        if status not in {'scored', 'failed', 'missing', 'abstained'}:
            raise ValueError('Unknown robustness prediction status.')
        expected = examples[aid]['proposed_criterion_scores']
        decisions = {}
        for item in run.get('criteria', []):
            cid = item.get('criterion_id')
            if cid not in expected or cid in decisions:
                raise ValueError('Unknown or repeated robustness criterion.')
            score = item.get('score')
            if score is not None:
                maximum = guides[examples[aid]['question_id']][1][cid]
                score = number(score, 'criterion score')
                if status != 'scored' or not 0 <= score <= maximum:
                    raise ValueError('Invalid robustness criterion score.')
            decisions[cid] = score
        complete = status == 'scored' and set(decisions) == set(expected) and all(v is not None for v in decisions.values())
        total = run.get('score')
        if status != 'scored' and total is not None:
            raise ValueError('Unavailable robustness answers cannot have a numeric total.')
        if status == 'scored':
            maximum = guides[examples[aid]['question_id']][0]['max_score']
            total = number(total, 'score')
            if not 0 <= total <= maximum or (complete and abs(sum(decisions.values())-total) > EPSILON):
                raise ValueError('Robustness criterion total differs from its proposed total.')
        runs[aid] = dict(complete=complete, decisions=decisions,
            matches=complete and all(abs(decisions[c]-value) <= EPSILON for c, value in expected.items()))
    for pair in bank['robustness_pairs']:
        baseline, variant = runs.get(pair['baseline']), runs.get(pair['variant'])
        complete = bool(baseline and variant and baseline['complete'] and variant['complete'])
        changed = None
        if complete:
            changed = sorted(cid for cid, value in baseline['decisions'].items()
                             if abs(value-variant['decisions'][cid]) > EPSILON)
        results.append(dict(pair_id=pair['pair_id'], kind=pair['kind'], complete=complete,
            observed_changed_criterion_ids=changed, expected_changed_criterion_ids=pair['changed_criterion_ids'],
            matches_proposed_expectation=bool(complete and baseline['matches'] and variant['matches'])))
    def summary(values):
        complete = sum(r['complete'] for r in values)
        passed = sum(r['matches_proposed_expectation'] for r in values)
        return dict(scheduled_pair_count=len(values), complete_pair_count=complete,
            matching_pair_count=passed, matching_rate_over_scheduled=passed/len(values) if values else None)
    return dict(summary(results), prediction_origin=prediction_origin,
        approval_status=bank['approval_status'], bank_id=bank['bank_id'], pairs=results,
        by_kind={kind: summary([r for r in results if r['kind']==kind]) for kind in sorted(KINDS)},
        interpretation='Matches draft synthetic criterion expectations. Pending instructor approval; '
            'fixture decisions test the evaluation software and do not establish model robustness or grading accuracy.')
