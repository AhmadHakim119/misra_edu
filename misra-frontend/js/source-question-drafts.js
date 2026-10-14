/* Source-question generation reuses the persisted setup draft/review workflow. */
(function () {
  'use strict';
  const form = document.getElementById('source-draft-form');
  const versionInput = document.getElementById('question-source-version');
  const pagesInput = document.getElementById('question-source-pages');
  const status = document.getElementById('source-question-library-status');
  const button = document.getElementById('source-draft-button');
  const error = document.getElementById('source-draft-error');
  const assessment = document.getElementById('rubric-exam');
  let examId = '', courseId = '', options = [], dirty = false, busy = false, generation = 0;
  const esc = value => MisraUI.escapeHTML(String(value ?? ''));
  async function refresh() {
    const token = generation, course = courseId;
    button.disabled = true;
    if (!course) { status.textContent = 'Choose an assessment with a course to access approved sources.'; return; }
    status.textContent = 'Loading approved source versions…';
    try {
      const materials = await MisraAPI.courseMaterials(course);
      if (token !== generation || course !== courseId) return;
      if (!Array.isArray(materials)) throw new Error('Source library response is invalid. Try refreshing.');
      options = materials.flatMap(material => (material.versions || []).filter(version => ['approved','superseded'].includes(version.status)).map(version => ({material,version})));
      const previous = versionInput.value;
      versionInput.innerHTML = '<option value="">Choose approved material…</option>' + options.map(({material,version}) => `<option value="${esc(version.id)}">${esc(material.title)} · v${version.version_number}${version.status === 'superseded' ? ' (previous approval)' : ''}</option>`).join('');
      if (options.some(item => item.version.id === previous)) versionInput.value = previous;
      status.textContent = options.length ? 'Choose an approved source and the topic you want to assess.' : 'No approved sources yet. Open Manage course library, add material, review its text and approve pages first.';
      button.disabled = !options.length || busy;
    } catch (failure) { if (token === generation) status.textContent = `${failure.message} Use Refresh approved sources to retry.`; }
  }
  window.addEventListener('misra:assessment-loaded', event => {
    const sameAssessment = examId === event.detail.examId;
    generation++; examId = event.detail.examId; courseId = event.detail.courseId || '';
    if (sameAssessment) { refresh(); return; }
    form.reset(); dirty = false; error.textContent = ''; options = [];
    versionInput.innerHTML = '<option value="">Choose approved material…</option>'; refresh();
  });
  document.getElementById('refresh-question-sources').addEventListener('click', refresh);
  window.addEventListener('misra:material-approved', event => { if (event.detail.courseId === courseId) refresh(); });
  document.getElementById('manage-question-sources').addEventListener('click', () => {
    const emptyLibrary = document.getElementById('setup-source-library');
    const panel = emptyLibrary.hidden ? document.getElementById('course-material-panel') : document.getElementById('setup-library-host');
    if (!panel) { status.textContent = 'Wait for assessment loading, then try again.'; return; }
    const details = panel.closest('details'); if (details) details.open = true;
    panel.scrollIntoView({ block: 'start' });
  });
  versionInput.addEventListener('change', () => {
    const selected = options.find(item => item.version.id === versionInput.value);
    pagesInput.value = (selected?.version.approved_page_indices || []).map(index => index + 1).join(', ');
  });
  form.addEventListener('input', () => { dirty = true; });
  assessment.addEventListener('change', event => {
    if (busy || (dirty && !window.confirm('Discard your unsaved question-generation request?'))) {
      assessment.value = examId; event.stopImmediatePropagation();
    }
  }, true);
  window.addEventListener('beforeunload', event => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !examId) return;
    error.textContent = '';
    if (window.MisraRubricEditor?.hasUnsaved() || window.MisraExamSetup.hasUnsaved() || window.MisraMaterials.hasUnsaved() || window.MisraAnswerKeys.hasUnsaved()) {
      error.textContent = 'Save your current question, rubric, answer-key and source edits before generating proposals.'; return;
    }
    const selected = options.find(item => item.version.id === versionInput.value);
    if (!selected) { error.textContent = 'Choose an approved source first.'; return; }
    const indices = new Set();
    try {
      for (const part of pagesInput.value.replaceAll('–','-').split(',')) {
        const match = part.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
        if (!match) throw new Error('Use document pages such as 2-4, 6.');
        const first = Number(match[1]), last = Number(match[2] || match[1]);
        if (!Number.isSafeInteger(first) || !Number.isSafeInteger(last) || first < 1 || last < first || last > selected.version.page_count) throw new Error('Choose valid document page positions.');
        for (let page=first; page<=last; page++) indices.add(page-1);
      }
      if (!indices.size || [...indices].some(index => !selected.version.approved_page_indices.includes(index))) throw new Error('Choose only pages included in this source approval.');
    } catch (failure) { error.textContent = failure.message; return; }
    const body = { bindings:[{version_id:selected.version.id,page_indices:[...indices].sort((a,b)=>a-b)}],
      topic:document.getElementById('question-source-topic').value.trim(),count:Number(document.getElementById('source-draft-count').value),
      points_per_question:Number(document.getElementById('source-draft-marks').value),language:document.getElementById('source-draft-language').value,
      difficulty:document.getElementById('source-draft-difficulty').value };
    busy = true; assessment.disabled = true;
    const controls = [...form.elements]; controls.forEach(control => { control.disabled = true; });
    button.textContent = 'Saving generation request…'; const targetExam = examId, token = generation;
    try {
      const data = await MisraAPI.sourceQuestionDrafts(targetExam, body);
      if (token !== generation) return;
      dirty = false; document.getElementById('source-question-details').open = false;
      window.MisraExamSetup.watchSourceDraft(data);
    } catch (failure) { if (token === generation) error.textContent = `${failure.message} Your entries are still here. Reload to check saved setup requests before retrying.`; }
    finally {
      busy = false; assessment.disabled = false; controls.forEach(control => { control.disabled = false; });
      button.disabled = !options.length; button.textContent = 'Generate question drafts';
    }
  });
  window.MisraSourceDrafts = { hasUnsaved: () => dirty || busy, isBusy: () => busy };
})();
