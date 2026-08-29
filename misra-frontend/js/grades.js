(function () {
  'use strict';

  const courseSelect = document.getElementById('grades-course');
  const examSelect = document.getElementById('grades-exam');
  const statusSelect = document.getElementById('grades-status');
  const result = document.getElementById('grades-result');
  const copy = document.getElementById('grades-list-copy');
  const exportCsv = document.getElementById('export-csv');
  const exportXlsx = document.getElementById('export-xlsx');
  const exportNote = document.getElementById('grade-export-note');
  const exportPreflight = document.getElementById('grade-export-preflight');
  const exportProfile = document.getElementById('export-profile');
  let records = [];
  let exams = [];
  let examsById = {};
  let preflightRequest = 0;

  function courseLabel(exam) {
    const code = exam.course_code || '';
    const title = exam.course_title || '';
    return [code, title].filter(Boolean).join(' · ') || 'Unassigned course';
  }

  function examLabel(exam, includeCourse = false) {
    const title = exam.title || 'Untitled assessment';
    const term = exam.term ? ` · ${exam.term}` : '';
    return `${includeCourse ? `${courseLabel(exam)} · ` : ''}${title}${term}`;
  }

  function replaceOptions(select, placeholder, options) {
    const fragment = document.createDocumentFragment();
    fragment.appendChild(new Option(placeholder, ''));
    options.forEach(({ value, label }) => fragment.appendChild(new Option(label, value)));
    select.replaceChildren(fragment);
  }

  function populateCourseOptions() {
    const courses = new Map();
    exams.forEach((exam) => {
      const key = exam.course_id || 'unassigned';
      if (!courses.has(key)) courses.set(key, courseLabel(exam));
    });
    const options = [...courses.entries()]
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
    replaceOptions(courseSelect, 'All courses', options);
  }

  function populateAssessmentOptions(preferredExamId = '') {
    const courseId = courseSelect.value;
    const available = exams
      .filter((exam) => !courseId || (exam.course_id || 'unassigned') === courseId)
      .sort((a, b) => examLabel(a).localeCompare(examLabel(b)));
    replaceOptions(
      examSelect,
      courseId ? 'All assessments in this course' : 'All assessments',
      available.map((exam) => ({
        value: exam.id,
        label: examLabel(exam, !courseId),
      })),
    );
    if (preferredExamId && available.some((exam) => exam.id === preferredExamId)) {
      examSelect.value = preferredExamId;
    }
    examSelect.disabled = available.length === 0;
  }

  function initializeCatalog(catalog) {
    exams = Array.isArray(catalog) ? catalog : [];
    examsById = Object.fromEntries(exams.map((exam) => [exam.id, exam]));
    populateCourseOptions();
    const requestedExamId = MisraUI.getParam('exam_id');
    const requestedExam = examsById[requestedExamId];
    if (requestedExam) courseSelect.value = requestedExam.course_id || 'unassigned';
    populateAssessmentOptions(requestedExamId);
  }

  function syncUrl() {
    const url = new URL(window.location.href);
    if (examSelect.value) url.searchParams.set('exam_id', examSelect.value);
    else url.searchParams.delete('exam_id');
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
  }

  function updateExports() {
    const examId = examSelect.value;
    [exportCsv, exportXlsx].forEach((link) => link.setAttribute('aria-disabled', String(!examId)));
    if (!examId) {
      exportCsv.removeAttribute('href');
      exportXlsx.removeAttribute('href');
      delete exportCsv.dataset.downloadUrl;
      delete exportXlsx.dataset.downloadUrl;
      exportCsv.textContent = exportProfile.value === 'blackboard' ? 'Blackboard CSV' : 'Generic CSV';
      exportNote.textContent = 'Select one assessment to export. LMS CSV includes only complete, unflagged grades; the Excel report includes review and question-level detail.';
      return;
    }
    exportCsv.href = '#';
    exportXlsx.href = '#';
    const blackboard = exportProfile.value === 'blackboard';
    exportCsv.dataset.downloadUrl = MisraAPI.gradeExportCsvUrl(examId, exportProfile.value, 'student_number');
    exportXlsx.dataset.downloadUrl = MisraAPI.gradeExportXlsxUrl(examId);
    exportCsv.textContent = blackboard ? 'Blackboard CSV' : 'Generic CSV';
    exportNote.textContent = blackboard
      ? 'Blackboard CSV uses the student number as Username and omits incomplete or flagged grades. Verify that this matches the Blackboard roster and target grade column before upload.'
      : 'Generic CSV includes score, maximum score, percentage, readiness, and review state for LMS mapping or record keeping.';
  }

  async function updatePreflight() {
    const requestId = ++preflightRequest;
    const examId = examSelect.value;
    const blackboard = exportProfile.value === 'blackboard';
    if (!examId) {
      exportPreflight.innerHTML = `<div class="identity-reminder"><span class="readiness-mark">!</span><div><strong>Select one assessment before export</strong><p>${blackboard ? 'Blackboard requires a verified Username for every included student.' : 'MISRA will check grading completion, review flags, and recorded identity before creating the file.'}</p></div></div>`;
      return;
    }
    exportPreflight.innerHTML = '<div class="export-preflight-loading"><span class="api-status-dot"></span><span>Checking student identities and export readiness…</span></div>';
    try {
      const preflight = await MisraAPI.gradeExportPreflight(examId, 'student_number');
      if (requestId !== preflightRequest) return;
      const issues = preflight.rows.filter((row) => row.issues.length);
      const displayRows = (issues.length ? issues : preflight.rows).slice(0, 8);
      const hiddenCount = (issues.length ? issues : preflight.rows).length - displayRows.length;
      exportPreflight.innerHTML = `<div class="export-preflight-head">
        <div><strong>${blackboard ? 'Blackboard import check' : 'Generic CSV export check'}</strong><p>${blackboard ? 'The import file intentionally contains only Blackboard Username and one grade column. Confirm the selected assessment and roster identity before upload.' : 'The generic file includes identity, score, maximum score, percentage, completion, and review state for local records or LMS mapping.'}</p></div>
        <div class="export-preflight-counts">${MisraUI.badge(`${preflight.counts.ready} export ready`, 'success')}${preflight.counts.missing_name ? MisraUI.badge(`${preflight.counts.missing_name} missing name`, 'warning') : ''}${preflight.counts.missing_identifier ? MisraUI.badge(`${preflight.counts.missing_identifier} missing ID`, blackboard ? 'danger' : 'warning') : ''}${preflight.counts.incomplete_grading ? MisraUI.badge(`${preflight.counts.incomplete_grading} incomplete`, 'warning') : ''}${preflight.counts.needs_review ? MisraUI.badge(`${preflight.counts.needs_review} to review`, 'warning') : ''}</div>
      </div>
      <div class="export-preflight-column"><span>${blackboard ? 'Blackboard grade column' : 'Selected assessment column'}</span><strong>${MisraUI.escapeHTML(preflight.grade_column)}</strong></div>
      ${displayRows.length ? `<div class="export-preflight-list">${displayRows.map((row) => {
        const name = row.student_name || 'Student name missing';
        const username = row.username || 'Student number missing';
        const blocking = row.issues.some((issue) => issue.blocking);
        const status = blocking ? row.issues.filter((issue) => issue.blocking).map((issue) => issue.message).join(' · ') : row.issues.length ? row.issues.map((issue) => issue.message).join(' · ') : (blackboard ? 'Ready for Blackboard import' : 'Ready for generic export');
        return `<div class="export-preflight-row">
          <div><strong>${MisraUI.escapeHTML(name)}</strong><span>${MisraUI.escapeHTML(username)}</span></div>
          <div class="export-preflight-score"><strong>${number(row.score)}</strong><span>/ ${number(row.max_score)}</span></div>
          <div>${MisraUI.badge(status, blocking ? 'danger' : row.issues.length ? 'warning' : 'success')}</div>
          <a class="link-button" href="submission.html?id=${encodeURIComponent(row.submission_id)}">Check record</a>
        </div>`;
      }).join('')}</div>` : '<p class="section-copy">No submissions are recorded for this assessment.</p>'}
      ${hiddenCount > 0 ? `<p class="export-preflight-more">${hiddenCount} more row${hiddenCount === 1 ? '' : 's'} not shown. The downloaded Excel report includes every student.</p>` : ''}`;
      MisraUI.reveal(exportPreflight.querySelectorAll('.export-preflight-row'));
    } catch (error) {
      if (requestId !== preflightRequest) return;
      exportPreflight.innerHTML = MisraUI.errorState(`${error.message} Open the Excel report or try again.`);
    }
  }

  async function downloadExport(event) {
    event.preventDefault();
    const link = event.currentTarget;
    const url = link.dataset.downloadUrl;
    if (!url || link.getAttribute('aria-disabled') === 'true') return;
    const idleLabel = link.textContent;
    link.setAttribute('aria-disabled', 'true');
    link.textContent = 'Preparing…';
    try {
      const response = await fetch(url, { credentials: 'include', cache: 'no-store' });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const detail = payload.detail;
        const message = typeof detail === 'string' ? detail : detail?.message;
        throw new Error(message || `Export failed (${response.status})`);
      }
      const disposition = response.headers.get('content-disposition') || '';
      const match = disposition.match(/filename="?([^";]+)"?/i);
      const objectUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = match?.[1] || (idleLabel.includes('Excel') ? 'gradebook.xlsx' : 'gradebook.csv');
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      const omitted = Number(response.headers.get('x-misra-omitted-rows') || 0);
      if (omitted > 0) {
        const missingId = Number(response.headers.get('x-misra-missing-identifier') || 0);
        const incomplete = Number(response.headers.get('x-misra-incomplete-grading') || 0);
        const review = Number(response.headers.get('x-misra-needs-review') || 0);
        const reasons = [
          missingId ? `${missingId} missing student ID` : '',
          incomplete ? `${incomplete} incomplete` : '',
          review ? `${review} awaiting review` : '',
        ].filter(Boolean).join(', ');
        window.showToast(`${idleLabel} downloaded. ${omitted} row${omitted === 1 ? '' : 's'} withheld${reasons ? `: ${reasons}` : ''}.`, 'warning');
      } else {
        window.showToast(`${idleLabel} downloaded.`, 'success');
      }
    } catch (error) {
      window.showToast(error.message || 'Could not prepare the export.', 'error');
    } finally {
      link.textContent = idleLabel;
      link.setAttribute('aria-disabled', String(!examSelect.value));
    }
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—';
  }

  function scoreFor(answer) {
    return answer.teacher_override_score ?? answer.score;
  }

  function renderRecord(record) {
    const identity = MisraUI.identityState(record.submission);
    const percentage = record.maxScore ? (record.score / record.maxScore) * 100 : null;
    return `<a class="gradebook-row" href="grade-results.html?id=${encodeURIComponent(record.submission.id)}">
      <div class="gradebook-person"><strong>${MisraUI.escapeHTML(identity.displayName)}</strong><span>${MisraUI.escapeHTML(identity.displayNumber)}</span></div>
      <div class="gradebook-score"><strong>${number(record.score)} <span>/ ${number(record.maxScore)}</span></strong><small>${percentage === null ? 'Score unavailable' : `${number(percentage)}%`}</small></div>
      <div class="gradebook-review">${MisraUI.badge(record.needsReview ? `${record.reviewCount} to review` : record.gradedCount < record.questionCount ? `${record.gradedCount} of ${record.questionCount} graded` : 'Complete', record.needsReview || record.gradedCount < record.questionCount ? 'warning' : 'draft')}</div>
      <div class="gradebook-date"><span>${MisraUI.formatDate(record.submission.uploaded_at)}</span><span aria-hidden="true">→</span></div>
    </a>`;
  }

  function render() {
    const filter = statusSelect.value;
    const courseId = courseSelect.value;
    const examId = examSelect.value;
    const visible = records.filter((record) => {
      const exam = examsById[record.submission.exam_id];
      const matchesCourse = !courseId || (exam?.course_id || 'unassigned') === courseId;
      const matchesExam = !examId || record.submission.exam_id === examId;
      const matchesStatus = filter === 'all' || (filter === 'attention') === record.needsReview;
      return matchesCourse && matchesExam && matchesStatus;
    });
    copy.textContent = `${visible.length} graded submission${visible.length === 1 ? '' : 's'}${filter === 'all' ? '' : ' matching this filter'}`;
    if (!visible.length) {
      result.innerHTML = MisraUI.emptyState('No recorded grades', filter === 'all' ? 'Grade an extracted submission and it will appear here.' : 'No graded submissions match this review status.', MisraUI.icons.grades);
      return;
    }

    const groups = new Map();
    visible.forEach((record) => {
      const key = record.submission.exam_id;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(record);
    });
    const sortedGroups = [...groups.entries()].sort(([examA], [examB]) => {
      return examLabel(examsById[examA] || {}).localeCompare(examLabel(examsById[examB] || {}));
    });
    result.innerHTML = `<div class="gradebook-groups">${sortedGroups.map(([groupExamId, groupRecords]) => {
      const groupExam = examsById[groupExamId];
      return `<section class="gradebook-group">
        <button class="gradebook-group-head" type="button" data-exam-id="${MisraUI.escapeHTML(groupExamId)}">
          <span><strong>${MisraUI.escapeHTML(groupExam?.title || 'Unknown assessment')}</strong><small>${MisraUI.escapeHTML(groupExam ? courseLabel(groupExam) : groupExamId)}</small></span>
          <span>${groupRecords.length} student${groupRecords.length === 1 ? '' : 's'} <span aria-hidden="true">→</span></span>
        </button>
        <div class="gradebook-list">${groupRecords.map(renderRecord).join('')}</div>
      </section>`;
    }).join('')}</div>`;
    MisraUI.reveal(result.querySelectorAll('.gradebook-group'));
  }

  async function load() {
    result.innerHTML = '<div class="loading-list card-pad"><div class="skel loading-row"></div><div class="skel loading-row"></div><div class="skel loading-row"></div></div>';
    try {
      const [catalog, submissions] = await Promise.all([MisraAPI.exams(), MisraAPI.submissions()]);
      initializeCatalog(catalog);
      const loadedRecords = await Promise.all(submissions.map(async (submission) => {
        const report = await MisraAPI.results(submission.id);
        const scored = report.answers.filter((answer) => scoreFor(answer) !== null && scoreFor(answer) !== undefined);
        const reviewCount = report.answers.filter((answer) => answer.needs_review || answer.review_status === 'pending').length;
        const exam = examsById[submission.exam_id];
        return {
          submission,
          score: scored.reduce((sum, answer) => sum + Number(scoreFor(answer) || 0), 0),
          maxScore: scored.reduce((sum, answer) => sum + Number(answer.max_score || 0), 0),
          gradedCount: scored.length,
          questionCount: Number(exam?.question_count || report.answers.length),
          reviewCount,
          needsReview: reviewCount > 0,
        };
      }));
      records = loadedRecords.filter((record) => record.gradedCount > 0);
      records.sort((a, b) => new Date(b.submission.uploaded_at) - new Date(a.submission.uploaded_at));
      updateExports();
      updatePreflight();
      render();
    } catch (error) {
      copy.textContent = 'Could not load recorded results';
      result.innerHTML = MisraUI.errorState(error.message);
    }
  }

  courseSelect.addEventListener('change', () => {
    populateAssessmentOptions();
    syncUrl();
    updateExports();
    updatePreflight();
    render();
  });
  examSelect.addEventListener('change', () => {
    const selectedExam = examsById[examSelect.value];
    if (selectedExam && !courseSelect.value) {
      courseSelect.value = selectedExam.course_id || 'unassigned';
      populateAssessmentOptions(selectedExam.id);
    }
    syncUrl();
    updateExports();
    updatePreflight();
    render();
  });
  exportProfile.addEventListener('change', () => {
    updateExports();
    updatePreflight();
  });
  exportCsv.addEventListener('click', downloadExport);
  exportXlsx.addEventListener('click', downloadExport);
  statusSelect.addEventListener('change', render);
  result.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-exam-id]');
    if (!trigger) return;
    const selectedExam = examsById[trigger.dataset.examId];
    if (!selectedExam) return;
    courseSelect.value = selectedExam.course_id || 'unassigned';
    populateAssessmentOptions(selectedExam.id);
    syncUrl();
    updateExports();
    updatePreflight();
    render();
    document.querySelector('.gradebook-controls').scrollIntoView({ block: 'start' });
  });
  updateExports();
  updatePreflight();
  load();
})();
