"""Readable explanations of saved review signals; no inference or score changes."""

REASONS = {
    'deduction_on_uncertain_evidence': ('Lost credit rests on uncertain evidence', 'The AI withheld credit while recording uncertainty about the supporting work.', 'Open the original crop, check the disputed writing and reconsider each affected criterion before approving.'),
    'instructor_reopened_review': ('Instructor reopened this decision', 'A previous instructor decision was reopened for checking.', 'Review the saved decision history, then save the corrected instructor grade.'),
    'low_blended_confidence': ('Low combined estimate', 'The recorded combined estimate is below its operational threshold.', 'Check extraction and criterion decisions; this estimate is uncalibrated.'),
    'low_model_confidence': ('The grader reported uncertainty', 'The grader estimate is below its operational threshold.', 'Inspect the affected criterion and the actual work. This is a heuristic, not a probability.'),
    'confidence_unavailable': ('Combined estimate unavailable', 'No valid combined estimate was recorded.', 'Review the actual evidence rather than assuming a missing estimate is high confidence.'),
    'model_confidence_unavailable': ('Grader estimate unavailable', 'No valid grader estimate was recorded.', 'Check the recorded reasoning and evidence.'),
    'extraction_legibility_uncertain': ('Handwriting needs checking', 'Extraction was not recorded as clear.', 'Compare signs, digits, cancelled work and wording with the original page.'),
    'verification_unavailable': ('Independent check unavailable', 'The verification stage did not complete a supported check.', 'Review the proposal against the rubric and course evidence.'),
    'verification_flagged': ('Verification requested review', 'The verification stage recorded a concern.', 'Inspect the criterion-specific verification explanation.'),
    'model_total_discrepancy': ('Criterion marks and total disagree', 'A total differed from the sum of the recorded criterion decisions.', 'Check the individual marks and their sum; do not use the original total blindly.'),
    'corrected_extraction_review_required': ('Extraction changed', 'A proposal uses newly corrected extraction.', 'Compare the new proposal with the confirmed correction before finalizing.'),
    'unresolved_marks': ('Some marks are unresolved', 'The available evidence does not establish a point score.', 'Inspect the unclear or missing portion; do not treat an unknown mark as zero.'),
    'rubric_changed_since_saved_grading': ('Rubric changed after grading', 'The active rubric differs from the snapshot used for this saved result.', 'Compare the versions. Existing marks have not been recalculated.'),
    'criterion_evidence_uncertain': ('Criterion evidence needs checking', 'At least one criterion has uncertain or incomplete supporting evidence.', 'Inspect the criterion feedback, student citation and course passage.'),
    'grading_definition_advisory': ('Marking guidance needs checking', 'The saved guide or source checks recorded an advisory.', 'Resolve the specific guide/source issue before relying on the result.'),
    'source_informed_reassessment': ('Assessments disagree', 'An additional source-based assessment was recorded.', 'Compare both explanations and decide under the approved rubric.'),
    'recorded_review_flag': ('Saved review request', 'The saved result requests review without a detailed structured reason.', 'Read the original explanation and evidence; no reason has been invented.'),
}


def explain_review(raw=None, criteria=None, *, needs_review=False, review_status='none', codes=()):
    raw = raw if isinstance(raw, dict) else {}
    criteria = criteria if isinstance(criteria, list) else []
    policy = raw.get('review_policy') or {}
    items = {}

    def add(code, reason=None, cid=None, source='saved_check'):
        title, standard, action = REASONS.get(code, (
            code.replace('_', ' ').capitalize(), 'A saved check raised this concern.',
            'Check the stated issue against this criterion, the student work and the approved policy.'))
        entry = next((c for c in criteria if c.get('criterion_id')==cid), {})
        previous = items.get((code, cid))
        text = reason or standard
        if previous and text not in previous['reason']:
            text = previous['reason'] + '\n' + text
        items[(code, cid)] = dict(code=code, title=title, reason=text, action=action,
            criterion_id=cid, source=source,
            evidence_refs=list(entry.get('evidence_refs') or []), reference_refs=list(entry.get('reference_refs') or []))

    for code in [*(policy.get('reasons') or []), *codes]:
        if isinstance(code, str):
            add(code, source='uncalibrated_heuristic' if 'confidence' in code else 'saved_check')
    if raw.get('review_reopened') and review_status not in {'approved','overridden'}:
        add('instructor_reopened_review', raw['review_reopened'].get('reason'), source='instructor_action')
    if raw.get('guide_review_required'):
        add('rubric_changed_since_saved_grading', raw['guide_review_required'].get('reason'), source='rule_check')
    findings = (raw.get('decision_review') or {}).get('findings') or policy.get('criterion_findings') or []
    for finding in findings:
        add(finding.get('code', 'recorded_review_flag'), finding.get('message'), finding.get('criterion_id'), 'rule_check')
    verification = raw.get('verification') or {}
    for item in verification.get('criteria') or []:
        if item.get('verdict') == 'needs_review':
            add('verification_flagged', item.get('explanation'), item.get('criterion_id'), 'model_verifier')
    for criterion in criteria:
        for uncertainty in criterion.get('uncertainties') or []:
            add('criterion_evidence_uncertain', str(uncertainty), criterion.get('criterion_id'), 'model_reported_uncertainty')
    validation = raw.get('validation') or {}
    for issue in validation.get('evidence_issues') or []:
        for text in issue.get('uncertainties') or []:
            add('criterion_evidence_uncertain', text, issue.get('criterion_id'))
    for issue in validation.get('definition_advisories') or []:
        add(issue.get('code', 'grading_definition_advisory'), issue.get('message'))
    if needs_review and not items:
        add('recorded_review_flag')
    return dict(status='instructor_reviewed' if review_status in {'approved','overridden'} else
        'needs_review' if needs_review else 'no_recorded_issue', items=list(items.values()),
        confidence_calibrated=False, automatic_finalization=False,
        interpretation='These are recorded concerns and check results. An unflagged proposal can still be wrong.')
