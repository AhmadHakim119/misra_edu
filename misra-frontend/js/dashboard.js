(async function () {
  'use strict';
  const stats = document.getElementById('dashboard-stats');
  const recent = document.getElementById('recent-assessments');
  const review = document.getElementById('review-summary');

  try {
    const [exams, submissions] = await Promise.all([
      window.MisraAPI.exams(),
      window.MisraAPI.submissions(),
    ]);
    const totals = exams.reduce((sum, exam) => ({
      questions: sum.questions + exam.question_count,
      submissions: sum.submissions + exam.submission_count,
      reviews: sum.reviews + exam.review_count,
    }), { questions: 0, submissions: 0, reviews: 0 });
    const identityIssues = submissions.filter((submission) => MisraUI.identityState(submission).needsAttention);

    stats.innerHTML = [
      ['Assessments', exams.length, 'Persisted in the catalog'],
      ['Submissions', totals.submissions, 'Uploaded papers'],
      ['Needs review', totals.reviews, totals.reviews ? 'Instructor attention required' : 'Queue is clear'],
      ['Identity checks', identityIssues.length, identityIssues.length ? 'Missing student name or ID' : 'Names and IDs are complete'],
    ].map(([label, value, note]) => `<article class="workspace-card stat"><div class="stat-label">${MisraUI.escapeHTML(label)}</div><div class="stat-value">${value}</div><div class="stat-note">${MisraUI.escapeHTML(note)}</div></article>`).join('');

    recent.innerHTML = exams.length ? `<div class="data-list">${exams.slice(0, 5).map((exam) => `
      <div class="data-row">
        <div><div class="data-row-title">${MisraUI.escapeHTML(exam.title)}</div><div class="data-row-meta">${MisraUI.escapeHTML(exam.course_code || exam.course_title || 'Course not labeled')} · ${exam.question_count} question${exam.question_count === 1 ? '' : 's'} · ${exam.submission_count} submission${exam.submission_count === 1 ? '' : 's'}</div></div>
        <div class="data-row-actions"><a class="link-button" href="grades.html?exam_id=${encodeURIComponent(exam.id)}">Grades</a><a class="link-button" href="rubric-studio.html?exam_id=${encodeURIComponent(exam.id)}">Rubrics</a><a class="link-button" href="upload.html?exam_id=${encodeURIComponent(exam.id)}">Upload</a></div>
      </div>`).join('')}</div>` : MisraUI.emptyState('No assessments yet', 'Create an assessment in the backend, then return here to configure its questions and rubrics.');

    review.innerHTML = `<div class="attention-list">
      <a class="attention-row" href="reviews.html"><span class="attention-count">${totals.reviews}</span><span><strong>Grade reviews</strong><small>${totals.reviews ? 'Resolve disagreements and low-confidence answers' : 'No answers are currently flagged'}</small></span><span aria-hidden="true">→</span></a>
      <a class="attention-row" href="submissions.html?identity=attention"><span class="attention-count">${identityIssues.length}</span><span><strong>Student identities</strong><small>${identityIssues.length ? 'Add missing names or student numbers' : 'Every paper has a name and student number'}</small></span><span aria-hidden="true">→</span></a>
    </div>`;
    MisraUI.reveal(stats.querySelectorAll('.stat'));
    MisraUI.reveal(recent.querySelectorAll('.data-row'));
    MisraUI.reveal(review.querySelectorAll('.attention-row'));
  } catch (error) {
    stats.innerHTML = '';
    recent.innerHTML = MisraUI.errorState(`${error.message}. Start the backend on port 8000 and refresh.`);
    review.innerHTML = MisraUI.errorState('Review data is unavailable while the engine is offline.');
  }
})();
