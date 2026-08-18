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
  const acceptedExtensions = ['.pdf', '.png', '.jpg', '.jpeg'];
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

  function renderExtractionProgress(submissionId, status) {
    const statusLabel = status === 'extracting' ? 'Extracting pages…' : 'Waiting to start OCR…';
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card" role="status">
      <div class="upload-status-line"><span class="upload-status-pulse" aria-hidden="true"></span><strong>${statusLabel}</strong></div>
      <p class="section-copy">Submission ${MisraUI.escapeHTML(submissionId)}. Processing continues in the background, so you may leave this page.</p>
      <a class="btn btn-secondary" href="${submissionLink(submissionId)}">Open extraction result</a>
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

  function renderExtractionFailure(report) {
    const message = report.submission.error_message || 'OCR could not process this paper.';
    result.innerHTML = `<div class="workspace-card card-pad upload-status-card is-error" role="alert">
      <strong>Extraction failed</strong>
      <p class="section-copy">${MisraUI.escapeHTML(message)}</p>
      <a class="btn btn-secondary" href="${submissionLink(report.submission.id)}">Inspect submission</a>
    </div>`;
    window.showToast('Extraction failed. Inspect the submission for details.', 'error');
  }

  async function pollExtraction(submissionId, pollId) {
    for (let attempt = 0; attempt < maxPollAttempts && pollId === activePoll; attempt += 1) {
      try {
        const report = await MisraAPI.extractionReview(submissionId);
        const status = report.submission.status;
        if (status === 'error') { renderExtractionFailure(report); return; }
        if (status === 'extracted' || status === 'graded') { renderExtractionComplete(report); return; }
        renderExtractionProgress(submissionId, status);
      } catch (error) {
        if (attempt === maxPollAttempts - 1) showError(error.message);
      }
      await wait(pollIntervalMs);
    }
    if (pollId === activePoll) {
      result.innerHTML = `<div class="workspace-card card-pad upload-status-card"><strong>Extraction is still running</strong><p class="section-copy">You can safely leave this page and return to the extraction result later.</p><a class="btn btn-secondary" href="${submissionLink(submissionId)}">Open extraction result</a></div>`;
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
      showError('Choose a PDF, PNG, or JPEG file.');
      return;
    }
    const skippedUnsupported = accepted.length !== files.length;

    const selected = mode === 'single' ? accepted.slice(0, 1) : accepted;
    const transfer = new DataTransfer();
    selected.forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    updateFiles();
    if (skippedUnsupported) {
      showError('Some files were skipped because they are not PDF, PNG, or JPEG.');
    }
  }

  document.querySelectorAll('[data-mode]').forEach((control) => control.addEventListener('click', () => {
    mode = control.dataset.mode;
    document.querySelectorAll('[data-mode]').forEach((item) => item.setAttribute('aria-pressed', String(item === control)));
    input.multiple = mode === 'batch';
    pagesField.hidden = mode !== 'batch';
    button.textContent = mode === 'batch' ? 'Upload batch' : 'Upload and start extraction';
    input.value = ''; updateFiles(); result.innerHTML = '';
  }));

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
    if (!files.length) { showError('Choose or drop at least one PDF, PNG, or JPEG file.'); return; }
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
        result.innerHTML = `<div class="workspace-card card-pad upload-status-card is-complete"><strong>Batch queued</strong><p class="section-copy">${response.total_submissions} submissions · Batch ${MisraUI.escapeHTML(response.batch_id)}</p><a class="btn btn-secondary" href="${destination}">View submissions</a></div>`;
        window.showToast('Batch queued for extraction.', 'success');
      } else {
        const pollId = ++activePoll;
        renderExtractionProgress(response.id, response.status);
        window.showToast('Upload received. OCR is running in the background.', 'success');
        pollExtraction(response.id, pollId).catch((error) => showError(error.message));
      }
    } catch (error) { showError(error.message); }
    finally { button.disabled = false; button.textContent = mode === 'batch' ? 'Upload batch' : 'Upload and start extraction'; }
  });

  loadExams();
})();
