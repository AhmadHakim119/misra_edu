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

  async function pollJob(jobId, context, pollId) {
    for (let attempt = 0; attempt < maxPollAttempts && pollId === activePoll; attempt += 1) {
      try {
        const job = await MisraAPI.job(jobId);
        if (job.status === 'failed') { renderExtractionFailure(job, context); return; }
        if (job.status === 'completed') {
          if (context.submissionId) {
            renderExtractionComplete(await MisraAPI.extractionReview(context.submissionId));
          } else {
            result.innerHTML = `<div class="workspace-card card-pad upload-status-card is-complete"><strong>Batch extraction complete</strong><p class="section-copy">${job.progress_total} submissions processed. Open the batch to review mappings and any paper-level errors.</p><a class="btn btn-secondary" href="${context.destination}">View submissions</a></div>`;
            window.showToast('Batch extraction complete.', 'success');
          }
          return;
        }
        renderJobProgress(job, context);
      } catch (error) {
        if (attempt === maxPollAttempts - 1) showError(error.message);
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
    } catch (error) { examSelect.innerHTML = '<option value="">Engine unavailable</option>'; result.innerHTML = MisraUI.errorState(error.message); }
  }

  function updateFiles() {
    activePoll += 1;
    const files = [...input.files];
    summary.textContent = files.length ? `${files.length} file${files.length === 1 ? '' : 's'} · ${files.map((file) => file.name).join(', ')}` : 'No files selected';
    result.innerHTML = '';
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
    const accepted = [...files].filter(isAccepted);
    if (!accepted.length) {
      showError('Choose a PDF, PNG, JPEG, or WebP file.');
      return;
    }
    const skippedUnsupported = accepted.length !== files.length;

    const selected = mode === 'single' ? accepted.slice(0, 1) : accepted;
    const transfer = new DataTransfer();
    selected.forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    updateFiles();
    if (skippedUnsupported) {
      showError('Some files were skipped because they are not PDF, PNG, JPEG, or WebP.');
    }
  }

  function setMode(nextMode, clearFiles = true) {
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

  input.addEventListener('change', updateFiles);
  ['dragenter', 'dragover'].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add('is-dragging'); }));
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('is-dragging'));
  dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    dropzone.classList.remove('is-dragging');
    assignFiles(event.dataTransfer.files);
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const files = [...input.files];
    if (!examSelect.value) { showError('Choose an assessment before uploading.'); return; }
    if (!files.length) { showError('Choose or drop at least one PDF, PNG, JPEG, or WebP file.'); return; }
    if (mode === 'single' && files.length !== 1) { showError('Single mode accepts one file.'); return; }
    const body = new FormData(); body.append('exam_id', examSelect.value);
    if (mode === 'batch') files.forEach((file) => body.append('files', file)); else body.append('file', files[0]);
    if (mode === 'batch' && pagesInput.value) body.append('pages_per_student', pagesInput.value);
    button.disabled = true; button.textContent = mode === 'batch' ? 'Creating batch…' : 'Uploading paper…';
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card" role="status"><strong>${mode === 'batch' ? 'Creating batch…' : 'Uploading paper…'}</strong><p class="section-copy">${mode === 'batch' ? 'Preparing submissions for background extraction.' : 'OCR will continue in the background after the upload is accepted.'}</p></div>`;
    try {
      const response = mode === 'batch' ? await MisraAPI.uploadBatch(body) : await MisraAPI.uploadExam(body);
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
    finally { button.disabled = false; button.textContent = mode === 'batch' ? 'Upload batch' : 'Upload and start extraction'; }
  });

  result.addEventListener('click', async (event) => {
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
