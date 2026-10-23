"""Authenticated saved-study review. No inference, final grades or mutable history.

Trusted local imports bind each archive to an institution and existing exams.
Rubric editing uses the ordinary rubric-version APIs, not this read-only archive.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from models import Exam, Question, RubricVersion

ARCHIVE_ROOT = Path(__file__).resolve().parents[1]/'storage/pilot_archives'
IDENTIFIER = re.compile(r'^[A-Za-z0-9_.-]{1,100}$')


def _identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or value in {'.','..'}:
        raise ValueError('Invalid pilot identifier.')
    return value


def _file(base, relative):
    base = Path(base).resolve()
    path = (base/relative).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError('Invalid archive file.')
    return path


def _read(path, expected=None):
    content = path.read_bytes()
    if expected is not None and (not isinstance(expected,str) or not re.fullmatch(r'[a-f0-9]{64}',expected)
            or hashlib.sha256(content).hexdigest() != expected):
        raise ValueError('Saved pilot data changed. Reconcile the import before viewing it.')
    return json.loads(content)


def owned_archive(db, user, study_id):
    base = ARCHIVE_ROOT/_identifier(user.institution_id)/_identifier(study_id)
    manifest = _read(base/'manifest.json')
    if manifest.get('institution_id') != user.institution_id or manifest.get('study_id') != study_id:
        raise FileNotFoundError('Pilot not found.')
    ids = manifest['exam_ids']
    exams = db.query(Exam).filter(Exam.id.in_(ids), Exam.institution_id == user.institution_id).all()
    if not ids or {e.id for e in exams} != set(ids):
        raise FileNotFoundError('Pilot not found.')
    return base, manifest


def list_archives(db, user):
    directory = ARCHIVE_ROOT/_identifier(user.institution_id)
    items = []
    if directory.is_dir():
        for path in sorted(directory.glob('*/manifest.json')):
            try:
                _, manifest = owned_archive(db, user, path.parent.name)
                items.append({k: manifest[k] for k in ('study_id', 'title', 'paper_count', 'answer_count', 'exam_ids')})
            except (FileNotFoundError, ValueError, KeyError):
                continue
    return {'items': items}


def paper_review(answers, total):
    """Paper status is the union of observed gates, not a confidence cutoff.

    A matching historical total cannot clear an evidence/criterion conflict.
    Lack of instructor finalization is shown separately, not counted as an error.
    """
    reasons, flagged, unresolved = Counter(), 0, 0
    for answer in answers:
        codes = set(answer.get('review_reasons') or [])
        if answer.get('score') is None:
            codes.add('unresolved_marks')
            unresolved += 1
        if answer.get('rubric_changed_since_run'):
            codes.add('rubric_changed_since_saved_grading')
        if answer.get('needs_review') or codes:
            flagged += 1
            reasons.update(codes or ['recorded_review_flag'])
    if total.get('point_proposal') is None:
        reasons['unresolved_paper_total'] += 1
    return dict(needs_review=bool(reasons or flagged), flagged_answer_count=flagged,
        unresolved_answer_count=unresolved, reasons=[dict(code=k, count=v) for k, v in sorted(reasons.items())],
        instructor_finalized=False, status='needs_review' if reasons or flagged else 'no_recorded_issue',
        interpretation='Recorded review gates, not a calibrated probability. No recorded issue does not approve a paper.')


def _rubric_changes(db, user, manifest):
    questions = db.query(Question).filter(Question.exam_id.in_(manifest['exam_ids']),
        Question.institution_id == user.institution_id).all()
    changed = set()
    for question in questions:
        original = manifest['question_versions'].get(question.id)
        if not original or question.active_rubric_version_id != original:
            changed.add(question.id)
    return changed


def study_detail(db, user, study_id):
    base, manifest = owned_archive(db, user, study_id)
    changed = _rubric_changes(db, user, manifest)
    papers = []
    for entry in manifest['papers']:
        paper = _read(_file(base, entry['file']), entry['sha256'])
        for answer in paper['answers']:
            answer['rubric_changed_since_run'] = answer['question_id'] in changed
        papers.append(dict(paper_id=paper['paper_id'], label=paper['label'], exam_version=paper['exam_version'],
            exam_id=paper['exam_id'], answer_count=len(paper['answers']), total=paper['total'],
            review=paper_review(paper['answers'], paper['total'])))
    return dict(study_id=study_id, title=manifest['title'], papers=papers,
        answer_count=manifest['answer_count'], question_count=len(manifest['question_versions']),
        reference_comparison=manifest.get('reference_comparison', []),
        finalized=False, new_inference_performed=False,
        note='Saved pilot proposals. MCQ readings and source evidence may still need review. '
             'Paper totals retain the original study caps/bounds. Rubric edits do not regrade saved answers.')


def paper_detail(db, user, study_id, paper_id):
    base, manifest = owned_archive(db, user, study_id)
    entry = next((p for p in manifest['papers'] if p['paper_id']==paper_id), None)
    if not entry:
        raise FileNotFoundError('Paper not found.')
    paper = _read(_file(base, entry['file']), entry['sha256'])
    changed = _rubric_changes(db, user, manifest)
    for answer in paper['answers']:
        answer['rubric_changed_since_run'] = answer['question_id'] in changed
        if answer['rubric_changed_since_run']:
            from services.review_explanation_service import explain_review
            answer['recorded_needs_review'] = answer['needs_review']
            answer['needs_review'] = True
            report = answer.get('review_explanation') or {}
            new = explain_review(needs_review=True, codes=['rubric_changed_since_saved_grading'])
            answer['review_explanation'] = {**new, 'items': [*(report.get('items') or []), *new['items']]}
    result = {k: deepcopy(v) for k, v in paper.items() if k not in {'pages', 'original_document'}}
    result['review'] = paper_review(paper['answers'], paper['total'])
    result['page_count'] = len(paper['pages'])
    return result


def page_file(db, user, study_id, paper_id, index):
    base, manifest = owned_archive(db, user, study_id)
    entry = next((p for p in manifest['papers'] if p['paper_id']==paper_id), None)
    if not entry:
        raise FileNotFoundError('Paper not found.')
    paper = _read(_file(base, entry['file']), entry['sha256'])
    if type(index) is not int or not 0 <= index < len(paper['pages']):
        raise FileNotFoundError('Page not found.')
    page = paper['pages'][index]
    path = _file(base, page['file'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != page['sha256']:
        raise ValueError('Original page fingerprint changed.')
    return path
