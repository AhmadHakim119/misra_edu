/* Existing MISRA workspace: a separate setup flow, with truthful job-state motion. */
(function () {
  'use strict';
  const form = document.getElementById('setup-upload-form');
  const uploadDetails = document.getElementById('setup-upload-details');
  const status = document.getElementById('setup-status');
  const review = document.getElementById('setup-review');
  const readiness = document.getElementById('setup-readiness');
  const button = document.getElementById('setup-upload-button');
  const another = document.getElementById('setup-new-upload');
  const history = document.getElementById('setup-history');
  const historyList = document.getElementById('setup-history-list');
  const examSelect = document.getElementById('rubric-exam');
  const studentLink = document.getElementById('upload-link');
  const nextStep = document.getElementById('rubric-next-step');
  const esc = (value) => MisraUI.escapeHTML(String(value ?? ''));
  let examId = '', generation = 0, selected = null, dirty = false, busy = false;

  function setStatus(title, message, phase = 'idle') {
    const changed = status.dataset.phase !== phase;
    status.dataset.phase = phase;
    status.innerHTML = `<div class="setup-status-line">${phase === 'working' ? '<span class="upload-status-pulse" aria-hidden="true"></span>' : ''}<strong>${esc(title)}</strong></div><p class="section-copy">${esc(message)}</p>`;
    if (changed && !matchMedia('(prefers-reduced-motion: reduce)').matches) status.animate([{ transform: 'translateY(6px)', opacity: .65 }, { transform: 'translateY(0)', opacity: 1 }], { duration: 260, easing: 'cubic-bezier(.16,1,.3,1)' });
  }
  async function checkReadiness() {
    const id = examId;
    const checks = document.getElementById('rubric-setup-checks');
    if (checks) checks.textContent = 'Checking question setup…';
    studentLink.setAttribute('aria-disabled', 'true');
    nextStep.hidden = true;
    if (!id) return;
    try {
      const value = await MisraAPI.setupReadiness(id);
      if (id !== examId) return;
      readiness.textContent = value.message;
      if (checks) checks.innerHTML = MisraAssessmentChecks.render(value, id);
      studentLink.setAttribute('aria-disabled', String(!value.ready));
      const nextQuestion = (value.questions || []).find((question) => question.errors?.length);
      const destination = value.ready ? `upload.html?exam_id=${encodeURIComponent(id)}` : nextQuestion ? `rubric-studio.html?exam_id=${encodeURIComponent(id)}&question_id=${encodeURIComponent(nextQuestion.question_id)}` : '#question-list';
      const action = value.ready ? 'Continue to student uploads' : nextQuestion ? `Open question ${nextQuestion.question_number}` : 'Add a question';
      nextStep.innerHTML = `<div><strong>${value.ready ? 'Assessment ready for student papers' : `${esc(value.pending_questions?.length || 0)} question${value.pending_questions?.length === 1 ? '' : 's'} still need setup`}</strong><p>${value.ready ? 'Every question passed the setup checks. The blank exam and key stay separate from student submissions.' : 'Review the remaining question checks, then approve the grading foundations.'}</p></div><a class="btn ${value.ready ? 'btn-primary' : 'btn-secondary'}" href="${destination}">${esc(action)}</a>`;
      nextStep.hidden = false;
      window.dispatchEvent(new CustomEvent('misra:assessment-readiness', { detail: { examId: id, ready: value.ready, questionCount: value.question_count, approvedCount: value.approved_count } }));
    } catch (_) { if (id === examId) { readiness.textContent = 'Could not check rubric readiness. Reload to retry.'; if (checks) checks.textContent = readiness.textContent; nextStep.hidden = true; } }
  }
  studentLink.addEventListener('click', (event) => {
    if (studentLink.getAttribute('aria-disabled') === 'true') { event.preventDefault(); readiness.scrollIntoView({ block: 'center' }); }
  });

  function sources(data) {
    return (data.documents || []).map((doc, index) => `<a target="_blank" rel="noopener" href="${MisraAPI.setupDocumentUrl(examId, data.job.id, index)}">Open ${doc.role === 'answer_key' ? 'answer key' : 'exam'} (${doc.page_count} pages)</a>`).join('');
  }
  function showReview(data) {
    selected = data; dirty = false;
    form.hidden = true; uploadDetails.hidden = true; another.hidden = false;
    if (data.imported_question_ids?.length) {
      document.getElementById('workspace-content').dataset.setupReview = 'false';
      review.hidden = true;
      setStatus('Questions added to Rubric Studio', 'Next: review the draft criteria below and approve each rubric. Nothing has been graded.', 'complete');
      return;
    }
    review.hidden = false;
    document.getElementById('workspace-content').dataset.setupReview = 'true';
    setStatus('Your exam is ready to review', 'Check the question numbers, text and marks against the original. Unknown marks are left blank, never guessed.', 'complete');
    review.innerHTML = `<div class="section-head"><div><h3 class="section-title">Review extracted questions</h3><p class="section-copy">AI marking guides are starting points, not approved rubrics. Exclude any repeated or unwanted question.</p></div></div>
      <div class="setup-actions">${sources(data)}</div>
      ${(data.warnings || []).length ? `<details open class="setup-warnings"><summary>Check these extraction notes</summary><ul>${data.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></details>` : ''}
      <form id="setup-confirm-form">
      <div class="setup-drafts">${data.questions.map((q, i) => `<fieldset class="setup-question" data-import-question="${i}"><legend>Question ${esc(q.question_number)}</legend>
        <label class="setup-include"><input type="checkbox" name="include" checked> Include this question</label>
        <div class="setup-file-grid"><div class="field"><label for="import-number-${i}">Question number</label><input class="input" id="import-number-${i}" name="question_number" value="${esc(q.question_number)}" required maxlength="20"></div><div class="field"><label for="import-marks-${i}">Maximum marks</label><input class="input" id="import-marks-${i}" name="max_score" type="number" min="0.01" max="9999.99" step="0.01" value="${q.max_score == null ? '' : esc(q.max_score)}" required></div></div>
        <div class="field"><label for="import-text-${i}">Question text and shared context</label><textarea class="input textarea" id="import-text-${i}" name="question_text" rows="5" maxlength="20000" required dir="auto">${esc(q.question_text)}</textarea></div>
        <div class="field"><label for="import-guide-${i}">Suggested marking guide</label><textarea class="input textarea" id="import-guide-${i}" name="marking_guide" rows="3" maxlength="20000" required dir="auto">${esc(q.marking_guide)}</textarea></div>
        <details><summary>Answer key and source pages</summary><div class="field"><label for="import-key-${i}">Reference solution (optional)</label><textarea class="input textarea" id="import-key-${i}" name="answer_key" rows="3" maxlength="20000" dir="auto">${esc(q.answer_key)}</textarea></div><p class="field-hint">${(q.source_pages || []).map(ref => { const [d, p] = ref.split(':').map(Number); return `${d ? 'Answer key' : 'Exam'} page ${p + 1}`; }).map(esc).join(' · ')}</p></details>
      </fieldset>`).join('')}</div>
      <div class="field"><label for="setup-approach">Initial grading approach</label><select class="input select" id="setup-approach"><option value="balanced">Balanced</option><option value="lenient">Lenient</option><option value="strict">Strict</option></select></div>
      <p class="field-hint" id="setup-total"></p><div id="setup-confirm-error" role="alert"></div>
      <button class="btn btn-primary" id="setup-confirm-button">Add questions as draft rubrics</button></form>`;
    const confirmForm = document.getElementById('setup-confirm-form');
    function totals() {
      const rows = [...review.querySelectorAll('[data-import-question]')];
      rows.forEach(row => row.querySelectorAll('input:not([name="include"]), textarea').forEach(field => { field.disabled = !row.querySelector('[name="include"]').checked; }));
      const included = rows.filter(row => row.querySelector('[name="include"]').checked);
      document.getElementById('setup-total').textContent = `${included.length} questions selected · ${included.reduce((sum, row) => sum + Number(row.querySelector('[name="max_score"]').value || 0), 0).toFixed(2)} total marks. Confirm these against the exam.`;
    }
    totals(); confirmForm.addEventListener('input', () => { dirty = true; totals(); });
    confirmForm.addEventListener('submit', async (event) => {
      event.preventDefault(); if (busy) return;
      const questions = [...review.querySelectorAll('[data-import-question]')].filter(row => row.querySelector('[name="include"]').checked).map(row => Object.fromEntries(['question_number', 'question_text', 'max_score', 'marking_guide', 'answer_key'].map(key => [key, key === 'max_score' ? Number(row.querySelector(`[name="${key}"]`).value) : row.querySelector(`[name="${key}"]`).value.trim()])));
      const error = document.getElementById('setup-confirm-error');
      if (!questions.length) { error.textContent = 'Select at least one question.'; return; }
      const targetExam = examId, targetJob = selected.job.id;
      busy = true; examSelect.disabled = true;
      const save = document.getElementById('setup-confirm-button'); save.disabled = true; save.textContent = 'Adding draft rubrics…';
      try {
        const result = await MisraAPI.confirmSetup(targetExam, targetJob, { questions, grading_approach: document.getElementById('setup-approach').value });
        dirty = false; selected.imported_question_ids = result.question_ids; showReview(selected);
        window.dispatchEvent(new CustomEvent('misra:questions-imported', { detail: { examId: targetExam, questionId: result.question_ids[0] } }));
      } catch (e) { error.textContent = `${e.message} Your edits are still here.`; }
      finally { busy = false; examSelect.disabled = false; save.disabled = false; save.textContent = 'Add questions as draft rubrics'; }
    });
  }
  async function watch(data, token) {
    selected = data; form.hidden = true; uploadDetails.hidden = true; another.hidden = false; review.hidden = true;
    while (token === generation) {
      if (data.job.status === 'completed') { showReview(data); return; }
      if (data.job.status === 'failed') {
        setStatus('Exam reading failed', data.job.error_message || 'Try a clearer file or retry this job.', 'error');
        const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn btn-secondary'; retry.textContent = 'Retry exam reading'; status.append(retry);
        retry.addEventListener('click', async () => { retry.disabled = true; try { await MisraAPI.retryJob(data.job.id); if (token === generation) watch(await MisraAPI.setupImport(examId, data.job.id), token); } catch (e) { setStatus('Could not retry', e.message, 'error'); } });
        return;
      }
      setStatus(data.job.status === 'processing' ? 'Reading your exam…' : data.job.status === 'retrying' ? 'Retry scheduled…' : 'Exam received — waiting for worker', data.job.progress_message || 'You can leave this page. The setup draft is saved separately from submissions.', 'working');
      if (data.job.progress_total) {
        const progress = document.createElement('progress'); progress.max = data.job.progress_total; progress.value = data.job.progress_current || 0; progress.setAttribute('aria-label', 'Exam pages read'); status.append(progress);
      }
      await new Promise(resolve => setTimeout(resolve, 2500));
      if (token !== generation) return;
      try { data = await MisraAPI.setupImport(examId, data.job.id); if (token !== generation) return; }
      catch (e) {
        if (token !== generation) return;
        setStatus('Connection interrupted', 'The worker may still be reading your exam. Reload this page to reconnect; do not upload the same file again.', 'error'); return;
      }
    }
  }
  async function load(id) {
    if (id === examId && dirty) return;
    document.getElementById('workspace-content').dataset.setupReview = 'false';
    examId = id; const token = ++generation;
    button.disabled = !id; selected = null; dirty = false; form.hidden = false; uploadDetails.hidden = false; another.hidden = true; review.hidden = true; status.innerHTML = ''; history.hidden = true;
    checkReadiness();
    if (!id) return;
    try {
      const items = await MisraAPI.setupImports(id);
      if (token !== generation) return;
      history.hidden = !items.length;
      historyList.replaceChildren();
      items.forEach((item, index) => {
        const control = document.createElement('button'); control.type = 'button'; control.className = 'btn btn-secondary'; control.textContent = `${index ? 'Earlier upload' : 'Latest upload'} · ${item.job.status}`;
        control.addEventListener('click', async () => { if (busy || (dirty && !confirm('Discard your unsaved question edits?'))) return; const token = ++generation; try { const fresh = await MisraAPI.setupImport(examId, item.job.id); if (token === generation) watch(fresh, token); } catch (e) { if (token === generation) setStatus('Could not open setup upload', e.message, 'error'); } }); historyList.append(control);
      });
      if (items.length) watch(items[0], token);
    } catch (e) { if (token === generation) setStatus('Setup uploads unavailable', `${e.message} Reload to retry.`, 'error'); }
  }
  examSelect.addEventListener('change', (event) => { if (busy || (dirty && !confirm('Discard your unsaved imported-question edits?'))) { examSelect.value = examId; event.stopImmediatePropagation(); } }, true);
  window.addEventListener('beforeunload', (event) => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('misra:assessment-loaded', event => load(event.detail.examId));
  window.addEventListener('misra:rubric-approved', checkReadiness);
  another.addEventListener('click', () => { if (busy || (dirty && !confirm('Discard your unsaved question edits?'))) return; generation++; dirty = false; document.getElementById('workspace-content').dataset.setupReview = 'false'; form.hidden = false; uploadDetails.hidden = false; uploadDetails.open = true; review.hidden = true; status.innerHTML = ''; another.hidden = true; form.reset(); document.getElementById('setup-exam-file').focus(); });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !examId) return;
    const body = new FormData(); body.append('exam_file', document.getElementById('setup-exam-file').files[0]);
    const key = document.getElementById('setup-key-file').files[0]; if (key) body.append('answer_key', key);
    busy = true; button.disabled = true; examSelect.disabled = true; button.textContent = 'Uploading exam…';
    form.querySelectorAll('input').forEach(input => { input.disabled = true; });
    setStatus('Uploading setup documents…', 'Validating the files before queueing question extraction. No student submission will be created.', 'working');
    try { const data = await MisraAPI.uploadSetup(examId, body); form.reset(); watch(data, ++generation); status.focus(); }
    catch (e) { setStatus('Upload not confirmed', `${e.message} Reload to check previous setup uploads before trying again.`, 'error'); }
    finally { busy = false; button.disabled = false; examSelect.disabled = false; form.querySelectorAll('input').forEach(input => { input.disabled = false; }); button.textContent = 'Read exam & suggest questions'; }
  });
})();
