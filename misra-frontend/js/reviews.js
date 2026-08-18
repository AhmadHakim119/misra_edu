(function () {
  'use strict';
  const examSelect = document.getElementById('review-exam');
  const list = document.getElementById('review-list');
  const count = document.getElementById('queue-count');
  const detail = document.getElementById('review-detail');
  const state = { answers: [], questions: new Map(), selected: null };

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
    detail.innerHTML = `<section class="workspace-card card-pad">
      <div class="rubric-toolbar-meta" style="margin-bottom:14px">${MisraUI.badge(`Question ${question?.question_number || 'unknown'}`, 'slate')}${MisraUI.badge(`${answer.final_confidence ?? '—'}% confidence`, Number(answer.final_confidence) >= 80 ? 'success' : 'warning')}</div>
      <div class="score-display"><strong>${answer.score ?? '—'}</strong><span>/ ${answer.max_score ?? question?.max_score ?? '—'}</span></div>
      <p class="section-copy" style="margin:8px 0 18px">${MisraUI.escapeHTML(answer.feedback || 'No AI feedback was recorded.')}</p>
      <h2 class="section-title">Extracted answer</h2>
      <div class="review-answer" style="margin-top:10px">${MisraUI.escapeHTML(answer.raw_ocr_text || 'No OCR text available.')}</div>
      ${renderReasons(answer.review_reasons)}
      <form id="review-form" style="margin-top:20px;padding-top:18px;border-top:1px solid var(--line)">
        <div class="field"><label for="human-score">Human score</label><input class="input" id="human-score" name="human_score" type="number" min="0" max="${answer.max_score}" step="0.25" value="${answer.teacher_override_score ?? answer.score ?? ''}"></div>
        <div class="field"><label for="review-notes">Instructor notes</label><textarea class="input textarea" id="review-notes" name="reviewer_notes" placeholder="Record why this result was approved or changed."></textarea></div>
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
    const body = {
      action,
      was_review_warranted: form.get('was_review_warranted') === 'on',
      reviewer_notes: form.get('reviewer_notes') || null,
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
      state.answers = answers; state.questions = new Map(questions.map((question) => [question.id, question]));
      count.textContent = `${answers.length} answer${answers.length === 1 ? '' : 's'} waiting`;
      if (!answers.length) { list.innerHTML = MisraUI.emptyState('Queue is clear', 'No answers in this assessment need instructor review.', MisraUI.icons.review); return; }
      list.innerHTML = answers.map((answer) => { const question = state.questions.get(answer.question_id); return `<button class="question-button" type="button" data-answer-id="${answer.id}" aria-current="false"><span class="question-number">${MisraUI.escapeHTML(question?.question_number || '?')}</span><span class="question-summary">${MisraUI.escapeHTML(answer.feedback || answer.raw_ocr_text || 'Flagged answer')}</span><span class="question-points">${answer.score ?? '—'}/${answer.max_score ?? question?.max_score ?? '—'}</span></button>`; }).join('');
      list.querySelectorAll('[data-answer-id]').forEach((button) => button.addEventListener('click', () => selectAnswer(button.dataset.answerId)));
      selectAnswer(answers[0].id);
    } catch (error) { list.innerHTML = MisraUI.errorState(error.message); }
  }

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
