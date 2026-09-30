(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const examSelect = $('submission-exam'), readinessSelect = $('submission-readiness');
  const identitySelect = $('submission-identity'), search = $('paper-search');
  const result = $('submissions-result'), notice = $('paper-connection'), refreshButton = $('refresh-papers');
  const escape = MisraUI.escapeHTML;
  let submissions = [], examsById = {}, loaded = false, loading = false, pendingRefresh = false;
  let timer, fingerprint = '', pageNumber = 1, mutationPending = false, revision = 0, batchId = '';
  const pageSize = 20;

  function applyURL() {
    const params = new URLSearchParams(location.search);
    for (const [name, select] of [['status', readinessSelect], ['identity', identitySelect]]) {
      select.value = [...select.options].some((option) => option.value === params.get(name)) ? params.get(name) : 'all';
    }
    search.value = params.get('q') || '';
    examSelect.value = params.get('exam_id') || '';
    batchId = params.get('batch_id') || '';
  }
  function persist() {
    const url = new URL(location.href);
    for (const [name, value] of [['exam_id', examSelect.value], ['batch_id', batchId], ['status', readinessSelect.value], ['identity', identitySelect.value], ['q', search.value.trim()]]) {
      if (value && value !== 'all') url.searchParams.set(name, value); else url.searchParams.delete(name);
    }
    history.replaceState(null, '', url);
  }
  function render() {
    const scoped = submissions.filter((paper) => (!examSelect.value || paper.exam_id === examSelect.value) && (!batchId || paper.batch_id === batchId));
    $('paper-batch-scope').hidden = !batchId;
    const counts = MisraPaperFlow.counts(scoped);
    const query = search.value.trim().toLocaleLowerCase();
    const visible = scoped.filter((paper) => {
      const flow = MisraPaperFlow.state(paper), identity = MisraUI.identityState(paper), exam = examsById[paper.exam_id];
      const haystack = [identity.name, identity.number, exam?.title, exam?.course_code].join(' ').toLocaleLowerCase();
      const statusMatches = readinessSelect.value === 'all' || (readinessSelect.value === 'graded' ? flow.graded : flow.key === readinessSelect.value);
      const identityMatches = identitySelect.value === 'all' || (!flow.active && (identitySelect.value === 'complete') === identity.complete);
      return statusMatches && identityMatches && (!query || haystack.includes(query));
    });
    // Keep stage buttons stable so automatic refresh never steals keyboard focus.
    for (const button of $('paper-stages').querySelectorAll('[data-stage]')) {
      const key = button.dataset.stage;
      button.setAttribute('aria-pressed', String(readinessSelect.value === key));
      button.querySelector('strong').textContent = key === 'graded' ? counts.graded + counts.review : counts[key];
    }
    const pageCount = Math.max(1, Math.ceil(visible.length / pageSize));
    pageNumber = Math.min(pageNumber, pageCount);
    $('paper-count').textContent = visible.length + (visible.length === 1 ? ' paper' : ' papers') + (visible.length !== scoped.length ? ' of ' + scoped.length : '');
    $('paper-filter-summary').textContent = [examSelect.value ? examSelect.selectedOptions[0]?.textContent : 'All assessments', identitySelect.value === 'all' ? '' : identitySelect.selectedOptions[0].textContent, readinessSelect.value === 'review' ? 'Grade review needed' : ''].filter(Boolean).join(' · ');
    $('paper-identity-note').hidden = counts.identity === 0;
    $('paper-identity-note').textContent = counts.identity + (counts.identity === 1 ? ' paper needs' : ' papers need') + ' a name or student ID. Review identity before exporting.';
    $('papers-upload').href = 'upload.html' + (examSelect.value ? '?exam_id=' + encodeURIComponent(examSelect.value) : '');
    const pageItems = visible.slice((pageNumber - 1) * pageSize, pageNumber * pageSize);
    let html;
    if (!visible.length) {
      html = MisraUI.emptyState(scoped.length ? 'No papers match these filters' : batchId ? 'No papers visible in this batch yet' : 'No student papers yet', scoped.length ? 'Try another name, assessment or processing stage.' : batchId ? 'A queued batch may still be creating its submissions. Check background activity or refresh shortly.' : 'Upload student work after approving the assessment in Rubric Studio.', MisraUI.icons.submissions);
      html += scoped.length ? '<button class="btn btn-secondary" type="button" data-clear-filters>Clear filters</button>' : batchId ? '' : '<a class="btn btn-primary" href="' + $('papers-upload').getAttribute('href') + '">Upload student papers</a>';
    } else html = pageItems.map((paper) => {
      const flow = MisraPaperFlow.state(paper), identity = MisraUI.identityState(paper), exam = examsById[paper.exam_id];
      const name = identity.name || (flow.active ? 'Reading student identity…' : 'Student name missing');
      const mapping = paper.readiness;
      const job = flow.href.startsWith('grade-results') ? paper.latest_grading_job : paper.latest_ocr_job;
      const percent = Math.min(100, MisraPaperFlow.number(job?.progress_percent));
      const hasProgress = flow.active && Number(job?.progress_total) > 0;
      const retry = !flow.active && paper.latest_ocr_job?.status === 'failed';
      return `<article class="paper-item" data-paper-id="${escape(paper.id)}" data-state="${flow.key}">
        <div class="paper-icon" aria-hidden="true">${flow.graded ? MisraUI.icons.grades : MisraUI.icons.submissions}</div>
        <div class="paper-person"><h2><a href="${flow.href}" dir="auto">${escape(name)}</a></h2><p>${escape([identity.number, exam?.course_code, exam?.title].filter(Boolean).join(' · '))}</p>
          <div class="paper-meta"><span>${paper.page_count == null ? 'Page count pending' : MisraPaperFlow.number(paper.page_count) + ' pages'}</span><span>${escape(MisraUI.formatDate(paper.uploaded_at))}</span>${!flow.active && mapping ? '<span>' + MisraPaperFlow.number(mapping.mapped_answer_count) + '/' + MisraPaperFlow.number(mapping.expected_question_count) + ' answers mapped</span>' : ''}</div>
          ${!flow.active && identity.needsAttention ? '<a class="paper-identity-link" href="submission.html?id=' + encodeURIComponent(paper.id) + '">' + escape(identity.message) + ' Review identity</a>' : ''}
        </div>
        <div class="paper-status">${MisraUI.badge(flow.label, flow.tone)}<p>${escape(flow.detail)}</p>${hasProgress ? '<progress max="100" value="' + percent + '" aria-label="Processing progress for ' + escape(name) + '">' + percent + '%</progress>' : ''}</div>
        <div class="paper-actions"><a class="btn btn-secondary" href="${flow.href}">${escape(flow.action)}</a>${retry ? '<button class="link-button" type="button" data-retry-paper="' + escape(paper.id) + '">Retry extraction</button>' : ''}
          <button class="icon-button" type="button" data-delete-submission="${escape(paper.id)}" aria-label="Delete ${escape(name)} submission" ${flow.active ? 'disabled title="Wait for processing to finish before deleting"' : 'title="Delete submission"'}>${MisraUI.icons.trash}</button></div>
      </article>`;
    }).join('');
    if (fingerprint !== html) {
      const previousStates = new Map([...result.querySelectorAll('[data-paper-id]')].map((row) => [row.dataset.paperId, row.dataset.state]));
      const focused = result.contains(document.activeElement) ? document.activeElement : null;
      const focusKey = focused?.dataset.retryPaper || focused?.dataset.deleteSubmission;
      const focusAttr = focused?.dataset.retryPaper ? 'data-retry-paper' : 'data-delete-submission';
      const focusHref = focused?.getAttribute('href');
      result.innerHTML = html; fingerprint = html;
      if (focusKey) result.querySelector('[' + focusAttr + '="' + CSS.escape(focusKey) + '"]')?.focus();
      else if (focusHref) [...result.querySelectorAll('a')].find((a) => a.getAttribute('href') === focusHref)?.focus();
      if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
        const highlight = getComputedStyle(document.documentElement).getPropertyValue('--celadon-50').trim();
        result.querySelectorAll('[data-paper-id]').forEach((row) => {
          const previous = previousStates.get(row.dataset.paperId);
          if (previous && previous !== row.dataset.state) row.animate([{ backgroundColor: highlight }, { backgroundColor: 'transparent' }], { duration: 240, easing: 'ease-out' });
        });
      }
    }
    $('paper-pagination').hidden = pageCount <= 1;
    $('paper-page-label').textContent = 'Page ' + pageNumber + ' of ' + pageCount;
    $('paper-prev').disabled = pageNumber <= 1; $('paper-next').disabled = pageNumber >= pageCount;
  }
  function schedule() {
    clearTimeout(timer);
    if (!document.hidden) timer = setTimeout(() => load(), submissions.some((paper) => MisraPaperFlow.state(paper).active) ? 12000 : 60000);
  }
  async function load() {
    if (loading || mutationPending) { pendingRefresh = true; return; }
    loading = true; refreshButton.disabled = true;
    const requestRevision = revision;
    try {
      const [exams, items] = await Promise.all([loaded ? Promise.resolve(Object.values(examsById)) : MisraAPI.exams(), MisraAPI.submissions()]);
      if (revision !== requestRevision) { pendingRefresh = true; return; }
      if (!loaded) {
        examsById = Object.fromEntries(exams.map((exam) => [exam.id, exam]));
        examSelect.insertAdjacentHTML('beforeend', exams.map((exam) => '<option value="' + escape(exam.id) + '">' + escape([exam.course_code, exam.title].filter(Boolean).join(' · ')) + '</option>').join(''));
        applyURL();
      }
      submissions = items; loaded = true; notice.hidden = true;
      $('paper-sync').textContent = 'Updated ' + new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date()) + ' · refreshes automatically';
      render();
    } catch (error) {
      notice.hidden = false;
      notice.textContent = (loaded ? 'Showing the last loaded records. ' : '') + 'Could not refresh papers. ' + error.message + ' Use Refresh to try again. Background jobs may still be running.';
      if (!loaded) { result.innerHTML = ''; $('paper-count').textContent = 'Papers unavailable'; }
      $('paper-sync').textContent = 'Connection interrupted';
    } finally {
      loading = false; refreshButton.disabled = false; schedule();
      if (pendingRefresh && !mutationPending) { pendingRefresh = false; load(); }
    }
  }
  function changed() { pageNumber = 1; persist(); render(); }
  examSelect.addEventListener('change', () => { batchId = ''; changed(); });
  [readinessSelect, identitySelect].forEach((select) => select.addEventListener('change', changed));
  $('paper-clear-batch').addEventListener('click', () => { batchId = ''; changed(); });
  search.addEventListener('input', changed);
  $('paper-stages').addEventListener('click', (event) => {
    const button = event.target.closest('[data-stage]');
    if (button) { readinessSelect.value = button.dataset.stage; changed(); }
  });
  refreshButton.addEventListener('click', load);
  $('paper-identity-note').addEventListener('click', () => { identitySelect.value = 'attention'; readinessSelect.value = 'all'; changed(); });
  $('paper-prev').addEventListener('click', () => { pageNumber -= 1; render(); });
  $('paper-next').addEventListener('click', () => { pageNumber += 1; render(); });
  window.addEventListener('popstate', () => { applyURL(); pageNumber = 1; render(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); else clearTimeout(timer); });
  window.addEventListener('online', load);
  window.addEventListener('pagehide', () => clearTimeout(timer));
  result.addEventListener('click', async (event) => {
    if (event.target.closest('[data-clear-filters]')) { search.value = ''; readinessSelect.value = 'all'; identitySelect.value = 'all'; changed(); search.focus(); return; }
    const button = event.target.closest('[data-delete-submission], [data-retry-paper]');
    if (!button || button.disabled || mutationPending) return;
    const id = button.dataset.deleteSubmission || button.dataset.retryPaper;
    const item = submissions.find((paper) => paper.id === id);
    if (!item) return;
    const retrying = Boolean(button.dataset.retryPaper), name = MisraUI.identityState(item).displayName;
    if (!window.confirm(retrying ? 'Retry extraction for ' + name + '? This uses your configured OCR provider and may consume quota.' : 'Delete the submission for ' + name + '? This permanently removes the uploaded paper, OCR text, grades, review labels, and job history. This cannot be undone.')) return;
    mutationPending = true;
    revision += 1;
    result.querySelectorAll('[data-delete-submission], [data-retry-paper]').forEach((action) => { action.disabled = true; });
    try {
      if (retrying) {
        const retried = await MisraAPI.retryJob(item.latest_ocr_job.id);
        item.latest_ocr_job = { ...item.latest_ocr_job, ...retried };
        window.showToast('Extraction retry requested. Progress will appear here.', 'success');
      } else {
        const deletion = await MisraAPI.deleteSubmission(id);
        submissions = submissions.filter((paper) => paper.id !== id); render();
        window.showToast(deletion.file_removed ? 'Submission and uploaded paper deleted.' : 'Records deleted, but the stored paper could not be removed. Check storage permissions.', deletion.file_removed ? 'success' : 'warning');
      }
    } catch (error) { window.showToast(error.message, 'error'); }
    finally {
      mutationPending = false;
      fingerprint = '';
      render();
      await load();
    }
  });
  load();
})();
