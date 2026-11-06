(function(){
  'use strict';
  const {$,esc,number,link,ready}=MisraApp;
  let exams=null,papers=[],jobs=[],timer,loading=false,loadFailed=false;

  async function load(){
    if(loading)return;
    loading=true;
    loadFailed=false;
    clearTimeout(timer);
    const refresh=$('dashboard-refresh');
    refresh.disabled=true;
    if(!exams)render();
    try{
      const data=await Promise.all([MisraAPI.exams(),MisraAPI.submissions(),MisraAPI.workspaceJobs(20)]);
      if(!Array.isArray(data[0])||!Array.isArray(data[1])||!Array.isArray(data[2]?.items))throw Error('Dashboard data is incomplete. Refresh to retry.');
      [exams,papers]=data;
      jobs=data[2].items;
      $('dashboard-summary').innerHTML=[['Exams',exams.length],['Papers',papers.length],['Awaiting review',papers.filter(p=>p.grading_summary?.review_count>0).length],['Processing',data[2].active_count]].map(([label,value])=>`<div><dt>${label}</dt><dd>${number(value)}</dd></div>`).join('');
      $('dashboard-error').textContent='';
      render();
      activity();
      reviewPreview();
      if(jobs.some(j=>['queued','processing','retrying'].includes(j.status)))timer=setTimeout(load,6000);
    }catch{
      loadFailed=true;
      $('dashboard-error').textContent=exams?.length
        ? 'Could not refresh the dashboard. Showing the last loaded exams.'
        : 'Could not load the dashboard. Use Refresh to try again.';
      if(!exams)render();
    }finally{
      loading=false;
      refresh.disabled=false;
    }
  }
  let reviewRequest=0;
  async function reviewPreview(){
    let host=$('dashboard-review-concerns');if(!host){host=document.createElement('section');host.id='dashboard-review-concerns';host.className='native-panel';$('dashboard-summary').after(host);}
    const current=++reviewRequest;
    try{const rows=await MisraAPI.reviewQueue();if(current!==reviewRequest)return;if(!Array.isArray(rows))throw Error('Review concerns could not be loaded.');
      host.innerHTML=`<div class="section-heading"><h2>Review concerns</h2><a href="reviews.html">Open review queue</a></div>${rows.length?rows.slice(0,3).map(a=>{
        const paper=papers.find(p=>p.id===a.submission_id),items=a.review_explanation?.items||[];
        const item=items.find(i=>i.code==='deduction_on_uncertain_evidence')||items.find(i=>i.source==='rule_check'||i.criterion_id)||items.find(i=>i.source!=='uncalibrated_heuristic')||items[0];
        return `<article class="record-row"><div><h3>${esc(paper?.extracted_student_name||'Paper identity needs checking')} · ${number(a.score)} / ${number(a.max_score)}</h3><p><strong>${esc(item?.title||'Saved review request')}</strong></p><p dir="auto">${esc(item?.reason||a.feedback||'Inspect the original work and saved criterion decisions.')}</p>${item?.action?`<p>Check: ${esc(item.action)}</p>`:''}</div><a href="${link('grading',{exam_id:paper?.exam_id,submission_id:a.submission_id,question_id:a.question_id})}">Review evidence</a></article>`;
      }).join(''):`<p>No recorded review concerns. Unflagged proposals still require instructor judgment.</p>`}`;
    }catch(error){if(current===reviewRequest)host.textContent=error.message+' Open the review queue or refresh to retry.';}
  }
  function render(){
    const list=$('dashboard-exams');
    if(!exams){
      list.textContent=loadFailed?'':'Loading your exams…';
      return;
    }
    if(!exams.length){
      list.innerHTML='<div class="empty"><h3>Your next exam starts here</h3><p data-i18n>Create an exam, approve its marking guide, then upload handwritten papers.</p><a class="button primary" href="assessments.html?create=1">Create exam</a></div>';
      return;
    }
    const query=$('dashboard-search').value.trim().toLowerCase();
    const shown=exams.filter(exam=>[exam.title,exam.course_code,exam.course_title]
      .some(value=>String(value??'').toLowerCase().includes(query)));
    if(!shown.length){
      list.innerHTML='<div class="empty"><h3>No exams match your search</h3><button type="button" id="dashboard-clear-search">Clear search</button></div>';
      return;
    }
    list.innerHTML=shown.map(exam=>{
      const rows=papers.filter(paper=>paper.exam_id===exam.id);
      const done=rows.filter(paper=>paper.grading_summary?.complete).length;
      const review=rows.filter(paper=>paper.grading_summary?.review_count>0).length;
      const course=exam.course_code||exam.course_title;
      return `<article class="record-row">
        <div><h3 dir="auto">${esc(exam.title)}</h3>
          <p>${course?`<bdi>${esc(course)}</bdi> · `:''}${number(rows.length)} <span data-i18n>papers</span> · ${number(done)} <span data-i18n>graded</span> · ${number(review)} <span data-i18n>awaiting review</span></p>
          ${rows.length?`<progress value="${done}" max="${rows.length}" aria-label="${esc(exam.title)} graded papers"></progress>`:''}
        </div>
        <a class="button primary" href="${link('grading',{exam_id:exam.id})}">Open exam</a>
      </article>`;
    }).join('');
  }
  function activity(){$('dashboard-activity').innerHTML=jobs.length?jobs.slice(0,8).map(j=>`<div class="record-row"><div><strong data-i18n>${esc(({ocr_submission:'Reading handwriting',grade_submission:'Proposing grades',exam_setup_extraction:'Reading exam setup',material_ingestion:'Reading course material',source_question_drafts:'Drafting questions'})[j.job_type]||'Processing')}</strong><p data-i18n>${esc(MisraJobStatus.message(j))}</p></div><span data-i18n>${esc(MisraJobStatus.title(j))}</span></div>`).join(''):'<p>No recent processing jobs.</p>';}
  window.addEventListener('misra:language',()=>{render();activity();});
  $('dashboard-search').addEventListener('input',render);$('dashboard-refresh').addEventListener('click',load);
  $('dashboard-exams').addEventListener('click',event=>{
    if(event.target.id!=='dashboard-clear-search')return;
    const search=$('dashboard-search');
    search.value='';
    render();
    search.focus();
  });
  ready.then(load).catch(error=>{
    loadFailed=true;
    $('dashboard-error').textContent=error.message;
    render();
  });
  ready.then(async user=>{
    if(user.must_change_password)return;
    const versions=await MisraAPI.instructorPreferenceVersions();
    if(!Array.isArray(versions))return;
    if(versions.some(v=>v.status==='approved')){
      const settings=MisraMarkingProfile.validate(await MisraAPI.accountSettings());
      if(settings.survey_completed){const done=document.createElement('section');done.id='marking-survey-completed';done.innerHTML=MisraMarkingProfile.completion(settings)+'<a href="account.html#marking-settings">Marking preferences in Settings</a>';$('dashboard-summary').before(done);MisraLocale.apply();}return;
    }
    if(sessionStorage.getItem(`misra-survey-later:${user.id}`)==='1')return;
    const panel=document.createElement('section');panel.className='native-panel';panel.id='marking-survey-invitation';
    panel.innerHTML='<h2>Set your marking preferences</h2><p data-i18n>Answer 12 grading scenarios so MISRA can suggest the marking rules you normally use.</p><div class="inline-actions"><a class="button primary" href="marking-survey.html">Start marking survey</a><button type="button" id="survey-later">Do this later</button></div>';
    $('dashboard-summary').before(panel);$('survey-later').addEventListener('click',()=>{sessionStorage.setItem(`misra-survey-later:${user.id}`,'1');panel.remove();});MisraLocale.apply();
  }).catch(()=>{});
})();
