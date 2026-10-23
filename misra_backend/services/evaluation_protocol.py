"""Frozen, local evaluation imports. No database, provider clients or inference.

Hashes detect accidental drift, not dishonest provenance. Exposure and approval
records must be checked by a person. Reference labels are imported only at report
time, separately from the frozen inputs and saved predictions.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from services.benchmark_metrics import (MetricPolicy, SPLITS, digest, identifier,
                                       number, on_grid, snapshot_hash)
from services.evaluation_reliability import REFERENCE_EVENTS
from services.evaluation_scorecard import build_scorecard
from services.evaluation_transfer import EXPOSURE_FIELDS, INPUT_MODES

VERSION = 'frozen-evaluation.v1'
COHORT_FIELDS = {'answer_id', 'subject_id', 'question_id', 'group_id', 'split', 'input_mode',
    'input_sha256', 'max_score', 'score_step', 'group_checked', *EXPOSURE_FIELDS}
PREDICTION_FIELDS = {'answer_id', 'run_id', 'status', 'score', 'criteria', 'needs_review',
    'hard_review_required', 'review_risk', 'confidence', 'protocol_sha256', 'input_sha256'}
LABEL_FIELDS = {'answer_id', 'reference_score', 'reference_kind', 'label_checked', 'reference_criteria'}
IMPLEMENTATION_FILES = ('benchmark_metrics.py', 'evaluation_reliability.py', 'evaluation_error_profile.py',
    'evaluation_transfer.py', 'evaluation_criteria.py', 'evaluation_review.py', 'evaluation_scorecard.py',
    'evaluation_protocol.py', 'evaluation_robustness.py')


def local_path(root, path):
    root, relative = Path(root).resolve(), Path(path)
    if relative.is_absolute():
        raise ValueError('Use a workspace-relative path for frozen artifacts.')
    resolved = (root/relative).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('Frozen artifacts must stay inside the workspace.')
    return resolved


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _unique(records, name):
    if not isinstance(records, list):
        raise ValueError(f'{name} must be an array.')
    result = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError(f'{name} records must be objects.')
        key = identifier(raw.get('answer_id'), 'answer_id')
        if key in result:
            raise ValueError(f'Duplicate {name} answer; never choose the best repeat.')
        result[key] = raw
    return result


def _validate_cohort(cohort, registry, spec):
    indexed = _unique(cohort, 'cohort')
    if not indexed:
        raise ValueError('Freeze a nonempty prescheduled cohort.')
    previous = _unique(registry, 'registry')
    previous_groups, previous_questions, previous_subjects = set(), set(), set()
    for old in previous.values():
        previous_groups.add(identifier(old.get('group_id'), 'registry group_id'))
        subject = identifier(old.get('subject_id'), 'registry subject_id')
        previous_subjects.add(subject)
        previous_questions.add((subject, identifier(old.get('question_id'), 'registry question_id')))
    groups, scales, exposure = {}, {}, {}
    for row in indexed.values():
        if set(row)-{'input_path'} != COHORT_FIELDS:
            raise ValueError('Cohort fields must match the contract; keep labels, text and identities separate.')
        for name in ('subject_id', 'question_id', 'group_id'):
            identifier(row.get(name), name)
        if row['split'] not in SPLITS or row['input_mode'] != spec['input_mode']:
            raise ValueError('Declare valid splits and one frozen input mode.')
        if row['group_checked'] is not True or any(type(row[f]) is not bool for f in EXPOSURE_FIELDS):
            raise ValueError('Check student grouping and explicit exposure metadata.')
        if row['answer_previously_used'] and not all(row[f] for f in EXPOSURE_FIELDS):
            raise ValueError('Reused answers expose their student and question.')
        if groups.setdefault(row['group_id'], row['split']) != row['split']:
            raise ValueError('A student/group crosses development/calibration/test splits.')
        maximum, step = number(row['max_score'], 'max_score'), number(row['score_step'], 'score_step')
        if maximum <= 0 or step <= 0 or not on_grid(maximum, step):
            raise ValueError('Invalid cohort score grid.')
        question = (row['subject_id'], row['question_id'])
        if scales.setdefault(question, (maximum, step)) != (maximum, step):
            raise ValueError('Question scales are inconsistent.')
        if exposure.setdefault(question, row['question_previously_used']) != row['question_previously_used']:
            raise ValueError('Question exposure must be consistent.')
        digest(row['input_sha256'])
        if spec['purpose'] != 'development' and not row.get('input_path'):
            raise ValueError('Validation needs a local immutable input packet for every answer.')
    selected = [r for r in cohort if r['split'] == spec['evaluation_split']]
    if not selected:
        raise ValueError('No answers scheduled in the declared evaluation split.')
    if spec['purpose'] != 'development':
        non_test = [r for r in cohort if r['split'] != 'test']
        known_questions = previous_questions | {(r['subject_id'], r['question_id']) for r in non_test}
        known_subjects = previous_subjects | {r['subject_id'] for r in non_test}
        for row in selected:
            if (row['answer_previously_used'] or row['answer_id'] in previous
                    or row['student_previously_used'] or row['group_id'] in previous_groups):
                raise ValueError('Held-out tests require new answers and new student groups; reuse is regression evidence.')
            question = (row['subject_id'], row['question_id'])
            if question in known_questions and not row['question_previously_used']:
                raise ValueError('Known questions must not be described as new.')
            if spec['purpose'] == 'subject_transfer' and (
                    row['subject_id'] in known_subjects or row['question_previously_used']):
                raise ValueError('Subject-transfer tests must hold out the subject and its questions.')


def freeze_protocol(spec, cohort, *, root):
    spec, cohort = deepcopy(spec), deepcopy(cohort)
    identifier(spec.get('protocol_id'), 'protocol_id')
    if spec.get('purpose') not in {'development', 'held_out_validation', 'subject_transfer'}:
        raise ValueError('Declare the evaluation purpose.')
    if spec.get('reference_kind') not in REFERENCE_EVENTS or spec.get('input_mode') not in INPUT_MODES:
        raise ValueError('Declare reference provenance and grading input mode.')
    if spec.get('evaluation_split') not in SPLITS:
        raise ValueError('Declare the evaluation split.')
    if spec.get('data_kind') not in {'synthetic', 'local_private'}:
        raise ValueError('Declare synthetic or local_private data.')
    if spec.get('prediction_origin') not in {'synthetic_fixture', 'saved_model_run'}:
        raise ValueError('Declare prediction origin; fixture scores are not model results.')
    if spec['purpose'] != 'development':
        if (spec['evaluation_split'] != 'test' or spec['data_kind'] != 'local_private'
                or spec['prediction_origin'] != 'saved_model_run'
                or spec['reference_kind'] != 'instructor_adjudicated'):
            raise ValueError('Validation requires a test split, real saved runs and instructor-adjudicated labels.')
        if spec.get('registry_complete') is not True or not spec.get('prior_registry_path'):
            raise ValueError('Validation needs a checked prior-use registry, even if empty.')
    configuration = spec.get('configuration')
    if not isinstance(configuration, dict):
        raise ValueError('Freeze the actual model, prompts, retrieval and verification settings.')
    for name in ('model_id', 'prompt_version', 'verification_version', 'calculator_version', 'review_risk_signal'):
        identifier(configuration.get(name), name)
    if not isinstance(configuration.get('inference_settings'), dict):
        raise ValueError('Freeze inference settings.')
    if not isinstance(configuration.get('retrieval'), dict):
        raise ValueError('Freeze retrieval settings.')
    identifier(configuration['retrieval'].get('strategy'), 'retrieval strategy')
    policy = spec.setdefault('metric_policy', {})
    target = number(policy.setdefault('target', .8), 'target')
    threshold = number(policy.setdefault('review_risk_threshold', .25), 'review_risk_threshold')
    if not 0 < target <= 1 or not 0 <= threshold <= 1:
        raise ValueError('Invalid target or review threshold.')
    MetricPolicy(bootstrap_samples=policy.setdefault('bootstrap_samples', 2000), seed=policy.setdefault('seed', 171))
    if set(policy) != {'target', 'review_risk_threshold', 'bootstrap_samples', 'seed'}:
        raise ValueError('Unknown metric policy fields.')
    artifacts = spec.get('artifacts')
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError('Freeze guide, course sources, policy, prompt and grading implementation files.')
    frozen_artifacts, roles, paths = [], set(), set()
    for artifact in artifacts:
        role = artifact.get('role')
        if role not in {'guide', 'source', 'policy', 'prompt', 'implementation', 'examples'}:
            raise ValueError('Unknown frozen artifact role.')
        path = local_path(root, artifact.get('path', ''))
        if str(path) in paths:
            raise ValueError('List each frozen artifact path once; combined files may use separate snapshot files.')
        paths.add(str(path)); roles.add(role)
        sha = file_sha256(path)
        approval = artifact.get('approval', {})
        if approval.get('status') not in {'approved', 'pending', 'not_required'}:
            raise ValueError('Record each artifact approval status explicitly.')
        if approval['status'] == 'approved':
            if digest(approval.get('artifact_sha256')) != sha:
                raise ValueError('Approval applies to a different artifact revision.')
            identifier(approval.get('approved_by'), 'approved_by')
            identifier(approval.get('approved_at'), 'approved_at')
        if spec['purpose'] != 'development' and role in {'guide', 'source', 'examples'}:
            if approval['status'] != 'approved' or (role == 'source' and approval.get('checked') is not True):
                raise ValueError('Guide, separately checked sources and any active examples need approval.')
        frozen_artifacts.append(dict(artifact, sha256=sha))
    if not {'guide', 'source', 'policy', 'prompt', 'implementation'} <= roles:
        raise ValueError('Missing guide, source, policy, prompt or grading implementation snapshot.')
    registry, registry_hash = [], None
    if spec.get('prior_registry_path'):
        import json
        path = local_path(root, spec['prior_registry_path'])
        registry = json.loads(path.read_text(encoding='utf-8'))
        registry_hash = file_sha256(path)
    _validate_cohort(cohort, registry, spec)
    for row in cohort:
        if row.get('input_path') and file_sha256(local_path(root, row['input_path'])) != row['input_sha256']:
            raise ValueError('Answer input packet changed after its fingerprint.')
    implementation = {name: file_sha256(Path(__file__).parent/name) for name in IMPLEMENTATION_FILES}
    baseline_hash = None
    if spec['purpose'] == 'subject_transfer':
        import json
        if not spec.get('baseline_protocol_path'):
            raise ValueError('Subject transfer needs the earlier frozen protocol as a baseline.')
        baseline = json.loads(local_path(root, spec['baseline_protocol_path']).read_text(encoding='utf-8'))
        baseline_payload = {k: v for k, v in baseline.items() if k != 'protocol_sha256'}
        baseline_hash = digest(baseline.get('protocol_sha256'))
        if snapshot_hash(baseline_payload) != baseline_hash:
            raise ValueError('Baseline protocol fingerprint is invalid.')
        if (baseline['spec']['purpose'] == 'development'
                or baseline['spec']['prediction_origin'] != 'saved_model_run'):
            raise ValueError('Subject transfer needs a validation baseline, not synthetic/development evidence.')
        baseline_subjects = {r['subject_id'] for r in baseline['cohort']}
        baseline_groups = {r['group_id'] for r in baseline['cohort']}
        for row in cohort:
            if row['split'] == spec['evaluation_split'] and (
                    row['subject_id'] in baseline_subjects or row['group_id'] in baseline_groups):
                raise ValueError('Subject transfer must hold out the subject and students from the baseline.')
        if baseline['spec']['configuration'] != configuration or baseline['spec']['metric_policy'] != policy:
            raise ValueError('Keep model/settings and metric policy frozen for subject transfer.')
        for role in ('prompt', 'implementation'):
            if ({a['sha256'] for a in baseline['artifacts'] if a['role']==role}
                    != {a['sha256'] for a in frozen_artifacts if a['role']==role}):
                raise ValueError('Keep prompts and grading implementation frozen for subject transfer.')
    payload = dict(version=VERSION, spec=spec, cohort=cohort,
        artifacts=frozen_artifacts, registry_sha256=registry_hash, metric_implementation=implementation,
        baseline_protocol_sha256=baseline_hash)
    return dict(payload, protocol_sha256=snapshot_hash(payload))


def verify_protocol(manifest, *, root):
    if manifest.get('version') != VERSION:
        raise ValueError('Unsupported frozen evaluation version.')
    payload = {k: v for k, v in manifest.items() if k != 'protocol_sha256'}
    if snapshot_hash(payload) != digest(manifest.get('protocol_sha256')):
        raise ValueError('Frozen manifest fingerprint is invalid.')
    current = freeze_protocol(manifest['spec'], manifest['cohort'], root=root)
    if current != manifest:
        raise ValueError('Frozen artifact, registry or metric implementation drift; create a new protocol version.')


def evaluate_frozen(manifest, references, predictions, *, root):
    verify_protocol(manifest, root=root)
    spec = manifest['spec']
    cohort = _unique(manifest['cohort'], 'cohort')
    refs, runs = _unique(references, 'reference'), _unique(predictions, 'prediction')
    if set(refs)-set(cohort) or set(runs)-set(cohort):
        raise ValueError('Reference or prediction is outside the prescheduled cohort.')
    run_ids = set()
    for aid, run in runs.items():
        if set(run)-PREDICTION_FIELDS:
            raise ValueError('Unknown prediction fields; keep labels, identities and text out of this import.')
        run_id = identifier(run.get('run_id'), 'run_id')
        if run_id in run_ids:
            raise ValueError('Reused run ID.')
        run_ids.add(run_id)
        if (digest(run.get('protocol_sha256')) != manifest['protocol_sha256']
                or digest(run.get('input_sha256')) != cohort[aid]['input_sha256']):
            raise ValueError('Prediction configuration or answer input fingerprint differs.')
        if run.get('status') not in {'scored', 'failed', 'missing', 'abstained'}:
            raise ValueError('Unknown prediction status.')
    rows = []
    for aid, case in cohort.items():
        if case['split'] != spec['evaluation_split']:
            continue
        ref = refs.get(aid)
        if ref is None or ref.get('label_checked') is not True:
            raise ValueError('Every scheduled evaluation answer needs a checked total label; missing labels block reporting.')
        if set(ref)-LABEL_FIELDS or ref.get('reference_kind') != spec['reference_kind']:
            raise ValueError('Reference fields or provenance differ from the frozen protocol.')
        run = runs.get(aid, dict(status='missing', score=None, needs_review=True,
                                 hard_review_required=True, review_risk=None))
        row = dict(case, **{k: v for k, v in run.items() if k not in case},
                   reference_kind=ref['reference_kind'], reference_score=ref.get('reference_score'),
                   reference_criteria=ref.get('reference_criteria', []))
        rows.append(row)
    report = build_scorecard(rows, reference_kind=spec['reference_kind'], **spec['metric_policy'])
    report.update(protocol_sha256=manifest['protocol_sha256'], protocol_id=spec['protocol_id'],
        purpose=spec['purpose'], data_kind=spec['data_kind'], prediction_origin=spec['prediction_origin'],
        evaluation_split=spec['evaluation_split'], references_sha256=snapshot_hash(references),
        predictions_sha256=snapshot_hash(predictions),
        pending_approval_roles=sorted({a['role'] for a in manifest['artifacts'] if a['approval']['status']=='pending'}),
        inference_performed=False)
    return report
