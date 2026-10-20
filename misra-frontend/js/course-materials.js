/* Approved course references. Provider calls happen only when grading, never here. */
(function () {
  'use strict';
  const escape = value => MisraUI.escapeHTML(String(value ?? ''));
  let host, courseId, questionId, criteria = [], materials = [], scopes = [], bindings = [];
  let mode = 'required', loading = false, busy = false, dirty = false, error = '', notice = '', generation = 0;
  let effective = null;
  let review = null, page = null, pageDirty = false, preview = null, timer = null;
  let materialForm = { title: '', text: '', file: null };
  let revisionFiles = new Map();
  const disabledControls = new Map();
  const native = /\/(?:next|app)\//.test(location.pathname);
  const suffix = number => native ? '' : ` · v${number}`;
  const materialLabel = (m,v) => native ? ((m.versions || []).length > 1 ? ` · ${v.status} · revision ${v.version_number}` : '') : ` · v${v.version_number}`;
  const active = new Set(['queued', 'processing', 'retrying']);

  function reviewDirty() { return pageDirty || Boolean(review?._approvalPages || review?._confirmed); }
  function hasUnsaved() { return dirty || reviewDirty() || busy || revisionFiles.size > 0 || Boolean(materialForm.title || materialForm.text || materialForm.file); }
  function canLeave() {
    if (busy) { window.showToast('Wait for the source operation to finish.', 'info'); return false; }
    return !hasUnsaved() || window.confirm('Discard unsaved course-source edits?');
  }
  function reset() {
    generation++; clearTimeout(timer); host = null; courseId = null; questionId = null;
    materials = []; scopes = []; bindings = []; review = null; page = null; preview = null; effective = null;
    materialForm = { title: '', text: '', file: null };
    revisionFiles = new Map(); disabledControls.clear();
    loading = busy = dirty = pageDirty = false; error = notice = '';
  }
  async function load(course, question, rubricCriteria) {
    generation++; clearTimeout(timer); courseId = course; questionId = question; criteria = rubricCriteria || [];
    materials = []; scopes = []; bindings = []; materialForm = { title: '', text: '', file: null };
    revisionFiles = new Map();
    review = page = preview = null; dirty = pageDirty = false; error = notice = ''; loading = true; render();
    const request = generation;
    if (!course) { loading = false; error = 'Course information is unavailable. Reload this assessment to access its source library.'; render(); return; }
    try {
      const [library, versions, inherited] = await Promise.all([MisraAPI.courseMaterials(course), question ? MisraAPI.materialScopes(question) : Promise.resolve([]), question ? MisraAPI.effectiveMaterialScope(question).catch(() => null) : Promise.resolve(null)]);
      if (request !== generation) return;
      if (!Array.isArray(library) || !Array.isArray(versions)) throw new Error('Source-library response is invalid. Reload before making changes.');
      materials = library; scopes = versions; effective = inherited;
      const selected = scopes.find(item => item.status === 'draft') || scopes.find(item => item.status === 'approved');
      bindings = structuredClone(selected?.bindings || []); mode = selected?.mode || (effective?.origin === 'assessment' ? 'inherit' : 'required');
      loading = false; render(); schedule();
    } catch (failure) { if (request === generation) { loading = false; error = failure.message; render(); } }
  }
  function choices() {
    return materials.flatMap(material => (material.versions || []).filter(v => ['approved', 'superseded'].includes(v.status))
      .map(version => ({ material, version })));
  }
  function parsePages(value, max) {
    const indices = new Set();
    const input = String(value).trim();
    if (!input) throw new Error('Choose reference pages, such as 2–4 or 2, 6.');
    for (const part of input.replaceAll('–', '-').split(',')) {
      const match = part.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
      if (!match) throw new Error('Use page numbers or ranges, such as 2-4, 6. Page numbers start at 1.');
      const first = Number(match[1]), last = Number(match[2] || match[1]);
      if (!Number.isSafeInteger(first) || !Number.isSafeInteger(last) || first < 1 || last < first || last > max) throw new Error(`Choose pages between 1 and ${max}.`);
      for (let number = first; number <= last; number++) indices.add(number - 1);
    }
    return [...indices].sort((a, b) => a - b);
  }
  const pageLabels = indices => (indices || []).map(index => index + 1).join(', ');
  function readBindings() {
    return [...host.querySelectorAll('[data-source-binding]')].map(row => {
      const option = choices().find(item => item.version.id === row.querySelector('[data-source-version]').value);
      if (!option) throw new Error('Choose an approved material version for each reference.');
      const indices = parsePages(row.querySelector('[data-source-pages]').value, option.version.page_count);
      if (indices.some(index => !(option.version.approved_page_indices || []).includes(index))) throw new Error('One of these pages is not approved. Review and approve it in the course library first.');
      return { version_id: option.version.id, page_indices: indices,
        criterion_id: row.querySelector('[data-source-criterion]').value || null,
        chunk_ids: row.querySelector('[data-source-passages]').value.split(',').map(id => id.trim()).filter(Boolean) };
    });
  }
  function preserveBindings() {
    // Preserve incomplete fields too; failed validation must not erase typed pages.
    host?.querySelectorAll('[data-source-binding]').forEach((row, index) => {
      const previous = bindings[index] || {};
      bindings[index] = { ...previous, version_id: row.querySelector('[data-source-version]').value,
        criterion_id: row.querySelector('[data-source-criterion]').value || null,
        _pages: row.querySelector('[data-source-pages]').value, _chunks: row.querySelector('[data-source-passages]').value };
    });
    const selection = host?.querySelector('#source-retrieval-mode'); if (selection) mode = selection.value;
  }
  function scopeEditor() {
    const approved = effective?.scope || scopes.find(item => item.status === 'approved' && item.mode !== 'inherit');
    const draft = scopes.find(item => item.status === 'draft');
    const options = choices();
    return `<div class="material-scope-head"><div><h3>Sources for this question</h3><p class="section-copy">${effective?.origin === 'assessment' ? 'Uses the approved assessment default. Change only if this question needs an exception. ' : ''}The rubric decides the marks. Course sources supply context, not new grading rules.</p></div>${MisraUI.badge(approved ? `${effective?.origin === 'assessment' ? 'Assessment default' : 'Active scope'}${native ? '' : ` v${approved.version_number}`}` : 'Not configured', approved ? 'success' : 'draft')}</div>
      <div class="field"><label for="source-retrieval-mode">How should sources be used?</label><select class="input select" id="source-retrieval-mode"><option value="inherit" ${mode === 'inherit' ? 'selected' : ''}>Use assessment default — no question exception</option><option value="required" ${mode === 'required' ? 'selected' : ''}>Required — stop if relevant context is missing</option><option value="optional" ${mode === 'optional' ? 'selected' : ''}>Optional — flag missing context for review</option><option value="disabled" ${mode === 'disabled' ? 'selected' : ''}>Do not retrieve course sources</option></select></div>
      ${mode === 'inherit' ? '<p class="field-hint">Approve this choice to use the current and future approved assessment default. Existing runs keep their snapshots.</p>' : mode === 'disabled' ? '<p class="field-hint">Disabling sources is a versioned decision. Your approved key and rubric still apply.</p>' : `<div class="source-bindings">${bindings.map((binding,index) => `<fieldset data-source-binding="${index}"><legend>Reference ${index + 1}</legend><div class="material-binding-grid"><div class="field"><label for="source-version-${index}">Approved material</label><select class="input select" id="source-version-${index}" data-source-version><option value="">Choose a source</option>${options.map(({material,version}) => `<option value="${escape(version.id)}" ${version.id === binding.version_id ? 'selected' : ''}>${escape(material.title)}${escape(materialLabel(material,version))}${version.status === 'superseded' ? ' (previous approval)' : ''}</option>`).join('')}</select></div><div class="field"><label for="source-pages-${index}">Document pages</label><input class="input" id="source-pages-${index}" data-source-pages value="${escape(binding._pages ?? pageLabels(binding.page_indices))}" placeholder="e.g. 2-4, 6"><span class="field-hint">PDF position, starting at 1; not the printed page label.</span></div><div class="field"><label for="source-criterion-${index}">Applies to</label><select class="input select" id="source-criterion-${index}" data-source-criterion><option value="">All criteria</option>${criteria.map(c => `<option value="${escape(c.id)}" ${binding.criterion_id === c.id ? 'selected' : ''}>${escape(c.title || c.description || c.id)}</option>`).join('')}</select></div></div><details class="source-exact"><summary>Choose exact passages instead of search (optional)</summary><label for="source-passages-${index}">Passage IDs from the page review</label><input class="input" id="source-passages-${index}" data-source-passages value="${escape(binding._chunks ?? (binding.chunk_ids || []).join(', '))}"><p class="field-hint">Normally, leave empty. Exact links help with formulas or wording that keyword search misses. Up to 8 IDs, separated by commas; retrieval takes up to 2 passages per criterion.</p></details><button class="btn btn-ghost" data-source-remove="${index}" type="button">Remove reference</button></fieldset>`).join('')}</div><button class="btn btn-secondary" type="button" data-source-add ${!options.length || bindings.length >= 8 ? 'disabled' : ''}>Add reference</button>${!options.length ? '<p class="field-hint">Add a source to the library below, review its extracted text, and approve it first.</p>' : ''}`}
      <div class="material-actions"><button class="btn btn-secondary" type="button" data-source-save>Save source draft</button><button class="btn btn-primary" type="button" data-source-approve>Save &amp; approve sources</button><button class="btn btn-ghost" type="button" data-source-preview ${!approved ? 'disabled' : ''}>Preview active retrieval</button></div>
      <p class="field-hint" role="status">${dirty ? 'Unsaved source changes' : draft ? `Saved draft${native ? '' : ` v${draft.version_number}`} — not used for grading` : approved ? 'Approved sources apply to future runs. Historical runs keep their own snapshots.' : 'Existing grading works without a course-source scope. Configure one to enable grounded retrieval.'}</p>
      ${preview ? `<div class="retrieval-preview"><h4>What the next grading run can retrieve</h4><p>${escape(preview.status)} · ${preview.passages?.length || 0} passages · keyword retrieval, not a correctness guarantee.</p>${(preview.passages || []).map(p => `<details><summary>${escape(p.title)}${suffix(p.material_version_number)} · document page ${p.page_index + 1}${p.printed_page_label ? ` (printed ${escape(p.printed_page_label)})` : ''}</summary><pre dir="auto">${escape(p.text)}</pre><p class="field-hint">Applies to ${escape((p.criterion_ids || []).join(', '))} · ${escape(p.selection)}</p></details>`).join('')}</div>` : ''}`;
  }
  function render() {
    if (!host?.isConnected) return;
    if (loading) { host.innerHTML = '<p role="status">Loading this course’s approved sources…</p><div class="skel material-loading"></div>'; return; }
    if (!courseId) { host.innerHTML = `<p role="alert">${escape(error || 'Choose an assessment first.')}</p>`; return; }
    host.innerHTML = `${error ? `<div class="material-error" role="alert"><strong>Source action could not finish</strong><p>${escape(error)}</p><p>Your current entries have been retained where possible.</p><button class="btn btn-secondary" type="button" data-material-reload>Reload sources</button></div>` : ''}${notice ? `<p class="material-notice" role="status">${escape(notice)}</p>` : ''}
      ${questionId ? `<div class="material-scope">${scopeEditor()}</div>` : host.closest('#native-library') ? '<p class="section-copy">Approved pages can be used as assessment defaults or linked to individual questions. Approval never changes existing grading runs.</p>' : '<p class="section-copy">Review and approve course pages here before generating questions. Question-specific source links are configured after you add a question.</p>'}
      <details class="material-library" ${host.closest('#native-library') || !materials.length || review || revisionFiles.size || materialForm.title || materialForm.text || materialForm.file ? 'open' : ''}><summary>Course library <span>${materials.length} material${materials.length === 1 ? '' : 's'}</span></summary>
        <p class="section-copy">Upload textbook chapters or slides once, then link approved pages to different questions. These files never count as student papers.</p>
        <div class="material-library-list">${materials.map(m => `<div class="material-library-row"><div><strong>${escape(m.title)}</strong><p>${(m.versions || []).map(v => `${escape(`${native ? ((m.versions || []).length > 1 ? `Revision ${v.version_number} · ` : '') : `v${v.version_number} · `}${v.status} · ${v.ingestion_status.replaceAll('_',' ')} · ${v.page_count} pages`)}`).join('<br>')}</p></div><div class="material-actions">${(m.versions || []).map(v => `<button class="btn btn-secondary" data-material-review="${escape(m.id)}" data-version="${escape(v.id)}" type="button" ${active.has(v.job?.status || v.ingestion_status) ? 'disabled' : ''}>${native ? 'Review source pages' : 'Review'}${native ? ((m.versions || []).length > 1 ? ` · ${escape(v.status)} · revision ${v.version_number}` : '') : ` v${v.version_number}`}</button>${v.job?.status === 'failed' ? `<button class="btn btn-secondary" data-material-retry="${escape(v.job.id)}" type="button">Retry reading</button>` : ''}`).join('')}</div><details><summary>Upload a new version</summary><form data-revision-form="${escape(m.id)}"><label>Replacement PDF<input class="input" type="file" accept=".pdf" required></label><button class="btn btn-secondary" type="submit">Upload draft version</button><p class="field-hint">Previous approvals and grading history remain unchanged.</p></form></details></div>`).join('')}</div>
        <details class="material-add"><summary>Add a textbook chapter or teaching notes</summary><form data-material-form><div class="field"><label for="material-title">Material title</label><input class="input" id="material-title" maxlength="255" required placeholder="e.g. Chapter 7 — Work and energy"></div><div class="field"><label for="material-file">PDF document <span class="field-hint">(or type reference text below)</span></label><input class="input" id="material-file" type="file" accept=".pdf"><span class="field-hint">Up to 25 MB by default. Native text is read locally, not sent to an AI.</span></div><div class="field"><label for="material-text">Reference text</label><textarea class="input textarea" id="material-text" rows="5" maxlength="50000" dir="auto" placeholder="Use this instead of a PDF for short, verified teaching notes."></textarea></div><button class="btn btn-primary" type="submit">Add material draft</button></form></details>
      </details><div class="material-review-host"></div>`;
    bind();
    host.querySelectorAll('[data-revision-form]').forEach(form => {
      const file = revisionFiles.get(form.dataset.revisionForm);
      if (file) { const transfer = new DataTransfer(); transfer.items.add(file); form.querySelector('input').files = transfer.files; form.closest('details').open = true; }
    });
    const addForm = host.querySelector('[data-material-form]');
    if (addForm) {
      addForm.querySelector('#material-title').value = materialForm.title;
      addForm.querySelector('#material-text').value = materialForm.text;
      if (materialForm.file) {
        const transfer = new DataTransfer(); transfer.items.add(materialForm.file);
        addForm.querySelector('#material-file').files = transfer.files;
      }
      if (materialForm.title || materialForm.text || materialForm.file) addForm.closest('details').open = true;
    }
    if (review) renderReview();
    setDisabled(busy);
  }
  function setDisabled(value) {
    host?.setAttribute('aria-busy',String(value));
    if (value) host?.querySelectorAll('button,input,textarea,select').forEach(el => { if (!disabledControls.has(el)) disabledControls.set(el,el.disabled); el.disabled = true; });
    else { disabledControls.forEach((disabled,el) => { if (el.isConnected) el.disabled = disabled; }); disabledControls.clear(); }
  }
  async function operation(fn, { rerender = true } = {}) {
    if (busy) return;
    preserveBindings();
    if (host?.closest('#rubric-workspace')?.getAttribute('aria-busy') === 'true') {
      window.showToast('Wait for the rubric save to finish before changing course sources.','info'); return;
    }
    busy = true; error = ''; setDisabled(true); const request = generation;
    try { await fn(request); }
    catch (failure) { if (request === generation) { error = failure.message; window.showToast(failure.message,'error'); } }
    finally { if (request === generation) { busy = false; setDisabled(false); if (rerender) render(); else { if (error) window.showToast('Your entries are still here. Correct the problem and retry.','info'); } schedule(); } }
  }
  async function refreshLibrary(request) {
    const library = await MisraAPI.courseMaterials(courseId);
    if (request === generation && Array.isArray(library)) materials = library;
  }
  function schedule() {
    clearTimeout(timer);
    if (!materials.some(m => m.versions?.some(v => active.has(v.job?.status || v.ingestion_status)))) return;
    const request = generation;
    timer = setTimeout(async () => {
      if (request !== generation) return;
      if (hasUnsaved()) { schedule(); return; }
      try { await refreshLibrary(request); if (request === generation) { render(); schedule(); } }
      catch (_) { if (request === generation) { notice = 'Connection interrupted. Reading may continue in the background. Reload sources to reconnect.'; render(); } }
    },4000);
  }
  function bind() {
    host.querySelector('#source-retrieval-mode')?.addEventListener('change',event => { preserveBindings(); dirty = true; if (['disabled','inherit'].includes(event.target.value)) bindings = []; render(); });
    host.querySelectorAll('[data-source-binding] input,[data-source-binding] select').forEach(el => el.addEventListener('input',() => { dirty = true; preserveBindings(); }));
    host.querySelector('[data-source-add]')?.addEventListener('click',() => { preserveBindings(); bindings.push({version_id:'',page_indices:[],criterion_id:null,chunk_ids:[]}); dirty = true; render(); });
    host.querySelectorAll('[data-source-remove]').forEach(el => el.addEventListener('click',() => { preserveBindings(); bindings.splice(Number(el.dataset.sourceRemove),1); dirty = true; render(); }));
    host.querySelector('[data-source-save]')?.addEventListener('click',() => saveScope(false));
    host.querySelector('[data-source-approve]')?.addEventListener('click',() => saveScope(true));
    host.querySelector('[data-source-preview]')?.addEventListener('click',() => operation(async request => { const result = await MisraAPI.materialRetrievalPreview(questionId); if (request === generation) preview = result; }));
    host.querySelector('[data-material-reload]')?.addEventListener('click',() => { if (canLeave()) load(courseId,questionId,criteria); });
    host.querySelectorAll('[data-material-review]').forEach(el => el.addEventListener('click',() => {
      if (reviewDirty() && !window.confirm('Discard unsaved page-review and approval edits?')) return;
      review = {materialId:el.dataset.materialReview,versionId:el.dataset.version,index:0}; pageDirty = false;
      openPage();
    }));
    host.querySelectorAll('[data-material-retry]').forEach(el => el.addEventListener('click',() => operation(async request => { await MisraAPI.retryJob(el.dataset.materialRetry); await refreshLibrary(request); notice = 'Reference reading queued again. You can leave this page.'; })));
    host.querySelectorAll('[data-revision-form]').forEach(form => {
      form.querySelector('input').addEventListener('change',() => { const file = form.querySelector('input').files[0]; if (file) revisionFiles.set(form.dataset.revisionForm,file); else revisionFiles.delete(form.dataset.revisionForm); });
      form.addEventListener('submit',event => {
        event.preventDefault(); const file = form.querySelector('input').files[0]; if (!file) return;
        operation(async request => { const data = new FormData(); data.append('file',file); await MisraAPI.uploadMaterialRevision(form.dataset.revisionForm,data);
          if (request !== generation) return; revisionFiles.delete(form.dataset.revisionForm); await refreshLibrary(request); notice = 'New draft version added. Previous grading runs keep their original sources.'; });
      });
    });
    const form = host.querySelector('[data-material-form]');
    form?.addEventListener('input',() => {
      materialForm = {title:form.querySelector('#material-title').value, text:form.querySelector('#material-text').value, file:form.querySelector('#material-file').files[0] || null};
    });
    form?.addEventListener('submit',event => {
      event.preventDefault(); const title = form.querySelector('#material-title').value.trim(); const file = form.querySelector('#material-file').files[0]; const text = form.querySelector('#material-text').value.trim();
      if (Boolean(file) === Boolean(text)) { window.showToast('Choose either a PDF or typed notes, not both.','error'); return; }
      operation(async request => {
        if (file) { const data = new FormData(); data.append('file',file); data.append('title',title); await MisraAPI.uploadMaterial(courseId,data); }
        else await MisraAPI.createMaterialText(courseId,{title,text});
        if (request !== generation) return; form.reset(); materialForm = {title:'',text:'',file:null};
        await refreshLibrary(request); notice = file ? 'Material uploaded. Reading continues in the background; review and approve it when ready.' : 'Text draft saved. Review and approve it before linking it to questions.';
      },{rerender:false}).then(() => { if (!error) render(); });
    });
  }
  async function saveScope(approve) {
    preserveBindings();
    let body;
    try { body = {mode,bindings:['disabled','inherit'].includes(mode) ? [] : readBindings()}; if (!['disabled','inherit'].includes(mode) && !body.bindings.length) throw new Error('Add at least one approved reference, use assessment defaults, or explicitly disable retrieval.'); }
    catch (failure) { window.showToast(failure.message,'error'); return; }
    if (approve && !window.confirm('Approve these sources for future grading? The current rubric determines marks; source content cannot add deductions.')) return;
    operation(async request => {
      const draft = await MisraAPI.createMaterialScope(questionId,body);
      if (request !== generation) return;
      // The draft is persisted even if the subsequent approval fails.
      scopes = [{...body,...draft},...scopes]; bindings = body.bindings; dirty = false;
      notice = 'Source draft saved — it does not affect grading yet.';
      if (approve) {
        notice = 'Draft saved. Approval requested — reload sources if confirmation is interrupted.';
        const approved = await MisraAPI.approveMaterialScope(questionId,draft.id);
        if (request !== generation) return;
        const currentExamId = document.getElementById('rubric-exam')?.value;
        window.dispatchEvent(new CustomEvent('misra:question-sources-approved', {detail:{examId:currentExamId,questionId}}));
        scopes = scopes.map(item => item.id === draft.id ? {...item,status:approved.status} : item.status === 'approved' ? {...item,status:'superseded'} : item);
        notice = 'Sources approved. Preview retrieval before grading the first paper.'; preview = null;
        scopes = await MisraAPI.materialScopes(questionId);
        effective = await MisraAPI.effectiveMaterialScope(questionId).catch(() => null);
      }
    });
  }
  async function openPage(index = review.index) {
    const request = generation; const selected = {...review,index};
    operation(async () => {
      const result = await MisraAPI.materialPages(selected.materialId,selected.versionId,selected.index,1);
      if (request !== generation) return;
      page = result.items?.[0] || null;
      if (!page) throw new Error('No extracted page is available. Wait for reading to finish or retry the failed job.');
      review.index = selected.index; review.version = result.version; pageDirty = false;
    });
  }
  function renderReview() {
    const target = host.querySelector('.material-review-host');
    if (!page || !review.version) { target.innerHTML = '<p role="status">Opening reference page…</p>'; return; }
    const version = review.version, editable = version.status === 'draft' && ['ready','needs_transcription'].includes(version.ingestion_status);
    const documentUrl = MisraAPI.materialDocumentUrl(review.materialId,review.versionId);
    target.innerHTML = `<section class="material-page-review" aria-labelledby="material-review-title"><header><div><h3 id="material-review-title">Review source text${suffix(version.version_number)}</h3><p class="section-copy">Compare text with the original, especially equations. Scans need verified transcription; a blank page is not accepted as evidence.</p></div><button class="btn btn-ghost" data-material-close type="button">Close review</button></header>
      <div class="material-page-nav"><button class="btn btn-secondary" data-material-prev type="button" ${page.page_index === 0 ? 'disabled' : ''}>Previous page</button><span>Document page ${page.page_index + 1} of ${version.page_count}</span><button class="btn btn-secondary" data-material-next type="button" ${page.page_index + 1 >= version.page_count ? 'disabled' : ''}>Next page</button></div>
      <div class="material-page-grid">${version.media_type === 'application/pdf' ? `<div><a href="${escape(documentUrl)}#page=${page.page_index + 1}" target="_blank" rel="noopener">Open original PDF at this page</a><iframe src="${escape(documentUrl)}#page=${page.page_index + 1}" title="Original reference document, page ${page.page_index + 1}"></iframe></div>` : version.media_type === 'application/vnd.openxmlformats-officedocument.presentationml.presentation' ? `<div><a href="${escape(documentUrl)}" target="_blank" rel="noopener">Download original PowerPoint</a><p class="field-hint">Slide text is extracted. Check images, diagrams and equations in the original deck; add any missing explanation before approving source pages.</p></div>` : '<p class="field-hint">Instructor-entered notes; no original PDF.</p>'}<div><div class="field"><label for="material-page-label">Printed page label <span class="field-hint">(optional)</span></label><input class="input" id="material-page-label" value="${escape(page.printed_page_label)}" maxlength="30" ${editable ? '' : 'disabled'}></div><div class="field"><label for="material-page-text">Reference text</label><textarea class="input textarea" id="material-page-text" rows="16" dir="auto" maxlength="50000" ${editable ? '' : 'readonly'}>${escape(page.text)}</textarea></div>${editable ? '<button class="btn btn-secondary" data-material-page-save type="button">Save page correction</button>' : '<p class="field-hint">Approved content is read-only. Upload a new document version to change it.</p>'}<details><summary>Exact passage identifiers</summary>${(page.chunks || []).map(c => `<p><code>${escape(c.id)}</code> · characters ${c.char_start}–${c.char_end}</p>`).join('') || '<p>No passages yet. Save a readable transcription first.</p>'}</details></div></div>
      ${editable ? `<form data-material-approval><div class="field"><label for="material-approved-pages">Pages approved for retrieval</label><input class="input" id="material-approved-pages" required placeholder="e.g. 2-4, 6"><span class="field-hint">Approve only pages you checked. You do not need to approve the whole book.</span></div><label class="material-confirm"><input type="checkbox" required> I checked these pages against the original, including equations and symbols.</label><button class="btn btn-primary" type="submit">Approve selected source pages</button></form>` : `<p>Approved document pages: ${escape(pageLabels(version.approved_page_indices))}</p>`}</section>`;
    if (page._text !== undefined) target.querySelector('#material-page-text').value = page._text;
    if (page._label !== undefined) target.querySelector('#material-page-label').value = page._label;
    target.querySelectorAll('#material-page-text,#material-page-label').forEach(el => el.addEventListener('input',() => {
      pageDirty = true; page._text = target.querySelector('#material-page-text').value; page._label = target.querySelector('#material-page-label').value;
    }));
    target.querySelector('[data-material-close]').addEventListener('click',() => { if (reviewDirty() && !window.confirm('Discard unsaved page-review and approval edits?')) return; review = page = null; pageDirty = false; render(); });
    for (const [selector,delta] of [['[data-material-prev]',-1],['[data-material-next]',1]]) target.querySelector(selector).addEventListener('click',() => { if (pageDirty && !window.confirm('Discard this unsaved transcription?')) return; openPage(page.page_index + delta); });
    target.querySelector('[data-material-page-save]')?.addEventListener('click',() => {
      const text = target.querySelector('#material-page-text').value, printed_page_label = target.querySelector('#material-page-label').value || null;
      operation(async request => {
        await MisraAPI.editMaterialPage(review.materialId,review.versionId,page.page_index,{text,printed_page_label,expected_text_sha256:page.text_sha256});
        if (request !== generation) return; pageDirty = false;
        const result = await MisraAPI.materialPages(review.materialId,review.versionId,page.page_index,1); page = result.items[0]; review.version = result.version;
        notice = 'Corrected transcription saved. It still needs approval.';
      },{rerender:false}).then(() => { if (!error) render(); });
    });
    const approval = target.querySelector('[data-material-approval]');
    if (approval) {
      approval.querySelector('#material-approved-pages').value = review._approvalPages || '';
      approval.querySelector('[type="checkbox"]').checked = Boolean(review._confirmed);
      approval.addEventListener('input',() => { review._approvalPages = approval.querySelector('#material-approved-pages').value; review._confirmed = approval.querySelector('[type="checkbox"]').checked; });
    }
    approval?.addEventListener('submit',event => {
      event.preventDefault(); if (pageDirty) { window.showToast('Save your transcription correction before approving.','error'); return; }
      let indices; try { indices = parsePages(target.querySelector('#material-approved-pages').value,version.page_count); } catch (failure) { window.showToast(failure.message,'error'); return; }
      operation(async request => {
        const approved = await MisraAPI.approveMaterial(review.materialId,review.versionId,{page_indices:indices,confirm_content_reviewed:true});
        if (request !== generation) return; review.version = approved; delete review._approvalPages; delete review._confirmed; await refreshLibrary(request);
        notice = questionId ? 'Source pages approved. Add them to this question’s references above.' : host.closest('#native-library') ? 'Source pages approved. Select them in Assessment source defaults below, or add a question-specific exception.' : 'Source pages approved. Refresh approved sources above to generate question drafts.';
        window.dispatchEvent(new CustomEvent('misra:material-approved', { detail: { courseId } }));
      });
    });
  }
  window.addEventListener('misra:assessment-sources-approved', async () => {
    if (!questionId || hasUnsaved()) return;
    const request = generation;
    const value = await MisraAPI.effectiveMaterialScope(questionId).catch(() => null);
    if (request === generation) { effective = value; if (!scopes.some(s => ['draft','approved'].includes(s.status)) && value?.origin === 'assessment') mode = 'inherit'; render(); }
  });
  window.MisraMaterials = { load, reset, canLeave, hasUnsaved, isBusy: () => busy, async saveDraft(){if(questionId && dirty && !busy)await saveScope(false);return !hasUnsaved();}, mount(element) { preserveBindings(); host = element; render(); } };
})();
