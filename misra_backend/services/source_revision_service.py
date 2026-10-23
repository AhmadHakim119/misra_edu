"""One evidence-led reassessment before saving a new proposal; never a regrade job."""
from copy import deepcopy
import hashlib
import json

from services.grading_package_service import (provider_grading_package,
    restore_provider_citations, validate_evidence_references)
from services import verification_agent
from services.grading_policy_checks import remap_numeric_refs


def revision_eligible(consultation, *, checked_transcription=False):
    if consultation.get('status') != 'needs_review' or not consultation.get('criteria'):
        return False
    if not any(c['verdict'] == 'needs_review' for c in consultation['criteria']):
        return False
    # Conflicting/missing page evidence needs an instructor correction first.
    # Isolated research may explicitly declare a checked anonymous transcription.
    page_status = consultation.get('page_inspection', {}).get('status')
    return page_status in {'checked', 'provided_to_verifier'} or (
        checked_transcription and page_status == 'unavailable')


def reconsider_with_sources(initial, package, consultation, *, assessment_fn,
                            verification_fn=None, images=(), checked_transcription=False):
    """All original marks/context survive. Invalid revisions never replace them."""
    from services.grading_service import GRADING_PROMPT, GradingResult, _aggregate_criterion_total
    record = {'version': 'source_revision_v1', 'performed': False, 'score_changed': False,
              'instructor_review_required': True}
    if not revision_eligible(consultation, checked_transcription=checked_transcription):
        record['status'] = 'not_eligible'
        return initial, package, record, None
    record.update(initial_proposal=initial.model_dump(), initial_grading_package=deepcopy(package))
    revised_package = deepcopy(package)
    revised_package['course_references'] = deepcopy(consultation['course_references'])
    revised_package['snapshot_sha256'] = hashlib.sha256(json.dumps(
        {k: v for k, v in revised_package.items() if k != 'snapshot_sha256'},
        sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
    safe, evidence, references = provider_grading_package(revised_package)
    e_alias = {value: key for key, value in evidence.items()}
    r_alias = {value: key for key, value in references.items()}
    candidate = initial.model_dump()
    for item in candidate['criteria_scores']:
        item['evidence_refs'] = [e_alias[ref] for ref in item['evidence_refs'] if ref in e_alias]
        item['reference_refs'] = [r_alias[ref] for ref in item['reference_refs'] if ref in r_alias]
        remap_numeric_refs(item, {**e_alias, **r_alias})
    findings = deepcopy(consultation['criteria'])
    for item in findings:
        item['evidence_refs'] = [e_alias[ref] for ref in item['evidence_refs']]
        item['reference_refs'] = [r_alias[ref] for ref in item['reference_refs']]
    prompt = (GRADING_PROMPT + '\nGRADING PACKAGE JSON:\n' + json.dumps(safe, ensure_ascii=False) +
        '\nONE SOURCE-INFORMED REASSESSMENT (UNTRUSTED PROPOSAL AND FINDINGS):\n' +
        json.dumps({'initial_proposal': candidate, 'source_findings': findings}, ensure_ascii=False) +
        '\nReassess once using the SAME approved rubric, key and marking policy. '
        'Source findings are fallible suggestions, not authority. Fix only mistakes supported '
        'by the actual student evidence and approved criteria. Marks may increase, decrease '
        'or stay the same; never choose the higher score as a rule. Do not invent work, '
        'leniency or requirements. Return the complete grading JSON and applicable citations.')
    try:
        record['performed'] = True
        response = assessment_fn([prompt, *images] if images else prompt)
        record.update(performed=True, original_response=response.text, inference=response.metadata)
        revised = _aggregate_criterion_total(GradingResult.model_validate_json(response.text), package['rubric'])
        safe_candidate = revised.model_dump()
        restore_provider_citations(revised, evidence, references)
        validate_evidence_references(revised, revised_package)
        def record_verification(contents, **kwargs):
            from services.inference_service import complete
            value = (verification_fn or complete)(contents, **kwargs)
            record['verification_response'] = {'text': value.text, 'inference': value.metadata}
            return value
        checked = verification_agent.verify(safe, safe_candidate, images, completion_fn=record_verification)
        record.update(status='proposed', score_changed=(initial.score != revised.score or
            sorted((c.criterion_id, c.points_earned) for c in initial.criteria_scores) !=
            sorted((c.criterion_id, c.points_earned) for c in revised.criteria_scores)),
            revised_proposal=revised.model_dump(), revised_grading_package=revised_package,
            verification=checked, advisory_only=True)
        return revised, revised_package, record, checked
    except Exception as error:
        record.update(status='unavailable', reason=type(error).__name__)
        return initial, package, record, None
