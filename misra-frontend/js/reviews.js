(function () {
  'use strict';
  const examSelect = document.getElementById('review-exam');
  const list = document.getElementById('review-list');
  const count = document.getElementById('queue-count');
  const detail = document.getElementById('review-detail');
  const bulkToolbar = document.getElementById('review-bulk-toolbar');
  const selectAll = document.getElementById('review-select-all');
  const approveSelected = document.getElementById('review-approve-selected');
  const state = { answers: [], questions: new Map(), selected: null, checked: new Set() };
  const reviewReasonOptions = [
    ['valid_alternative', 'Valid alternative', 'Another correct approach.'],
    ['minor_notation', 'Minor notation', 'The meaning is clear despite notation or handwritten syntax.'],
    ['method_credit', 'Method credit', 'The method earns partial credit.'],
    ['carried_forward_error', 'Carried-forward error', 'Later work follows consistently from an earlier mistake.'],
    ['language_tolerance', 'Language tolerance', 'Language quality is not assessed here.'],
    ['rubric_issue', 'Rubric issue', 'The marking rule needs correction.'],
    ['ocr_or_mapping_error', 'OCR or mapping error', 'Extraction is wrong; this is not a marking preference.'],
    ['other', 'Other', 'A different reason described below.'],
  ];

  function reasonFields() {
    return `<fieldset class="review-reason-fieldset">
      <legend>Reason for this decision <span>Required for a score change</span></legend>
      <p>Choose all that apply. OCR or mapping problems are recorded separately from instructor marking preferences.</p>
      <div class="review-reason-options">${reviewReasonOptions.map(([value, label, description]) => `<label><input type="checkbox" name="review_reason_codes" value="${value}"><span><strong>${label}</strong><small>${description}</small></span></label>`).join('')}</div>
      <label class="field review-reason-note"><span>Reason detail <small>Optional</small></span><textarea class="input textarea" name="review_reason_note" maxlength="1000" rows="2" placeholder="Add context for future evaluation."></textarea></label>
      <p class="field-error" data-review-reason-error role="alert" hidden>Select at least one reason before saving a changed score.</p>
    </fieldset>`;
  }

  function syncBulkControls() {
    bulkToolbar.hidden = state.answers.length === 0;
    selectAll.checked = state.answers.length > 0 && state.checked.size === state.answers.length;
    selectAll.indeterminate = state.checked.size > 0 && state.checked.size < state.answers.length;
    approveSelected.disabled = state.checked.size === 0;
    approveSelected.textContent = state.checked.size ? `Approve selected (${state.checked.size})` : 'Approve selected';
  }

  function renderReasons(reasons) {
    if (!reasons) return '';
    const items = Array.isArray(reasons) ? reasons : [reasons];
    const labels = {
      material_mode_disagreement: 'Text-only and image + text grading produced materially different results.',
      visual_evidence_not_seen: 'The original page was required, but this grading run received extracted text only.',
    };
    return `<div class="review-reasons">${items.map((reason) => `<div class="review-reason">${MisraUI.escapeHTML(labels[reason.code] || (reason.code ? reason.code.replaceAll('_', ' ') : JSON.stringify(reason)))}</div>`).join('')}</div>`;
  }

  function selectAnswer(answerId) {
    state.selected = state.answers.find((answer) => answer.id === answerId);
    list.querySelectorAll('.question-button').forEach((button) => button.setAttribute('aria-current', String(button.dataset.answerId === answerId)));
    if (!state.selected) return;
    const answer = state.selected;
    const question = state.questions.get(answer.question_id);
    const confidence = Number.isFinite(Number(answer.final_confidence))
      ? `${Number(answer.final_confidence)}%`
      : 'Not available';
    const evidenceLink = answer.submission_id
      ? `<div class="review-evidence-cta">
          <div><strong>Check the student work before deciding</strong><p>Open the full grade result to compare this score with the original paper, highlighted source regions, criterion evidence, and saved grading context.</p></div>
          <a class="btn btn-secondary" href="grade-results.html?id=${encodeURIComponent(answer.submission_id)}">Open grade results &amp; source evidence</a>
        </div>`
      : '<p class="review-evidence-unavailable" role="status">Source evidence is unavailable from this queue record. Open the submission from Extraction results before changing the score.</p>';
    detail.innerHTML = `<section class="workspace-card card-pad">
      <div class="rubric-toolbar-meta" style="margin-bottom:8px">${MisraUI.badge(`Question ${question?.question_number || 'unknown'}`, 'slate')}${MisraUI.badge(`Model confidence estimate: ${confidence}`, 'slate')}</div>
      <p class="review-confidence-note">This is an uncalibrated model estimate, not a guarantee that the grade is correct.</p>
      <div class="score-display"><strong>${answer.score ?? '—'}</strong><span>/ ${answer.max_score ?? question?.max_score ?? '—'}</span></div>
      <p class="section-copy" style="margin:8px 0 18px">${MisraUI.escapeHTML(answer.feedback || 'No AI feedback was recorded.')}</p>
      <h2 class="section-title">Extracted answer</h2>
      <div class="review-answer" style="margin-top:10px">${MisraUI.escapeHTML(answer.raw_ocr_text || 'No OCR text available.')}</div>
      ${renderReasons(answer.review_reasons)}
      ${evidenceLink}
      <form id="review-form" style="margin-top:20px;padding-top:18px;border-top:1px solid var(--line)">
        <div class="field"><label for="human-score">Human score</label><input class="input" id="human-score" name="human_score" type="number" min="0" max="${answer.max_score}" step="0.25" value="${answer.teacher_override_score ?? answer.score ?? ''}"></div>
        <div class="field"><label for="review-notes">Instructor notes</label><textarea class="input textarea" id="review-notes" name="reviewer_notes" placeholder="Record why this result was approved or changed."></textarea></div>
        ${reasonFields()}
        <label class="checkbox-row" style="margin-bottom:18px"><input type="checkbox" name="was_review_warranted" checked><span>The AI was right to route this answer for review.</span></label>
        <div class="page-actions"><button class="btn btn-secondary" type="submit" data-action="approve">Approve AI score</button><button class="btn btn-primary" type="submit" data-action="override">Save human score</button></div>
      </form>
    </section>`;
    detail.querySelector('#review-form').addEventListener('submit', resolveAnswer);
  }

  async function resolveAnswer(event) {
    event.preventDefault();
    const submitter = event.submitter;
    const form = new FormData(event.currentTarget);
    const action = submitter.dataset.action;
    const reasonCodes = form.getAll('review_reason_codes');
    const reasonError = event.currentTarget.querySelector('[data-review-reason-error]');
    if (action === 'override' && !reasonCodes.length) {
      reasonError.hidden = false;
      event.currentTarget.querySelector('[name="review_reason_codes"]').focus();
      return;
    }
    reasonError.hidden = true;
    const body = {
      action,
      was_review_warranted: form.get('was_review_warranted') === 'on',
      reviewer_notes: form.get('reviewer_notes') || null,
      review_reason_codes: reasonCodes,
      review_reason_note: form.get('review_reason_note')?.trim() || null,
    };
    if (action === 'override') body.human_score = Number(form.get('human_score'));
    submitter.disabled = true; submitter.textContent = 'Saving…';
    try {
      await MisraAPI.resolveReview(state.selected.id, body);
      window.showToast('Review saved and evaluation label created.', 'success');
      await loadQueue();
    } catch (error) { window.showToast(error.message, 'error'); submitter.disabled = false; submitter.textContent = action === 'override' ? 'Save human score' : 'Approve AI score'; }
  }

  async function loadQueue() {
    if (!examSelect.value) return;
    list.innerHTML = '<div class="loading-list"><div class="skel loading-row"></div><div class="skel loading-row"></div></div>';
    detail.innerHTML = '';
    try {
      const [answers, questions] = await Promise.all([MisraAPI.reviewQueue(examSelect.value), MisraAPI.questions(examSelect.value)]);
      state.answers = answers; state.questions = new Map(questions.map((question) => [question.id, question])); state.checked.clear();
      count.textContent = `${answers.length} answer${answers.length === 1 ? '' : 's'} waiting`;
      syncBulkControls();
      if (!answers.length) { list.innerHTML = MisraUI.emptyState('Queue is clear', 'No answers in this assessment need instructor review.', MisraUI.icons.review); return; }
      list.innerHTML = answers.map((answer) => { const question = state.questions.get(answer.question_id); return `<div class="review-queue-row"><label class="review-select"><input type="checkbox" data-select-answer="${answer.id}" aria-label="Select Question ${MisraUI.escapeHTML(question?.question_number || '?')}"></label><button class="question-button" type="button" data-answer-id="${answer.id}" aria-current="false"><span class="question-number">${MisraUI.escapeHTML(question?.question_number || '?')}</span><span class="question-summary">${MisraUI.escapeHTML(answer.feedback || answer.raw_ocr_text || 'Flagged answer')}</span><span class="question-points">${answer.score ?? '—'}/${answer.max_score ?? question?.max_score ?? '—'}</span></button></div>`; }).join('');
      list.querySelectorAll('[data-answer-id]').forEach((button) => button.addEventListener('click', () => selectAnswer(button.dataset.answerId)));
      list.querySelectorAll('[data-select-answer]').forEach((checkbox) => checkbox.addEventListener('change', () => {
        if (checkbox.checked) state.checked.add(checkbox.dataset.selectAnswer);
        else state.checked.delete(checkbox.dataset.selectAnswer);
        syncBulkControls();
      }));
      selectAnswer(answers[0].id);
    } catch (error) { list.innerHTML = MisraUI.errorState(error.message); }
  }

  selectAll.addEventListener('change', () => {
    state.checked = new Set(selectAll.checked ? state.answers.map((answer) => answer.id) : []);
    list.querySelectorAll('[data-select-answer]').forEach((checkbox) => { checkbox.checked = selectAll.checked; });
    syncBulkControls();
  });

  approveSelected.addEventListener('click', async () => {
    const selectedAnswers = state.answers.filter((answer) => state.checked.has(answer.id));
    if (!selectedAnswers.length) return;
    if (!window.confirm(`Approve the current AI score for ${selectedAnswers.length} selected answer${selectedAnswers.length === 1 ? '' : 's'}? Each approval creates an evaluation label.`)) return;
    approveSelected.disabled = true;
    approveSelected.textContent = 'Approving…';
    const outcomes = await Promise.allSettled(selectedAnswers.map((answer) => MisraAPI.resolveReview(answer.id, {
      action: 'approve',
      was_review_warranted: true,
      reviewer_notes: 'Bulk-approved from the instructor review queue.',
    })));
    const failed = outcomes.filter((outcome) => outcome.status === 'rejected');
    window.showToast(
      failed.length ? `${selectedAnswers.length - failed.length} approved; ${failed.length} could not be saved.` : `${selectedAnswers.length} selected answer${selectedAnswers.length === 1 ? '' : 's'} approved.`,
      failed.length ? 'warning' : 'success',
    );
    await loadQueue();
  });

  async function init() {
    try {
      const exams = await MisraAPI.exams();
      examSelect.innerHTML = exams.length ? exams.map((exam) => `<option value="${exam.id}">${MisraUI.escapeHTML(exam.course_code ? `${exam.course_code} · ${exam.title}` : exam.title)}</option>`).join('') : '<option value="">No assessments found</option>';
      const requested = MisraUI.getParam('exam_id'); if (exams.some((exam) => exam.id === requested)) examSelect.value = requested;
      examSelect.addEventListener('change', loadQueue); await loadQueue();
    } catch (error) { list.innerHTML = MisraUI.errorState(error.message); }
  }
  init();
})();
