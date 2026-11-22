(function () {
  'use strict';
  const routeScope=MisraWorkspace.page;
  const { $, esc, number, link, ready } = MisraApp;
  const translate = MisraLocale.text;
  const activeStatuses = new Set(['queued', 'processing', 'retrying']);
  const lastMarkup = new WeakMap();
  let exams = null, papersById = new Map(), examTotals = new Map();
  let paperTotals, activeCount, reviewRows;
  let authenticated = false;
  let timer, loading = false, loadFailed = false, reviewRequest = 0;

  const search = $('dashboard-search');
  const refresh = $('dashboard-refresh');
  const examList = $('dashboard-exams');

  function setText(id, value) {
    const element = $(id);
    if (element.textContent !== value) element.textContent = value;
  }

  function setStatus(id, message) {
    // Write the source text so the existing locale observer can translate it on language changes.
    if ($(id).textContent !== translate(message)) setText(id, message);
  }

  function updateList(host, markup, fallback) {
    if (lastMarkup.get(host) === markup) return;
    const active = document.activeElement;
    const hadFocus = host.contains(active);
    const destination = hadFocus ? active.getAttribute('href') : null;
    host.innerHTML = markup;
    lastMarkup.set(host, markup);
    if (hadFocus) {
      const replacement = [...host.querySelectorAll('a')].find(anchor => anchor.getAttribute('href') === destination);
      (replacement || fallback)?.focus({ preventScroll: true });
    }
  }

  function countPapers(papers) {
    examTotals = new Map();
    papersById = new Map();
    let graded = 0, review = 0;
    for (const paper of papers) {
      papersById.set(paper.id, paper);
      const total = examTotals.get(paper.exam_id) || { papers: 0, graded: 0, review: 0 };
      total.papers++;
      if (paper.grading_summary?.complete) {
        total.graded++;
        graded++;
      }
      if (paper.grading_summary?.review_count > 0) {
        total.review++;
        review++;
      }
      examTotals.set(paper.exam_id, total);
    }
    return { papers: papers.length, graded, review };
  }

  function renderProgress() {
    const { papers, graded, review } = paperTotals;
    const share = papers ? graded / papers : 0;
    $('dashboard-ring').style.setProperty('--graded-share', `${share * 100}%`);
    setText('dashboard-graded-total', `${number(graded)} / ${number(papers)}`);
    setText('dashboard-review-count', number(review));
    setText('dashboard-job-count', number(activeCount));
    $('dashboard-progress-state').hidden = true;
    $('dashboard-progress').hidden = false;
  }

  function renderExams() {
    if (exams === null) {
      if (loadFailed) updateList(examList, '', search);
      return;
    }
    if (!exams.length) {
      setText('dashboard-exam-count', '');
      updateList(examList, `<div class="empty"><h3>Your next exam starts here</h3>
        <p data-i18n>Create an exam, approve its marking guide, then upload handwritten papers.</p>
        <a class="button primary" href="assessments.html?create=1">Create exam</a></div>`, search);
      return;
    }

    const query = search.value.trim().toLowerCase();
    const matches = exams.filter(exam => [exam.title, exam.course_code, exam.course_title]
      .some(value => String(value ?? '').toLowerCase().includes(query)));
    const count = translate(matches.length === 1 ? '{count} exam' : '{count} exams');
    setText('dashboard-exam-count', count.replace('{count}', number(matches.length)));
    if (!matches.length) {
      updateList(examList, `<div class="empty"><h3>No exams match your search</h3>
        <button type="button" id="dashboard-clear-search">Clear search</button></div>`, search);
      return;
    }

    updateList(examList, matches.map(exam => {
      const totals = examTotals.get(exam.id) || { papers: 0, graded: 0, review: 0 };
      const course = exam.course_code || exam.course_title;
      const progressLabel = `${exam.title} · ${translate('Papers graded')}`;
      const paperLabel = totals.papers === 1 ? 'paper' : 'papers';
      return `<article class="record-row">
        <div>
          <h3><bdi>${esc(exam.title)}</bdi></h3>
          <p>${course ? `<bdi>${esc(course)}</bdi> · ` : ''}${number(totals.papers)} <span data-i18n>${paperLabel}</span>
            · ${number(totals.graded)} <span data-i18n>graded</span> · ${number(totals.review)} <span data-i18n>awaiting review</span></p>
          ${totals.papers ? `<progress value="${totals.graded}" max="${totals.papers}" aria-label="${esc(progressLabel)}"></progress>` : ''}
        </div>
        <a class="button" href="${link('grading', { exam_id: exam.id })}">Open exam</a>
      </article>`;
    }).join(''), search);
  }

  function renderReviews() {
    const host = $('dashboard-review-list');
    updateList(host, reviewRows.slice(0, 3).map(answer => {
      const paper = papersById.get(answer.submission_id);
      const explanation = answer.review_explanation?.items;
      const items = Array.isArray(explanation) ? explanation.filter(Boolean) : [];
      const item = items.find(i => i.code === 'deduction_on_uncertain_evidence')
        || items.find(i => i.source === 'rule_check' || i.criterion_id)
        || items.find(i => i.source !== 'uncalibrated_heuristic') || items[0];
      const evidence = paper?.exam_id && answer.question_id
        ? link('grading', { exam_id: paper.exam_id, submission_id: answer.submission_id, question_id: answer.question_id })
        : null;
      const reason = item?.reason || answer.feedback;
      return `<article class="dashboard-review-item">
        <h3>${paper?.extracted_student_name ? `<bdi>${esc(paper.extracted_student_name)}</bdi>` : '<span data-i18n>Paper identity needs checking</span>'}
          · <bdi dir="ltr">${number(answer.score)} / ${number(answer.max_score)}</bdi></h3>
        <p><strong>${item?.title ? `<bdi>${esc(item.title)}</bdi>` : '<span data-i18n>Saved review request</span>'}</strong></p>
        <p>${reason ? `<bdi>${esc(reason)}</bdi>` : '<span data-i18n>Inspect the original work and saved criterion decisions.</span>'}</p>
        ${item?.action ? `<p><span data-i18n>Check:</span> <bdi>${esc(item.action)}</bdi></p>` : ''}
        ${evidence ? `<a class="dashboard-panel-link" href="${evidence}">Review evidence</a>` : ''}
      </article>`;
    }).join(''), $('dashboard-open-review'));
  }

  async function loadReviewPreview() {
    const request = ++reviewRequest;
    try {
      const rows = await MisraAPI.reviewQueue();
      if (request !== reviewRequest) return;
      if (!Array.isArray(rows) || rows.some(row => !row?.submission_id)) {
        throw Error('Review concerns could not be loaded.');
      }
      reviewRows = rows;
      renderReviews();
      setStatus('dashboard-review-state', rows.length ? '' : 'No recorded review concerns. Unflagged proposals still require instructor judgment.');
    } catch {
      if (request !== reviewRequest) return;
      setStatus('dashboard-review-state', $('dashboard-review-list').childElementCount
        ? 'Could not refresh review concerns. Showing the last loaded concerns.'
        : 'Could not load review concerns. Open the review queue or refresh to retry.');
    }
  }

  function renderActivity(jobs) {
    const host = $('dashboard-activity');
    if (!jobs.length) {
      updateList(host, '<p data-i18n>No recent processing jobs.</p>');
      return;
    }
    updateList(host, jobs.slice(0, 8).map(job => `<div class="record-row">
      <div><strong data-i18n>${esc(MisraJobStatus.task(job))}</strong>
        <p><bdi data-i18n>${esc(MisraJobStatus.message(job))}</bdi></p></div>
      <span class="dashboard-job-status" data-status="${esc(job.status)}" data-i18n>${esc(MisraJobStatus.title(job))}</span>
    </div>`).join(''));
  }

  function showLoadFailure() {
    loadFailed = true;
    setStatus('dashboard-error', exams !== null
      ? 'Could not refresh the dashboard. Showing the last loaded exams.'
      : 'Could not load the dashboard. Use Refresh to try again.');
    if (exams === null) {
      setStatus('dashboard-progress-state', 'Paper progress is unavailable.');
      setStatus('dashboard-review-state', 'Review concerns are unavailable.');
      updateList($('dashboard-activity'), '<p data-i18n>Recent activity is unavailable.</p>');
    }
    renderExams();
  }

  async function load() {
    if (loading) return;
    loading = true;
    routeScope.cancelTimer(timer);
    refresh.disabled = true;
    if (exams === null) {
      examList.setAttribute('aria-busy', 'true');
      updateList(examList, '<p data-i18n>Loading your exams…</p>', search);
    }
    try {
      const [nextExams, papers, activity] = await Promise.all([
        MisraAPI.exams(), MisraAPI.submissions(), MisraAPI.workspaceJobs(20)
      ]);
      if (!Array.isArray(nextExams) || !Array.isArray(papers) || !Array.isArray(activity?.items)) {
        throw Error('Dashboard data is incomplete.');
      }
      paperTotals = countPapers(papers);
      activeCount = activity.active_count;
      exams = nextExams;
      loadFailed = false;
      setStatus('dashboard-error', '');
      renderExams();
      renderProgress();
      renderActivity(activity.items);
      loadReviewPreview();
      if (activity.active_count > 0 || activity.items.some(job => activeStatuses.has(job.status))) {
        timer = routeScope.later(load, 6000);
      }
    } catch {
      showLoadFailure();
    } finally {
      loading = false;
      refresh.disabled = false;
      examList.setAttribute('aria-busy', 'false');
    }
  }

  routeScope.listen(window,'misra:language', () => {
    renderExams();
    if (paperTotals) renderProgress();
    if (reviewRows) renderReviews();
  });
  search.addEventListener('input', renderExams);
  refresh.addEventListener('click', () => {
    if (authenticated) load();
    else location.reload();
  });
  examList.addEventListener('click', event => {
    if (event.target.id !== 'dashboard-clear-search') return;
    search.value = '';
    renderExams();
    search.focus();
  });

  ready.then(user => {
    if (user.must_change_password) return;
    authenticated = true;
    return load();
  }).catch(() => {
    showLoadFailure();
    refresh.disabled = false;
    examList.setAttribute('aria-busy', 'false');
  });

  ready.then(async user => {
    if (user.must_change_password) return;
    const versions = await MisraAPI.instructorPreferenceVersions();
    if (!Array.isArray(versions)) return;
    const host = $('dashboard-preferences');
    const panel = document.createElement('section');
    panel.className = 'dashboard-panel';
    if (versions.some(version => version.status === 'approved')) {
      const settings = MisraMarkingProfile.validate(await MisraAPI.accountSettings());
      if (!settings.survey_completed) return;
      panel.id = 'marking-survey-completed';
      panel.innerHTML = MisraMarkingProfile.completion(settings)
        + '<a class="dashboard-panel-link" href="account.html#marking-settings">Marking preferences in Settings</a>';
    } else {
      const key = `misra-survey-later:${user.id}`;
      if (sessionStorage.getItem(key) === '1') return;
      panel.id = 'marking-survey-invitation';
      panel.innerHTML = `<h2>Set your marking preferences</h2>
        <p data-i18n>Answer 12 grading scenarios so MISRA can suggest the marking rules you normally use.</p>
        <div class="inline-actions"><a class="button" href="marking-survey.html">Start marking survey</a>
        <button type="button" id="survey-later">Do this later</button></div>`;
      panel.querySelector('#survey-later').addEventListener('click', () => {
        try { sessionStorage.setItem(key, '1'); } catch {}
        host.hidden = true;
        panel.remove();
        $('dashboard-activity-title').parentElement.querySelector('a').focus();
      });
    }
    host.replaceChildren(panel);
    host.hidden = false;
  }).catch(() => {});
})();
