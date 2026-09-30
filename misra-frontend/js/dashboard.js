(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const escape = MisraUI.escapeHTML, number = MisraPaperFlow.number;
  const plural = (n, label) => n + ' ' + label + (n === 1 ? '' : 's');
  const href = (page, id) => page + '.html?exam_id=' + encodeURIComponent(id);
  let exams = [], submissions = [], context = {}, loading = false, loaded = false, timer;
  let currentChecks = null;

  function assessmentState(exam) {
    const papers = submissions.filter((paper) => paper.exam_id === exam.id);
    const counts = MisraPaperFlow.counts(papers);
    const questions = number(exam.question_count), approved = number(exam.approved_question_count);
    const destination = (label, page, detail, tone) => ({ label, href: href(page, exam.id), detail, tone });
    if (!questions) return destination('Add questions', 'rubric-studio', 'Add the source exam or create questions to begin.', 'setup');
    if (approved < questions) return destination('Finish rubrics', 'rubric-studio', approved + ' of ' + questions + ' question rubrics approved.', 'setup');
    if (exam.id === context.selectedId && currentChecks?.ready === false) return destination('Finish setup', 'rubric-studio', 'Resolve the answer-key, rubric or policy checks.', 'setup');
    if (counts.attention) return destination('Check papers', 'submissions', plural(counts.attention, 'paper') + ' need processing or evidence checks.', 'review');
    if (number(exam.review_count) || counts.review) return destination('Review grades', 'reviews', 'Instructor decisions are waiting in the review queue.', 'review');
    if (counts.processing) return destination('View progress', 'submissions', plural(counts.processing, 'paper') + ' still processing. You can leave the page.', 'ready');
    if (counts.ready) return destination('Start grading', 'submissions', plural(counts.ready, 'paper') + ' ready to grade.', 'ready');
    if (counts.graded) return destination('Open grades', 'grades', 'Grades recorded. Export eligibility is checked separately.', 'complete');
    if (number(exam.submission_count)) return destination('Open papers', 'submissions', 'Inspect the uploaded papers and their saved progress.', 'ready');
    return destination('Upload papers', 'upload', 'Rubrics approved. Upload student work when ready.', 'ready');
  }
  function renderAssessments() {
    const query = $('assessment-search').value.trim().toLocaleLowerCase();
    const visible = exams.filter((exam) => [exam.course_code, exam.course_title, exam.title].join(' ').toLocaleLowerCase().includes(query));
    $('recent-assessments').innerHTML = visible.length ? visible.map((exam) => {
      const state = assessmentState(exam);
      return `<article class="dashboard-assessment" data-tone="${state.tone}">
        <div class="assessment-main"><div class="assessment-course">${escape(exam.course_code || exam.course_title || 'Assessment')}</div>
        <h3>${escape(exam.title)}</h3><div class="assessment-meta"><span>${plural(number(exam.question_count), 'question')}</span><span>${plural(number(exam.submission_count), 'paper')}</span></div></div>
        <div class="assessment-readiness"><span class="assessment-state-note">${escape(state.detail)}</span></div>
        <a class="assessment-next" href="${state.href}"><span>${escape(state.label)}</span><span aria-hidden="true">→</span></a>
      </article>`;
    }).join('') : MisraUI.emptyState(exams.length ? 'No matching assessments' : 'Create your first assessment', exams.length ? 'Try a different course code or title.' : 'Add a course and assessment, then prepare its grading foundations.');
  }
  function focusItem(count, label, copy, url, tone = 'neutral') {
    return `<a class="focus-action focus-action-${tone}" href="${url}"><span class="focus-action-count">${count}</span><span class="focus-action-copy"><strong>${escape(label)}</strong><small>${escape(copy)}</small></span><span class="focus-action-arrow" aria-hidden="true">→</span></a>`;
  }
  function render() {
    const counts = MisraPaperFlow.counts(submissions);
    const reviews = exams.reduce((total, exam) => total + number(exam.review_count), 0);
    const setup = exams.filter((exam) => !number(exam.question_count) || number(exam.approved_question_count) < number(exam.question_count) || (exam.id === context.selectedId && currentChecks?.ready === false));
    const current = exams.find((exam) => exam.id === context.selectedId) || exams[0];
    if (current) {
      const action = assessmentState(current);
      $('dashboard-primary-action').textContent = action.label === 'Finish rubrics' ? 'Continue assessment setup' : action.label;
      $('dashboard-primary-action').href = action.href;
    }
    const tasks = [];
    if (counts.attention) tasks.push(focusItem(counts.attention, 'Paper checks', 'Inspect stopped jobs or unresolved evidence', 'submissions.html?status=attention', 'urgent'));
    if (reviews || counts.review) tasks.push(focusItem(reviews || counts.review, reviews ? 'Answers to review' : 'Papers to review', 'Confirm or correct recorded grades', 'reviews.html', 'warning'));
    if (counts.ready) tasks.push(focusItem(counts.ready, 'Ready for grading', 'Open papers with completed mapping checks', 'submissions.html?status=ready', 'setup'));
    if (counts.identity) tasks.push(focusItem(counts.identity, 'Identity checks', 'Confirm missing names or student IDs before export', 'submissions.html?identity=attention', 'warning'));
    if (setup.length) tasks.push(focusItem(setup.length, 'Assessment setup', 'Finish questions, keys, rubrics and policies', href('rubric-studio', setup[0].id), 'setup'));
    if (!tasks.length && counts.processing) tasks.push(focusItem(counts.processing, 'Work is in progress', 'Your background worker keeps going while you leave this page', 'submissions.html?status=processing'));
    if (!tasks.length) tasks.push(focusItem(exams.length ? counts.graded : 0, exams.length ? 'Ready for your next assessment' : 'Start your workspace', exams.length ? 'Recorded grades are available; check eligibility before exporting.' : 'Create an assessment and prepare its grading foundations.', exams.length ? 'assessments.html' : 'assessments.html'));
    $('dashboard-lead').textContent = counts.processing ? plural(counts.processing, 'paper') + ' processing in the background. Continue your work here.'
      : 'Prepare assessments, follow your papers and make the decisions that matter.';
    $('focus-copy').textContent = 'Next actions from saved records. Identity checks and grading decisions stay separate.';
    $('dashboard-focus-actions').innerHTML = tasks.join('');
    $('dashboard-stats').innerHTML = [
      ['Assessments', exams.length, plural(setup.length, 'assessment') + ' need setup checks'],
      ['Processing', counts.processing, 'OCR or grading in progress'],
      ['Ready to grade', counts.ready, 'Mapping checks passed'],
      ['Grades recorded', counts.graded + counts.review, 'Recorded does not mean export-ready'],
    ].map(([label, count, note]) => `<article class="dashboard-metric"><span class="dashboard-metric-label">${label}</span><strong>${count}</strong><small>${note}</small></article>`).join('');
    renderAssessments();
    $('dashboard-pipeline').innerHTML = [
      ['Prepare', setup.length ? plural(setup.length, 'assessment') + ' to finish' : 'Review keys, rubrics and policies', setup.length ? 'attention' : 'idle', setup.length ? href('rubric-studio', setup[0].id) : 'assessments.html'],
      ['Extract', counts.processing ? plural(counts.processing, 'paper') + ' processing' : plural(counts.attention, 'paper') + ' to check', counts.attention ? 'attention' : counts.processing ? 'active' : 'idle', 'submissions.html'],
      ['Grade & review', plural(counts.ready, 'paper') + ' ready to grade', counts.ready ? 'active' : 'idle', counts.ready ? 'submissions.html?status=ready' : 'reviews.html'],
      ['Export', 'Check student identity and final grade eligibility', 'idle', 'grades.html'],
    ].map(([label, detail, state, url]) => `<li data-state="${state}"><span class="pipeline-marker"></span><div><strong>${label}</strong><small>${escape(detail)}</small></div><a href="${url}" aria-label="Open ${escape(label)}">→</a></li>`).join('');
  }
  async function load() {
    if (loading) return;
    loading = true; $('dashboard-refresh').disabled = true;
    try {
      if (!loaded) { context = await MisraUI.assessmentReady; }
      const [newExams, papers, checks] = await Promise.all([
        loaded || context.error ? MisraAPI.exams() : Promise.resolve(context.exams),
        MisraAPI.submissions(),
        context.selectedId ? MisraAPI.setupReadiness(context.selectedId).catch(() => null) : Promise.resolve(null),
      ]);
      exams = newExams; submissions = papers; currentChecks = checks;
      if (!context.selectedId) context.selectedId = exams[0]?.id;
      loaded = true; $('dashboard-connection').hidden = true;
      render();
      $('dashboard-sync').textContent = 'Updated ' + new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date()) + ' · refreshes automatically';
    } catch (error) {
      $('dashboard-sync').textContent = 'Connection interrupted';
      if (loaded) {
        $('dashboard-connection').hidden = false;
        $('dashboard-connection').textContent = 'Showing the last loaded overview. Refresh when the connection returns. Background work may still be running.';
      } else {
        $('dashboard-stats').innerHTML = '';
        $('focus-copy').textContent = 'Workspace data could not load.';
        $('dashboard-focus-actions').innerHTML = MisraUI.errorState(error.message + '. Start the backend on port 8000 and try again.');
        $('recent-assessments').innerHTML = MisraUI.emptyState('Waiting for your workspace', 'Reconnect to load assessments. No records were changed.');
      }
    } finally {
      loading = false; $('dashboard-refresh').disabled = false;
      clearTimeout(timer);
      if (!document.hidden) timer = setTimeout(load, submissions.some((paper) => MisraPaperFlow.state(paper).active) ? 20000 : 60000);
    }
  }
  $('assessment-search').addEventListener('input', renderAssessments);
  $('dashboard-refresh').addEventListener('click', load);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); else clearTimeout(timer); });
  window.addEventListener('online', load);
  window.addEventListener('pagehide', () => clearTimeout(timer));
  load();
})();
