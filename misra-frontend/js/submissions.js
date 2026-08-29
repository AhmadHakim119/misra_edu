(function () {
  'use strict';
  const examSelect = document.getElementById('submission-exam');
  const readinessSelect = document.getElementById('submission-readiness');
  const identitySelect = document.getElementById('submission-identity');
  const result = document.getElementById('submissions-result');
  let submissions = [];
  let examsById = {};

  function render() {
    const status = readinessSelect.value;
    const identityFilter = identitySelect.value;
    const visible = submissions.filter((item) => {
      const identity = MisraUI.identityState(item);
      const mappingMatches = status === 'all' || (status === 'ready') === item.readiness.bulk_grading_allowed;
      const identityMatches = identityFilter === 'all' || (identityFilter === 'complete') === identity.complete;
      return mappingMatches && identityMatches;
    });
    if (!visible.length) {
      result.innerHTML = MisraUI.emptyState('No extraction results', status === 'all' ? 'Upload a paper to begin extraction review.' : 'No submissions match this mapping status.', MisraUI.icons.submissions);
      return;
    }
    result.innerHTML = `<div class="submission-list">${visible.map((item) => {
      const exam = examsById[item.exam_id];
      const ready = item.readiness.bulk_grading_allowed;
      const graded = item.status === 'graded' || item.status === 'reviewed';
      const extractionFailed = item.latest_ocr_job?.status === 'failed';
      const identity = MisraUI.identityState(item);
      const mapped = `${item.readiness.mapped_answer_count}/${item.readiness.expected_question_count}`;
      const destination = identity.needsAttention ? 'submission' : graded ? 'grade-results' : 'submission';
      const submissionUrl = `${destination}.html?id=${encodeURIComponent(item.id)}`;
      return `<div class="submission-row" data-submission-row="${item.id}">
        <a class="submission-row-link" href="${submissionUrl}" aria-label="Open ${MisraUI.escapeHTML(identity.displayName)} extraction result"></a>
        <div class="submission-person"><strong>${MisraUI.escapeHTML(identity.displayName)}</strong><span>${MisraUI.escapeHTML(identity.displayNumber)} · ${MisraUI.escapeHTML(exam ? `${exam.course_code || ''} · ${exam.title}` : item.exam_id)}</span></div>
        <div class="submission-measure"><strong>${mapped}</strong><span>answers mapped</span></div>
        <div class="submission-measure"><strong>${item.page_count}</strong><span>pages</span></div>
        <div>${extractionFailed ? MisraUI.badge('Extraction failed', 'danger') : identity.needsAttention ? MisraUI.badge(identity.label, 'warning') : MisraUI.badge(graded ? 'View grades' : ready ? 'Ready to grade' : 'Check mapping', graded || ready ? 'success' : 'warning')}</div>
        <div class="submission-date"><span>${MisraUI.formatDate(item.uploaded_at)}</span><span aria-hidden="true">→</span></div>
        <button class="icon-button submission-delete" type="button" data-delete-submission="${item.id}" aria-label="Delete ${MisraUI.escapeHTML(identity.displayName)} submission" title="Delete submission">${MisraUI.icons.trash}</button>
      </div>`;
    }).join('')}</div>`;
    MisraUI.reveal(result.querySelectorAll('.submission-row'));
  }

  async function load() {
    result.innerHTML = '<div class="loading-list"><div class="skel loading-row"></div><div class="skel loading-row"></div><div class="skel loading-row"></div></div>';
    try {
      const [exams, items] = await Promise.all([MisraAPI.exams(), MisraAPI.submissions(examSelect.value)]);
      examsById = Object.fromEntries(exams.map((exam) => [exam.id, exam]));
      if (examSelect.options.length === 1) {
        examSelect.insertAdjacentHTML('beforeend', exams.map((exam) => `<option value="${exam.id}">${MisraUI.escapeHTML(exam.course_code ? `${exam.course_code} · ${exam.title}` : exam.title)}</option>`).join(''));
        const requested = MisraUI.getParam('exam_id');
        if (requested && examsById[requested]) { examSelect.value = requested; return load(); }
      }
      submissions = items;
      const requestedIdentity = MisraUI.getParam('identity');
      if (requestedIdentity && [...identitySelect.options].some((option) => option.value === requestedIdentity)) identitySelect.value = requestedIdentity;
      render();
    } catch (error) { result.innerHTML = MisraUI.errorState(error.message); }
  }

  examSelect.addEventListener('change', load);
  readinessSelect.addEventListener('change', render);
  identitySelect.addEventListener('change', render);
  result.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-delete-submission]');
    if (!button) return;
    const item = submissions.find((submission) => submission.id === button.dataset.deleteSubmission);
    const identity = MisraUI.identityState(item || {});
    const confirmed = window.confirm(`Delete the submission for ${identity.displayName}? This permanently removes the uploaded paper, OCR text, grades, review labels, and job history. This cannot be undone.`);
    if (!confirmed) return;

    button.disabled = true;
    try {
      const deletion = await MisraAPI.deleteSubmission(button.dataset.deleteSubmission);
      submissions = submissions.filter((submission) => submission.id !== button.dataset.deleteSubmission);
      render();
      window.showToast(
        deletion.file_removed ? 'Submission and uploaded paper deleted.' : 'Submission records deleted, but the stored paper could not be removed. Check storage permissions.',
        deletion.file_removed ? 'success' : 'warning',
      );
    } catch (error) {
      button.disabled = false;
      window.showToast(error.message, 'error');
    }
  });
  load();
})();
