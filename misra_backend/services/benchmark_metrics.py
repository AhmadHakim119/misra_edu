"""Offline thesis metrics. No database writes, inference, or operational grade changes.

Reference labels and model predictions are separate inputs. Fitting uses only the
calibration partition; held-out results never select a threshold or calibrator.
"""
from collections import Counter, defaultdict
from bisect import bisect_right
from dataclasses import dataclass
from dataclasses import asdict
import hashlib
import json
import math
import random


CONDITIONS = ('no_rag', 'bm25')
SPLITS = ('development', 'calibration', 'test')
EPSILON = 1e-6
METRIC_VERSION = '2026-10-17.v1'


def snapshot_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def number(value, name):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be a finite number, not a boolean.')
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a finite number.') from None
    if not math.isfinite(result):
        raise ValueError(f'{name} must be a finite number.')
    return result


def digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Snapshot fingerprints must be lowercase SHA-256 values.')
    return value


def identifier(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} is required.')
    return value


def on_grid(value, step):
    return abs(value / step - round(value / step)) <= EPSILON


@dataclass(frozen=True)
class MetricPolicy:
    """Predeclared pilot settings, not evidence-based guarantees of sufficiency."""
    tolerance_steps: int = 1
    confidence_bins: int = 5
    bootstrap_samples: int = 2000
    seed: int = 171
    min_fit_answers: int = 50
    min_fit_groups: int = 10
    target_error_recall: float = .9

    def __post_init__(self):
        for name, lower, upper in [('tolerance_steps', 0, 10), ('confidence_bins', 2, 20),
                                   ('bootstrap_samples', 100, 10000), ('min_fit_answers', 2, 100000),
                                   ('min_fit_groups', 2, 10000)]:
            value = getattr(self, name)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f'Invalid {name}.')
        if type(self.seed) is not int or not 0 < number(self.target_error_recall, 'target_error_recall') <= 1:
            raise ValueError('Invalid calibration policy.')
        object.__setattr__(self,'target_error_recall',number(self.target_error_recall,'target_error_recall'))


def validate_inputs(references, predictions):
    """Reject ambiguous repetitions and leakage instead of choosing a best run."""
    refs, groups, papers, question_scales = {}, {}, {}, {}
    for raw in references:
        row = dict(raw)
        for key in ('answer_id', 'paper_id', 'group_id', 'exam_version', 'question_id'):
            identifier(row.get(key), key)
        if row.get('split') not in SPLITS:
            raise ValueError('Every reference needs a declared split.')
        for key in ('independent_reference', 'label_checked', 'input_reviewed', 'guide_checked', 'group_checked'):
            if row.get(key) is not True:
                raise ValueError(f'{row["answer_id"]}: {key} must be explicitly confirmed.')
        row['max_score'] = maximum = number(row.get('max_score'), 'max_score')
        row['score_step'] = step = number(row.get('score_step'), 'score_step')
        row['reference_score'] = human = number(row.get('reference_score'), 'reference_score')
        if maximum <= 0 or step <= 0 or not on_grid(maximum, step) or not 0 <= human <= maximum or not on_grid(human, step):
            raise ValueError('Reference marks must fit a positive, declared score scale.')
        digest(row.get('fixed_inputs_sha256'))
        if row['answer_id'] in refs:
            raise ValueError('Duplicate reference answer; resolve label revisions explicitly.')
        if groups.setdefault(row['group_id'], row['split']) != row['split']:
            raise ValueError('A student/group crosses calibration/development/test partitions.')
        paper = (row['group_id'], row['split'], row['exam_version'])
        if papers.setdefault(row['paper_id'], paper) != paper:
            raise ValueError('A paper has conflicting group, split, or exam assignments.')
        scale_key = (row['exam_version'], row['question_id'])
        if question_scales.setdefault(scale_key, (maximum, step)) != (maximum, step):
            raise ValueError('A question has conflicting score scales.')
        refs[row['answer_id']] = row
    runs, seen_runs, systems = {}, set(), {}
    common_settings=set()
    for raw in predictions:
        row = dict(raw)
        if any(key in row for key in ('human_score', 'reference_score', 'reference_text', 'student_name', 'student_number')):
            raise ValueError('Reference marks and identities do not belong in prediction inputs.')
        ref = refs.get(row.get('answer_id'))
        if ref is None:
            raise ValueError('Prediction references an unknown answer.')
        condition = row.get('condition')
        if condition not in CONDITIONS:
            raise ValueError('Unknown research condition.')
        key = (ref['answer_id'], condition)
        if key in runs:
            raise ValueError('Multiple runs for one answer/condition; preselect a repetition protocol.')
        run_id = identifier(row.get('run_id'), 'run_id')
        if run_id in seen_runs:
            raise ValueError('A run ID was reused.')
        seen_runs.add(run_id)
        if digest(row.get('fixed_inputs_sha256')) != ref['fixed_inputs_sha256']:
            raise ValueError('Frozen question/key/rubric/policy/student inputs differ.')
        system = digest(row.get('system_sha256'))
        if systems.setdefault(condition, system) != system:
            raise ValueError('Model/prompt/pipeline changed within an experimental condition.')
        # Shared provider/model/inference/verification settings across both arms.
        common_settings.add(digest(row.get('comparison_sha256')))
        if len(common_settings)>1:
            raise ValueError('Common model/prompt/inference settings changed during the experiment.')
        if condition == 'bm25':
            digest(row.get('retrieval_snapshot_sha256'))
        elif row.get('retrieval_snapshot_sha256') is not None:
            raise ValueError('No-retrieval runs cannot contain a retrieval snapshot.')
        status = row.get('status')
        if status not in ('scored', 'failed', 'abstained'):
            raise ValueError('Unknown prediction status.')
        if status == 'scored':
            row['score'] = score = number(row.get('score'), 'score')
            if not 0 <= score <= ref['max_score'] or not on_grid(score, ref['score_step']):
                raise ValueError('AI score is outside the approved score grid; do not round it silently.')
        elif row.get('score') is not None:
            raise ValueError('Failed or abstained predictions must not carry a numeric grade.')
        if row.get('confidence') is not None:
            row['confidence'] = confidence = number(row['confidence'], 'confidence')
            if not 0 <= confidence <= 100:
                raise ValueError('Raw confidence must be between 0 and 100.')
        if type(row.get('hard_review_required')) is not bool:
            raise ValueError('Record deterministic/verification review gates explicitly.')
        runs[key] = row
    for answer_id in refs:
        pair = [runs.get((answer_id, condition)) for condition in CONDITIONS]
        if all(pair) and pair[0]['comparison_sha256'] != pair[1]['comparison_sha256']:
            raise ValueError('Paired arms changed model/prompt/inference settings beyond retrieval.')
    return refs, runs


def mean(values):
    return sum(values) / len(values) if values else None


def _summary(rows, policy):
    errors = [run['score'] - ref['reference_score'] for ref, run in rows]
    normalized = [error / ref['max_score'] for error, (ref, _) in zip(errors, rows)]
    by_group = defaultdict(list)
    for error, (ref, _) in zip(normalized, rows):
        by_group[ref['group_id']].append(abs(error))
    return dict(scored_count=len(rows), group_count=len(by_group),
        mae=mean([abs(error) for error in errors]),
        rmse=math.sqrt(mean([error * error for error in errors])) if errors else None,
        normalized_mae=mean([abs(error) for error in normalized]),
        normalized_rmse=math.sqrt(mean([error * error for error in normalized])) if errors else None,
        normalized_bias=mean(normalized),
        macro_group_normalized_mae=mean([mean(values) for values in by_group.values()]),
        exact_agreement=mean([abs(error) <= EPSILON for error in errors]),
        tolerance_agreement=mean([abs(error) <= policy.tolerance_steps * ref['score_step'] + EPSILON
                                  for error, (ref, _) in zip(errors, rows)]))


def quadratic_kappa(rows):
    """Only called within one exam/question/scale; constant marginals are undefined."""
    if not rows:
        return None
    human = [ref['reference_score'] / ref['score_step'] for ref, _ in rows]
    ai = [run['score'] / ref['score_step'] for ref, run in rows]
    observed = mean([(a - b) ** 2 for a, b in zip(ai, human)])
    expected = mean([a * a for a in ai]) + mean([b * b for b in human]) - 2 * mean(ai) * mean(human)
    return 1 - observed / expected if expected > EPSILON else None


def confidence_diagnostics(rows, bins=5, probabilities=None):
    items = [(ref, run) for ref, run in rows if run.get('confidence') is not None]
    if probabilities is not None and len(probabilities)!=len(items):raise ValueError('Probability count does not match confidence observations.')
    values = [(probabilities[index] if probabilities is not None else run['confidence'] / 100,
               int(abs(run['score'] - ref['reference_score']) <= EPSILON))
              for index, (ref, run) in enumerate(items)]
    buckets = [[] for _ in range(bins)]
    for probability, event in values:
        if not 0 <= probability <= 1 or not math.isfinite(probability):
            raise ValueError('Invalid probability estimate.')
        buckets[min(bins - 1, int(probability * bins))].append((probability, event))
    curve = []
    for index, bucket in enumerate(buckets):
        curve.append({'lower':index / bins,'upper':(index + 1) / bins,'count':len(bucket),
            'mean_estimate':mean([p for p, _ in bucket]),'observed_exact_agreement':mean([y for _, y in bucket])})
    return {'event':'exact_score_agreement','observation_count':len(values),
        'missing_confidence_count':len(rows)-len(values),
        'brier_score':mean([(p-y)**2 for p,y in values]),
        'ece':sum(len(bucket)/len(values)*abs(mean([p for p,_ in bucket])-mean([y for _,y in bucket]))
                  for bucket in buckets if bucket) if values else None,
        'reliability_bins':curve,
        'interpretation':'Raw self-reported confidence is an uncalibrated estimate. Brier also reflects discrimination; neither Brier nor ECE proves calibration.'}


def _percentile(values, proportion):
    ordered=sorted(values);position=(len(ordered)-1)*proportion
    low=int(position);high=min(low+1,len(ordered)-1)
    return ordered[low]+(ordered[high]-ordered[low])*(position-low)


def paired_retrieval_effect(refs, runs, split, policy):
    groups=defaultdict(list)
    for ref in refs:
        left=runs.get((ref['answer_id'],'no_rag'));right=runs.get((ref['answer_id'],'bm25'))
        if left and right and left['status']==right['status']=='scored':
            delta=(abs(left['score']-ref['reference_score'])-abs(right['score']-ref['reference_score']))/ref['max_score']
            groups[ref['group_id']].append(delta)
    deltas=[value for values in groups.values() for value in values]
    interval=None
    if len(groups)>=2:
        rng=random.Random(policy.seed);keys=sorted(groups);samples=[]
        for _ in range(policy.bootstrap_samples):
            sampled=[value for key in rng.choices(keys,k=len(keys)) for value in groups[key]]
            samples.append(mean(sampled))
        interval={'lower':_percentile(samples,.025),'upper':_percentile(samples,.975),
                  'method':'paired_group_bootstrap_percentile','resamples':policy.bootstrap_samples,'seed':policy.seed}
    return {'split':split,'expected_answer_count':len(refs),'paired_scored_count':len(deltas),
        'unpaired_or_unscored_count':len(refs)-len(deltas),'group_count':len(groups),
        'normalized_mae_improvement':mean(deltas),'interval_95':interval,
        'interpretation':'Positive means lower error with BM25. Conditional on both arms scoring; failures are reported separately. Few groups make intervals unstable.'}


def _calibration_rows(refs,runs,condition):
    return [(ref,runs[(ref['answer_id'],condition)]) for ref in refs.values()
            if ref['split']=='calibration' and (ref['answer_id'],condition) in runs
            and runs[(ref['answer_id'],condition)]['status']=='scored'
            and runs[(ref['answer_id'],condition)].get('confidence') is not None]


def _calibration_cohort_hash(refs,runs,condition):
    """Freeze missing/failed runs too, so coverage cannot change after fitting."""
    return snapshot_hash(sorted([
        {'reference':ref,'prediction':runs.get((ref['answer_id'],condition))}
        for ref in refs.values() if ref['split']=='calibration'
    ],key=lambda item:item['reference']['answer_id']))


def fit_calibration(references,predictions,condition,policy=MetricPolicy()):
    refs,runs=validate_inputs(references,predictions)
    if condition not in CONDITIONS:raise ValueError('Unknown calibration condition.')
    rows=_calibration_rows(refs,runs,condition)
    groups={ref['group_id'] for ref,_ in rows}
    outcomes=[int(abs(run['score']-ref['reference_score'])<=EPSILON) for ref,run in rows]
    artifact={'schema_version':1,'metric_version':METRIC_VERSION,'status':'insufficient_data','condition':condition,
        'event':'exact_score_agreement','fit_split':'calibration','answer_count':len(rows),
        'group_count':len(groups),'fit_answer_ids':sorted(ref['answer_id'] for ref,_ in rows),
        'fit_group_ids':sorted(groups),'min_fit_answers':policy.min_fit_answers,'min_fit_groups':policy.min_fit_groups,
        'system_sha256':rows[0][1]['system_sha256'] if rows else None,
        'comparison_sha256':rows[0][1]['comparison_sha256'] if rows else None,
        'knots':[],'review_threshold':None,
        'interpretation':'Research-only fit. Thresholds never approve a grade or bypass review gates. Minimum sample settings are pilot safeguards, not statistical guarantees.'}
    artifact['policy']=asdict(policy)
    artifact['calibration_cohort_sha256']=_calibration_cohort_hash(refs,runs,condition)
    artifact['fit_data_sha256']=snapshot_hash(sorted([{'reference':ref,'prediction':run} for ref,run in rows],key=lambda item:item['reference']['answer_id']))
    if len(rows)<policy.min_fit_answers or len(groups)<policy.min_fit_groups or len(set(outcomes))<2:
        artifact['reason']='Need more calibration answers/groups and both exact and nonexact outcomes.'
        return artifact
    ties=defaultdict(list)
    for (_,run),outcome in zip(rows,outcomes):ties[run['confidence']/100].append(outcome)
    if len(ties)<2:
        artifact['reason']='Confidence is constant; a confidence-dependent mapping cannot be fitted.'
        return artifact
    # Weighted pool-adjacent-violators; equal confidence values stay together.
    blocks=[]
    for x,ys in sorted(ties.items()):
        blocks.append({'xs':[x],'sum':sum(ys),'weight':len(ys)})
        while len(blocks)>1 and blocks[-2]['sum']/blocks[-2]['weight']>blocks[-1]['sum']/blocks[-1]['weight']:
            right=blocks.pop();left=blocks.pop()
            blocks.append({'xs':left['xs']+right['xs'],'sum':left['sum']+right['sum'],'weight':left['weight']+right['weight']})
    artifact['knots']=[{'x':x,'probability':block['sum']/block['weight']} for block in blocks for x in block['xs']]
    candidates=[]
    for threshold in sorted({0.0,101.0,*[run['confidence'] for _,run in rows]}):
        flags=[run['hard_review_required'] or run['confidence']<threshold for _,run in rows]
        errors=sum(1-y for y in outcomes)
        caught=sum(flag and not outcome for flag,outcome in zip(flags,outcomes))
        recall=caught/errors
        if recall>=policy.target_error_recall:
            candidates.append({'raw_confidence_below':threshold,'calibration_review_rate':mean(flags),
                'calibration_error_recall':recall,'target_error_recall':policy.target_error_recall})
    artifact['review_threshold']=min(candidates,key=lambda item:(item['calibration_review_rate'],item['raw_confidence_below']))
    artifact['status']='fitted_unvalidated'
    return artifact


def calibrated_probability(confidence,artifact):
    if artifact.get('status')!='fitted_unvalidated' or not artifact.get('knots'):
        raise ValueError('A fitted calibration artifact is required.')
    x=number(confidence,'confidence')/100
    if not 0<=x<=1:raise ValueError('Confidence out of range.')
    knots=artifact['knots'];xs=[number(item['x'],'calibration knot') for item in knots]
    ps=[number(item['probability'],'calibration probability') for item in knots]
    if any(not 0<=v<=1 for v in [*xs,*ps]) or any(a>=b for a,b in zip(xs,xs[1:])) or any(a>b for a,b in zip(ps,ps[1:])):
        raise ValueError('Calibration knots must be bounded and monotone.')
    position=bisect_right(xs,x)
    if position==0:return knots[0]['probability']
    if position==len(knots):return knots[-1]['probability']
    left,right=knots[position-1],knots[position]
    return left['probability']+(right['probability']-left['probability'])*(x-left['x'])/(right['x']-left['x'])


def build_benchmark_report(references,predictions,policy=MetricPolicy(),calibration=None):
    refs,runs=validate_inputs(references,predictions)
    if calibration:
        if calibration.get('schema_version')!=1 or calibration.get('metric_version')!=METRIC_VERSION or calibration.get('fit_split')!='calibration' or calibration.get('event')!='exact_score_agreement' or calibration.get('condition') not in CONDITIONS or calibration.get('status') not in ('fitted_unvalidated','insufficient_data'):
            raise ValueError('Invalid calibration artifact scope.')
        forbidden={ref['group_id'] for ref in refs.values() if ref['split']=='test'}
        if forbidden.intersection(calibration.get('fit_group_ids',[])):
            raise ValueError('Calibration groups leak into the held-out test set.')
        fitted=_calibration_rows(refs,runs,calibration.get('condition'))
        fit_digest=snapshot_hash(sorted([{'reference':ref,'prediction':run} for ref,run in fitted],key=lambda item:item['reference']['answer_id']))
        if fit_digest!=calibration.get('fit_data_sha256') or asdict(policy)!=calibration.get('policy'):
            raise ValueError('Calibration data/policy changed. Keep the original fit inputs with the held-out report.')
        if _calibration_cohort_hash(refs,runs,calibration['condition'])!=calibration.get('calibration_cohort_sha256'):
            raise ValueError('Calibration cohort changed, including missing/failed runs.')
        if sorted(ref['answer_id'] for ref,_ in fitted)!=calibration.get('fit_answer_ids') or sorted({ref['group_id'] for ref,_ in fitted})!=calibration.get('fit_group_ids'):
            raise ValueError('Calibration cohort metadata does not match the fit data.')
        expected_fit=fit_calibration(references,predictions,calibration['condition'],policy)
        for key in ('status','knots','review_threshold','system_sha256','comparison_sha256'):
            if calibration.get(key)!=expected_fit[key]:
                raise ValueError('Calibration mapping/threshold differs from the frozen fit.')
    output={'schema_version':1,'metric_version':METRIC_VERSION,'metric_policy':asdict(policy),'numeric_epsilon':EPSILON,
        'purpose':'independent_reference_benchmark','confidence_status':'uncalibrated_operational_scores',
        'reference_count':len(refs),'prediction_count':len(runs),'splits':{},'calibration_artifact_status':calibration.get('status') if calibration else None,
        'notes':['Raw marks are summarized per question/scale; normalized error supports mixed maxima.',
                 'Disagreement is not measured instructor effort. Actual correction time/edits need separate workflow observations.',
                 'No live assessment, guide, grade or review threshold is changed.',
                 'Reference marks remain independent and separate from model predictions.',
                 'Bootstrap groups are verified student groups; repeats and all answers from one student stay together.',
                 'A fitted confidence mapping remains research-only until held-out evidence is reviewed.']}
    for split in SPLITS:
        selected=[ref for ref in refs.values() if ref['split']==split]
        section={'reference_count':len(selected),'group_count':len({ref['group_id'] for ref in selected}),'conditions':{}}
        for condition in CONDITIONS:
            rows=[(ref,runs[(ref['answer_id'],condition)]) for ref in selected if (ref['answer_id'],condition) in runs and runs[(ref['answer_id'],condition)]['status']=='scored']
            status=Counter(runs[(ref['answer_id'],condition)]['status'] if (ref['answer_id'],condition) in runs else 'missing' for ref in selected)
            per_question=defaultdict(list)
            for ref,run in rows:per_question[(ref['exam_version'],ref['question_id'])].append((ref,run))
            metrics=_summary(rows,policy)
            metrics.update(expected_count=len(selected),status_counts=dict(status),
                scoring_coverage=len(rows)/len(selected) if selected else None,
                exact_agreement_over_all_expected=sum(abs(run['score']-ref['reference_score'])<=EPSILON for ref,run in rows)/len(selected) if selected else None,
                confidence=confidence_diagnostics(rows,policy.confidence_bins),
                per_question=[{'exam_version':key[0],'question_id':key[1],**_summary(values,policy),
                    'quadratic_weighted_kappa':quadratic_kappa(values)} for key,values in sorted(per_question.items())])
            if calibration and calibration.get('status')=='fitted_unvalidated' and calibration.get('condition')==condition and split=='test':
                if any(run['system_sha256']!=calibration['system_sha256'] or run['comparison_sha256']!=calibration['comparison_sha256'] for _,run in rows):
                    raise ValueError('Held-out predictions use a different system from calibration.')
                confident=[(ref,run) for ref,run in rows if run.get('confidence') is not None]
                probabilities=[calibrated_probability(run['confidence'],calibration) for _,run in confident]
                metrics['calibrated_confidence']=confidence_diagnostics(rows,policy.confidence_bins,probabilities)
                threshold=calibration['review_threshold']['raw_confidence_below']
                flagged=[run['hard_review_required'] or run.get('confidence') is None or run['confidence']<threshold for _,run in rows]
                errors=[abs(run['score']-ref['reference_score'])>EPSILON for ref,run in rows]
                caught=sum(flag and error for flag,error in zip(flagged,errors))
                metrics['held_out_review_threshold']={'raw_confidence_below':threshold,'flagged_count':sum(flagged),
                    'review_rate_among_scored':mean(flagged),'error_count':sum(errors),
                    'review_rate_over_all_expected':(sum(flagged)+len(selected)-len(rows))/len(selected) if selected else None,
                    'error_recall':caught/sum(errors) if any(errors) else None,
                    'error_precision':caught/sum(flagged) if any(flagged) else None,
                    'missed_error_count':sum(error and not flag for flag,error in zip(flagged,errors))}
            section['conditions'][condition]=metrics
        section['paired_bm25']=paired_retrieval_effect(selected,runs,split,policy)
        output['splits'][split]=section
    return output
