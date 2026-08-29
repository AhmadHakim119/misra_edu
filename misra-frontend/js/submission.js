(function () {
  'use strict';
  const submissionId = MisraUI.getParam('id');
  const title = document.getElementById('submission-title');
  const meta = document.getElementById('submission-meta');
  const errorRegion = document.getElementById('submission-error');
  const readinessPanel = document.getElementById('readiness-panel');
  const unmatchedPanel = document.getElementById('unmatched-panel');
  const metadataForm = document.getElementById('metadata-form');
  const metadataEditor = document.getElementById('metadata-editor');
  const identityGuidance = document.getElementById('identity-guidance');
  const studentName = document.getElementById('student-name');
  const studentNumber = document.getElementById('student-number');
  const instructorName = document.getElementById('instructor-name');
  const mappingCopy = document.getElementById('mapping-copy');
  const mappingList = document.getElementById('question-mappings');
  const pageImage = document.getElementById('page-image');
  const pageLabel = document.getElementById('page-label');
  const previousPage = document.getElementById('previous-page');
  const nextPage = document.getElementById('next-page');
  const reextractPage = document.getElementById('reextract-page');
  const recoveryToolbar = document.getElementById('page-recovery-toolbar');
  const recoveryPanel = document.getElementById('page-recovery-panel');
  const gradeAll = document.getElementById('grade-all');
  const gradeMode = document.getElementById('grade-mode');
  gradeMode.value = window.MisraPreferences.get().gradingMode;
  let report = null;
  const requestedPage = Number.parseInt(MisraUI.getParam('page'), 10);
  let pageIndex = Number.isInteger(requestedPage) && requestedPage >= 0 ? requestedPage : 0;
  let filter = 'all';
  let recoveryPreview = null;
  let activeOcrPoll = 0;

  function wait(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  function renderOcrJob(job) {
    if (job.status === 'failed') {
      errorRegion.innerHTML = `<div class="workspace-card card-pad upload-status-card is-error" role="alert">
        <strong>Extraction failed</strong>
        <p class="section-copy">${MisraUI.escapeHTML(job.error_message || 'OCR could not process this paper.')}</p>
        <div class="job-actions"><button class="btn btn-primary" type="button" data-retry-ocr="${job.id}">Retry safely</button><a class="btn btn-secondary" href="upload.html">Upload another paper</a></div>
      </div>`;
      return;
    }

    const current = Number(job.progress_current || 0);
    const total = Number(job.progress_total || 0);
    const percent = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
    const label = job.status === 'retrying' ? 'Extraction retry scheduled…' : job.status === 'processing' ? 'Extracting this paper…' : 'Waiting for an OCR worker…';
    errorRegion.innerHTML = `<div class="workspace-card card-pad upload-status-card" role="status">
      <div class="upload-status-line"><span class="upload-status-pulse" aria-hidden="true"></span><strong>${label}</strong><span class="job-progress-count">${total ? `${current} / ${total}` : 'Queued'}</span></div>
      <div class="job-progress-track" aria-label="Extraction progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span style="width:${percent}%"></span></div>
      <p class="section-copy">${MisraUI.escapeHTML(job.progress_message || 'The worker is processing this paper in the background.')}</p>
    </div>`;
  }

  async function watchOcrJob(jobId) {
    const pollId = ++activeOcrPoll;
    for (let attempt = 0; attempt < 240 && pollId === activeOcrPoll; attempt += 1) {
      const job = await MisraAPI.job(jobId);
      if (job.status === 'completed') {
        activeOcrPoll += 1;
        window.showToast('Extraction complete. Review the mapped answers.', 'success');
        await load();
        return;
      }
      renderOcrJob(job);
      if (job.status === 'failed') return;
      await wait(2500);
    }
  }

  function clearRecoveryPreview() {
    recoveryPreview = null;
    recoveryPanel.hidden = true;
    recoveryPanel.innerHTML = '';
  }

  function setPage(nextIndex) {
    if (!report) return;
    if (!Number.isInteger(nextIndex)) {
      window.showToast('This answer has no tracked source page.', 'error');
      return;
    }
    const resolvedIndex = Math.max(0, Math.min(report.submission.page_count - 1, nextIndex));
    if (resolvedIndex !== pageIndex) clearRecoveryPreview();
    pageIndex = resolvedIndex;
    pageLabel.textContent = `Page ${pageIndex + 1} of ${report.submission.page_count}`;
    pageImage.src = MisraAPI.submissionPageUrl(report.submission.id, pageIndex);
    pageImage.alt = `Original submitted paper, page ${pageIndex + 1}`;
    previousPage.disabled = pageIndex === 0;
    nextPage.disabled = pageIndex === report.submission.page_count - 1;
    reextractPage.textContent = `Re-extract page ${pageIndex + 1}`;
    const hasMissingAnswers = Boolean(report.readiness.missing_question_numbers.length);
    recoveryToolbar.hidden = !hasMissingAnswers;
    reextractPage.disabled = !hasMissingAnswers;
  }

  function renderReadiness() {
    const ready = report.readiness.bulk_grading_allowed;
    const missing = report.readiness.missing_question_numbers;
    readinessPanel.innerHTML = `<div class="readiness-band ${ready ? 'is-ready' : 'needs-action'}">
      <div class="readiness-state"><span class="readiness-mark">${ready ? '✓' : '!'}</span><div><strong>${ready ? 'Mapping verified for grading' : 'Extraction needs attention'}</strong><p>${ready ? 'Every expected answer has traceable OCR source segments.' : report.readiness.blocking_reasons.map(MisraUI.escapeHTML).join(' ')}</p></div></div>
      <dl class="readiness-metrics"><div><dt>Mapped</dt><dd>${report.readiness.mapped_answer_count}/${report.readiness.expected_question_count}</dd></div><div><dt>Suspicious</dt><dd>${report.readiness.suspicious_mapping_count}</dd></div><div><dt>Unmatched</dt><dd>${report.readiness.unmatched_segment_count}</dd></div></dl>
      ${missing.length ? `<div class="missing-strip"><strong>Missing:</strong> ${missing.map((number) => `<span>${MisraUI.escapeHTML(number)}</span>`).join('')}</div>` : ''}
    </div>`;
    gradeAll.disabled = !ready;
    gradeAll.title = ready ? '' : 'Resolve all missing and suspicious mappings first.';
  }

  function renderIdentity() {
    const identity = MisraUI.identityState(report.submission);
    title.textContent = identity.displayName;
    meta.textContent = `${identity.displayNumber} · ${report.submission.page_count} pages · uploaded ${MisraUI.formatDate(report.submission.uploaded_at)}`;
    studentName.value = report.submission.extracted_student_name || '';
    studentNumber.value = report.submission.extracted_student_number || '';
    instructorName.value = report.submission.instructor_name || '';
    identityGuidance.innerHTML = `<div class="identity-guidance-state ${identity.needsAttention ? 'needs-action' : 'is-ready'}">
      <span class="readiness-mark">${identity.needsAttention ? '!' : '✓'}</span>
      <div><strong>${MisraUI.escapeHTML(identity.label)}</strong><p>${MisraUI.escapeHTML(identity.message)}</p></div>
      <button class="btn btn-secondary" type="button" data-open-identity>${identity.needsAttention ? 'Complete identity' : 'Review details'}</button>
    </div>`;
    if (identity.needsAttention) metadataEditor.open = true;
  }

  function renderSegmentOrganizer() {
    const groups = Array.from({ length: report.submission.page_count }, (_, index) => ({ pageIndex: index, items: [] }));
    report.questions.forEach((row) => row.sources.forEach((source) => {
      groups[source.page_index]?.items.push({
        kind: 'source',
        id: source.id,
        segmentIndex: source.segment_index,
        text: source.extracted_text,
        questionNumber: row.question.question_number,
        detectedLabel: source.ocr_segment?.question_number || null,
      });
    }));
    (report.unmatched_segments || []).forEach((segment, index) => {
      if (!Number.isInteger(segment.page_index) || !groups[segment.page_index]) return;
      groups[segment.page_index].items.push({
        kind: 'unmatched',
        index,
        segmentIndex: Number(segment.segment_index ?? 10000 + index),
        text: segment.text || '',
        questionNumber: null,
        detectedLabel: segment.question_number || null,
      });
    });

    const visibleGroups = groups.filter((group) => group.items.length);
    if (!visibleGroups.length) {
      unmatchedPanel.innerHTML = '';
      return;
    }
    visibleGroups.forEach((group) => group.items.sort((left, right) => left.segmentIndex - right.segmentIndex));
    const questionOptions = report.questions.map((row) => `<option value="${row.question.id}">Question ${MisraUI.escapeHTML(row.question.question_number)} — ${MisraUI.escapeHTML(row.question.question_text || 'Untitled question')}</option>`).join('');

    unmatchedPanel.innerHTML = `<section class="workspace-card segment-organizer" aria-labelledby="segment-organizer-title">
      <div class="segment-organizer-head"><div><h2 class="section-title" id="segment-organizer-title">Organize OCR by page</h2><p class="section-copy">Select several fragments, then move them together. Use “Mark as noise” only for headers, footers, and OCR mistakes.</p></div>${report.readiness.unmatched_segment_count ? MisraUI.badge(`${report.readiness.unmatched_segment_count} unassigned`, 'warning') : MisraUI.badge('All assigned', 'success')}</div>
      <div class="segment-bulk-toolbar">
        <strong><span data-selection-count>0</span> selected</strong>
        <select class="input select" data-bulk-target aria-label="Question for selected OCR fragments"><option value="">Move selected to…</option>${questionOptions}</select>
        <button class="btn btn-primary" type="button" data-bulk-assign disabled>Move selected</button>
        <button class="btn btn-ghost source-noise" type="button" data-bulk-ignore disabled>Mark as noise</button>
      </div>
      <div class="segment-page-groups">${visibleGroups.map((group) => {
        const unmatchedCount = group.items.filter((item) => item.kind === 'unmatched').length;
        const shouldOpen = unmatchedCount > 0 || group.pageIndex === pageIndex;
        return `<details class="segment-page-group" data-segment-page-group="${group.pageIndex}" ${shouldOpen ? 'open' : ''}>
          <summary><span><strong>Page ${group.pageIndex + 1}</strong><small>${group.items.length} fragment${group.items.length === 1 ? '' : 's'}${unmatchedCount ? ` · ${unmatchedCount} unassigned` : ''}</small></span><span class="disclosure" aria-hidden="true">⌄</span></summary>
          <div class="segment-page-actions"><button class="btn btn-ghost" type="button" data-view-segment-page="${group.pageIndex}">View paper page</button><button class="btn btn-secondary" type="button" data-select-page="${group.pageIndex}">Select page</button></div>
          <div class="segment-choice-list">${group.items.map((item) => `<label class="segment-choice ${item.kind === 'unmatched' ? 'is-unmatched' : ''}">
            <input type="checkbox" ${item.kind === 'source' ? `data-source-id="${item.id}"` : `data-unmatched-index="${item.index}"`}>
            <span class="segment-choice-copy"><strong>${item.kind === 'source' ? `Question ${MisraUI.escapeHTML(item.questionNumber)}` : 'Unassigned'}${item.detectedLabel ? `<small>OCR label ${MisraUI.escapeHTML(item.detectedLabel)}</small>` : ''}</strong><span>${MisraUI.escapeHTML(item.text)}</span></span>
            ${MisraUI.badge(item.kind === 'source' ? `Q${item.questionNumber}` : 'Unassigned', item.kind === 'source' ? 'draft' : 'warning')}
          </label>`).join('')}</div>
        </details>`;
      }).join('')}</div>
    </section>`;
  }

  function sourceMarkup(source, row) {
    return `<div class="source-segment" data-source="${source.id}">
      <button class="source-page-link" type="button" data-source-page="${source.page_index}">Page ${source.page_number} · ${source.resolved_from_unmatched ? 'manually assigned' : `OCR segment ${source.segment_index + 1}`}</button>
      <p>${MisraUI.escapeHTML(source.extracted_text)}</p>
    </div>`;
  }

  function renderMappings() {
    const rows = report.questions.filter((row) => {
      if (filter === 'missing') return !row.answer;
      if (filter === 'issues') return !row.answer || row.mapping_flags.length;
      return true;
    });
    mappingCopy.textContent = `${report.readiness.mapped_answer_count} of ${report.readiness.expected_question_count} expected answers mapped`;
    if (!rows.length) {
      mappingList.innerHTML = MisraUI.emptyState('No questions in this view', 'Choose another filter to see the full mapping.');
      return;
    }
    mappingList.innerHTML = `<div class="extraction-rows">${rows.map((row) => {
      const state = !row.answer ? 'missing' : row.mapping_flags.length ? 'warning' : 'mapped';
      const stateLabel = state === 'mapped' ? 'Mapped' : state === 'missing' ? 'Missing' : 'Verify';
      const pages = row.sources.length ? [...new Set(row.sources.map((source) => source.page_number))].join(', ') : '—';
      const sourcePageAttribute = row.sources.length ? ` data-source-page="${row.sources[0].page_index}"` : '';
      return `<details class="extraction-row is-${state}" ${state !== 'mapped' ? 'open' : ''}>
        <summary${sourcePageAttribute}><span class="mapping-number">${MisraUI.escapeHTML(row.question.question_number)}</span><span class="mapping-question"><strong>${MisraUI.escapeHTML(row.question.question_text || `Question ${row.question.question_number}`)}</strong><small>${row.question.max_score} points · source page${pages.includes(',') ? 's' : ''} ${pages}</small></span>${MisraUI.badge(stateLabel, state === 'mapped' ? 'success' : state === 'missing' ? 'danger' : 'warning')}<span class="disclosure" aria-hidden="true">⌄</span></summary>
        <div class="mapping-body">
          ${row.mapping_flags.map((flag) => `<div class="mapping-warning"><strong>Check mapping</strong><span>${MisraUI.escapeHTML(flag.message)}</span></div>`).join('')}
          ${row.answer ? `<div class="ocr-answer"><div class="ocr-answer-head"><span>Combined OCR text</span>${row.answer.ocr_legibility ? MisraUI.badge(row.answer.ocr_legibility, row.answer.ocr_legibility === 'clear' ? 'draft' : 'warning') : ''}</div><p>${MisraUI.escapeHTML(row.answer.raw_ocr_text || '')}</p></div><div class="source-segments"><h3>Tracked source segments</h3>${row.sources.map((source) => sourceMarkup(source, row)).join('') || '<p class="section-copy">No source segments were recorded.</p>'}</div>` : `<div class="missing-answer"><strong>No OCR answer was mapped here.</strong><p>Open the page containing this answer and use Re-extract page, or move an existing source segment here.</p></div>`}
        </div>
      </details>`;
    }).join('')}</div>`;
  }

  async function load() {
    if (!submissionId) {
      errorRegion.innerHTML = MisraUI.errorState('No submission ID was provided. Open a submission from Extraction results.');
      return;
    }
    try {
      const [nextReport, jobs] = await Promise.all([
        MisraAPI.extractionReview(submissionId),
        MisraAPI.submissionJobs(submissionId, 'ocr_submission'),
      ]);
      report = nextReport;
      renderIdentity();
      renderReadiness();
      renderSegmentOrganizer();
      renderMappings();
      setPage(Math.min(pageIndex, report.submission.page_count - 1));
      const latestJob = jobs[0];
      if (latestJob && ['queued', 'processing', 'retrying', 'failed'].includes(latestJob.status)) {
        renderOcrJob(latestJob);
        if (latestJob.status !== 'failed') watchOcrJob(latestJob.id);
      } else {
        errorRegion.innerHTML = '';
      }
    } catch (error) {
      errorRegion.innerHTML = MisraUI.errorState(error.message);
      readinessPanel.innerHTML = '';
      mappingList.innerHTML = '';
    }
  }

  previousPage.addEventListener('click', () => setPage(pageIndex - 1));
  nextPage.addEventListener('click', () => setPage(pageIndex + 1));
  errorRegion.addEventListener('click', async (event) => {
    const retry = event.target.closest('[data-retry-ocr]');
    if (!retry) return;
    retry.disabled = true;
    retry.textContent = 'Scheduling retry…';
    try {
      const job = await MisraAPI.retryJob(retry.dataset.retryOcr);
      renderOcrJob(job);
      watchOcrJob(job.id);
    } catch (error) {
      window.showToast(error.message, 'error');
      retry.disabled = false;
      retry.textContent = 'Retry safely';
    }
  });
  metadataForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = metadataForm.querySelector('[type="submit"]');
    button.disabled = true; button.textContent = 'Saving…';
    try {
      report = await MisraAPI.updateSubmissionMetadata(submissionId, {
        student_name: studentName.value.trim() || null,
        student_number: studentNumber.value.trim() || null,
        instructor_name: instructorName.value.trim() || null,
      });
      renderIdentity();
      const identity = MisraUI.identityState(report.submission);
      window.showToast(identity.complete ? 'Student identity saved and linked to the roster.' : 'Details saved. Student identity is still incomplete.', identity.complete ? 'success' : 'warning');
    } catch (error) {
      window.showToast(error.message, 'error');
    } finally {
      button.disabled = false; button.textContent = 'Save paper details';
    }
  });
  identityGuidance.addEventListener('click', (event) => {
    if (!event.target.closest('[data-open-identity]')) return;
    metadataEditor.open = true;
    const identity = MisraUI.identityState(report.submission);
    window.setTimeout(() => (identity.hasName ? studentNumber : studentName).focus(), 0);
  });
  function selectedSegments() {
    return [...unmatchedPanel.querySelectorAll('.segment-choice input:checked')];
  }

  function updateSegmentActions() {
    const selected = selectedSegments();
    const target = unmatchedPanel.querySelector('[data-bulk-target]');
    const assign = unmatchedPanel.querySelector('[data-bulk-assign]');
    const ignore = unmatchedPanel.querySelector('[data-bulk-ignore]');
    const count = unmatchedPanel.querySelector('[data-selection-count]');
    if (!target || !assign || !ignore || !count) return;
    count.textContent = String(selected.length);
    assign.disabled = !selected.length || !target.value;
    ignore.disabled = !selected.length || selected.some((input) => !input.hasAttribute('data-unmatched-index'));
  }

  unmatchedPanel.addEventListener('change', (event) => {
    if (event.target.matches('.segment-choice input, [data-bulk-target]')) updateSegmentActions();
  });
  unmatchedPanel.addEventListener('click', async (event) => {
    const viewPage = event.target.closest('[data-view-segment-page]');
    if (viewPage) {
      setPage(Number(viewPage.dataset.viewSegmentPage));
      document.getElementById('source-viewer').scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }

    const selectPage = event.target.closest('[data-select-page]');
    if (selectPage) {
      const group = selectPage.closest('[data-segment-page-group]');
      const checkboxes = [...group.querySelectorAll('.segment-choice input')];
      const shouldSelect = checkboxes.some((checkbox) => !checkbox.checked);
      checkboxes.forEach((checkbox) => { checkbox.checked = shouldSelect; });
      selectPage.textContent = shouldSelect ? 'Clear page' : 'Select page';
      updateSegmentActions();
      return;
    }

    const assign = event.target.closest('[data-bulk-assign]');
    const ignore = event.target.closest('[data-bulk-ignore]');
    if (!assign && !ignore) return;
    const selected = selectedSegments();
    if (!selected.length) return;
    const target = unmatchedPanel.querySelector('[data-bulk-target]');
    const payload = {
      action: ignore ? 'ignore' : 'assign',
      question_id: ignore ? null : target.value,
      source_ids: selected.map((input) => input.dataset.sourceId).filter(Boolean),
      unmatched_indices: selected.map((input) => input.dataset.unmatchedIndex).filter((value) => value !== undefined).map(Number),
    };
    if (!ignore && !payload.question_id) {
      window.showToast('Choose the destination question first.', 'error');
      return;
    }
    assign && (assign.disabled = true);
    ignore && (ignore.disabled = true);
    try {
      report = await MisraAPI.bulkResolveSegments(submissionId, payload);
      renderReadiness();
      renderSegmentOrganizer();
      renderMappings();
      setPage(pageIndex);
      window.showToast(ignore ? 'Selected OCR noise removed.' : `${selected.length} fragment${selected.length === 1 ? '' : 's'} moved and saved.`, 'success');
    } catch (error) {
      window.showToast(error.message, 'error');
      updateSegmentActions();
    }
  });
  reextractPage.addEventListener('click', async () => {
    const targets = report?.readiness.missing_question_numbers || [];
    if (!targets.length) { window.showToast('There are no missing answers to recover.', 'success'); return; }
    reextractPage.disabled = true;
    reextractPage.textContent = 'Scanning page…';
    recoveryPanel.hidden = false;
    recoveryPanel.innerHTML = `<div class="recovery-loading" role="status"><span class="api-status-dot"></span><div><strong>Scanning page ${pageIndex + 1}</strong><p>Looking for ${targets.map(MisraUI.escapeHTML).join(', ')}. This uses one OCR request.</p></div></div>`;
    try {
      recoveryPreview = await MisraAPI.previewPageRecovery(submissionId, pageIndex, targets);
      if (!recoveryPreview.segments.length) {
        recoveryPanel.innerHTML = `<div class="recovery-empty"><strong>No missing answers were found on page ${pageIndex + 1}.</strong><p>Move to the page where the answers are visible and try again.</p><button class="btn btn-secondary" type="button" data-dismiss-recovery>Close</button></div>`;
        return;
      }
      recoveryPanel.innerHTML = `<div class="recovery-preview"><div class="recovery-preview-head"><div><strong>Review ${recoveryPreview.segments.length} proposed answer${recoveryPreview.segments.length === 1 ? '' : 's'}</strong><p>Nothing is saved until you approve this preview.</p></div><button class="icon-button" type="button" data-dismiss-recovery aria-label="Close recovery preview"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 6 12 12M18 6 6 18"/></svg></button></div><div class="recovery-candidates">${recoveryPreview.segments.map((segment) => `<div class="recovery-candidate"><span>${MisraUI.escapeHTML(segment.question_number)}</span><p>${MisraUI.escapeHTML(segment.text)}</p></div>`).join('')}</div>${recoveryPreview.notes ? `<p class="recovery-note">OCR note: ${MisraUI.escapeHTML(recoveryPreview.notes)}</p>` : ''}<div class="recovery-actions"><button class="btn btn-ghost" type="button" data-dismiss-recovery>Cancel</button><button class="btn btn-primary" type="button" data-confirm-recovery>Approve and merge</button></div></div>`;
    } catch (error) {
      recoveryPreview = null;
      recoveryPanel.innerHTML = `${MisraUI.errorState(error.message)}<button class="btn btn-secondary" type="button" data-dismiss-recovery style="margin-top:10px">Close</button>`;
    } finally {
      reextractPage.textContent = `Re-extract page ${pageIndex + 1}`;
      reextractPage.disabled = !report?.readiness.missing_question_numbers.length;
    }
  });
  recoveryPanel.addEventListener('click', async (event) => {
    if (event.target.closest('[data-dismiss-recovery]')) { clearRecoveryPreview(); return; }
    const confirmButton = event.target.closest('[data-confirm-recovery]');
    if (!confirmButton || !recoveryPreview) return;
    confirmButton.disabled = true;
    confirmButton.textContent = 'Merging answers…';
    try {
      report = await MisraAPI.confirmPageRecovery(submissionId, recoveryPreview.page_index, recoveryPreview);
      clearRecoveryPreview();
      renderReadiness();
      renderSegmentOrganizer();
      renderMappings();
      setPage(pageIndex);
      window.showToast('Recovered answers merged into this submission.', 'success');
    } catch (error) {
      window.showToast(error.message, 'error');
      confirmButton.disabled = false;
      confirmButton.textContent = 'Approve and merge';
    }
  });
  document.querySelectorAll('[data-filter]').forEach((control) => control.addEventListener('click', () => {
    filter = control.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach((item) => item.setAttribute('aria-pressed', String(item === control)));
    renderMappings();
  }));
  mappingList.addEventListener('click', async (event) => {
    const pageTarget = event.target.closest('[data-source-page]');
    if (pageTarget) {
      setPage(Number.parseInt(pageTarget.dataset.sourcePage, 10));
      document.getElementById('source-viewer').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  gradeAll.addEventListener('click', async () => {
    if (!report?.readiness.bulk_grading_allowed) return;
    const confirmed = window.confirm(`Grade all ${report.readiness.expected_question_count} answers using ${gradeMode.options[gradeMode.selectedIndex].text}? This will use AI quota.`);
    if (!confirmed) return;
    gradeAll.disabled = true; gradeAll.textContent = 'Grading all answers…';
    try {
      const response = await MisraAPI.gradeSubmission(submissionId, gradeMode.value);
      window.location.href = `grade-results.html?id=${encodeURIComponent(submissionId)}&job_id=${encodeURIComponent(response.job.id)}`;
    }
    catch (error) { window.showToast(error.message, 'error'); }
    finally { gradeAll.textContent = 'Grade all answers'; gradeAll.disabled = !report?.readiness.bulk_grading_allowed; }
  });
  load();
})();
