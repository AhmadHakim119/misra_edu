/* Read-only explanation of server checks. Never a client-side grading authority. */
(function () {
  'use strict';
  const esc = value => MisraUI.escapeHTML(String(value ?? ''));
  const modes = { adaptive: 'Adaptive evidence', pilot: 'Compare text and image', text_only: 'Text only', image_text: 'Image + text', image_text_required: 'Image required', disabled: 'Routing policy disabled' };
  window.MisraAssessmentChecks = {
    render(value, examId) {
      const rows = value.questions || [];
      const questionLink = id => `rubric-studio.html?exam_id=${encodeURIComponent(examId)}&question_id=${encodeURIComponent(id)}`;
      return `<div class="assessment-checks">
        <div class="section-head"><div><h3>Before grading</h3><p class="section-copy">${esc(value.message)}</p></div>${MisraUI.badge(value.ready ? 'Setup checked' : 'Action needed', value.ready ? 'success' : 'warning')}</div>
        <p class="section-copy">Question context defines the task. Reference answers guide interpretation. Approved criteria and policy define credit. These checks verify setup, not AI accuracy.</p>
        ${rows.length ? `<ul class="readiness-list">${rows.map(row => `<li>
          <div class="readiness-question"><a href="${questionLink(row.question_id)}">Question ${esc(row.question_number)}</a><span>${esc(row.max_score)} points</span></div>
          <div class="readiness-detail"><p>${row.approved ? `Approved rubric v${esc(row.rubric_version)}` : row.rubric_source === 'legacy' && row.definition_ready ? 'Legacy rubric accepted' : 'Rubric not approved'} · ${esc(row.grading_approach)} · ${esc(modes[row.evidence_mode] || row.evidence_mode)}</p>
          <p class="section-copy">${row.answer_key_version ? `Approved answer key v${esc(row.answer_key_version)}${row.answer_key_mode === 'no_fixed_answer' ? ' · No fixed answer; evaluate against criteria.' : '.'}` : row.reference_recorded ? 'Legacy reference recorded in rubric version.' : 'No reference answer recorded.'}</p>
          ${(row.errors || []).map(text => `<p class="check-error">Action: ${esc(text)}</p>`).join('')}
          ${(row.warnings || []).map(text => `<p class="check-advisory">Check: ${esc(text)}</p>`).join('')}</div>
          <a class="link-button" href="${questionLink(row.question_id)}" aria-label="Edit question ${esc(row.question_number)} rubric">Edit rubric</a>
        </li>`).join('')}</ul>` : '<p>Add questions in Rubric Studio to start these checks.</p>'}
      </div>`;
    }
  };
})();
