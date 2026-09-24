/* Answer references are independently versioned; scoring remains in the rubric. */
(function () {
  'use strict';
  let host, examId, questionId, versions = [], current, draft, dirty = false, busy = false, loading = false, error = '', generation = 0;
  const esc = value => MisraUI.escapeHTML(String(value ?? ''));
  const blank = () => ({ mode: 'reference', reference_text: '', acceptable_answers: [], document_refs: [], change_summary: '' });
  const editable = () => !current || current.status === 'draft';
  const documentIndex = ref => versions.flatMap(v => v.document_refs || [])
    .find(saved => saved.job_id === ref.job_id && Number.isInteger(saved.document_index))?.document_index ?? 0;
  let pageValues = {};
  function reset() { generation++; host = null; versions = []; current = null; draft = blank(); dirty = false; busy = false; loading = false; error = ''; }
  function canLeave() {
    if (busy) { window.showToast('Wait for the answer-key operation to finish.', 'info'); return false; }
    return !dirty || window.confirm('Discard unsaved answer-key edits?');
  }
  function sync() {
    if (!host || !editable()) return;
    host.querySelectorAll('[data-key-pages]').forEach(el => { pageValues[draft.document_refs[Number(el.dataset.keyPages)]?.job_id] = el.value; });
    draft.reference_text = host.querySelector('#key-reference')?.value || '';
    draft.acceptable_answers = (host.querySelector('#key-alternatives')?.value || '').split('\n').map(x => x.trim()).filter(Boolean);
    draft.change_summary = host.querySelector('#key-summary')?.value || '';
  }
  function choose(version) { pageValues = {}; current = version || null; draft = version ? { mode: version.mode, reference_text: version.reference_text || '', acceptable_answers: [...(version.acceptable_answers || [])], document_refs: (version.document_refs || []).map(ref => ({ job_id: ref.job_id, page_indices: [...ref.page_indices] })), change_summary: version.change_summary || '' } : blank(); dirty = false; }
  async function load(assessmentId, qid) {
    reset(); examId = assessmentId; questionId = qid; loading = true;
    const request = generation;
    try { const result = await MisraAPI.answerKeyVersions(qid); if (request !== generation) return; versions = Array.isArray(result) ? result : []; choose(versions.find(v => v.status === 'draft') || versions.find(v => v.status === 'approved') || versions[0]); }
    catch (_) { if (request === generation) error = 'Could not load answer keys. Retry before editing.'; }
    finally { if (request === generation) { loading = false; render(); } }
  }
  function render() {
    if (!host?.isConnected) return;
    if (loading) { host.innerHTML = '<p role="status">Loading answer keys…</p>'; return; }
    const readOnly = !editable();
    host.innerHTML = `<div class="section-head"><div><h2 class="section-title" id="answer-key-title">Answer key</h2><p class="section-copy">Reference answers belong to this question. Scoring criteria and marks stay in the rubric.</p></div>${current ? MisraUI.badge(`Version ${current.version_number} · ${current.status}`, current.status === 'approved' ? 'success' : 'draft') : MisraUI.badge('Not saved', 'draft')}</div>
      ${error ? `<p class="check-error" role="alert">${esc(error)}</p>` : ''}
      ${error === 'Could not load answer keys. Retry before editing.' ? '<button class="btn btn-secondary" data-key-retry type="button">Retry answer keys</button>' : `
      <p class="field-hint">${versions.some(v => v.status === 'approved') ? 'Future grading uses the approved answer key. Draft changes do not affect grading.' : 'Until a key is approved, grading uses the legacy rubric reference when available.'}</p>
      <fieldset class="answer-key-fields" ${readOnly || busy ? 'disabled' : ''}>
        <div class="field"><label for="key-mode">Answer format</label><select class="input select" id="key-mode"><option value="reference" ${draft.mode === 'reference' ? 'selected' : ''}>Reference answer</option><option value="no_fixed_answer" ${draft.mode === 'no_fixed_answer' ? 'selected' : ''}>No fixed answer — judge using criteria</option></select></div>
        ${draft.mode === 'reference' ? `<div class="field"><label for="key-reference">Reference answer or worked solution</label><textarea class="input textarea" id="key-reference" rows="5" maxlength="50000" dir="auto">${esc(draft.reference_text)}</textarea></div><div class="field"><label for="key-alternatives">Acceptable alternatives (one per line)</label><textarea class="input textarea" id="key-alternatives" rows="3" dir="auto">${esc(draft.acceptable_answers.join('\n'))}</textarea></div>
<div class="key-documents"><h3>Reference documents</h3><p class="field-hint">Upload a PDF or image, then select the pages for this question. This stores a reference; it does not run OCR.</p>${draft.document_refs.map((ref, i) => `<div class="key-document"><a href="${esc(MisraAPI.setupDocumentUrl(examId, ref.job_id, documentIndex(ref)))}" target="_blank" rel="noopener">Open reference document ${i + 1}</a><label for="key-pages-${i}">Pages (starting at 1)</label><input id="key-pages-${i}" class="input" data-key-pages="${i}" value="${esc(ref.page_indices.map(p => p + 1).join(', '))}" placeholder="e.g. 1, 3"><button class="btn btn-ghost" data-key-remove="${i}" type="button">Remove reference ${i + 1}</button></div>`).join('')}${!readOnly ? '<label for="key-file">Add PDF or image</label><input class="input" type="file" id="key-file" accept="application/pdf,image/jpeg,image/png,image/webp"><button class="btn btn-secondary" type="button" data-key-upload>Upload reference document</button>' : ''}</div>` : '<p class="field-hint">No model answer is required. Approved scoring criteria guide evaluation of valid responses.</p>'}
        <div class="field"><label for="key-summary">Change summary</label><input class="input" id="key-summary" maxlength="2000" value="${esc(draft.change_summary)}"></div>
      </fieldset>
      <div class="key-actions">${readOnly ? '<button class="btn btn-secondary" data-key-new type="button">Create answer-key draft</button>' : '<button class="btn btn-secondary" data-key-save type="button">Save answer-key draft</button><button class="btn btn-primary" data-key-approve type="button">Save &amp; approve answer key</button>'}<span class="field-hint" role="status">${busy ? 'Working…' : dirty ? 'Unsaved answer-key changes' : readOnly ? 'This version is read-only.' : 'Approval applies to future grading only.'}</span></div>`}
      ${versions.length ? `<details class="key-history"><summary>Answer-key version history (${versions.length})</summary>${versions.map(v => `<div class="version-row"><button class="btn btn-ghost" data-key-version="${esc(v.id)}" type="button">Version ${v.version_number} · ${esc(v.status)}</button><span>${esc(v.change_summary)}</span></div>`).join('')}</details>` : ''}`;
    host.setAttribute('aria-busy', String(busy));
    host.querySelectorAll('[data-key-pages]').forEach(el => { const value = pageValues[draft.document_refs[Number(el.dataset.keyPages)]?.job_id]; if (value !== undefined) el.value = value; });
    if (busy) host.querySelectorAll('button, input, select, textarea').forEach(el => { el.disabled = true; });
    host.querySelector('[data-key-retry]')?.addEventListener('click', () => { const target = host; load(examId, questionId); host = target; render(); });
    host.querySelectorAll('input, textarea').forEach(el => el.addEventListener('input', () => { dirty = true; const status = host.querySelector('.key-actions [role="status"]'); if (status) status.textContent = 'Unsaved answer-key changes'; }));
    host.querySelector('#key-mode')?.addEventListener('change', event => { sync(); draft.mode = event.target.value; dirty = true; render(); });
    host.querySelector('[data-key-new]')?.addEventListener('click', () => { current = null; dirty = true; render(); });
    host.querySelector('[data-key-save]')?.addEventListener('click', () => save(false));
    host.querySelector('[data-key-approve]')?.addEventListener('click', () => save(true));
    host.querySelector('[data-key-upload]')?.addEventListener('click', upload);
    host.querySelectorAll('[data-key-remove]').forEach(el => el.addEventListener('click', () => { sync(); draft.document_refs.splice(Number(el.dataset.keyRemove), 1); dirty = true; render(); }));
    host.querySelectorAll('[data-key-version]').forEach(el => el.addEventListener('click', () => { if (canLeave()) { choose(versions.find(v => v.id === el.dataset.keyVersion)); error = ''; render(); } }));
  }
  function payload() {
    sync();
    if (draft.mode === 'no_fixed_answer') return { ...draft, reference_text: '', acceptable_answers: [], document_refs: [] };
    host.querySelectorAll('[data-key-pages]').forEach(el => {
      const tokens = el.value.split(',').map(x => x.trim());
      if (!tokens.length || tokens.some(x => !/^[1-9]\d*$/.test(x) || !Number.isSafeInteger(Number(x)))) throw new Error('Enter page numbers starting at 1, separated by commas.');
      const pages = tokens.map(x => Number(x) - 1);
      if (new Set(pages).size !== pages.length) throw new Error('Select each page only once.');
      draft.document_refs[Number(el.dataset.keyPages)].page_indices = pages;
    });
    if (!draft.reference_text.trim() && !draft.acceptable_answers.length && !draft.document_refs.length) throw new Error('Add reference text, an alternative, or reference pages. Or select No fixed answer.');
    return structuredClone(draft);
  }
  async function save(approve) {
    if (busy || !editable()) return;
    let body;
    try { body = payload(); } catch (e) { error = e.message; render(); return; }
    if (approve && !window.confirm('Approve this answer key for future grading? Approved versions cannot be edited.')) return;
    const request = generation, qid = questionId; busy = true; error = ''; render();
    try {
      const saved = current ? await MisraAPI.updateAnswerKey(qid, current.id, body) : await MisraAPI.createAnswerKey(qid, body);
      if (request !== generation) return;
      current = saved; dirty = false;
      versions = [saved, ...versions.filter(v => v.id !== saved.id)];
      if (approve) { const approved = await MisraAPI.approveAnswerKey(qid, saved.id); if (request !== generation) return; choose(approved); versions = versions.map(v => v.id === approved.id ? approved : v.status === 'approved' ? { ...v, status: 'superseded' } : v); window.dispatchEvent(new CustomEvent('misra:answer-key-approved')); }
      else choose(saved);
      window.showToast(approve ? 'Answer key approved.' : 'Answer-key draft saved.', 'success');
    } catch (_) { if (request === generation) error = approve && !dirty ? 'Draft saved, but approval failed. Retry approval.' : 'Could not save the answer key. Your edits are still here; retry when connected.'; }
    finally { if (request === generation) { busy = false; render(); } }
  }
  async function upload() {
    if (busy) return;
    const file = host.querySelector('#key-file')?.files[0];
    if (!file) { error = 'Choose a PDF or image first.'; render(); return; }
    sync(); if (draft.document_refs.length >= 5) { error = 'Use no more than five reference documents.'; render(); return; } const request = generation; const data = new FormData(); data.append('file', file); busy = true; error = ''; render();
    try { const doc = await MisraAPI.uploadAnswerKeyDocument(questionId, data); if (request !== generation) return; draft.document_refs.push({ job_id: doc.job_id, page_indices: [0] }); dirty = true; window.showToast(`Document uploaded (${doc.page_count} pages). Select the pages for this question.`, 'success'); }
    catch (_) { if (request === generation) error = 'Document upload failed. Choose the file again and retry.'; }
    finally { if (request === generation) { busy = false; render(); } }
  }
  window.MisraAnswerKeys = { load, reset, canLeave, discard() { choose(current); error = ''; render(); }, hasUnsaved: () => dirty || busy, mount(element) { sync(); host = element; render(); } };
})();
