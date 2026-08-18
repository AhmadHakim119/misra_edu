(async function () {
  'use strict';
  const stats = document.getElementById('dashboard-stats');
  const recent = document.getElementById('recent-assessments');
  const review = document.getElementById('review-summary');

  try {
    const exams = await window.MisraAPI.exams();
    const totals = exams.reduce((sum, exam) => ({
      questions: sum.questions + exam.question_count,
      submissions: sum.submissions + exam.submission_count,
      reviews: sum.reviews + exam.review_count,
    }), { questions: 0, submissions: 0, reviews: 0 });

    stats.innerHTML = [
      ['Assessments', exams.length, 'Persisted in the catalog'],
      ['Questions', totals.questions, 'Across all assessments'],
      ['Submissions', totals.submissions, 'Uploaded papers'],
      ['Needs review', totals.reviews, totals.reviews ? 'Instructor attention required' : 'Queue is clear'],
    ].map(([label, value, note]) => `<article class="workspace-card stat"><div class="stat-label">${MisraUI.escapeHTML(label)}</div><div class="stat-value">${value}</div><div class="stat-note">${MisraUI.escapeHTML(note)}</div></article>`).join('');

    recent.innerHTML = exams.length ? `<div class="data-list">${exams.slice(0, 5).map((exam) => `
      <div class="data-row">
        <div><div class="data-row-title">${MisraUI.escapeHTML(exam.title)}</div><div class="data-row-meta">${MisraUI.escapeHTML(exam.course_code || exam.course_title || 'Course not labeled')} · ${exam.question_count} question${exam.question_count === 1 ? '' : 's'} · ${exam.submission_count} submission${exam.submission_count === 1 ? '' : 's'}</div></div>
        <div class="data-row-actions"><a class="link-button" href="rubric-studio.html?exam_id=${encodeURIComponent(exam.id)}">Rubrics</a><a class="link-button" href="upload.html?exam_id=${encodeURIComponent(exam.id)}">Upload</a></div>
      </div>`).join('')}</div>` : MisraUI.emptyState('No assessments yet', 'Create an assessment in the backend, then return here to configure its questions and rubrics.');

    if (totals.reviews) {
      review.innerHTML = `<div class="score-display"><strong>${totals.reviews}</strong><span>answers waiting</span></div><p class="section-copy" style="margin:8px 0 16px">Review disagreements and low-confidence grades before results are finalized.</p><a class="btn btn-primary btn-block" href="reviews.html">Open review queue</a>`;
    } else {
      review.innerHTML = MisraUI.emptyState('Queue is clear', 'No answer is currently flagged for instructor review.', MisraUI.icons.review);
    }
  } catch (error) {
    stats.innerHTML = '';
    recent.innerHTML = MisraUI.errorState(`${error.message}. Start the backend on port 8000 and refresh.`);
    review.innerHTML = MisraUI.errorState('Review data is unavailable while the engine is offline.');
  }
})();
