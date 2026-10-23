"""Local frozen evaluation and scorecards. Never calls a model, database or network."""
import argparse
import json
from pathlib import Path

from benchmark_cli import private_output, write_new_json
from services.evaluation_protocol import evaluate_frozen, file_sha256, freeze_protocol, local_path
from services.evaluation_robustness import summarize_robustness, validate_marking_bank


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def scorecard_markdown(report):
    def rate(value):
        return 'undefined' if value is None else f'{value:.1%}'
    h, reliability = report['headline'], report['reliability']
    risk, criteria = report['review']['operating_point'], report['criterion_errors']
    lines = ['# MISRA offline evaluation scorecard', '',
        f"Protocol: `{report['protocol_id']}`; {report['purpose']}; {report['data_kind']}; {report['prediction_origin']}.", '',
        f"**Exact grade agreement: {h['exact_count']}/{h['scheduled_count']} — {rate(h['rate'])}.**", '',
        f"Reference: {h['reference_kind']}. Scored: {reliability['scored_count']}; unavailable: {reliability['unavailable_count']}.",
        f"Exact among scored: {rate(h['rate_among_scored'])}. Question macro: {rate(report['transfer']['question_macro_exact_yield'])}; subject macro: {rate(report['transfer']['subject_macro_exact_yield'])}.", '',
        f"Criterion comparisons: {criteria['comparable_count']}/{criteria['labelled_count']} labelled; {criteria['unlabelled_count']} unlabelled. "
        f"Above reference: {criteria['above_reference_count']}; below: {criteria['below_reference_count']}. "
        f"Matching totals hiding opposing criterion errors: {criteria['total_agreement_with_offsetting_criterion_errors_count']}.", '',
        f"Frozen review threshold: {risk['threshold']}; retained coverage: {rate(risk['coverage_over_scheduled'])}; "
        f"retained disagreement: {rate(risk['retained_disagreement_rate'])}; review/unavailable workload: {rate(risk['review_or_unavailable_rate'])}.", '',
        '| Subject | Question | Exact / scheduled | Exact agreement |', '|---|---|---:|---:|']
    for question in report['transfer']['questions']:
        metrics = question['metrics']
        # IDs originate locally; avoid Markdown table/newline injection.
        subject = str(question['subject_id']).replace('|', '\\|').replace('\n', ' ')
        qid = str(question['question_id']).replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| {subject} | {qid} | {metrics['exact_count']}/{metrics['scheduled_count']} | {rate(metrics['exact_rate_over_scheduled'])} |")
    lines += ['', 'The JSON contains criterion differences, the full risk/coverage curve, error direction and size, '
              'per-question QWK, uncalibrated-confidence diagnostics and student/question cluster intervals.', '',
              'No inference, threshold fitting or grade changes were performed. Unavailable runs are not zero grades. '
              'Reused answers remain regression evidence. Instructor acceptance, OCR fidelity and semantic citation support are unmeasured.']
    if report['data_kind'] == 'synthetic':
        lines += ['', '**Synthetic software demonstration only. These percentages are not measured model accuracy.**']
    if report['pending_approval_roles']:
        lines += ['', 'Pending instructor approval: '+', '.join(report['pending_approval_roles'])+'.']
    return '\n'.join(lines)+'\n'


def write_report(root, output, report):
    directory = private_directory(root, output)
    directory.mkdir(parents=True, exist_ok=False)
    write_new_json(directory/'scorecard.json', report)
    with (directory/'scorecard.md').open('x', encoding='utf-8') as stream:
        stream.write(scorecard_markdown(report))
    return directory


def private_directory(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not any(output.is_relative_to(root/name) and output != root/name
               for name in ('private', 'evaluation-artifacts')):
        raise ValueError('Use a new directory inside ignored private/ or evaluation-artifacts/.')
    return output


def demo(root, output):
    """Manufactured decisions deliberately include errors, gates and unavailable runs."""
    root = Path(root).resolve()
    output = private_directory(root, output)
    output.mkdir(parents=True, exist_ok=False)
    (output/'inputs').mkdir()
    bank_path = root/'evaluation/synthetic/marking-bank-v1.json'
    bank = read_json(bank_path)
    guides, _ = validate_marking_bank(bank)
    paths = {}
    content = {
        'guide': {'approval_status': bank['approval_status'], 'guides': bank['guides']},
        'source': {'data_kind': 'synthetic', 'approval_status': 'requires_instructor_approval',
                   'passages': ['Acceleration is velocity change divided by elapsed time. Net force equals mass times acceleration.',
                                'Replication stores copies on multiple nodes; a surviving node can serve a copy after another fails.']},
        'policy': {'data_kind': 'synthetic', 'policies': [g['proposed_policy'] for g in bank['guides']]},
        'prompt': {'data_kind': 'synthetic', 'text': 'No model is called. Import deliberately manufactured criterion decisions.'}}
    for role, value in content.items():
        path = output/'inputs'/f'{role}.json'
        write_new_json(path, value)
        paths[role] = path.relative_to(root).as_posix()
    cohort, references = [], []
    for index, example in enumerate(bank['examples']):
        guide = guides[example['question_id']][0]
        aid = example['answer_id']
        packet = output/'inputs'/f'{aid}.json'
        write_new_json(packet, dict(answer_id=aid, question_id=guide['question_id'],
                                   question=guide['question'], student_text=example['student_text']))
        cohort.append(dict(answer_id=aid, subject_id=guide['subject_id'], question_id=guide['question_id'],
            group_id=f'synthetic-group-{index}', split='development', input_mode='checked_text',
            input_path=packet.relative_to(root).as_posix(), input_sha256=file_sha256(packet),
            max_score=guide['max_score'], score_step=guide['score_step'], group_checked=True,
            answer_previously_used=True, question_previously_used=True, student_previously_used=True))
        references.append(dict(answer_id=aid, label_checked=True, reference_kind='agent_development_audit',
            reference_score=sum(example['proposed_criterion_scores'].values()),
            reference_criteria=[dict(criterion_id=c['criterion_id'], max_score=c['max_score'], score_step=1,
                reference_score=example['proposed_criterion_scores'][c['criterion_id']]) for c in guide['criteria']]))
    spec = dict(protocol_id='synthetic-scorecard-demo-v1', purpose='development',
        data_kind='synthetic', prediction_origin='synthetic_fixture', evaluation_split='development',
        reference_kind='agent_development_audit', input_mode='checked_text',
        configuration=dict(model_id='none-synthetic-fixture', prompt_version='fixture-v1',
            verification_version='none', calculator_version='none', review_risk_signal='manufactured fixture risk; not probability', inference_settings={},
            retrieval=dict(strategy='synthetic-approved-scope-demonstration-no-inference')),
        metric_policy=dict(target=.8, review_risk_threshold=.25, bootstrap_samples=200, seed=171),
        artifacts=[dict(role=role, path=path, approval=dict(status='pending' if role in {'guide','source'} else 'not_required'))
                   for role, path in paths.items()] + [
            dict(role='examples', path=bank_path.relative_to(root).as_posix(), approval=dict(status='pending')),
            dict(role='implementation', path='misra_backend/services/grading_service.py', approval=dict(status='not_required'))])
    manifest = freeze_protocol(spec, cohort, root=root)
    predictions = []
    for example, case in zip(bank['examples'], cohort):
        aid = example['answer_id']
        if aid == 'syn-keywords':
            continue  # A scheduled missing run must remain in the denominator.
        scores = dict(example['proposed_criterion_scores'])
        if aid == 'syn-partial':
            scores.update(acceleration_method=0, force_method=1)  # Equal total, different decisions.
        if aid == 'syn-follow-through':
            scores['force_result'] = 0
        if aid == 'syn-negation':
            scores = dict(availability=1, mechanism=1)  # Deliberately missed negation.
        failed = aid == 'syn-zero'
        hard = failed or aid == 'syn-reasoning'
        risk = .8 if aid in {'syn-follow-through', 'syn-partial'} else .1
        predictions.append(dict(answer_id=aid, run_id=f'fixture-{aid}',
            protocol_sha256=manifest['protocol_sha256'], input_sha256=case['input_sha256'],
            status='failed' if failed else 'scored', score=None if failed else sum(scores.values()),
            criteria=[] if failed else [dict(criterion_id=c, score=s) for c, s in scores.items()],
            confidence=None, needs_review=hard or risk>.25, hard_review_required=hard,
            review_risk=None if failed else risk))
    for name, value in [('spec', spec), ('cohort', cohort), ('frozen', manifest),
                        ('references', references), ('predictions', predictions)]:
        write_new_json(output/f'{name}.json', value)
    report = evaluate_frozen(manifest, references, predictions, root=root)
    report['robustness'] = summarize_robustness(bank, predictions, prediction_origin='synthetic_fixture')
    return write_report(root, output/'report', report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    commands = parser.add_subparsers(dest='command', required=True)
    initial = commands.add_parser('freeze')
    initial.add_argument('--spec', type=Path, required=True)
    initial.add_argument('--cohort', type=Path, required=True)
    initial.add_argument('--output', type=Path, required=True)
    report = commands.add_parser('report')
    for name in ('manifest', 'references', 'predictions', 'output'):
        report.add_argument('--'+name, type=Path, required=True)
    report.add_argument('--robustness-bank', type=Path)
    synthetic = commands.add_parser('demo')
    synthetic.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'freeze':
            result = freeze_protocol(read_json(args.spec), read_json(args.cohort), root=args.root)
            output = private_output(args.root, args.output)
            write_new_json(output, result)
        elif args.command == 'report':
            manifest, predictions = read_json(args.manifest), read_json(args.predictions)
            result = evaluate_frozen(manifest, read_json(args.references), predictions, root=args.root)
            if args.robustness_bank:
                path = args.robustness_bank.resolve()
                if not any(a['role']=='examples' and local_path(args.root, a['path'])==path
                           for a in manifest['artifacts']):
                    raise ValueError('Robustness bank must be frozen as an examples artifact.')
                result['robustness'] = summarize_robustness(read_json(path), predictions,
                    prediction_origin=manifest['spec']['prediction_origin'])
            output = write_report(args.root, args.output, result)
        else:
            output = demo(args.root, args.output)
        print(json.dumps(dict(output=str(output), inference_performed=False)))
    except (ValueError, OSError, TypeError, KeyError) as error:
        parser.exit(2, f'{error}\n')


if __name__ == '__main__':
    main()
