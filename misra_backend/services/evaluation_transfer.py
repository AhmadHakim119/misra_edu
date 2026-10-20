"""Subject-independent offline transfer metrics. No inference or grade mutation.

Exposure metadata is required: cleaning an answer does not make it held out.
Report each prescheduled pipeline/repeat separately; never select a best repeat.
"""
from collections import defaultdict
import random

from services.benchmark_metrics import EPSILON, identifier, number, on_grid
from services.evaluation_reliability import summarize_reliability


EXPOSURE_FIELDS = ('answer_previously_used', 'question_previously_used', 'student_previously_used')
INPUT_MODES = {'checked_text', 'raw_ocr', 'reviewed_ocr'}
REFERENCE_KINDS = {'historical_teacher', 'instructor_adjudicated'}


def _exposure(row):
    if row['answer_previously_used']:
        return 'reused_answer_regression'
    if row['student_previously_used']:
        return ('new_answer_reused_student_known_question' if row['question_previously_used']
                else 'new_answer_reused_student_new_question')
    return ('new_student_known_question' if row['question_previously_used']
            else 'new_student_new_question')


def _bootstrap(rows, field, *, samples, seed):
    """Preserve within-cluster dependence, including unavailable attempts.

    Student and question bootstrap intervals are separate descriptions, not an
    independence guarantee or a simultaneous two-way confidence interval.
    """
    clusters = defaultdict(list)
    for row in rows:
        key = row['group_id'] if field == 'student' else (row['subject_id'], row['question_id'])
        exact = row['status'] == 'scored' and abs(number(row['score'], 'score') - number(row['reference_score'], 'reference_score')) <= EPSILON
        clusters[key].append(int(exact))
    if len(clusters) < 2:
        return {'cluster_count':len(clusters), 'interval_95':None,
                'reason':'At least two clusters are required.'}
    blocks = list(clusters.values())
    rng = random.Random(seed)
    rates = []
    for _ in range(samples):
        drawn = [rng.choice(blocks) for _ in blocks]
        rates.append(sum(sum(block) for block in drawn) / sum(len(block) for block in drawn))
    rates.sort()
    return {'cluster_count':len(blocks), 'interval_95':{
        'lower':rates[int((samples-1)*.025)], 'upper':rates[int((samples-1)*.975)]},
        'samples':samples, 'seed':seed,
        'method':f'Percentile bootstrap of {field} clusters; descriptive, one clustering axis at a time.'}


def summarize_transfer(rows, *, target=.8, bootstrap_samples=2000, seed=171):
    """One record per answer in ONE frozen pipeline, repeat and input mode.

    References and exposure are local audit metadata, never provider inputs.
    score_step defines a secondary within-one-step metric, not exact agreement.
    Group IDs must already be checked across the entire study, not just a PDF.
    No confidence mapping is fitted and no decision threshold is selected here.
    """
    if type(bootstrap_samples) is not int or not 100 <= bootstrap_samples <= 10000:
        raise ValueError('Use 100 to 10000 prescheduled bootstrap samples.')
    if type(seed) is not int:
        raise ValueError('A fixed integer seed is required.')
    rows = list(rows)
    base = summarize_reliability(rows, target=target)
    scales, assignments, question_exposure = {}, {}, {}
    modes = set()
    for row in rows:
        for field in ('subject_id', 'question_id', 'group_id'):
            identifier(row.get(field), field)
        for field in EXPOSURE_FIELDS:
            if type(row.get(field)) is not bool:
                raise ValueError('Explicit answer, question and student exposure checks are required.')
        if row['answer_previously_used'] and not (row['question_previously_used'] and row['student_previously_used']):
            raise ValueError('A reused answer also exposes its question and student.')
        if row.get('group_checked') is not True:
            raise ValueError('Student grouping must be explicitly checked.')
        if row.get('input_mode') not in INPUT_MODES:
            raise ValueError('Declare the actual grading input stage.')
        modes.add(row['input_mode'])
        if row.get('reference_kind') not in REFERENCE_KINDS:
            raise ValueError('Keep historical and adjudicated reference provenance explicit.')
        maximum = number(row['max_score'], 'max_score')
        step = number(row.get('score_step'), 'score_step')
        if step <= 0 or not on_grid(maximum,step) or not on_grid(number(row['reference_score'],'reference_score'), step):
            raise ValueError('Reference scale must lie on the declared score grid.')
        if row['status']=='scored' and not on_grid(number(row['score'],'score'), step):
            raise ValueError('Proposal must lie on the declared score grid.')
        key = (row['subject_id'], row['question_id'])
        if scales.setdefault(key,(maximum,step)) != (maximum,step):
            raise ValueError('A question has inconsistent score scales.')
        if question_exposure.setdefault(key,row['question_previously_used']) != row['question_previously_used']:
            raise ValueError('Question exposure must be consistent across answers.')
        if assignments.setdefault(row['group_id'],row['student_previously_used']) != row['student_previously_used']:
            raise ValueError('Student exposure must be consistent across questions.')
    if len(modes)>1:
        raise ValueError('Report raw OCR and checked-text grading in separate reports.')

    def summary(values):
        result=summarize_reliability(values,target=target)
        kinds={r['reference_kind'] for r in values}
        result['event']=('exact_historical_reference_agreement' if kinds=={'historical_teacher'}
            else 'exact_instructor_adjudicated_reference_agreement' if kinds=={'instructor_adjudicated'}
            else 'exact_mixed_reference_agreement' if kinds else 'exact_reference_agreement')
        if kinds != {'historical_teacher'}:
            result['interpretation']='Agreement with the declared local reference labels. Reference provenance is reported separately; this is not instructor satisfaction or automatic finalization.'
        return result

    base=summary(rows)
    def grouped(key_fn):
        groups = defaultdict(list)
        for row in rows:
            groups[key_fn(row)].append(row)
        return {key:summary(values) for key,values in sorted(groups.items())}

    by_question = grouped(lambda r:(r['subject_id'],r['question_id']))
    by_subject = grouped(lambda r:r['subject_id'])
    within_step = sum(row['status']=='scored' and abs(number(row['score'],'score')-number(row['reference_score'],'reference_score')) <= number(row['score_step'],'score_step')+EPSILON for row in rows)
    return {'metric_version':'2026-10-19.transfer.v2', 'overall':base,
        'input_mode':next(iter(modes)) if modes else None,
        'question_count':len(by_question), 'student_group_count':len(assignments),
        'subject_count':len(by_subject),
        'question_macro_exact_yield':sum(r['exact_rate_over_scheduled'] for r in by_question.values())/len(by_question) if by_question else None,
        'subject_macro_exact_yield':sum(r['exact_rate_over_scheduled'] for r in by_subject.values())/len(by_subject) if by_subject else None,
        'all_questions_reach_target_descriptively':all(r['target_met_descriptively'] for r in by_question.values()) if by_question else None,
        'within_one_score_step_yield':within_step/len(rows) if rows else None,
        'questions':[dict(subject_id=k[0],question_id=k[1],metrics=v) for k,v in by_question.items()],
        'subjects':[dict(subject_id=k,metrics=v) for k,v in by_subject.items()],
        'exposure_groups':grouped(_exposure),
        'reference_kinds':grouped(lambda r:r['reference_kind']),
        'student_cluster_bootstrap':_bootstrap(rows,'student',samples=bootstrap_samples,seed=seed),
        'question_cluster_bootstrap':_bootstrap(rows,'question',samples=bootstrap_samples,seed=seed),
        'confidence_calibrated':False,
        'interpretation':'Exact agreement, within-step agreement, review capture and OCR fidelity are distinct events. '
            'Report each frozen pipeline/repeat separately. Macro averages prevent large questions or subjects from dominating. '
            'Exposure groups do not establish independence from unknown external use. Cluster intervals are descriptive; '
            'a small physics study cannot establish calibration or reliability for other subjects.'}
