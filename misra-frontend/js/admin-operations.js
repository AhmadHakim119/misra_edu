(function () {
  'use strict';

  const escapeHTML = window.MisraUI.escapeHTML;
  const tabs = [...document.querySelectorAll('[data-operations-tab]')];
  const auditPanel = document.querySelector('[data-operations-panel="audit"]');
  const jobsPanel = document.querySelector('[data-operations-panel="jobs"]');
  const systemPanel = document.querySelector('[data-operations-panel="system"]');
  const auditList = document.getElementById('audit-list');
  const auditCopy = document.getElementById('audit-copy');
  const jobsList = document.getElementById('jobs-list');
  const jobsCopy = document.getElementById('jobs-copy');
  const healthSummary = document.getElementById('health-summary');
  const retentionCopy = document.getElementById('retention-copy');
  const auditFilters = document.getElementById('audit-filters');
  const jobFilters = document.getElementById('job-filters');
  const exportLink = document.getElementById('audit-export');
  const refreshButton = document.getElementById('operations-refresh');
  const recoverButton = document.getElementById('recover-jobs');
  let activeSection = 'activity';

  const jobLabels = {
    ocr_submission: 'Paper extraction',
    ocr_batch: 'Batch extraction',
    grade_submission: 'Submission grading',
  };

  function titleCase(value) {
    return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function dateTime(value) {
    if (!value) return 'Not recorded';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Not recorded';
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }

  function auditParams() {
    const values = Object.fromEntries(new FormData(auditFilters));
    const params = { category: activeSection, outcome: values.outcome, search: values.search.trim(), limit: 200 };
    if (values.date_from) params.date_from = `${values.date_from}T00:00:00`;
    if (values.date_to) params.date_to = `${values.date_to}T23:59:59`;
    return params;
  }

  function safeDetails(details) {
    const entries = Object.entries(details || {}).slice(0, 5);
    if (!entries.length) return '<span class="operations-muted">No additional details</span>';
    return entries.map(([key, value]) => `<span><b>${escapeHTML(titleCase(key))}</b> ${escapeHTML(Array.isArray(value) ? value.join(', ') : value)}</span>`).join('');
  }

  function eventTone(outcome) {
    return outcome === 'failure' ? 'danger' : outcome === 'warning' ? 'warning' : 'success';
  }

  async function loadAudit() {
    auditList.innerHTML = '<div class="loading-list card-pad"><div class="skel loading-row"></div><div class="skel loading-row"></div></div>';
    auditCopy.textContent = `Loading ${activeSection === 'security' ? 'security' : 'activity'} events…`;
    const params = auditParams();
    exportLink.href = window.MisraAPI.adminAuditCsvUrl(params);
    try {
      const response = await window.MisraAPI.adminAudit(params);
      auditCopy.textContent = `${response.total} recorded event${response.total === 1 ? '' : 's'} · retained for ${response.retention_days} days`;
      if (!response.items.length) {
        auditList.innerHTML = window.MisraUI.emptyState(
          activeSection === 'security' ? 'No security events match' : 'No activity matches',
          'Change the filters or return after more work has been completed.',
          window.MisraUI.icons.operations,
        );
        return;
      }
      auditList.innerHTML = `<div class="operations-list">${response.items.map((event) => `
        <article class="operations-row">
          <div class="operations-event"><span class="operations-time">${escapeHTML(dateTime(event.timestamp))}</span><strong>${escapeHTML(titleCase(event.action))}</strong><small>${escapeHTML(event.actor?.name || 'System')} · ${escapeHTML(titleCase(event.target.type))}${event.target.id ? ` · <code>${escapeHTML(event.target.id)}</code>` : ''}</small></div>
          <div class="operations-details">${safeDetails(event.details)}</div>
          <div class="operations-outcome">${window.MisraUI.badge(titleCase(event.outcome), eventTone(event.outcome))}</div>
        </article>`).join('')}</div>`;
      window.MisraUI.reveal(auditList.querySelectorAll('.operations-row'), { limit: 8 });
    } catch (error) {
      auditCopy.textContent = 'Audit history unavailable';
      auditList.innerHTML = window.MisraUI.errorState(error.message || 'Could not load audit events.');
    }
  }

  function jobTone(status) {
    if (status === 'completed') return 'success';
    if (status === 'failed') return 'danger';
    if (status === 'processing' || status === 'retrying') return 'warning';
    return 'draft';
  }

  function jobParams() {
    const values = Object.fromEntries(new FormData(jobFilters));
    return { status: values.status, job_type: values.job_type, limit: 200 };
  }

  async function loadJobs() {
    jobsList.innerHTML = '<div class="loading-list card-pad"><div class="skel loading-row"></div><div class="skel loading-row"></div></div>';
    jobsCopy.textContent = 'Loading processing history…';
    try {
      const jobs = await window.MisraAPI.adminJobs(jobParams());
      jobsCopy.textContent = `${jobs.length} recent job${jobs.length === 1 ? '' : 's'}`;
      if (!jobs.length) {
        jobsList.innerHTML = window.MisraUI.emptyState('No jobs match', 'Change the filters or upload a paper to start extraction.', window.MisraUI.icons.operations);
        return;
      }
      jobsList.innerHTML = `<div class="operations-list">${jobs.map((job) => {
        const total = Number(job.progress_total || 0);
        const current = Number(job.progress_current || 0);
        const percent = total ? Math.min(100, Math.round((current / total) * 100)) : 0;
        return `<article class="operations-row operations-job" data-job-id="${escapeHTML(job.id)}">
          <div class="operations-event"><span class="operations-time">${escapeHTML(dateTime(job.created_at))}</span><strong>${escapeHTML(jobLabels[job.job_type] || titleCase(job.job_type))}</strong><small><code>${escapeHTML(job.id)}</code>${job.submission_id ? ` · Submission <code>${escapeHTML(job.submission_id)}</code>` : ''}</small></div>
          <div class="operations-progress"><div><span>${escapeHTML(job.progress_message || `${current} of ${total || '—'} complete`)}</span><strong>${percent}%</strong></div><div class="operations-progress-track"><span style="width:${percent}%"></span></div><small>Attempt ${Number(job.attempt_count || 0)} of ${Number(job.max_attempts || 0)}${job.duration_seconds != null ? ` · ${Number(job.duration_seconds).toFixed(1)}s` : ''}</small>${job.error_message ? `<p>${escapeHTML(job.error_message)}</p>` : ''}</div>
          <div class="operations-outcome">${window.MisraUI.badge(titleCase(job.status), jobTone(job.status))}${job.status === 'failed' ? '<button class="link-button" type="button" data-retry-job>Retry</button>' : ''}</div>
        </article>`;
      }).join('')}</div>`;
      window.MisraUI.reveal(jobsList.querySelectorAll('.operations-row'), { limit: 8 });
    } catch (error) {
      jobsCopy.textContent = 'Processing history unavailable';
      jobsList.innerHTML = window.MisraUI.errorState(error.message || 'Could not load background jobs.');
    }
  }

  function healthTone(status) {
    return status === 'online' ? 'online' : status === 'degraded' ? 'degraded' : 'offline';
  }

  async function loadHealth() {
    healthSummary.innerHTML = '<div class="workspace-card card-pad"><div class="skel loading-row"></div></div>';
    try {
      const health = await window.MisraAPI.adminHealth();
      const order = ['api', 'database', 'redis', 'worker', 'storage'];
      healthSummary.innerHTML = order.map((key) => {
        const service = health.services[key] || { status: 'offline', detail: 'No health result returned' };
        const extra = key === 'worker' && service.queue_depth
          ? ` · ${Number(service.queue_depth.ocr || 0) + Number(service.queue_depth.grading || 0)} queued`
          : '';
        return `<article class="workspace-card health-service" data-state="${healthTone(service.status)}"><div class="health-service-head"><span class="api-status-dot"></span><strong>${escapeHTML(titleCase(key))}</strong>${window.MisraUI.badge(titleCase(service.status), service.status === 'online' ? 'success' : 'danger')}</div><p>${escapeHTML(service.detail || '')}${escapeHTML(extra)}</p></article>`;
      }).join('');
      retentionCopy.textContent = `Audit records are automatically retained for ${health.retention_days} days. Last checked ${dateTime(health.checked_at)}.`;
      window.MisraUI.reveal(healthSummary.querySelectorAll('.health-service'), { limit: 5 });
    } catch (error) {
      healthSummary.innerHTML = window.MisraUI.errorState(error.message || 'Could not check system health.');
      retentionCopy.textContent = '';
    }
  }

  async function selectSection(section) {
    activeSection = section;
    tabs.forEach((tab) => tab.setAttribute('aria-pressed', String(tab.dataset.operationsTab === section)));
    auditPanel.hidden = !['activity', 'security'].includes(section);
    jobsPanel.hidden = section !== 'background_jobs';
    systemPanel.hidden = section !== 'system';
    exportLink.hidden = !['activity', 'security'].includes(section);
    if (section === 'activity' || section === 'security') {
      document.getElementById('audit-title').textContent = section === 'security' ? 'Security events' : 'Institution activity';
      await loadAudit();
    } else if (section === 'background_jobs') {
      await loadJobs();
    } else {
      await loadHealth();
    }
  }

  tabs.forEach((tab) => tab.addEventListener('click', () => selectSection(tab.dataset.operationsTab)));
  auditFilters.addEventListener('submit', (event) => { event.preventDefault(); loadAudit(); });
  jobFilters.addEventListener('submit', (event) => { event.preventDefault(); loadJobs(); });
  refreshButton.addEventListener('click', () => selectSection(activeSection));

  jobsList.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-retry-job]');
    const row = event.target.closest('[data-job-id]');
    if (!button || !row) return;
    button.disabled = true;
    button.textContent = 'Retrying…';
    try {
      await window.MisraAPI.retryJob(row.dataset.jobId);
      window.showToast('The failed job has been queued again.', 'success');
      await loadJobs();
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Retry';
      window.showToast(error.message || 'Could not retry this job.', 'error');
    }
  });

  recoverButton.addEventListener('click', async () => {
    recoverButton.disabled = true;
    recoverButton.textContent = 'Checking jobs…';
    try {
      const result = await window.MisraAPI.recoverOrphanedJobs();
      if (!result.queue_available || result.dispatch_failed) {
        window.showToast('Recovery found work but the Redis queue is unavailable. Check System health.', 'error');
      } else {
        window.showToast(
          result.requeued ? `${result.requeued} abandoned job${result.requeued === 1 ? '' : 's'} requeued.` : 'No abandoned jobs needed recovery.',
          'success',
        );
      }
      await loadJobs();
    } catch (error) {
      window.showToast(error.message || 'Could not recover abandoned jobs.', 'error');
    } finally {
      recoverButton.disabled = false;
      recoverButton.textContent = 'Recover abandoned work';
    }
  });

  async function start() {
    try {
      const user = await window.MisraAPI.currentUser();
      if (user.role !== 'admin') throw Object.assign(new Error('Administrator access is required to view operations.'), { status: 403 });
      await selectSection('activity');
    } catch (error) {
      auditPanel.innerHTML = window.MisraUI.errorState(error.message || 'Could not open admin operations.');
      tabs.forEach((tab) => { tab.disabled = true; });
      refreshButton.disabled = true;
      exportLink.hidden = true;
    }
  }

  start();
})();
