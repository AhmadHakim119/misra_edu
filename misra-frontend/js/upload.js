(function () {
  'use strict';
  const form = document.getElementById('upload-form');
  const examSelect = document.getElementById('upload-exam');
  const input = document.getElementById('paper-files');
  const dropzone = document.getElementById('dropzone');
  const summary = document.getElementById('file-summary');
  const fileList = document.getElementById('selected-file-list');
  const recent = document.getElementById('recent-upload');
  const pagesField = document.getElementById('pages-field');
  const pagesInput = document.getElementById('pages-per-student');
  const result = document.getElementById('upload-result');
  const button = document.getElementById('upload-button');
  const gate = document.getElementById('upload-setup-gate');
  const readyFields = document.getElementById('upload-ready-fields');
  const readinessStatus = document.getElementById('upload-readiness');
  const tips = document.getElementById('upload-tips');
  const layout = form.closest('.dashboard-grid');
  const acceptedExtensions = ['.pdf', '.png', '.jpg', '.jpeg', '.webp'];
  const pollIntervalMs = 2500;
  const maxPollAttempts = 240;
  let mode = 'single';
  let activePoll = 0;
  let ready = false;
  let sending = false;
  let uploaded = false;
  let selectedFiles = [];
  let readinessRequest = 0;
  const clear = document.getElementById('clear-files');
  const another = document.getElementById('upload-another');
  function syncControls() {
    const locked = sending || uploaded;
    input.disabled = !ready || locked || selectedFiles.length > 0;
    dropzone.classList.toggle('is-locked', input.disabled);
    dropzone.classList.toggle('has-files', selectedFiles.length > 0);
    if (input.disabled) dropzone.classList.remove('is-dragging');
    dropzone.setAttribute('aria-disabled', String(input.disabled));
    form.setAttribute('aria-busy', String(sending));
    clear.hidden = !selectedFiles.length;
    clear.disabled = locked;
    clear.textContent = selectedFiles.length > 1 ? 'Clear files' : 'Remove file';
    examSelect.disabled = locked;
    const canSplit = mode === 'batch' && (selectedFiles.length === 0 || (selectedFiles.length === 1 && selectedFiles[0].name.toLowerCase().endsWith('.pdf')));
    pagesField.hidden = !canSplit;
    pagesInput.disabled = locked || !canSplit;
    if (!canSplit) pagesInput.value = '';
    fileList.querySelectorAll('button').forEach(control => { control.disabled = locked; });
    document.querySelectorAll('[data-mode]').forEach(control => { control.disabled = !ready || locked || selectedFiles.length > 0; });
    button.disabled = !ready || locked;
    button.textContent = uploaded ? 'Upload received' : sending ? (mode === 'batch' ? 'Creating batch…' : 'Uploading paper…') : mode === 'batch' ? 'Upload batch' : 'Upload and start extraction';
    document.getElementById('dropzone-title').textContent = selectedFiles.length ? (selectedFiles.length === 1 ? 'File ready to upload' : 'Files ready to upload') : 'Choose or drop a PDF or image';
    document.getElementById('selection-hint').textContent = selectedFiles.length ? 'Remove or clear this selection to choose different files.' : 'PDF, PNG, JPEG, or WebP. In batch mode, select multiple files.';
  }
  function renderGate(value, examId) {
    readyFields.hidden = !value.ready;
    gate.hidden = Boolean(value.ready);
    tips.hidden = !value.ready;
    layout.classList.toggle('is-setup-blocked', !value.ready);
    if (value.ready) {
      gate.innerHTML = '';
      const count = Number(value.question_count);
      readinessStatus.textContent = Number.isFinite(count) && count > 0
        ? `${count} question${count === 1 ? '' : 's'} ready. Student papers can now be uploaded.`
        : 'Assessment ready. Student papers can now be uploaded.';
      if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) readyFields.animate([{ opacity: .92, transform: 'translateY(5px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 220, easing: 'cubic-bezier(.16,1,.3,1)' });
      return;
    }
    const blockers = (value.questions || []).filter((question) => question.errors?.length);
    const setupHref = `rubric-studio.html?exam_id=${encodeURIComponent(examId)}`;
    gate.innerHTML = `<div class="upload-gate-heading"><span class="upload-gate-symbol" aria-hidden="true">${MisraUI.icons.rubric}</span><div><h2>Finish assessment setup first</h2><p>Student papers stay separate from the blank exam and answer key. Approve the grading foundations before uploading.</p></div></div>
      ${blockers.length ? `<ul class="upload-gate-list">${blockers.map((question) => `<li><div><strong>Question ${MisraUI.escapeHTML(question.question_number)}</strong><span>${MisraUI.escapeHTML(question.errors[0])}</span></div><a href="${setupHref}&question_id=${encodeURIComponent(question.question_id)}">Fix question</a></li>`).join('')}</ul>` : '<p class="upload-gate-empty">Add questions and approve their rubrics in Rubric Studio.</p>'}
      <a class="btn btn-primary" href="${setupHref}">${blockers.length ? 'Open Rubric Studio' : 'Set up questions and rubrics'}</a>`;
    readinessStatus.textContent = value.message || `${blockers.length || 'Assessment'} setup ${blockers.length === 1 ? 'check' : 'checks'} remaining before upload.`;
  }
  async function checkReadiness() {
    const examId = examSelect.value;
    const request = ++readinessRequest;
    ready = false; readyFields.hidden = true; gate.hidden = true; tips.hidden = true; layout.classList.add('is-setup-blocked'); button.disabled = true; syncControls();
    document.getElementById('setup-link').href = `rubric-studio.html?exam_id=${encodeURIComponent(examId)}`;
    document.getElementById('upload-papers-link').href = `submissions.html${examId ? '?exam_id=' + encodeURIComponent(examId) : ''}`;
    loadRecent(examId);
    if (!examId) {
      tips.hidden = true; layout.classList.add('is-setup-blocked');
      readinessStatus.textContent = 'Create an assessment before uploading student papers.';
      gate.hidden = false;
      gate.innerHTML = '<div class="upload-gate-heading"><div><h2>No assessment selected</h2><p>Create an assessment, add its questions, and approve the rubrics first.</p></div></div><a class="btn btn-primary" href="assessments.html">Create an assessment</a>';
      return;
    }
    readinessStatus.textContent = 'Checking questions and approved rubrics…';
    try {
      const value = await MisraAPI.setupReadiness(examId);
      if (request !== readinessRequest || examSelect.value !== examId) return;
      ready = Boolean(value.ready); renderGate(value, examId); syncControls();
    } catch (_) {
      if (request !== readinessRequest) return;
      tips.hidden = true; layout.classList.add('is-setup-blocked');
      gate.hidden = false;
      gate.innerHTML = '<div class="upload-gate-heading"><div><h2>Setup check unavailable</h2><p>Upload stays closed until MISRA can verify the assessment. Check the connection and try again.</p></div></div><button class="btn btn-secondary" type="button" data-recheck-readiness>Try again</button>';
      readinessStatus.textContent = 'Could not verify rubric readiness.';
    }
  }
  function rememberJob(job, examId) {
    uploaded = true;
    recent.hidden = true;
    syncControls();
    window.dispatchEvent(new CustomEvent('misra:job-started', { detail: { jobId: job.id } }));
    history.replaceState(null, '', `?exam_id=${encodeURIComponent(examId)}&job_id=${encodeURIComponent(job.id)}`);
    form.hidden = true; another.hidden = false;
  }

  function wait(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  function submissionLink(submissionId) {
    return `submission.html?id=${encodeURIComponent(submissionId)}`;
  }

  function batchLink(job) {
    return `submissions.html?exam_id=${encodeURIComponent(examSelect.value)}${job.batch_id ? '&batch_id=' + encodeURIComponent(job.batch_id) : ''}`;
  }

  async function loadRecent(examId) {
    recent.hidden = true;
    if (!examId || uploaded || MisraUI.getParam('job_id')) return;
    try {
      const response = await MisraAPI.workspaceJobs();
      if (examSelect.value !== examId || uploaded || MisraUI.getParam('job_id')) return;
      const job = (response.items || []).find(item => item.exam_id === examId && ['ocr_submission', 'ocr_batch'].includes(item.job_type));
      if (!job) return;
      const label = { queued: 'Queued', processing: 'Processing', retrying: 'Retrying', completed: 'Finished — review results', failed: 'Needs attention' }[job.status] || 'View status';
      recent.innerHTML = `<div><strong>Your latest upload</strong><span>${job.job_type === 'ocr_batch' ? 'Batch' : 'Student paper'} · ${MisraUI.escapeHTML(label)}</span></div><a class="btn btn-secondary" href="upload.html?exam_id=${encodeURIComponent(examId)}&job_id=${encodeURIComponent(job.id)}">View upload progress</a>`;
      recent.hidden = false;
    } catch (_) { /* The shared background-activity panel remains available. */ }
  }

  function renderJobProgress(job, context) {
    const current = Number(job.progress_current || 0);
    const total = Number(job.progress_total || 0);
    const percent = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
    const statusLabel = job.status === 'retrying' ? 'Retry scheduled…' : job.status === 'processing' ? 'Extracting papers…' : 'Waiting for an OCR worker…';
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card" role="status">
      <div class="upload-status-line"><span class="upload-status-pulse" aria-hidden="true"></span><strong>${statusLabel}</strong><span class="job-progress-count">${total ? `${current} / ${total}` : 'Queued'}</span></div>
      <div class="job-progress-track" aria-label="Extraction progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span style="width:${percent}%"></span></div>
      <p class="section-copy">${MisraUI.escapeHTML(job.progress_message || 'Processing continues in the background. You may safely leave this page.')}</p>
      <p class="field-hint">You can switch pages. Reopen this job from background activity or Your latest upload.</p>
      ${context.submissionId ? `<a class="btn btn-secondary" href="${submissionLink(context.submissionId)}">Open extraction result</a>` : `<a class="btn btn-secondary" href="${context.destination}">View batch submissions</a>`}
    </div>`;
  }

  function renderExtractionComplete(report) {
    const readiness = report.readiness;
    const mapped = `${readiness.mapped_answer_count}/${readiness.expected_question_count}`;
    const needsAttention = !(readiness.bulk_grading_allowed ?? readiness.mapping_complete);
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card is-complete" role="status">
      <strong>${needsAttention ? 'Extraction ready for review' : 'Extraction complete'}</strong>
      <p class="section-copy">${mapped} answers found. ${needsAttention ? 'Next: check the answer locations MISRA could not verify. Your paper is saved; do not upload it again.' : 'Next: open your paper and start grading. You can inspect the original answers there first.'}</p>
      <a class="btn btn-primary" href="${submissionLink(report.submission.id)}">${needsAttention ? 'Check answers' : 'Continue to grading'}</a>
    </div>`;
    window.showToast(needsAttention ? 'Extraction needs mapping review.' : 'Paper extracted.', needsAttention ? 'warning' : 'success');
  }

  function renderExtractionFailure(job, context) {
    const message = job.error_message || 'OCR could not process this upload.';
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card is-error" role="alert">
      <strong>Extraction failed</strong>
      <p class="section-copy">${MisraUI.escapeHTML(message)}</p>
      <div class="job-actions"><button class="btn btn-primary" type="button" data-retry-job="${job.id}">Retry safely</button>${context.submissionId ? `<a class="btn btn-secondary" href="${submissionLink(context.submissionId)}">Inspect submission</a>` : `<a class="btn btn-secondary" href="${context.destination}">Inspect batch</a>`}</div>
    </div>`;
    window.showToast('Extraction failed. Inspect the submission for details.', 'error');
  }

  function renderBatchComplete(job, context, report) {
    const batch = report.batch || {};
    const completed = Number(batch.completed_count || 0);
    const failed = Number(batch.failed_count || 0);
    const total = Number(batch.total_count || job.progress_total || 0);
    if (failed) {
      result.innerHTML = `<div class="workspace-card card-pad upload-status-card is-error" role="alert">
        <strong>Batch finished with extraction errors</strong>
        <p class="section-copy">${completed} of ${total} papers extracted successfully; ${failed} failed. Review the failed papers before retrying them.</p>
        <div class="job-actions"><a class="btn btn-secondary" href="${context.destination}">Review batch</a><button class="btn btn-primary" type="button" data-retry-batch="${MisraUI.escapeHTML(job.batch_id)}">Retry failed papers</button></div>
      </div>`;
      window.showToast(`${failed} papers need extraction attention.`, 'warning');
      return;
    }
    const settled = total > 0 && completed === total;
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card ${settled ? 'is-complete' : ''}" role="status"><strong>${settled ? 'Batch extraction complete' : 'Batch needs a status check'}</strong><p class="section-copy">${completed} of ${total} papers recorded as extracted. ${settled ? 'Review mappings before grading.' : 'Open the batch to check the remaining papers; do not upload them again.'}</p><a class="btn btn-secondary" href="${context.destination}">View submissions</a></div>`;
    window.showToast(settled ? 'Batch extraction complete.' : 'Check the remaining batch papers.', settled ? 'success' : 'warning');
  }

  async function pollJob(jobId, context, pollId) {
    for (let attempt = 0; attempt < maxPollAttempts && pollId === activePoll; attempt += 1) {
      try {
        const job = await MisraAPI.job(jobId);
        if (pollId !== activePoll) return;
        if (job.status === 'failed') { renderExtractionFailure(job, context); return; }
        if (job.status === 'completed') {
          if (context.submissionId) {
            const report = await MisraAPI.extractionReview(context.submissionId);
            if (pollId !== activePoll) return;
            renderExtractionComplete(report);
          } else {
            const batch = await MisraAPI.batch(job.batch_id);
            if (pollId !== activePoll) return;
            renderBatchComplete(job, context, batch);
          }
          return;
        }
        renderJobProgress(job, context);
      } catch (error) {
        if (pollId !== activePoll) return;
        result.innerHTML = '<div class="upload-status-card" role="status"><strong>Connection interrupted</strong><p>Processing may still be running. Reconnecting automatically; do not upload this paper again.</p></div>';
      }
      await wait(pollIntervalMs);
    }
    if (pollId === activePoll) {
      result.innerHTML = `<div class="workspace-card card-pad upload-status-card"><strong>Live updates paused</strong><p class="section-copy">The job may still be running. Refresh this page to check its latest status; do not upload the same paper again.</p>${context.submissionId ? `<a class="btn btn-secondary" href="${submissionLink(context.submissionId)}">Open extraction result</a>` : `<a class="btn btn-secondary" href="${context.destination}">View submissions</a>`}</div>`;
    }
  }

  async function loadExams() {
    try {
      const context = await MisraUI.assessmentReady;
      if (context.error) throw context.error;
      const exams = context.exams;
      examSelect.innerHTML = exams.length ? exams.map((exam) => `<option value="${exam.id}">${MisraUI.escapeHTML(exam.course_code ? `${exam.course_code} · ${exam.title}` : exam.title)}</option>`).join('') : '<option value="">No assessments found</option>';
      const requested = MisraUI.getParam('exam_id') || context.selectedId;
      if (exams.some((exam) => exam.id === requested)) examSelect.value = requested;
      await checkReadiness();
      const jobId = MisraUI.getParam('job_id');
      if (jobId) {
        const job = await MisraAPI.job(jobId);
        if (!['ocr_submission', 'ocr_batch'].includes(job.job_type)) throw new Error('This is not a student extraction job. Open Rubric Studio for exam setup.');
        rememberJob(job, examSelect.value);
        const context = job.submission_id ? { submissionId: job.submission_id } : { destination: batchLink(job) };
        pollJob(job.id, context, ++activePoll);
      }
    } catch (error) { examSelect.innerHTML = '<option value="">Engine unavailable</option>'; result.innerHTML = MisraUI.errorState(error.message); }
  }

  function updateFiles() {
    activePoll += 1;
    const files = selectedFiles;
    const size = bytes => bytes < 1048576 ? `${Math.max(1, Math.ceil(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
    summary.textContent = files.length ? `${files.length} file${files.length === 1 ? '' : 's'} · ${files.length === 1 ? files[0].name + ' · ' : ''}${size(files.reduce((total, file) => total + file.size, 0))}` : 'No files selected';
    fileList.hidden = files.length < 2;
    fileList.innerHTML = files.length < 2 ? '' : files.map((file, index) => `<li><span><strong>${MisraUI.escapeHTML(file.name)}</strong><small>${size(file.size)}</small></span><button class="link-button" type="button" data-remove-file="${index}" aria-label="Remove ${MisraUI.escapeHTML(file.name)}">Remove</button></li>`).join('');
    result.innerHTML = '';
    syncControls();
  }

  function showError(message) {
    result.innerHTML = MisraUI.errorState(message);
    window.showToast(message, 'error');
  }

  function isAccepted(file) {
    const name = file.name.toLowerCase();
    return acceptedExtensions.some((extension) => name.endsWith(extension));
  }

  function assignFiles(files) {
    if (sending || uploaded || selectedFiles.length) return;
    const accepted = [...files].filter(isAccepted);
    if (!accepted.length) {
      input.value = '';
      showError('Choose a PDF, PNG, JPEG, or WebP file.');
      return;
    }
    const skippedUnsupported = accepted.length !== files.length;

    const selected = mode === 'single' ? accepted.slice(0, 1) : accepted;
    const transfer = new DataTransfer();
    selected.forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    selectedFiles = selected;
    updateFiles();
    if (skippedUnsupported) {
      showError('Some files were skipped because they are not PDF, PNG, JPEG, or WebP.');
    }
  }

  function setMode(nextMode, clearFiles = true) {
    if (sending || uploaded || selectedFiles.length) return;
    mode = nextMode === 'batch' ? 'batch' : 'single';
    document.querySelectorAll('[data-mode]').forEach((item) => item.setAttribute('aria-pressed', String(item.dataset.mode === mode)));
    input.multiple = mode === 'batch';
    pagesField.hidden = mode !== 'batch';
    button.textContent = mode === 'batch' ? 'Upload batch' : 'Upload and start extraction';
    if (clearFiles) { input.value = ''; updateFiles(); result.innerHTML = ''; }
  }

  document.querySelectorAll('[data-mode]').forEach((control) => control.addEventListener('click', () => {
    setMode(control.dataset.mode);
  }));
  setMode(window.MisraPreferences.get().uploadMode, false);

  input.addEventListener('change', () => assignFiles(input.files));
  dropzone.addEventListener('click', event => { if (input.disabled) event.preventDefault(); });
  clear.addEventListener('click', () => {
    if (sending || uploaded) return;
    selectedFiles = []; input.value = ''; pagesInput.value = ''; updateFiles(); input.focus();
  });
  fileList.addEventListener('click', event => {
    const remove = event.target.closest('[data-remove-file]');
    if (!remove || sending || uploaded) return;
    const index = Number(remove.dataset.removeFile);
    selectedFiles.splice(index, 1);
    const transfer = new DataTransfer();
    selectedFiles.forEach(file => transfer.items.add(file));
    input.files = transfer.files;
    updateFiles();
    const next = fileList.querySelectorAll('button');
    (next[Math.min(index, next.length - 1)] || clear).focus();
  });
  examSelect.addEventListener('change', () => {
    selectedFiles = []; input.value = ''; pagesInput.value = ''; updateFiles();
    checkReadiness();
  });
  gate.addEventListener('click', (event) => { if (event.target.closest('[data-recheck-readiness]')) checkReadiness(); });
  another.addEventListener('click', () => {
    if (sending) return;
    uploaded = false; selectedFiles = []; pagesInput.value = '';
    activePoll++; form.hidden = false; another.hidden = true; input.value = ''; updateFiles();
    history.replaceState(null, '', `?exam_id=${encodeURIComponent(examSelect.value)}`);
    checkReadiness(); input.focus();
  });
  ['dragenter', 'dragover'].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); if (!input.disabled) dropzone.classList.add('is-dragging'); }));
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('is-dragging'));
  dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    dropzone.classList.remove('is-dragging');
    if (input.disabled) return;
    assignFiles(event.dataTransfer.files);
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (sending || uploaded) return;
    if (!ready) { showError('Approve the assessment rubrics before uploading student answers.'); return; }
    const files = selectedFiles;
    if (!examSelect.value) { showError('Choose an assessment before uploading.'); return; }
    if (!files.length) { showError('Choose or drop at least one PDF, PNG, JPEG, or WebP file.'); return; }
    if (mode === 'single' && files.length !== 1) { showError('Single mode accepts one file.'); return; }
    if (mode === 'batch' && pagesInput.value && (!Number.isSafeInteger(Number(pagesInput.value)) || Number(pagesInput.value) < 1 || files.length !== 1 || !files[0].name.toLowerCase().endsWith('.pdf'))) {
      showError('Pages per student must be a whole number greater than zero, for one combined PDF only.'); pagesInput.focus(); return;
    }
    const body = new FormData(); body.append('exam_id', examSelect.value);
    if (mode === 'batch') files.forEach((file) => body.append('files', file)); else body.append('file', files[0]);
    if (mode === 'batch' && pagesInput.value) body.append('pages_per_student', pagesInput.value);
    sending = true;
    syncControls();
    button.textContent = mode === 'batch' ? 'Creating batch…' : 'Uploading paper…';
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card" role="status"><strong>${mode === 'batch' ? 'Creating batch…' : 'Uploading paper…'}</strong><p class="section-copy">${mode === 'batch' ? 'Preparing submissions for background extraction.' : 'OCR will continue in the background after the upload is accepted.'}</p></div>`;
    try {
      const response = mode === 'batch' ? await MisraAPI.uploadBatch(body) : await MisraAPI.uploadExam(body);
      rememberJob(response.job, examSelect.value);
      if (mode === 'batch') {
        const destination = batchLink(response.job);
        const pollId = ++activePoll;
        renderJobProgress(response.job, { destination });
        window.showToast('Batch queued for extraction.', 'success');
        pollJob(response.job.id, { destination }, pollId).catch((error) => showError(error.message));
      } else {
        const pollId = ++activePoll;
        const submissionId = response.submission.id;
        renderJobProgress(response.job, { submissionId });
        window.showToast('Upload received. OCR is queued.', 'success');
        pollJob(response.job.id, { submissionId }, pollId).catch((error) => showError(error.message));
      }
    } catch (error) { showError(error.message); }
    finally { sending = false; syncControls(); }
  });

  result.addEventListener('click', async (event) => {
    const retryBatch = event.target.closest('[data-retry-batch]');
    if (retryBatch) {
      retryBatch.disabled = true;
      retryBatch.textContent = 'Queueing failed papers…';
      try {
        const response = await MisraAPI.retryBatch(retryBatch.dataset.retryBatch);
        if (!response.retry_count || !response.job) {
          retryBatch.textContent = 'No failed papers to retry';
          return;
        }
        const context = { destination: batchLink(response.job) };
        const pollId = ++activePoll;
        rememberJob(response.job, examSelect.value);
        renderJobProgress(response.job, context);
        window.showToast(`${response.retry_count} failed papers queued again.`, 'success');
        pollJob(response.job.id, context, pollId).catch((error) => showError(error.message));
      } catch (error) {
        retryBatch.disabled = false;
        retryBatch.textContent = 'Retry failed papers';
        showError(error.message);
      }
      return;
    }
    const retry = event.target.closest('[data-retry-job]');
    if (!retry) return;
    retry.disabled = true;
    retry.textContent = 'Queueing retry…';
    try {
      const job = await MisraAPI.retryJob(retry.dataset.retryJob);
      const pollId = ++activePoll;
      const context = job.submission_id
        ? { submissionId: job.submission_id }
        : { destination: batchLink(job) };
      rememberJob(job, examSelect.value);
      renderJobProgress(job, context);
      pollJob(job.id, context, pollId).catch((error) => showError(error.message));
    } catch (error) { showError(error.message); }
  });

  loadExams();
})();
