(function () {
  'use strict';
  const submissionId = MisraUI.getParam('id');
  const title = document.getElementById('submission-title');
  const meta = document.getElementById('submission-meta');
  const errorRegion = document.getElementById('submission-error');
  const readinessPanel = document.getElementById('readiness-panel');
  const unmatchedPanel = document.getElementById('unmatched-panel');
  const metadataForm = document.getElementById('metadata-form');
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
  let report = null;
  const requestedPage = Number.parseInt(MisraUI.getParam('page'), 10);
  let pageIndex = Number.isInteger(requestedPage) && requestedPage >= 0 ? requestedPage : 0;
  let filter = 'all';
  let recoveryPreview = null;

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
    const student = report.submission.extracted_student_name || report.submission.extracted_student_number || 'Unidentified student';
    title.textContent = student;
    meta.textContent = `${report.submission.page_count} pages · ${report.submission.identity_status.replaceAll('_', ' ')} · uploaded ${MisraUI.formatDate(report.submission.uploaded_at)}`;
    studentName.value = report.submission.extracted_student_name || '';
    studentNumber.value = report.submission.extracted_student_number || '';
    instructorName.value = report.submission.instructor_name || '';
  }

  function renderUnmatched() {
    const segments = report.unmatched_segments || [];
    if (!segments.length) {
      unmatchedPanel.innerHTML = '';
      return;
    }
    const questionOptions = report.questions.map((row) => `<option value="${row.question.id}">Question ${MisraUI.escapeHTML(row.question.question_number)} — ${MisraUI.escapeHTML(row.question.question_text || 'Untitled question')}</option>`).join('');
    unmatchedPanel.innerHTML = `<details class="workspace-card unmatched-review" open>
      <summary><span>Unassigned OCR fragments</span>${MisraUI.badge(`${segments.length} remaining`, 'warning')}</summary>
      <p class="section-copy">Nothing is selected automatically. For each fragment, deliberately choose its question and paper page—or mark it as noise.</p>
      <div class="unmatched-list">${segments.map((segment, index) => `<div class="unmatched-item" data-unmatched-index="${index}">
        <div class="unmatched-copy"><span>${segment.question_number ? `OCR detected label ${MisraUI.escapeHTML(segment.question_number)}` : 'OCR could not identify a question'}</span><p>${MisraUI.escapeHTML(segment.text || '')}</p></div>
        <div class="unmatched-actions">
          <label>Belongs to<select class="input select" data-unmatched-question aria-label="Target question for unmatched fragment ${index + 1}"><option value="">Choose question…</option>${questionOptions}</select></label>
          <label>Seen on<select class="input select" data-unmatched-page aria-label="Source page for unmatched fragment ${index + 1}"><option value="">Choose page…</option>${Array.from({ length: report.submission.page_count }, (_, page) => `<option value="${page}" ${Number.isInteger(segment.page_index) && page === segment.page_index ? 'selected' : ''}>Page ${page + 1}</option>`).join('')}</select></label>
          <button class="btn btn-secondary" type="button" data-assign-unmatched disabled>Assign fragment</button><button class="btn btn-ghost" type="button" data-ignore-unmatched>Mark as noise</button>
        </div>
      </div>`).join('')}</div>
    </details>`;
  }

  function sourceMarkup(source, row) {
    const options = report.questions.filter((candidate) => candidate.question.id !== row.question.id).map((candidate) => `<option value="${candidate.question.id}">Question ${MisraUI.escapeHTML(candidate.question.question_number)} — ${MisraUI.escapeHTML(candidate.question.question_text || 'Untitled question')}</option>`).join('');
    return `<div class="source-segment" data-source="${source.id}">
      <button class="source-page-link" type="button" data-source-page="${source.page_index}">Page ${source.page_number} · ${source.resolved_from_unmatched ? 'manually assigned' : `OCR segment ${source.segment_index + 1}`}</button>
      <p>${MisraUI.escapeHTML(source.extracted_text)}</p>
      <div class="source-move"><span>Currently in Question ${MisraUI.escapeHTML(row.question.question_number)}</span><select class="input select" data-source-target aria-label="Move this OCR segment to another question"><option value="">Move to another question…</option>${options}</select><button class="btn btn-secondary" type="button" data-move-source="${source.id}" disabled>Move segment</button>${source.resolved_from_unmatched ? '<button class="btn btn-ghost source-noise" type="button" data-remove-source>Remove as noise</button>' : ''}</div>
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
      report = await MisraAPI.extractionReview(submissionId);
      renderIdentity();
      renderReadiness();
      renderUnmatched();
      renderMappings();
      setPage(Math.min(pageIndex, report.submission.page_count - 1));
    } catch (error) {
      errorRegion.innerHTML = MisraUI.errorState(error.message);
      readinessPanel.innerHTML = '';
      mappingList.innerHTML = '';
    }
  }

  previousPage.addEventListener('click', () => setPage(pageIndex - 1));
  nextPage.addEventListener('click', () => setPage(pageIndex + 1));
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
      window.showToast('Paper identity and instructor updated.', 'success');
    } catch (error) {
      window.showToast(error.message, 'error');
    } finally {
      button.disabled = false; button.textContent = 'Save paper details';
    }
  });
  unmatchedPanel.addEventListener('click', async (event) => {
    const row = event.target.closest('[data-unmatched-index]');
    if (!row) return;
    const assignButton = event.target.closest('[data-assign-unmatched]');
    const ignoreButton = event.target.closest('[data-ignore-unmatched]');
    if (!assignButton && !ignoreButton) return;
    row.querySelectorAll('button, select').forEach((control) => { control.disabled = true; });
    try {
      const payload = ignoreButton ? { action: 'ignore' } : {
        action: 'assign',
        question_id: row.querySelector('[data-unmatched-question]').value,
        page_index: Number(row.querySelector('[data-unmatched-page]').value),
      };
      await MisraAPI.resolveUnmatchedSegment(submissionId, Number(row.dataset.unmatchedIndex), payload);
      await load();
      window.showToast(ignoreButton ? 'Fragment marked as noise. Saved.' : 'Fragment assigned and saved.', 'success');
    } catch (error) {
      window.showToast(error.message, 'error');
      row.querySelectorAll('button, select').forEach((control) => { control.disabled = false; });
    }
  });
  unmatchedPanel.addEventListener('change', (event) => {
    const row = event.target.closest('[data-unmatched-index]');
    if (!row) return;
    const question = row.querySelector('[data-unmatched-question]').value;
    const page = row.querySelector('[data-unmatched-page]').value;
    row.querySelector('[data-assign-unmatched]').disabled = !question || page === '';
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
      if (pageTarget.matches('.source-page-link')) return;
    }
    const sourceRow = event.target.closest('[data-source]');
    const removeButton = event.target.closest('[data-remove-source]');
    if (removeButton && sourceRow) {
      const excerpt = sourceRow.querySelector('p')?.textContent.trim().slice(0, 90) || 'this fragment';
      if (!window.confirm(`Remove “${excerpt}${excerpt.length === 90 ? '…' : ''}” as OCR noise? This will be saved immediately.`)) return;
      removeButton.disabled = true; removeButton.textContent = 'Removing…';
      try {
        await MisraAPI.removeAnswerSource(sourceRow.dataset.source);
        await load();
        window.showToast('OCR noise removed and saved.', 'success');
      } catch (error) {
        window.showToast(error.message, 'error');
        removeButton.disabled = false; removeButton.textContent = 'Remove as noise';
      }
      return;
    }
    const moveButton = event.target.closest('[data-move-source]');
    if (!moveButton || !sourceRow) return;
    const select = sourceRow.querySelector('[data-source-target]');
    if (!select.value) { window.showToast('Choose the destination question first.', 'error'); return; }
    const targetLabel = select.options[select.selectedIndex].text;
    moveButton.disabled = true; moveButton.textContent = 'Moving…';
    try {
      await MisraAPI.moveAnswerSource(sourceRow.dataset.source, select.value);
      await load();
      window.showToast(`Moved to ${targetLabel}. Saved.`, 'success');
    } catch (error) { window.showToast(error.message, 'error'); moveButton.disabled = false; moveButton.textContent = 'Move segment'; }
  });
  mappingList.addEventListener('change', (event) => {
    const select = event.target.closest('[data-source-target]');
    if (!select) return;
    select.closest('[data-source]').querySelector('[data-move-source]').disabled = !select.value;
  });
  gradeAll.addEventListener('click', async () => {
    if (!report?.readiness.bulk_grading_allowed) return;
    const confirmed = window.confirm(`Grade all ${report.readiness.expected_question_count} answers using ${gradeMode.options[gradeMode.selectedIndex].text}? This will use AI quota.`);
    if (!confirmed) return;
    gradeAll.disabled = true; gradeAll.textContent = 'Grading all answers…';
    try {
      await MisraAPI.gradeSubmission(submissionId, gradeMode.value);
      window.location.href = `grade-results.html?id=${encodeURIComponent(submissionId)}`;
    }
    catch (error) { window.showToast(error.message, 'error'); }
    finally { gradeAll.textContent = 'Grade all answers'; gradeAll.disabled = !report?.readiness.bulk_grading_allowed; }
  });
  load();
})();
