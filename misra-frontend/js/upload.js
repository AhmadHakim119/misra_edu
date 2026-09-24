(function () {
  'use strict';
  const form = document.getElementById('upload-form');
  const examSelect = document.getElementById('upload-exam');
  const input = document.getElementById('paper-files');
  const dropzone = document.getElementById('dropzone');
  const summary = document.getElementById('file-summary');
  const pagesField = document.getElementById('pages-field');
  const pagesInput = document.getElementById('pages-per-student');
  const result = document.getElementById('upload-result');
  const button = document.getElementById('upload-button');
  const acceptedExtensions = ['.pdf', '.png', '.jpg', '.jpeg', '.webp'];
  const pollIntervalMs = 2500;
  const maxPollAttempts = 240;
  let mode = 'single';
  let activePoll = 0;
  let ready = false;
  let sending = false;
  let uploaded = false;
  let selectedFiles = [];
  const clear = document.getElementById('clear-files');
  const another = document.getElementById('upload-another');
  function syncControls() {
    const locked = sending || uploaded;
    input.disabled = locked || selectedFiles.length > 0;
    dropzone.classList.toggle('is-locked', input.disabled);
    if (input.disabled) dropzone.classList.remove('is-dragging');
    dropzone.setAttribute('aria-disabled', String(input.disabled));
    form.setAttribute('aria-busy', String(sending));
    clear.hidden = !selectedFiles.length;
    clear.disabled = locked;
    clear.textContent = selectedFiles.length > 1 ? 'Clear files' : 'Remove file';
    examSelect.disabled = locked;
    pagesInput.disabled = locked;
    document.querySelectorAll('[data-mode]').forEach(control => { control.disabled = locked || selectedFiles.length > 0; });
    button.disabled = !ready || locked;
    button.textContent = uploaded ? 'Upload received' : sending ? (mode === 'batch' ? 'Creating batch…' : 'Uploading paper…') : mode === 'batch' ? 'Upload batch' : 'Upload and start extraction';
    document.getElementById('dropzone-title').textContent = selectedFiles.length ? (selectedFiles.length === 1 ? 'File ready to upload' : 'Files ready to upload') : 'Choose or drop a PDF or image';
    document.getElementById('selection-hint').textContent = selectedFiles.length ? 'Remove or clear this selection to choose different files.' : 'PDF, PNG, JPEG, or WebP. In batch mode, select multiple files.';
  }
  async function checkReadiness() {
    const examId = examSelect.value;
    ready = false; button.disabled = true;
    document.getElementById('setup-link').href = `rubric-studio.html?exam_id=${encodeURIComponent(examId)}`;
    if (!examId) return;
    try {
      const value = await MisraAPI.setupReadiness(examId);
      if (examSelect.value !== examId) return;
      ready = value.ready; syncControls();
      document.getElementById('upload-readiness').textContent = value.message;
    } catch (_) { document.getElementById('upload-readiness').textContent = 'Could not check rubric readiness. Reload to reconnect before uploading.'; }
  }
  function rememberJob(job, examId) {
    uploaded = true;
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

  function renderJobProgress(job, context) {
    const current = Number(job.progress_current || 0);
    const total = Number(job.progress_total || 0);
    const percent = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
    const statusLabel = job.status === 'retrying' ? 'Retry scheduled…' : job.status === 'processing' ? 'Extracting papers…' : 'Waiting for an OCR worker…';
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card" role="status">
      <div class="upload-status-line"><span class="upload-status-pulse" aria-hidden="true"></span><strong>${statusLabel}</strong><span class="job-progress-count">${total ? `${current} / ${total}` : 'Queued'}</span></div>
      <div class="job-progress-track" aria-label="Extraction progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span style="width:${percent}%"></span></div>
      <p class="section-copy">${MisraUI.escapeHTML(job.progress_message || 'Processing continues in the background. You may safely leave this page.')}</p>
      ${context.submissionId ? `<a class="btn btn-secondary" href="${submissionLink(context.submissionId)}">Open extraction result</a>` : `<a class="btn btn-secondary" href="${context.destination}">View batch submissions</a>`}
    </div>`;
  }

  function renderExtractionComplete(report) {
    const readiness = report.readiness;
    const mapped = `${readiness.mapped_answer_count}/${readiness.expected_question_count}`;
    const needsAttention = !readiness.mapping_complete;
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card is-complete" role="status">
      <strong>${needsAttention ? 'Extraction ready for review' : 'Extraction complete'}</strong>
      <p class="section-copy">${mapped} expected answers mapped. Review the source pages before grading.</p>
      <a class="btn btn-secondary" href="${submissionLink(report.submission.id)}">Review extraction</a>
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
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card is-complete"><strong>Batch extraction complete</strong><p class="section-copy">${completed || total} submissions processed. Open the batch to review mappings before grading.</p><a class="btn btn-secondary" href="${context.destination}">View submissions</a></div>`;
    window.showToast('Batch extraction complete.', 'success');
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
      result.innerHTML = `<div class="workspace-card card-pad upload-status-card"><strong>Extraction is still running</strong><p class="section-copy">You can safely leave this page and return later.</p>${context.submissionId ? `<a class="btn btn-secondary" href="${submissionLink(context.submissionId)}">Open extraction result</a>` : `<a class="btn btn-secondary" href="${context.destination}">View submissions</a>`}</div>`;
    }
  }

  async function loadExams() {
    try {
      const exams = await MisraAPI.exams();
      examSelect.innerHTML = exams.length ? exams.map((exam) => `<option value="${exam.id}">${MisraUI.escapeHTML(exam.course_code ? `${exam.course_code} · ${exam.title}` : exam.title)}</option>`).join('') : '<option value="">No assessments found</option>';
      const requested = MisraUI.getParam('exam_id');
      if (exams.some((exam) => exam.id === requested)) examSelect.value = requested;
      await checkReadiness();
      const jobId = MisraUI.getParam('job_id');
      if (jobId) {
        const job = await MisraAPI.job(jobId);
        if (!['ocr_submission', 'ocr_batch'].includes(job.job_type)) throw new Error('This is not a student extraction job. Open Rubric Studio for exam setup.');
        rememberJob(job, examSelect.value);
        const context = job.submission_id ? { submissionId: job.submission_id } : { destination: `submissions.html?exam_id=${encodeURIComponent(examSelect.value)}` };
        pollJob(job.id, context, ++activePoll);
      }
    } catch (error) { examSelect.innerHTML = '<option value="">Engine unavailable</option>'; result.innerHTML = MisraUI.errorState(error.message); }
  }

  function updateFiles() {
    activePoll += 1;
    const files = selectedFiles;
    summary.textContent = files.length ? `${files.length} file${files.length === 1 ? '' : 's'} · ${files.map((file) => file.name).join(', ')}` : 'No files selected';
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
    selectedFiles = []; input.value = ''; updateFiles(); input.focus();
  });
  examSelect.addEventListener('change', checkReadiness);
  another.addEventListener('click', () => {
    if (sending) return;
    uploaded = false; selectedFiles = [];
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
        const destination = `submissions.html?exam_id=${encodeURIComponent(examSelect.value)}`;
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
        const context = { destination: `submissions.html?exam_id=${encodeURIComponent(examSelect.value)}` };
        const pollId = ++activePoll;
        window.dispatchEvent(new CustomEvent('misra:job-started', { detail: { jobId: response.job.id } }));
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
        : { destination: `submissions.html?exam_id=${encodeURIComponent(examSelect.value)}` };
      renderJobProgress(job, context);
      pollJob(job.id, context, pollId).catch((error) => showError(error.message));
    } catch (error) { showError(error.message); }
  });

  loadExams();
})();
