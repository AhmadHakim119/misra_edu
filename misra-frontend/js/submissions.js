(function () {
  'use strict';
  const examSelect = document.getElementById('submission-exam');
  const readinessSelect = document.getElementById('submission-readiness');
  const result = document.getElementById('submissions-result');
  let submissions = [];
  let examsById = {};

  function studentName(item) {
    return item.extracted_student_name || item.extracted_student_number || 'Unidentified student';
  }

  function render() {
    const status = readinessSelect.value;
    const visible = submissions.filter((item) => status === 'all' || (status === 'ready') === item.readiness.bulk_grading_allowed);
    if (!visible.length) {
      result.innerHTML = MisraUI.emptyState('No extraction results', status === 'all' ? 'Upload a paper to begin extraction review.' : 'No submissions match this mapping status.', MisraUI.icons.submissions);
      return;
    }
    result.innerHTML = `<div class="submission-list">${visible.map((item) => {
      const exam = examsById[item.exam_id];
      const ready = item.readiness.bulk_grading_allowed;
      const graded = item.status === 'graded' || item.status === 'reviewed';
      const mapped = `${item.readiness.mapped_answer_count}/${item.readiness.expected_question_count}`;
      return `<a class="submission-row" href="${graded ? 'grade-results' : 'submission'}.html?id=${encodeURIComponent(item.id)}">
        <div class="submission-person"><strong>${MisraUI.escapeHTML(studentName(item))}</strong><span>${MisraUI.escapeHTML(exam ? `${exam.course_code || ''} · ${exam.title}` : item.exam_id)}</span></div>
        <div class="submission-measure"><strong>${mapped}</strong><span>answers mapped</span></div>
        <div class="submission-measure"><strong>${item.page_count}</strong><span>pages</span></div>
        <div>${MisraUI.badge(graded ? 'View grades' : ready ? 'Ready to grade' : 'Check mapping', graded || ready ? 'success' : 'warning')}</div>
        <div class="submission-date"><span>${MisraUI.formatDate(item.uploaded_at)}</span><span aria-hidden="true">→</span></div>
      </a>`;
    }).join('')}</div>`;
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
      render();
    } catch (error) { result.innerHTML = MisraUI.errorState(error.message); }
  }

  examSelect.addEventListener('change', load);
  readinessSelect.addEventListener('change', render);
  load();
})();
