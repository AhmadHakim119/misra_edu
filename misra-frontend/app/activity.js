(function () {
  'use strict';
  const scope=MisraWorkspace.page;
  const {$,esc,link,params,ready}=MisraApp;
  const host=$('activity-host'), error=$('activity-error');
  const jobStatus=MisraJobStatus;
  let rows=[], request=0, timer, pending=false;

  function render() {
    const activePapers=new Set(rows.filter(job=>job.job_type==='grade_submission' && jobStatus.isActive(job))
      .map(job=>job.submission_id));
    const seenPapers=new Set();
    host.innerHTML=rows.map(job=>{
      const active=jobStatus.isActive(job), grading=job.job_type==='grade_submission';
      const gradingActive=grading && activePapers.has(job.submission_id);
      const older=grading && seenPapers.has(job.submission_id);
      if(grading)seenPapers.add(job.submission_id);
      const canRetry=['failed','stopped'].includes(job.status) && !gradingActive && !older && !jobStatus.needsVision(job);
      const paper=job.submission_id ? `<a class="button" href="${link(job.job_type.startsWith('ocr')?'extraction':'grading',{exam_id:job.exam_id,submission_id:job.submission_id})}">Open paper</a>` : '';
      const action=grading && active && job.status!=='stopping'
        ? `<button class="stop-grading" data-stop-job="${esc(job.id)}" type="button">Stop grading</button>`
        : canRetry ? `<button data-retry-job="${esc(job.id)}" type="button">${job.status==='stopped'?'Resume grading':'Retry safely'}</button>` : '';
      return `<article class="record-row"><div class="activity-job"><h3><span data-i18n>${esc(jobStatus.task(job))}</span> · <span data-i18n>${esc(jobStatus.title(job))}</span></h3><p data-i18n>${esc(jobStatus.message(job))}</p>${jobStatus.details(job,esc)}${active?jobStatus.progress(job):''}</div><div class="inline-actions">${paper}${action}</div></article>`;
    }).join('')||'<p data-i18n>No recent processing jobs.</p>';
  }

  function schedule() {
    scope.cancelTimer(timer);
    if(rows.some(jobStatus.isActive))timer=scope.later(load,5000);
  }

  async function load() {
    if(pending)return;
    const current=++request;
    try {
      const data=await MisraAPI.workspaceJobs(20);
      if(current!==request || scope.signal.aborted)return;
      if(!Array.isArray(data?.items))throw Error('Job response incomplete.');
      rows=data.items.filter(job=>!params.get('exam_id') || job.exam_id===params.get('exam_id'));
      render();error.textContent='';
    } catch(e) {
      if(current===request && !scope.signal.aborted)error.textContent=e.message+' Jobs may still be running; refresh to reconnect.';
    } finally { if(current===request)schedule(); }
  }

  host.addEventListener('click',async event=>{
    const button=event.target.closest('[data-stop-job],[data-retry-job]');
    if(!button || pending)return;
    const stop=button.dataset.stopJob;
    pending=true;++request;scope.cancelTimer(timer);
    try {
      if(stop && !await MisraWorkspace.confirm('Saved grades are kept. A hosted AI request may finish before the job stops.',
        {title:'Stop grading this paper?',action:'Stop grading'}))return;
      if(scope.signal.aborted)return;
      const id=stop||button.dataset.retryJob;
      button.disabled=true;error.textContent='';
      const updated=await (stop?MisraAPI.stopJob(id):MisraAPI.retryJob(id));
      if(scope.signal.aborted)return;
      if(updated?.id!==id)throw Error('The job action could not be confirmed. Refresh Activity.');
      const previous=rows.find(job=>job.id===id);
      rows=previous ? [{...previous,...updated}, ...rows.filter(job=>job.id!==id)] : rows;
      render();
      host.querySelector('a.button')?.focus({preventScroll:true});
    } catch(e) {
      if(!scope.signal.aborted)error.textContent=e.message;
    } finally {
      pending=false;button.disabled=false;schedule();
    }
  });
  scope.guard(()=>pending,()=>false);
  $('activity-refresh').addEventListener('click',load);
  ready.then(load).catch(e=>error.textContent=e.message);
})();
