(async function () {
  'use strict';

  const stats = document.getElementById('dashboard-stats');
  const recent = document.getElementById('recent-assessments');
  const focusActions = document.getElementById('dashboard-focus-actions');
  const focusCopy = document.getElementById('focus-copy');
  const dashboardLead = document.getElementById('dashboard-lead');
  const pipeline = document.getElementById('dashboard-pipeline');
  const primaryAction = document.getElementById('dashboard-primary-action');

  const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
  const plural = (value, singular, pluralForm = `${singular}s`) => `${value} ${value === 1 ? singular : pluralForm}`;
  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

  function assessmentState(exam) {
    const questions = number(exam.question_count);
    const approved = clamp(number(exam.approved_question_count), 0, questions);
    const submissions = number(exam.submission_count);
    const reviews = number(exam.review_count);
    const readiness = questions ? Math.round((approved / questions) * 100) : 0;

    if (!questions) return { label: 'Add questions', tone: 'setup', readiness, href: `rubric-studio.html?exam_id=${encodeURIComponent(exam.id)}` };
    if (approved < questions) return { label: 'Finish rubrics', tone: 'setup', readiness, href: `rubric-studio.html?exam_id=${encodeURIComponent(exam.id)}` };
    if (!submissions) return { label: 'Upload papers', tone: 'ready', readiness, href: `upload.html?exam_id=${encodeURIComponent(exam.id)}` };
    if (reviews) return { label: 'Review grades', tone: 'review', readiness, href: `reviews.html?exam_id=${encodeURIComponent(exam.id)}` };
    return { label: 'Open grades', tone: 'complete', readiness, href: `grades.html?exam_id=${encodeURIComponent(exam.id)}` };
  }

  function focusItem({ count, label, copy, href, tone = 'neutral' }) {
    return `<a class="focus-action focus-action-${tone}" href="${href}">
      <span class="focus-action-count">${number(count)}</span>
      <span class="focus-action-copy"><strong>${MisraUI.escapeHTML(label)}</strong><small>${MisraUI.escapeHTML(copy)}</small></span>
      <span class="focus-action-arrow" aria-hidden="true">→</span>
    </a>`;
  }

  function metric(label, value, note, tone = '') {
    return `<article class="dashboard-metric ${tone ? `is-${tone}` : ''}">
      <span class="dashboard-metric-label">${MisraUI.escapeHTML(label)}</span>
      <strong>${MisraUI.escapeHTML(value)}</strong>
      <small>${MisraUI.escapeHTML(note)}</small>
    </article>`;
  }

  function assessmentRow(exam) {
    const state = assessmentState(exam);
    const questions = number(exam.question_count);
    const approved = number(exam.approved_question_count);
    const submissions = number(exam.submission_count);
    const reviews = number(exam.review_count);
    const course = exam.course_code || exam.course_title || 'Course not labeled';
    const readinessLabel = questions ? `${approved} of ${questions} grading foundations approved` : 'No questions configured';

    return `<article class="dashboard-assessment" data-tone="${state.tone}">
      <div class="assessment-main">
        <div class="assessment-course">${MisraUI.escapeHTML(course)}</div>
        <h3>${MisraUI.escapeHTML(exam.title)}</h3>
        <div class="assessment-meta">
          <span>${plural(questions, 'question')}</span>
          <span>${plural(submissions, 'paper')}</span>
          ${reviews ? `<span class="assessment-review-count">${plural(reviews, 'review')}</span>` : '<span>No pending reviews</span>'}
        </div>
      </div>
      <div class="assessment-readiness">
        <div class="assessment-readiness-copy"><span>Rubric readiness</span><strong>${state.readiness}%</strong></div>
        <div class="assessment-progress" role="progressbar" aria-label="${MisraUI.escapeHTML(exam.title)} rubric readiness" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${state.readiness}"><span style="--assessment-progress:${state.readiness}%"></span></div>
        <small>${MisraUI.escapeHTML(readinessLabel)}</small>
      </div>
      <a class="assessment-next" href="${state.href}"><span>${MisraUI.escapeHTML(state.label)}</span><span aria-hidden="true">→</span></a>
    </article>`;
  }

  try {
    const [context, submissions] = await Promise.all([
      MisraUI.assessmentReady,
      window.MisraAPI.submissions(),
    ]);
    const exams = context.exams;
    if (context.error) throw context.error;
    const current = exams.find((exam) => exam.id === context.selectedId) || exams[0];
    if (current) {
      const checks = await MisraAPI.setupReadiness(current.id).catch(() => null);
      const action = !checks?.ready
        ? { label: 'Finish assessment setup', page: 'rubric-studio.html' }
        : !number(current.submission_count)
          ? { label: 'Upload student papers', page: 'upload.html' }
          : number(current.review_count)
            ? { label: 'Review flagged grades', page: 'reviews.html' }
            : { label: 'Open grades', page: 'grades.html' };
      primaryAction.textContent = action.label;
      primaryAction.href = `${action.page}?exam_id=${encodeURIComponent(current.id)}`;
    }

    const totals = exams.reduce((sum, exam) => ({
      questions: sum.questions + number(exam.question_count),
      approved: sum.approved + number(exam.approved_question_count),
      submissions: sum.submissions + number(exam.submission_count),
      reviews: sum.reviews + number(exam.review_count),
    }), { questions: 0, approved: 0, submissions: 0, reviews: 0 });
    const identityIssues = submissions.filter((submission) => MisraUI.identityState(submission).needsAttention);
    const setupIssues = exams.filter((exam) => number(exam.question_count) === 0 || number(exam.approved_question_count) < number(exam.question_count));
    const activeJobs = submissions.filter((submission) => ['uploaded', 'queued', 'processing', 'extracting', 'grading', 'retrying'].includes(String(submission.status || '').toLowerCase()));
    const gradedPapers = submissions.filter((submission) => ['graded', 'completed', 'needs_review'].includes(String(submission.status || '').toLowerCase()));
    const allClear = totals.reviews === 0 && identityIssues.length === 0 && setupIssues.length === 0;

    dashboardLead.textContent = allClear
      ? 'Your grading workspace is clear. Start a new upload or prepare the next assessment.'
      : `${plural(totals.reviews + identityIssues.length + setupIssues.length, 'item')} need a decision before every result is ready.`;
    focusCopy.textContent = allClear
      ? 'Everything is ready for the next batch.'
      : 'Resolve these items first to keep grading traceable and safe to export.';

    focusActions.innerHTML = allClear
      ? `<a class="focus-action focus-action-clear" href="upload.html"><span class="focus-clear-mark" aria-hidden="true">✓</span><span class="focus-action-copy"><strong>Workspace clear</strong><small>Upload the next set of papers when you are ready.</small></span><span class="focus-action-arrow" aria-hidden="true">→</span></a>`
      : [
        focusItem({ count: totals.reviews, label: 'Grade reviews', copy: totals.reviews ? 'Resolve low-confidence or disputed results' : 'No answers are currently flagged', href: 'reviews.html', tone: totals.reviews ? 'urgent' : 'quiet' }),
        focusItem({ count: identityIssues.length, label: 'Identity checks', copy: identityIssues.length ? 'Confirm missing names or student IDs' : 'All recorded identities are complete', href: 'submissions.html?identity=attention', tone: identityIssues.length ? 'warning' : 'quiet' }),
        focusItem({ count: setupIssues.length, label: 'Assessment setup', copy: setupIssues.length ? 'Finish questions or approve grading foundations' : 'All assessment rubrics are approved', href: 'rubric-studio.html', tone: setupIssues.length ? 'setup' : 'quiet' }),
      ].join('');

    const readinessPercent = totals.questions ? Math.round((totals.approved / totals.questions) * 100) : 0;
    stats.innerHTML = [
      metric('Assessments', String(exams.length), exams.length ? 'Available in your workspace' : 'Create your first assessment'),
      metric('Rubric readiness', `${readinessPercent}%`, totals.questions ? `${totals.approved} of ${totals.questions} questions approved` : 'No questions configured', readinessPercent === 100 && totals.questions ? 'good' : 'attention'),
      metric('Papers in progress', String(activeJobs.length), activeJobs.length ? 'OCR or grading is underway' : 'No active processing jobs'),
      metric('Graded papers', String(gradedPapers.length), totals.reviews ? `${plural(totals.reviews, 'answer')} still need review` : 'No pending grading reviews', totals.reviews ? 'attention' : 'good'),
    ].join('');

    recent.innerHTML = exams.length
      ? exams.slice(0, 6).map(assessmentRow).join('')
      : MisraUI.emptyState('No assessments yet', 'Create your first assessment, then add questions and approve its grading foundations.');

    pipeline.innerHTML = [
      { label: 'Assessment setup', value: setupIssues.length ? `${plural(setupIssues.length, 'assessment')} incomplete` : 'All active assessments configured', state: setupIssues.length ? 'attention' : 'complete', href: 'rubric-studio.html' },
      { label: 'Paper processing', value: activeJobs.length ? `${plural(activeJobs.length, 'paper')} in progress` : `${plural(totals.submissions, 'paper')} received`, state: activeJobs.length ? 'active' : (totals.submissions ? 'complete' : 'idle'), href: 'submissions.html' },
      { label: 'Instructor review', value: totals.reviews ? `${plural(totals.reviews, 'answer')} waiting` : 'Review queue is clear', state: totals.reviews ? 'attention' : 'complete', href: 'reviews.html' },
      { label: 'Grade export', value: gradedPapers.length ? `${plural(gradedPapers.length, 'paper')} recorded` : 'No completed papers yet', state: gradedPapers.length ? 'complete' : 'idle', href: 'grades.html' },
    ].map((item) => `<li data-state="${item.state}"><span class="pipeline-marker"></span><div><strong>${MisraUI.escapeHTML(item.label)}</strong><small>${MisraUI.escapeHTML(item.value)}</small></div><a href="${item.href}" aria-label="Open ${MisraUI.escapeHTML(item.label)}">→</a></li>`).join('');

    MisraUI.reveal(stats.querySelectorAll('.dashboard-metric'));
    MisraUI.reveal(focusActions.querySelectorAll('.focus-action'));
    MisraUI.reveal(recent.querySelectorAll('.dashboard-assessment'), { limit: 6 });
  } catch (error) {
    stats.innerHTML = '';
    focusCopy.textContent = 'Live workspace data is unavailable.';
    focusActions.innerHTML = MisraUI.errorState(`${error.message}. Start the backend on port 8000 and refresh.`);
    recent.innerHTML = MisraUI.errorState('Assessment data is unavailable while the engine is offline.');
    pipeline.innerHTML = '<li data-state="attention"><span class="pipeline-marker"></span><div><strong>Connection interrupted</strong><small>Reconnect to refresh the workflow.</small></div></li>';
  }
})();
