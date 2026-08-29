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
    ['account', 'Account', 'account.html'],
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

  function errorState(message) {
    return `<div class="error-state" role="alert"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 17h.01"/></svg><span>${escapeHTML(message)}</span></div>`;
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
          <div class="workspace-topbar-title"><strong>${escapeHTML(activePageTitle)}</strong><span>No simulated records</span></div>
        </div>
        <div class="workspace-topbar-actions">
          <span class="api-status" data-api-status data-state="checking"><span class="api-status-dot"></span><span>Checking engine</span></span>
          <a class="btn btn-secondary" href="../index.html" style="padding:8px 14px;font-size:12.5px">Public site</a>
        </div>
      </header>
    </div>`;
  document.body.prepend(shell);
  shell.querySelector('.workspace-main').appendChild(content);

  const openButton = shell.querySelector('[data-open-nav]');
  const closeButton = shell.querySelector('[data-close-nav]');
  function setNav(open) {
    shell.classList.toggle('is-nav-open', open);
    openButton.setAttribute('aria-expanded', String(open));
    document.body.style.overflow = open ? 'hidden' : '';
  }
  openButton.addEventListener('click', () => setNav(!shell.classList.contains('is-nav-open')));
  closeButton.addEventListener('click', () => setNav(false));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') setNav(false); });

  const apiStatus = shell.querySelector('[data-api-status]');
  const userPanel = shell.querySelector('[data-user-panel]');
  window.MisraAPI.currentUser().then((user) => {
    if (user.must_change_password && activePage !== 'account') {
      window.location.replace('account.html?required=1');
      return;
    }
    if (user.role === 'admin') {
      shell.querySelectorAll('[data-admin-only]').forEach((link) => { link.hidden = false; });
    }
    userPanel.innerHTML = `<strong>${escapeHTML(user.full_name || user.email)}</strong><br><span>${escapeHTML(user.email)}</span><button class="workspace-signout" type="button" data-signout>Sign out</button>`;
    userPanel.querySelector('[data-signout]').addEventListener('click', async () => {
      const button = userPanel.querySelector('[data-signout]');
      button.disabled = true;
      button.textContent = 'Signing out…';
      try {
        await window.MisraAPI.logout();
        window.location.replace('login.html?v=2');
      } catch (error) {
        button.disabled = false;
        button.textContent = 'Sign out';
        window.showToast(error.message || 'Could not sign out. Try again.', 'error');
      }
    });
  }).catch((error) => {
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

  window.MisraUI = { icons, escapeHTML, formatDate, badge, emptyState, errorState, getParam, identityState, reveal };
})();
