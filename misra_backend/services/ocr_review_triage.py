"""Offline review ordering and cross-view checks; never approve or repair text."""
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from services.ocr_verification import Reading, Region, critical_tokens, grading_gate


class ComponentReview(BaseModel):
    """Trusted local human reply, distinct from a complete instructor revision."""
    model_config = ConfigDict(extra='forbid')
    region_id: str = Field(min_length=1, max_length=100)
    component_id: str = Field(min_length=1, max_length=100)
    evidence_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    actor_role: str = Field(pattern=r'^(project_user|instructor)$')
    confirmed_component: str = Field(min_length=1, max_length=3000)
    source_warning_indices_resolved: list[StrictInt] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def unique_indices(self):
        indices = self.source_warning_indices_resolved
        if any(type(i) is not int or i < 0 for i in indices) or len(indices) != len(set(indices)):
            raise ValueError('Source warning indices must be unique nonnegative integers.')
        return self


def review_queue(comparisons, component_reviews=()):
    """Prioritize critical evidence and show replies without repeating resolved asks.

    All original review reasons and the full grading gate remain intact. Other
    pending review reasons are a separate queue, not declared harmless. Human
    component replies do not authorize every character in an entire answer.
    """
    gate = grading_gate(comparisons)
    indexed = {r['region']['region_id']: r for r in comparisons}
    resolved = {key: [] for key in indexed}
    seen = set()
    for raw in component_reviews:
        item = ComponentReview.model_validate(raw)
        if item.region_id not in indexed:
            raise ValueError('Component review refers to an unknown region.')
        row = indexed[item.region_id]
        if item.evidence_digest != row['evidence_digest']:
            raise ValueError('Component review is stale; evidence changed.')
        key = item.region_id, item.component_id
        if key in seen:
            raise ValueError('Duplicate component review.')
        seen.add(key)
        if any(i >= len(row['region']['source_warnings']) for i in item.source_warning_indices_resolved):
            raise ValueError('Unknown source warning index.')
        resolved[item.region_id].append(item.model_dump())
    ordered = []
    high_reasons = {'critical_symbol_disagreement', 'reported_uncertainty',
                    'reader_unavailable_or_illegible', 'insufficient_independent_readers',
                    'reader_not_blind', 'numeric_consistency_warning_not_proof_of_ocr_error'}
    for row in comparisons:
        identifier = row['region']['region_id']
        replies = resolved[identifier]
        covered = {i for reply in replies for i in reply['source_warning_indices_resolved']}
        unresolved = [warning for i, warning in enumerate(row['region']['source_warnings']) if i not in covered]
        if high_reasons.intersection(row['review_reasons']) or unresolved:
            priority = 'critical_or_uncertain'
        elif row['requires_review']:
            priority = 'remaining_region_review'
        else:
            priority = 'reader_agreement'
        ordered.append({'region_id': identifier, 'priority': priority,
            'original_review_reasons': list(row['review_reasons']),
            'unresolved_source_warnings': unresolved, 'confirmed_components': replies,
            'whole_region_review_still_required': row['requires_review']})
    rank = {'critical_or_uncertain': 0, 'remaining_region_review': 1, 'reader_agreement': 2}
    ordered.sort(key=lambda r: (rank[r['priority']], r['region_id']))
    return {'regions': ordered, 'counts': {key: sum(r['priority'] == key for r in ordered) for key in rank},
            'full_grading_gate': gate, 'component_reviews_are_full_answer_approvals': False}


def compare_critical_views(parent_region, parent_reading, focus_region, focus_reading):
    """Screen a tighter crop against the same reader's earlier wider-line reading.

    A matching critical subsequence is not proof the crop was read correctly: the
    same digits can occur elsewhere in a line or be wrong in both outputs. This
    is an additional disagreement signal; it cannot clear the grading gate or
    count another run of the same model as an independent reader.
    """
    parent, focus = Region.model_validate(parent_region), Region.model_validate(focus_region)
    left, right = Reading.model_validate(parent_reading), Reading.model_validate(focus_reading)
    if (left.region_id != parent.region_id or left.crop_sha256 != parent.crop_sha256
        or right.region_id != focus.region_id or right.crop_sha256 != focus.crop_sha256):
        raise ValueError('Reading does not belong to its declared image region.')
    if parent.page_sha256 != focus.page_sha256 or parent.page_index != focus.page_index:
        raise ValueError('Views must refer to the same preserved page.')
    p, f = parent.bounding_box, focus.bounding_box
    tolerance = .00001
    if (f.x < p.x-tolerance or f.y < p.y-tolerance or
        f.x+f.width > p.x+p.width+tolerance or f.y+f.height > p.y+p.height+tolerance):
        raise ValueError('Focus must stay inside the wider line region.')
    if left.reader_family != right.reader_family:
        raise ValueError('Use independent-reader comparisons for different reader families.')
    result = {'parent_region_id': parent.region_id, 'focus_region_id': focus.region_id,
              'reader_family': left.reader_family, 'counts_as_another_independent_reader': False,
              'text_repaired': False, 'status': 'indeterminate', 'reasons': []}
    if any(r.status != 'read' or not r.blind_to_other_readings_and_key for r in (left, right)):
        result['reasons'].append('unavailable_or_nonblind_reading')
        return result
    before, after = critical_tokens(left.text), critical_tokens(right.text)
    if '[unclear]' in right.text.lower() or not after:
        result['reasons'].append('focus_has_no_definite_critical_sequence')
        return result
    matched = any(before[i:i+len(after)] == after for i in range(len(before)-len(after)+1))
    if not matched:
        result.update(status='critical_view_conflict', reasons=['focus_critical_sequence_differs_from_wider_line'])
    elif left.uncertainties or right.uncertainties:
        result['reasons'].append('reported_uncertainty_remains')
    else:
        result.update(status='no_critical_conflict_observed', reasons=['matching_subsequence_is_not_accuracy_or_approval'])
    return result
