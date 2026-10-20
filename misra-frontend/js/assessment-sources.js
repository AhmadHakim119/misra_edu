/* Assessment defaults are versioned approvals, not automatically inferred rules. */
(function () {
  'use strict';
  const native = /\/(?:next|app)\//.test(location.pathname);
  const esc = value => MisraUI.escapeHTML(String(value ?? ''));
  const host = document.getElementById('assessment-sources-host');
  if (!host) return;
  let examId = '', courseId = '', epoch = 0, materials = [], data = null;
  let mode = 'required', rows = [], dirty = false, busy = false, loading = false, error = '', notice = '';
  const pending = v => v.status==='draft' && ['ready','needs_transcription'].includes(v.ingestion_status) && v.page_count>0;
  const choices = () => materials.flatMap(m => (m.versions || []).filter(v => ['approved','superseded'].includes(v.status) || native && pending(v)).map(v => ({m,v})));
  const hasUnsaved = () => dirty || busy;
  const canLeave = () => !busy && (!dirty || window.confirm('Discard unsaved assessment-source changes?'));
  let summaryPending = false;
  let sourceDetailsOpen = false;
  const summaryRows = () => (data?.questions || []).map(q => `<li>Question ${esc(q.question_number)}: ${q.origin === 'assessment' ? 'uses assessment default' : q.origin === 'question' ? `approved question exception (${esc(q.scope?.mode)})` : q.origin === 'blocked' ? esc(q.error) : 'no approved source scope'}</li>`).join('');
  function updateSaveStatus() {
    const status = host.querySelector('[data-default-save-state]');
    if (status) status.textContent = dirty ? 'Unsaved assessment-source changes' : notice;
  }
  async function refreshSummary() {
    if (!data || !examId) return;
    if (busy) { summaryPending = true; return; }
    const current = epoch;
    try {
      const value = await MisraAPI.assessmentMaterialScopes(examId);
      if (current !== epoch || !Array.isArray(value?.questions)) return;
      data.questions = value.questions;
      const list = host.querySelector('[data-default-summary]');
      if (list) list.innerHTML = summaryRows();
      const status = host.querySelector('[data-default-summary-status]');
      if (status) status.textContent = '';
    } catch (_) {
      if (current === epoch) { const status = host.querySelector('[data-default-summary-status]'); if (status) status.textContent = 'Question source status could not refresh. Reload saved sources to check it.'; }
    }
  }

  function capture() {
    const input = host.querySelector('[data-default-mode]');
    if (input) mode = input.value;
    host.querySelectorAll('[data-default-row]').forEach((el,i) => {
      rows[i] = {version_id:el.querySelector('[data-default-version]').value, pages:el.querySelector('[data-default-pages]').value};
    });
  }
  function pages(input, version, allowPending=false) {
    const selected = new Set();
    for (const token of input.trim().replaceAll('–','-').split(',')) {
      const match = token.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
      if (!match) throw new Error('Use document pages such as 2-4, 6.');
      const first = Number(match[1]), last = Number(match[2] || match[1]);
      if (first < 1 || last < first || last > version.page_count) throw new Error(`Choose document pages between 1 and ${version.page_count}.`);
      for (let n = first; n <= last; n++) selected.add(n - 1);
    }
    if (!(allowPending && pending(version)) && [...selected].some(n => !(version.approved_page_indices || []).includes(n))) throw new Error('Review and approve these pages in the course library first.');
    return [...selected].sort((a,b) => a-b);
  }
  function render() {
    if (loading) { host.innerHTML = '<p role="status">Loading assessment sources…</p>'; return; }
    const active = data?.versions?.find(v => v.status === 'approved');
    const draft = data?.versions?.find(v => v.status === 'draft');
    const disabled = busy ? 'disabled' : '';
    host.innerHTML = `${error ? `<div role="alert"><p>${esc(error)}</p><button type="button" class="btn btn-secondary" data-default-reload ${disabled}>Reload saved sources</button></div>` : ''}
      ${!data ? '' : `<p class="section-copy">Choose approved material once for this assessment. Every question uses it unless it has an approved exception. Sources explain the subject; your rubric still decides marks.</p>
      <p class="field-hint">${active ? `Active default${native ? '' : ` v${active.version_number}`} · ${esc(active.mode)}.` : 'No approved assessment default yet.'} Drafts do not affect grading or replace active defaults.</p>
      <button type="button" data-default-all ${busy || !choices().some(({v})=>v.status==='approved'&&v.approved_page_indices?.length) ? 'disabled' : ''}>Use all currently approved course materials</button><p class="field-hint">Copies checked pages into a draft. New material is never silently added. AI retrieves relevant passages per question.</p>
      <label for="assessment-source-mode">How should references be used?</label><select class="input select" id="assessment-source-mode" data-default-mode ${disabled}>
        <option value="required" ${mode === 'required' ? 'selected' : ''}>Require relevant references</option>
        <option value="optional" ${mode === 'optional' ? 'selected' : ''}>Use references when available</option>
        <option value="disabled" ${mode === 'disabled' ? 'selected' : ''}>Do not use references</option></select>
      <p class="field-hint">${mode === 'required' ? 'Grading stops if relevant approved context is missing.' : mode === 'optional' ? 'Missing context is flagged for instructor review.' : 'Question-specific exceptions still apply.'}</p>
      ${mode === 'disabled' ? '' : `<div class="source-bindings">${rows.map((row,i) => `<fieldset data-default-row><legend>Source ${i+1}</legend><div class="material-binding-grid">
        <div class="field"><label for="assessment-version-${i}">Approved material</label><select class="input select" id="assessment-version-${i}" data-default-version ${disabled}><option value="">Choose approved material</option>${choices().map(({m,v}) => `<option value="${esc(v.id)}" ${v.id === row.version_id ? 'selected' : ''}>${esc(m.title)}${native ? ((m.versions || []).length > 1 ? ` · ${esc(v.status)} · revision ${v.version_number}` : '') : ` · v${v.version_number}`}${v.status === 'superseded' ? ' (previous approval)' : ''}</option>`).join('')}</select></div>
        <div class="field"><label for="assessment-pages-${i}">Document pages</label><input class="input" id="assessment-pages-${i}" data-default-pages value="${esc(row.pages)}" placeholder="e.g. 2-4, 6" ${disabled}><span class="field-hint">PDF positions, starting at 1—not printed page labels.</span></div></div><button type="button" class="btn btn-ghost" data-default-remove="${i}" ${disabled}>Remove assessment source</button></fieldset>`).join('')}</div><button type="button" class="btn btn-secondary" data-default-add ${busy || !choices().length || rows.length >= 64 ? 'disabled' : ''}>Add assessment source</button>`}
      <div class="material-actions"><button type="button" class="btn btn-secondary" data-default-save ${disabled}>Save assessment source draft</button><button type="button" class="btn btn-primary" data-default-approve ${disabled}>Save &amp; approve assessment sources</button></div>
      <p role="status" data-default-save-state>${esc(dirty ? 'Unsaved assessment-source changes' : notice || (draft ? `Saved draft${native ? '' : ` v${draft.version_number}`} · not used for grading` : 'Existing grades and historical source snapshots are unchanged.'))}</p>
      <details><summary>Question exceptions and inheritance</summary><p>Existing question-specific approvals take precedence. In a question’s Course sources section, choose “Use assessment default” and approve to remove an exception.</p><ul data-default-summary>${summaryRows()}</ul><p role="status" data-default-summary-status></p></details>`}`;
    host.setAttribute('aria-busy', String(busy));
    const sourceRows = host.querySelector('.source-bindings');
    if (sourceRows && host.closest('#ledger-setup')) {
      const details = document.createElement('details'); details.open = sourceDetailsOpen;
      const summary = document.createElement('summary'); summary.textContent = `Choose or adjust materials · ${rows.length} selected`;
      details.append(summary); sourceRows.before(details); details.append(sourceRows);
      details.addEventListener('toggle',()=>{sourceDetailsOpen=details.open;});
    }
    host.querySelector('[data-default-mode]')?.addEventListener('change', () => { capture(); dirty = true; notice = ''; if (mode === 'disabled') rows = []; render(); });
    host.querySelectorAll('input,select').forEach(el => el.addEventListener('input', () => { dirty = true; notice = ''; capture(); updateSaveStatus(); }));
    host.querySelector('[data-default-add]')?.addEventListener('click', () => { capture(); rows.push({version_id:'',pages:''}); dirty = true; sourceDetailsOpen=true; render(); });
    host.querySelector('[data-default-all]')?.addEventListener('click', () => {
      const latest = materials.map(m => (m.versions || []).filter(v => v.status === 'approved' && v.approved_page_indices?.length).sort((a,b)=>b.version_number-a.version_number)[0]).filter(Boolean);
      if (!latest.length || latest.length > 64) { error = 'Choose up to 64 currently approved materials. Check pages in the course library first.'; render(); return; }
      mode = 'required'; rows = latest.map(v => ({version_id:v.id,pages:v.approved_page_indices.map(n=>n+1).join(', ')})); dirty = true; sourceDetailsOpen=false; notice = ''; error = ''; render();
    });
    host.querySelectorAll('[data-default-remove]').forEach(el => el.addEventListener('click', () => { capture(); rows.splice(Number(el.dataset.defaultRemove),1); dirty = true; render(); }));
    host.querySelector('[data-default-save]')?.addEventListener('click', () => save(false));
    host.querySelector('[data-default-approve]')?.addEventListener('click', () => save(true));
    host.querySelector('[data-default-reload]')?.addEventListener('click', () => { if (canLeave()) load(examId,courseId); });
  }
  async function load(id, course) {
    if (!id) return;
    const current = ++epoch;
    examId = id; courseId = course; dirty = false; error = notice = ''; rows = []; data = null; loading = true; render();
    sourceDetailsOpen = false;
    try {
      const [scope, library] = await Promise.all([MisraAPI.assessmentMaterialScopes(id), MisraAPI.courseMaterials(course)]);
      if (current !== epoch) return;
      if (!Array.isArray(scope?.versions) || !Array.isArray(scope?.questions) || !Array.isArray(library)) throw new Error('Source response is incomplete. Reload before saving.');
      data = scope; materials = library;
      const selection = data.versions.find(v => v.status === 'draft') || data.versions.find(v => v.status === 'approved');
      mode = selection?.mode || 'required'; rows = (selection?.bindings || []).map(b => ({version_id:b.version_id,pages:b.page_indices.map(n=>n+1).join(', ')}));
    } catch (failure) { if (current === epoch) error = failure.message; }
    finally { if (current === epoch) { loading = false; render(); window.dispatchEvent(new CustomEvent('misra:assessment-sources-loaded')); } }
  }
  async function save(approve,allowPending=false) {
    if (busy) return;
    capture(); let body;
    try {
      const seen = new Set();
      const bindings = mode === 'disabled' ? [] : rows.map(row => {
        const option = choices().find(({v}) => v.id === row.version_id);
        if (!option) throw new Error('Choose approved material for each assessment source.');
        if (seen.has(row.version_id)) throw new Error('Combine pages from the same material in one row.');
        seen.add(row.version_id);
        return {version_id:row.version_id,page_indices:pages(row.pages, option.v,!approve && allowPending),criterion_id:null,chunk_ids:[]};
      });
      if (mode !== 'disabled' && !bindings.length) throw new Error('Add approved material or explicitly disable assessment references.');
      body = {mode,bindings,...(!approve && allowPending?{allow_pending_sources:true}:{})};
    } catch (failure) { error = failure.message; render(); return; }
    if (approve && !window.confirm('Approve these defaults for future grading of this assessment? Question exceptions remain in force. Existing grades are not changed.')) return;
    const current = epoch, id = examId;
    busy = true; error = ''; render();
    try {
      const draft = await MisraAPI.createAssessmentMaterialScope(id, body);
      if (!draft?.id) throw new Error('The save response is incomplete. Reload saved versions before retrying.');
      if (current !== epoch) return;
      data.versions.unshift(draft); dirty = false;
      notice = `Draft${native ? '' : ` v${draft.version_number}`} saved—not active yet.`;
      if (approve) {
        notice = 'Approval requested. If confirmation is interrupted, reload saved sources before retrying.';
        const approved = await MisraAPI.approveAssessmentMaterialScope(id,draft.id);
        if (current !== epoch) return;
        notice = `Approval confirmed for default${native ? '' : ` v${draft.version_number}`}. Existing grades are unchanged.`;
        data.versions = data.versions.map(v => v.id === draft.id ? {...v,...approved,status:'approved'} : v.status === 'approved' ? {...v,status:'superseded'} : v);
        data = await MisraAPI.assessmentMaterialScopes(id);
        notice = 'Assessment sources approved for future runs. Historical grades are unchanged.';
        window.dispatchEvent(new CustomEvent('misra:assessment-sources-approved', {detail:{examId:id}}));
      }
    } catch (failure) { if (current === epoch) error = `${failure.message} ${dirty ? 'Your entries are retained.' : notice}`; }
    finally { if (current === epoch) { busy = false; render(); if (summaryPending) { summaryPending = false; refreshSummary(); } } }
  }
  function reset() {
    if (busy) return false;
    ++epoch; examId=courseId=''; materials=[]; data=null;rows=[];dirty=loading=false;error=notice='';summaryPending=false;
    host.innerHTML='<p>Choose an assessment to configure its shared references.</p>'; host.setAttribute('aria-busy','false'); return true;
  }
  window.MisraAssessmentSources = {hasUnsaved, canLeave, isBusy:()=>busy,reload:()=>load(examId,courseId),async saveDraft(options={}){if(dirty && !busy)await save(false,native && options.allowPendingSources===true);return !hasUnsaved();},reset,
    selection(){capture();return {ready:!loading&&Boolean(data),mode,bindings:rows.map(row=>{const choice=choices().find(({v})=>v.id===row.version_id);if(!choice)throw Error('Finish the existing source selection before choosing chapters.');return {version_id:row.version_id,page_indices:pages(row.pages,choice.v,native),criterion_id:null,chunk_ids:[]};})};},
    chooseChapters(bindings,nextMode){if(loading||busy||!data)return false;rows=bindings.map(b=>({version_id:b.version_id,pages:b.page_indices.map(n=>n+1).join(', ')}));mode=nextMode;dirty=true;notice='';error='';render();return true;}
  };
  window.addEventListener('misra:assessment-loaded', event => load(event.detail.examId,event.detail.courseId));
  window.addEventListener('misra:material-approved', () => { if (!hasUnsaved()) load(examId,courseId); });
  window.addEventListener('misra:question-sources-approved', event => { if (event.detail.examId === examId) refreshSummary(); });
  window.addEventListener('beforeunload', event => { if (hasUnsaved()) { event.preventDefault(); event.returnValue=''; } });
})();
