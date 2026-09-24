/* Shared instructor workspace shell and rendering helpers. */
(function () {
  'use strict';

  const icons = {
    dashboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    assessments: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 3h12a2 2 0 0 1 2 2v16H4V5a2 2 0 0 1 2-2Z"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>',
    rubric: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 5H4v5h5V5ZM20 5h-7M20 9h-7M9 14H4v5h5v-5ZM20 14h-7M20 18h-7"/></svg>',
    upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 16V4m0 0L7 9m5-5 5 5"/><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/></svg>',
    submissions: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 3h8l4 4v14H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M14 3v5h5M9 13h6M9 17h4"/></svg>',
    grades: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5h16v14H4z"/><path d="M8 9h8M8 13h4M16 13h.01M8 17h4M16 17h.01"/></svg>',
    review: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m9 11 2 2 4-4"/><path d="M20 12a8 8 0 1 1-3-6.2"/></svg>',
    evaluation: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
    account: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></svg>',
    settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.09A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.09A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.4.26.75.6 1 1 .24.33.38.72.4 1.1V11h.1v4h-.09a1.7 1.7 0 0 0-1.41 0Z"/></svg>',
    instructors: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/></svg>',
    operations: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3 4.5 6v5.2c0 4.5 3 8.6 7.5 9.8 4.5-1.2 7.5-5.3 7.5-9.8V6L12 3Z"/><path d="M8.5 9.5h7M8.5 13h7M8.5 16.5h4"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg>',
  };

  const pages = [
    ['dashboard', 'Overview', 'dashboard.html'],
    ['assessments', 'Assessments', 'assessments.html'],
    ['rubric', 'Rubric Studio', 'rubric-studio.html'],
    ['upload', 'Upload papers', 'upload.html'],
    ['submissions', 'Extraction results', 'submissions.html'],
    ['grades', 'Grades', 'grades.html'],
    ['review', 'Review queue', 'reviews.html'],
    ['evaluation', 'Evaluation', 'evaluation.html'],
    ['settings', 'Settings', 'account.html'],
    ['instructors', 'Instructor accounts', 'instructors.html', true],
    ['operations', 'Admin operations', 'admin-operations.html', true],
  ];

  function escapeHTML(value) {
    return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
  }

  function formatDate(value) {
    if (!value) return 'Not available';
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value));
  }

  function badge(label, tone = 'draft') {
    return `<span class="badge badge-${tone}">${escapeHTML(label)}</span>`;
  }

  function emptyState(title, copy, icon = icons.assessments) {
    return `<div class="empty-state"><div class="empty-state-icon">${icon}</div><h2>${escapeHTML(title)}</h2><p>${escapeHTML(copy)}</p></div>`;
  }

  function errorState(message, retryLabel = 'Reload and try again') {
    return `<div class="error-state" role="alert"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 17h.01"/></svg><span>${escapeHTML(message)}</span>${retryLabel ? `<button class="link-button" type="button" data-retry-page>${escapeHTML(retryLabel)}</button>` : ''}</div>`;
  }

  function getParam(name) { return new URLSearchParams(window.location.search).get(name); }

  function identityState(submission) {
    const name = String(submission?.extracted_student_name || '').trim();
    const number = String(submission?.extracted_student_number || '').trim();
    const hasName = Boolean(name);
    const hasNumber = Boolean(number);
    const rosterMatched = submission?.identity_status === 'matched';
    let label = rosterMatched ? 'Roster matched' : 'Check OCR identity';
    let message = 'Confirm the OCR name and student number against the original paper before exporting grades.';
    if (!hasName && !hasNumber) {
      label = 'Identity missing';
      message = 'Student name and student number are missing.';
    } else if (!hasName) {
      label = 'Name missing';
      message = 'A student number is recorded, but the student name is missing.';
    } else if (!hasNumber) {
      label = 'Student ID missing';
      message = 'The student name is recorded, but Blackboard username / student number is missing.';
    } else if (rosterMatched) {
      message = 'This paper is linked to a student record. Confirm it still matches the original paper.';
    }
    return {
      name,
      number,
      hasName,
      hasNumber,
      complete: hasName && hasNumber,
      rosterMatched,
      needsAttention: !hasName || !hasNumber,
      displayName: name || 'Student name missing',
      displayNumber: number || 'Student number missing',
      label,
      message,
    };
  }

  function reveal(targets, options = {}) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const nodes = typeof targets === 'string' ? document.querySelectorAll(targets) : targets;
    [...nodes].slice(0, options.limit || 12).forEach((node, index) => {
      node.animate(
        [
          { opacity: 0.94, transform: 'translateY(5px)', filter: 'blur(1.5px)' },
          { opacity: 1, transform: 'translateY(0)', filter: 'blur(0)' },
        ],
        {
          duration: 320,
          delay: Math.min(index, 5) * 42,
          easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
          fill: 'both',
        },
      );
    });
  }

  const activePage = document.body.dataset.page || 'dashboard';
  const activePageTitle = document.body.dataset.pageTitle || pages.find(([key]) => key === activePage)?.[1] || 'Instructor workspace';
  const content = document.getElementById('workspace-content');
  if (!content) return;
  content.setAttribute('tabindex', '-1');

  const skipLink = document.createElement('a');
  skipLink.className = 'skip-link';
  skipLink.href = '#workspace-content';
  skipLink.textContent = 'Skip to main content';
  document.body.prepend(skipLink);

  const shell = document.createElement('div');
  shell.className = 'workspace-shell';
  shell.innerHTML = `
    <button class="mobile-scrim" type="button" data-close-nav aria-label="Close navigation"></button>
    <aside class="workspace-sidebar" aria-label="Instructor workspace navigation">
      <a class="workspace-brand" href="dashboard.html">
        <img src="../assets/logo-white.png" alt="">
        <span>MISRA <strong>EDU</strong></span>
      </a>
      <nav class="workspace-nav">
        <div class="workspace-nav-label">Workspace</div>
        ${pages.map(([key, label, href, adminOnly]) => `<a class="workspace-nav-link" href="${href}" ${key === activePage ? 'aria-current="page"' : ''} ${adminOnly ? 'data-admin-only hidden' : ''}>${icons[key]}<span>${label}</span></a>`).join('')}
      </nav>
      <div class="workspace-sidebar-foot" data-user-panel><strong>Instructor workspace</strong><br><span>Checking your session…</span></div>
    </aside>
    <div class="workspace-main">
      <header class="workspace-topbar">
        <div style="display:flex;align-items:center;gap:12px;min-width:0">
          <button class="workspace-menu-button" type="button" data-open-nav aria-label="Open navigation" aria-expanded="false">
            <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
          </button>
          <div class="workspace-topbar-title"><strong>${escapeHTML(activePageTitle)}</strong><span>Instructor workspace</span></div>
        </div>
        <div class="workspace-topbar-actions">
          <span class="api-status" data-api-status data-state="checking"><span class="api-status-dot"></span><span>Checking engine</span></span>
          <a class="btn btn-secondary" href="../index.html" style="padding:8px 14px;font-size:12.5px">Project overview</a>
        </div>
      </header>
      <section class="workspace-assessment-context" data-assessment-context hidden aria-label="Current assessment workflow">
        <div class="workspace-assessment-choice">
          <label for="workspace-assessment-select">Current assessment</label>
          <select id="workspace-assessment-select" class="input select" data-assessment-select></select>
        </div>
        <nav class="workspace-assessment-flow" data-assessment-flow aria-label="Assessment steps"></nav>
        <a class="workspace-assessment-next" data-assessment-next href="assessments.html">Continue <span aria-hidden="true">→</span></a>
      </section>
      <section class="workspace-job-center" data-job-center hidden aria-live="polite">
        <div class="workspace-job-summary">
          <span class="workspace-job-symbol" aria-hidden="true">${icons.upload}</span>
          <div class="workspace-job-heading">
            <strong data-job-center-title>Background activity</strong>
            <span data-job-center-copy>Uploads and grading continue safely when you change pages.</span>
          </div>
          <button class="workspace-job-toggle" type="button" data-job-toggle aria-expanded="true">Hide details</button>
        </div>
        <div class="workspace-job-list" data-job-list></div>
      </section>
    </div>`;
  document.body.prepend(shell);
  shell.querySelector('.workspace-main').appendChild(content);

  const openButton = shell.querySelector('[data-open-nav]');
  const closeButton = shell.querySelector('[data-close-nav]');
  function setNav(open) {
    shell.classList.toggle('is-nav-open', open);
    openButton.setAttribute('aria-expanded', String(open));
    document.body.style.overflow = open ? 'hidden' : '';
    if (window.matchMedia('(max-width: 820px)').matches) {
      shell.querySelector('.workspace-sidebar').inert = !open;
    }
    if (open) {
      window.requestAnimationFrame(() => shell.querySelector('.workspace-nav-link')?.focus());
    }
  }
  openButton.addEventListener('click', () => setNav(!shell.classList.contains('is-nav-open')));
  closeButton.addEventListener('click', () => setNav(false));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') setNav(false); });
  shell.querySelectorAll('.workspace-nav-link').forEach((link) => link.addEventListener('click', () => setNav(false)));
  const mobileQuery = window.matchMedia('(max-width: 820px)');
  const syncNavMode = () => {
    const sidebar = shell.querySelector('.workspace-sidebar');
    if (!mobileQuery.matches) {
      sidebar.inert = false;
      shell.classList.remove('is-nav-open');
      document.body.style.overflow = '';
    } else if (!shell.classList.contains('is-nav-open')) {
      sidebar.inert = true;
    }
  };
  mobileQuery.addEventListener?.('change', syncNavMode);
  syncNavMode();
  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-retry-page]')) window.location.reload();
  });

  const apiStatus = shell.querySelector('[data-api-status]');
  const userPanel = shell.querySelector('[data-user-panel]');
  let assessmentContext = null;
  let resolveAssessmentReady;
  const assessmentReady = new Promise((resolve) => { resolveAssessmentReady = resolve; });

  function rememberAssessment(examId) {
    if (!assessmentContext || !assessmentContext.exams.some((exam) => exam.id === examId)) return;
    if (assessmentContext.selectedId === examId && assessmentContext.readinessChecked) return;
    assessmentContext.selectedId = examId;
    assessmentContext.ready = false;
    assessmentContext.readinessChecked = false;
    try { localStorage.setItem(assessmentContext.storageKey, examId); } catch (_) {}
    renderAssessmentContext();
    window.MisraAPI.setupReadiness(examId).then((readiness) => {
      if (assessmentContext?.selectedId !== examId) return;
      const exam = assessmentContext.exams.find((item) => item.id === examId);
      if (exam && Number.isFinite(Number(readiness.question_count))) exam.question_count = Number(readiness.question_count);
      if (exam && Number.isFinite(Number(readiness.approved_count))) exam.approved_question_count = Number(readiness.approved_count);
      assessmentContext.ready = Boolean(readiness.ready);
      assessmentContext.readinessChecked = true;
      renderAssessmentContext();
    }).catch(() => { if (assessmentContext?.selectedId === examId) renderAssessmentContext(); });
  }

  async function renderAssessmentContext() {
    if (!assessmentContext) return;
    const { exams, selectedId } = assessmentContext;
    const exam = exams.find((item) => item.id === selectedId);
    if (!exam) return;
    const box = shell.querySelector('[data-assessment-context]');
    const select = shell.querySelector('[data-assessment-select]');
    const flow = shell.querySelector('[data-assessment-flow]');
    const next = shell.querySelector('[data-assessment-next]');
    box.hidden = false;
    document.body.dataset.assessmentContextReady = 'true';
    select.value = exam.id;
    const href = (page) => `${page}?exam_id=${encodeURIComponent(exam.id)}`;
    shell.querySelectorAll('.workspace-nav-link').forEach((link) => {
      const page = link.getAttribute('href')?.split('?')[0];
      if (['rubric-studio.html', 'upload.html', 'submissions.html', 'grades.html', 'reviews.html', 'evaluation.html'].includes(page)) link.href = href(page);
    });
    const questions = Number(exam.question_count || 0);
    const approved = Number(exam.approved_question_count || 0);
    const papers = Number(exam.submission_count || 0);
    const reviews = Number(exam.review_count || 0);
    const steps = [
      ['Set up', href('rubric-studio.html'), questions ? `${approved}/${questions} rubrics` : assessmentContext.ready ? 'Checks passed' : 'Add questions'],
      ['Upload', href('upload.html'), papers ? `${papers} paper${papers === 1 ? '' : 's'}` : 'No papers yet'],
      ['Extraction', href('submissions.html'), 'Check mappings'],
      ['Grade & review', href('reviews.html'), reviews ? `${reviews} to review` : 'Open queue'],
      ['Export', href('grades.html'), 'Check eligibility'],
    ];
    flow.innerHTML = steps.map(([label, url, detail], index) => `<a href="${url}" ${index === 1 && !assessmentContext.ready ? 'data-locked="true" title="Finish assessment setup before uploading"' : ''}><strong>${escapeHTML(label)}</strong><span>${escapeHTML(detail)}</span></a>`).join('');
    const nextPage = !assessmentContext.ready ? 'rubric-studio.html' : !papers ? 'upload.html' : reviews ? 'reviews.html' : 'grades.html';
    next.href = href(nextPage);
    next.firstChild.textContent = !assessmentContext.ready ? 'Finish setup ' : !papers ? 'Upload papers ' : reviews ? 'Review grades ' : 'Open grades ';
  }

  async function initializeAssessmentContext(user) {
    try {
      const exams = await window.MisraAPI.exams();
      const storageKey = `misra-current-assessment:${user.id}`;
      let stored = null;
      try { stored = localStorage.getItem(storageKey); } catch (_) {}
      const requested = getParam('exam_id');
      const selectedId = [requested, stored, exams[0]?.id].find((id) => exams.some((exam) => exam.id === id));
      assessmentContext = { exams, selectedId, storageKey, ready: false };
      if (selectedId) {
        rememberAssessment(selectedId);
        const select = shell.querySelector('[data-assessment-select]');
        select.innerHTML = exams.map((exam) => `<option value="${escapeHTML(exam.id)}">${escapeHTML([exam.course_code, exam.title].filter(Boolean).join(' · '))}</option>`).join('');
        select.value = selectedId;
        select.addEventListener('change', () => {
          const target = select.value;
          const destination = ['rubric', 'upload', 'submissions', 'grades', 'review', 'evaluation'].includes(activePage)
            ? window.location.pathname.split('/').pop() : 'assessments.html';
          window.location.assign(`${destination}?exam_id=${encodeURIComponent(target)}`);
        });
        document.addEventListener('change', (event) => {
          if (event.target.matches('#rubric-exam, #upload-exam, #submission-exam, #grades-exam, #review-exam, #evaluation-exam')) rememberAssessment(event.target.value);
        });
        window.addEventListener('misra:assessment-readiness', (event) => {
          if (event.detail?.examId !== assessmentContext?.selectedId) return;
          assessmentContext.ready = Boolean(event.detail.ready);
          assessmentContext.readinessChecked = true;
          const exam = assessmentContext.exams.find((item) => item.id === event.detail.examId);
          if (exam && Number.isFinite(Number(event.detail.questionCount))) exam.question_count = Number(event.detail.questionCount);
          if (exam && Number.isFinite(Number(event.detail.approvedCount))) exam.approved_question_count = Number(event.detail.approvedCount);
          renderAssessmentContext();
        });
        renderAssessmentContext();
      }
      resolveAssessmentReady({ exams, selectedId });
    } catch (error) { resolveAssessmentReady({ exams: [], selectedId: null, error }); }
  }

  function initializeJobCenter(user) {
    const center = shell.querySelector('[data-job-center]');
    const list = shell.querySelector('[data-job-list]');
    const title = shell.querySelector('[data-job-center-title]');
    const copy = shell.querySelector('[data-job-center-copy]');
    const toggle = shell.querySelector('[data-job-toggle]');
    const dismissedKey = `misra-dismissed-jobs:${user.id}`;
    const collapsedKey = `misra-job-center-collapsed:${user.id}`;
    const activeStatuses = new Set(['queued', 'processing', 'retrying']);
    let timer = null;
    let loading = false;
    let initialized = false;
    let previousStatuses = new Map();

    function dismissedJobs() {
      try { return new Set(JSON.parse(localStorage.getItem(dismissedKey) || '[]')); }
      catch (_) { return new Set(); }
    }

    function dismiss(jobId) {
      const dismissed = dismissedJobs();
      dismissed.add(jobId);
      try { localStorage.setItem(dismissedKey, JSON.stringify([...dismissed].slice(-50))); } catch (_) {}
    }

    function destination(job) {
      if (job.job_type === 'exam_setup' && job.exam_id) return `rubric-studio.html?exam_id=${encodeURIComponent(job.exam_id)}`;
      if (job.job_type === 'ocr_batch' && job.exam_id) return `submissions.html?exam_id=${encodeURIComponent(job.exam_id)}`;
      if (job.job_type === 'ocr_submission' && job.submission_id) return `submission.html?id=${encodeURIComponent(job.submission_id)}`;
      if (job.job_type === 'grade_submission' && job.submission_id) return `grade-results.html?id=${encodeURIComponent(job.submission_id)}`;
      return job.exam_id ? `submissions.html?exam_id=${encodeURIComponent(job.exam_id)}` : 'admin-operations.html';
    }

    function jobLabel(job) {
      const labels = {
        exam_setup: 'Reading assessment setup',
        ocr_batch: 'Extracting uploaded batch',
        ocr_submission: 'Extracting student paper',
        grade_submission: 'Grading submission',
      };
      return labels[job.job_type] || 'Background task';
    }

    function statusLabel(job) {
      if (Number(job.batch_failed_count || 0) > 0) return 'Completed with errors';
      if (job.status === 'completed') return 'Completed';
      if (job.status === 'failed') return 'Needs attention';
      if (job.status === 'retrying') return 'Retrying';
      if (job.status === 'processing') return 'Processing';
      return 'Queued';
    }

    function render(response) {
      const dismissed = dismissedJobs();
      const jobs = (response.items || []).filter((job) => activeStatuses.has(job.status) || !dismissed.has(job.id));
      const activeCount = jobs.filter((job) => activeStatuses.has(job.status)).length;
      center.hidden = jobs.length === 0;
      if (!jobs.length) {
        list.innerHTML = '';
        return;
      }

      title.textContent = activeCount
        ? `${activeCount} background ${activeCount === 1 ? 'task' : 'tasks'} in progress`
        : 'Background activity finished';
      copy.textContent = activeCount
        ? 'You can move between pages. MISRA will keep working and preserve progress.'
        : 'Review the completed work or dismiss this notice.';
      center.dataset.state = jobs.some((job) => job.status === 'failed' || Number(job.batch_failed_count || 0) > 0) ? 'attention' : activeCount ? 'active' : 'complete';
      list.innerHTML = jobs.map((job) => {
        const percent = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
        const isActive = activeStatuses.has(job.status);
        const assessment = [job.course_code, job.exam_title].filter(Boolean).join(' · ') || 'Assessment';
        const batchFailed = Number(job.batch_failed_count || 0);
        const batchCompleted = Number(job.batch_completed_count || 0);
        const message = batchFailed
          ? `${batchCompleted} extracted successfully; ${batchFailed} failed. Review the batch before retrying failed papers.`
          : job.status === 'failed'
          ? (job.error_message || 'The worker could not finish this task.')
          : (job.progress_message || (job.status === 'completed' ? 'Work completed successfully.' : 'Waiting for worker progress.'));
        return `<article class="workspace-job-row" data-job-status="${escapeHTML(job.status)}"${batchFailed ? ' data-batch-errors="true"' : ''}>
          <div class="workspace-job-main">
            <div class="workspace-job-line"><strong>${escapeHTML(jobLabel(job))}</strong><span>${escapeHTML(statusLabel(job))}</span></div>
            <small class="workspace-job-assessment">${escapeHTML(assessment)}</small>
            <p>${escapeHTML(message)}</p>
            ${isActive ? `<div class="workspace-job-progress" role="progressbar" aria-label="${escapeHTML(jobLabel(job))} progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span style="width:${percent}%"></span></div>` : ''}
          </div>
          <div class="workspace-job-actions">
            ${batchFailed && job.batch_id ? `<button type="button" data-global-retry-batch="${escapeHTML(job.batch_id)}">Retry failed papers</button>` : job.status === 'failed' ? `<button type="button" data-global-retry-job="${escapeHTML(job.id)}">Retry</button>` : ''}
            <a href="${destination(job)}">${job.status === 'completed' ? 'Review' : 'Open'}</a>
            ${isActive ? '' : `<button type="button" data-dismiss-job="${escapeHTML(job.id)}" aria-label="Dismiss ${escapeHTML(jobLabel(job))}">Dismiss</button>`}
          </div>
        </article>`;
      }).join('');

      if (initialized) {
        jobs.forEach((job) => {
          const prior = previousStatuses.get(job.id);
          if (prior && prior !== job.status && job.status === 'completed') window.showToast(`${jobLabel(job)} completed.`, 'success');
          if (prior && prior !== job.status && job.status === 'failed') window.showToast(`${jobLabel(job)} needs attention.`, 'error');
        });
      }
      previousStatuses = new Map(jobs.map((job) => [job.id, job.status]));
      initialized = true;
    }

    function schedule(activeCount) {
      window.clearTimeout(timer);
      const delay = document.hidden ? 20000 : activeCount ? 4000 : 15000;
      timer = window.setTimeout(refresh, delay);
    }

    async function refresh() {
      if (loading) return;
      loading = true;
      try {
        const response = await window.MisraAPI.workspaceJobs();
        render(response);
        schedule(Number(response.active_count || 0));
      } catch (error) {
        if (!center.hidden) {
          copy.textContent = 'Status could not refresh. Your background worker may still be running.';
          center.dataset.state = 'attention';
        }
        schedule(0);
      } finally {
        loading = false;
      }
    }

    const initiallyCollapsed = (() => {
      try { return localStorage.getItem(collapsedKey) === 'true'; } catch (_) { return false; }
    })();
    center.classList.toggle('is-collapsed', initiallyCollapsed);
    toggle.setAttribute('aria-expanded', String(!initiallyCollapsed));
    toggle.textContent = initiallyCollapsed ? 'Show details' : 'Hide details';
    toggle.addEventListener('click', () => {
      const collapsed = center.classList.toggle('is-collapsed');
      toggle.setAttribute('aria-expanded', String(!collapsed));
      toggle.textContent = collapsed ? 'Show details' : 'Hide details';
      try { localStorage.setItem(collapsedKey, String(collapsed)); } catch (_) {}
    });
    center.addEventListener('click', async (event) => {
      const dismissButton = event.target.closest('[data-dismiss-job]');
      if (dismissButton) {
        dismiss(dismissButton.dataset.dismissJob);
        refresh();
        return;
      }
      const retryButton = event.target.closest('[data-global-retry-job]');
      const retryBatchButton = event.target.closest('[data-global-retry-batch]');
      if (!retryButton && !retryBatchButton) return;
      const actionButton = retryBatchButton || retryButton;
      actionButton.disabled = true;
      actionButton.textContent = 'Queueing…';
      if (retryBatchButton) {
        try {
          const response = await window.MisraAPI.retryBatch(retryBatchButton.dataset.globalRetryBatch);
          window.showToast(response.retry_count ? `${response.retry_count} failed papers queued again.` : 'No failed papers need retrying.', response.retry_count ? 'success' : 'info');
          window.dispatchEvent(new CustomEvent('misra:job-started', { detail: { jobId: response.job?.id } }));
          refresh();
        } catch (error) {
          actionButton.disabled = false;
          actionButton.textContent = 'Retry failed papers';
          window.showToast(error.message || 'Could not retry this batch.', 'error');
        }
        return;
      }
      try {
        await window.MisraAPI.retryJob(retryButton.dataset.globalRetryJob);
        window.showToast('Retry queued.', 'success');
        refresh();
      } catch (error) {
        actionButton.disabled = false;
        actionButton.textContent = 'Retry';
        window.showToast(error.message || 'Could not retry this task.', 'error');
      }
    });
    window.addEventListener('misra:job-started', refresh);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) refresh();
    });
    refresh();
  }

  window.MisraAPI.currentUser().then((user) => {
    if (user.must_change_password && activePage !== 'settings') {
      resolveAssessmentReady({ exams: [], selectedId: null });
      window.location.replace('account.html?required=1');
      return;
    }
    if (user.role === 'admin') {
      shell.querySelectorAll('[data-admin-only]').forEach((link) => { link.hidden = false; });
    }
    initializeJobCenter(user);
    initializeAssessmentContext(user);
    userPanel.innerHTML = `<strong>${escapeHTML(user.full_name || user.email)}</strong><br><span>${escapeHTML(user.email)}</span><button class="workspace-signout" type="button" data-signout>Sign out</button>`;
    userPanel.querySelector('[data-signout]').addEventListener('click', async () => {
      const button = userPanel.querySelector('[data-signout]');
      button.disabled = true;
      button.textContent = 'Signing out…';
      try {
        await window.MisraAPI.logout();
        try {
          localStorage.removeItem(`misra-dismissed-jobs:${user.id}`);
          localStorage.removeItem(`misra-job-center-collapsed:${user.id}`);
          localStorage.removeItem(`misra-current-assessment:${user.id}`);
        } catch (_) {}
        window.location.replace('login.html?v=2');
      } catch (error) {
        button.disabled = false;
        button.textContent = 'Sign out';
        window.showToast(error.message || 'Could not sign out. Try again.', 'error');
      }
    });
  }).catch((error) => {
    resolveAssessmentReady({ exams: [], selectedId: null });
    if (error.status === 401) return;
    userPanel.innerHTML = '<strong>Access unavailable</strong><br><span>Your account cannot open this instructor workspace.</span><button class="workspace-signout" type="button" data-return-login>Return to sign in</button>';
    userPanel.querySelector('[data-return-login]').addEventListener('click', async () => {
      try { await window.MisraAPI.logout(); } catch (_) {}
      window.location.replace('login.html?v=2');
    });
  });
  window.MisraAPI.health().then((health) => {
    const queueOnline = health.queue !== 'unavailable';
    apiStatus.dataset.state = queueOnline ? 'online' : 'degraded';
    apiStatus.lastElementChild.textContent = queueOnline
      ? (health.model ? `Engine online · ${health.model}` : 'Engine online')
      : 'Engine online · worker queue offline';
  }).catch(() => {
    apiStatus.dataset.state = 'offline';
    apiStatus.lastElementChild.textContent = 'Engine offline';
  });

  window.MisraUI = { icons, escapeHTML, formatDate, badge, emptyState, errorState, getParam, identityState, reveal, assessmentReady, rememberAssessment };
})();
