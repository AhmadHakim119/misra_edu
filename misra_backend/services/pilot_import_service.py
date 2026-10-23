"""Install saved study definitions into normal versioned authoring, without grades."""
from datetime import datetime, timezone
import uuid

from models import Course, Exam, Question, RubricVersion, AnswerKeyVersion
from schemas.rubric_v2 import RubricV2
from services.benchmark_metrics import snapshot_hash


def archive_id(institution_id, study_id, kind, source_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'misra-pilot/{institution_id}/{study_id}/{kind}/{source_id}'))


def install_definitions(db, user, definitions, *, study_id, title):
    """Caller commits once. Never update an existing guide, answer or instructor mark.

    Imported approval is the explicitly supplied historical approval, not a new
    instructor decision. Import attribution is recorded separately in the notes.
    """
    if not definitions or len({q['source_id'] for q in definitions}) != len(definitions):
        raise ValueError('Require unique imported questions.')
    parsed = []
    for q in definitions:
        if q.get('historically_approved') is not True or not q.get('approval_provenance'):
            raise ValueError('Imported definitions require exact prior approval provenance.')
        parsed.append((q, RubricV2.model_validate(q['rubric']).model_dump()))
    course_id = archive_id(user.institution_id, study_id, 'course', 'physics')
    course = db.get(Course, course_id)
    if course and course.institution_id != user.institution_id:
        raise ValueError('Import ownership conflict.')
    if not course:
        db.add(Course(id=course_id, institution_id=user.institution_id, teacher_id=user.id,
            course_code='GPHY171', title=title, term='Saved pilot studies'))
        db.flush()
    exam_ids, question_ids, versions = {}, {}, {}
    for index, (source, rubric) in enumerate(parsed):
        year = source['exam_version']
        exam_id = archive_id(user.institution_id, study_id, 'exam', year)
        exam = db.get(Exam, exam_id)
        if not exam:
            exam = Exam(id=exam_id, institution_id=user.institution_id, course_id=course_id,
                title=f'Physics {year} · saved pilot', language='en')
            db.add(exam); db.flush()
        elif exam.institution_id != user.institution_id or exam.course_id != course_id:
            raise ValueError('Import assessment conflict.')
        exam_ids[year] = exam_id
        qid = archive_id(user.institution_id, study_id, 'question', source['source_id'])
        version_id = archive_id(user.institution_id, study_id, 'rubric-v1', source['source_id'])
        question = db.get(Question, qid)
        if question:
            original = db.get(RubricVersion, version_id)
            if (question.institution_id != user.institution_id or question.exam_id != exam_id
                    or not original or snapshot_hash(original.rubric_json) != snapshot_hash(rubric)):
                raise ValueError('Existing imported definition differs. Create a new study version; never overwrite edits.')
        else:
            question = Question(id=qid, institution_id=user.institution_id, exam_id=exam_id,
                question_number=source['number'], question_text=source['text'], max_score=rubric['max_score'],
                rubric_json=rubric, order_index=index, language='en')
            db.add(question); db.flush()
            db.add(RubricVersion(id=version_id, question_id=qid, version_number=1, schema_version=2,
                rubric_json=rubric, grading_approach=rubric['policy']['grading_approach'], source='imported',
                status='approved', created_by=user.id, approved_by=None, approved_at=None,
                change_summary='Historical approved pilot guide imported for review. '+source['approval_provenance']))
            db.flush()
            question.active_rubric_version_id = version_id
            db.add(AnswerKeyVersion(id=archive_id(user.institution_id, study_id, 'key-v1', source['source_id']),
                question_id=qid, version_number=1, status='approved', mode='reference',
                reference_text=source['answer_key'], acceptable_answers=[], document_refs=[],
                change_summary='Imported historical approved reference; no new approval or regrading.',
                created_by=user.id, approved_by=None, approved_at=None))
        question_ids[source['source_id']] = qid
        versions[qid] = version_id
    db.flush()
    return dict(course_id=course_id, exam_ids=exam_ids, question_ids=question_ids, question_versions=versions)
