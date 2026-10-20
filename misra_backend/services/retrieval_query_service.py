"""Bound concept-query proposals to exact approved question/rubric definitions.

The caller must check guide approval first. A search query is derived data, never
marking authority, a new source scope, or a student/OCR-controlled instruction.
This module performs no model call and does not select a provider.
"""
import hashlib
import json

QUERY_VERSION = '2026-10-19.concept.v1'
MAX_CONCEPT_QUERY_CHARS = 500
FIELDS = {'version', 'definition_sha256', 'query', 'generator', 'request_id'}


def definition_fingerprint(question_text, criterion):
    if not isinstance(question_text,str) or not question_text.strip():
        raise ValueError('An approved question definition is required.')
    if not isinstance(criterion,dict) or not isinstance(criterion.get('id'),str) or not criterion['id'].strip():
        raise ValueError('An approved criterion identifier is required.')
    try:
        encoded=json.dumps({'question_text':question_text,'criterion':criterion},sort_keys=True,
                           ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    except (ValueError,TypeError):
        raise ValueError('The approved definition must have finite JSON values.') from None
    return hashlib.sha256(encoded).hexdigest()


def _text(value,name,limit):
    if (not isinstance(value,str) or not value.strip() or len(value)>limit
            or any(ord(c)<32 or ord(c)==127 for c in value)):
        raise ValueError(f'Invalid {name}.')
    return value.strip()


def bind_concept_query(question_text,criterion,query,*,generator,request_id):
    """Bind a generated/instructor concept query, without approving a guide."""
    return {'version':QUERY_VERSION,'definition_sha256':definition_fingerprint(question_text,criterion),
        'query':_text(query,'concept query',MAX_CONCEPT_QUERY_CHARS),
        'generator':_text(generator,'query generator',200),'request_id':_text(request_id,'query request identifier',200)}


def validate_concept_queries(question_text,criteria,records):
    """Opt-in is complete and explicit; stale/missing records never fall back.

    Do not pass provider/student dictionaries directly. Ownership, checked source
    pages, source approval and retrieval bounds remain the caller's responsibility.
    """
    if records is None:
        return None
    if not isinstance(criteria,list) or any(not isinstance(c,dict) for c in criteria):
        raise ValueError('Approved criteria must be a list of definitions.')
    ids=[c.get('id') for c in criteria]
    if (not isinstance(records,dict)
            or any(not isinstance(i,str) or not i.strip() for i in ids)
            or len(ids)!=len(set(ids)) or set(records)!=set(ids)):
        raise ValueError('Concept queries must cover exactly the approved criterion IDs.')
    result={}
    for criterion in criteria:
        record=records[criterion['id']]
        if not isinstance(record,dict) or set(record)!=FIELDS:
            raise ValueError('Unexpected concept-query fields; student data and labels cannot be search controls.')
        expected=bind_concept_query(question_text,criterion,record.get('query'),
            generator=record.get('generator'),request_id=record.get('request_id'))
        if record!=expected:
            raise ValueError('Concept query is stale or belongs to a different approved definition.')
        result[criterion['id']]=dict(expected)
    return result


def criterion_query(question_text,criterion,records=None):
    """Retain legacy query bytes unless an exact bound concept query is opted in."""
    if records is not None:
        return records[criterion['id']]['query']
    return ' '.join(str(v or '') for v in (question_text,criterion.get('title'),
        criterion.get('description'),criterion.get('full_credit_conditions')))[:5000]
