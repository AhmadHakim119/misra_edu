(function () {
  'use strict';

  const examSelect = document.getElementById('grades-exam');
  const statusSelect = document.getElementById('grades-status');
  const result = document.getElementById('grades-result');
  const copy = document.getElementById('grades-list-copy');
  let records = [];
  let examsById = {};

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—';
  }

  function studentName(submission) {
    return submission.extracted_student_name || submission.extracted_student_number || 'Unidentified student';
  }

  function scoreFor(answer) {
    return answer.teacher_override_score ?? answer.score;
  }

  function render() {
    const filter = statusSelect.value;
    const visible = records.filter((record) => filter === 'all' || (filter === 'attention') === record.needsReview);
    copy.textContent = `${visible.length} graded submission${visible.length === 1 ? '' : 's'}${filter === 'all' ? '' : ' matching this filter'}`;
    if (!visible.length) {
      result.innerHTML = MisraUI.emptyState('No recorded grades', filter === 'all' ? 'Grade an extracted submission and it will appear here.' : 'No graded submissions match this review status.', MisraUI.icons.grades);
      return;
    }
    result.innerHTML = `<div class="gradebook-list">${visible.map((record) => {
      const exam = examsById[record.submission.exam_id];
      const percentage = record.maxScore ? (record.score / record.maxScore) * 100 : null;
      return `<a class="gradebook-row" href="grade-results.html?id=${encodeURIComponent(record.submission.id)}">
        <div class="gradebook-person"><strong>${MisraUI.escapeHTML(studentName(record.submission))}</strong><span>${MisraUI.escapeHTML(exam ? `${exam.course_code ? `${exam.course_code} · ` : ''}${exam.title}` : record.submission.exam_id)}</span></div>
        <div class="gradebook-score"><strong>${number(record.score)} <span>/ ${number(record.maxScore)}</span></strong><small>${percentage === null ? 'Score unavailable' : `${number(percentage)}%`}</small></div>
        <div class="gradebook-review">${MisraUI.badge(record.needsReview ? `${record.reviewCount} to review` : 'Not flagged', record.needsReview ? 'warning' : 'draft')}</div>
        <div class="gradebook-date"><span>${MisraUI.formatDate(record.submission.uploaded_at)}</span><span aria-hidden="true">→</span></div>
      </a>`;
    }).join('')}</div>`;
  }

  async function load() {
    result.innerHTML = '<div class="loading-list card-pad"><div class="skel loading-row"></div><div class="skel loading-row"></div><div class="skel loading-row"></div></div>';
    try {
      const [exams, submissions] = await Promise.all([MisraAPI.exams(), MisraAPI.submissions(examSelect.value)]);
      examsById = Object.fromEntries(exams.map((exam) => [exam.id, exam]));
      if (examSelect.options.length === 1) {
        examSelect.insertAdjacentHTML('beforeend', exams.map((exam) => `<option value="${exam.id}">${MisraUI.escapeHTML(exam.course_code ? `${exam.course_code} · ${exam.title}` : exam.title)}</option>`).join(''));
        const requested = MisraUI.getParam('exam_id');
        if (requested && examsById[requested]) { examSelect.value = requested; return load(); }
      }
      const graded = submissions.filter((submission) => ['graded', 'reviewed'].includes(submission.status));
      records = await Promise.all(graded.map(async (submission) => {
        const report = await MisraAPI.results(submission.id);
        const scored = report.answers.filter((answer) => scoreFor(answer) !== null && scoreFor(answer) !== undefined);
        const reviewCount = report.answers.filter((answer) => answer.needs_review || answer.review_status === 'pending').length;
        return {
          submission,
          score: scored.reduce((sum, answer) => sum + Number(scoreFor(answer) || 0), 0),
          maxScore: scored.reduce((sum, answer) => sum + Number(answer.max_score || 0), 0),
          reviewCount,
          needsReview: reviewCount > 0,
        };
      }));
      records.sort((a, b) => new Date(b.submission.uploaded_at) - new Date(a.submission.uploaded_at));
      render();
    } catch (error) {
      copy.textContent = 'Could not load recorded results';
      result.innerHTML = MisraUI.errorState(error.message);
    }
  }

  examSelect.addEventListener('change', load);
  statusSelect.addEventListener('change', render);
  load();
})();
