(function(){
  'use strict';const {$,esc,number,link,ready}=MisraApp;let exams=[],papers=[],jobs=[],timer;
  async function load(){try{const data=await Promise.all([MisraAPI.exams(),MisraAPI.submissions(),MisraAPI.workspaceJobs(20)]);
    if(!Array.isArray(data[0])||!Array.isArray(data[1])||!Array.isArray(data[2]?.items))throw Error('Dashboard data is incomplete. Refresh to retry.');
    [exams,papers]=data;jobs=data[2].items;
    $('dashboard-summary').innerHTML=[['Exams',exams.length],['Papers',papers.length],['Awaiting review',papers.filter(p=>p.grading_summary?.review_count>0).length],['Processing',data[2].active_count]].map(([label,value])=>`<div><dt>${label}</dt><dd>${number(value)}</dd></div>`).join('');render();activity();
    $('dashboard-error').textContent='';reviewPreview();clearTimeout(timer);if(jobs.some(j=>['queued','processing','retrying'].includes(j.status)))timer=setTimeout(load,6000);
  }catch(e){$('dashboard-error').textContent=e.message;}}
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
  function render(){const query=$('dashboard-search').value.toLowerCase();const shown=exams.filter(e=>`${e.title} ${e.course_code||''}`.toLowerCase().includes(query));
    $('dashboard-exams').innerHTML=shown.length?shown.map(e=>{const rows=papers.filter(p=>p.exam_id===e.id),done=rows.filter(p=>p.grading_summary?.complete).length,review=rows.filter(p=>p.grading_summary?.review_count>0).length;
      return `<article class="record-row"><div><h3 dir="auto">${esc(e.title)}</h3><p><bdi>${esc(e.course_code||e.course_title||'')}</bdi> · ${number(rows.length)} <span data-i18n>papers</span> · ${number(done)} <span data-i18n>graded</span> · ${number(review)} <span data-i18n>awaiting review</span></p>${rows.length?`<progress value="${done}" max="${rows.length}" aria-label="${esc(e.title)} graded papers"></progress>`:''}</div><div class="inline-actions"><a class="button primary" href="${link(rows.length?'grading':'setup',{exam_id:e.id})}">${rows.length?'View & grade':'Prepare rubric'}</a><a href="${link('upload',{exam_id:e.id})}">Upload papers</a><a href="${link('results',{exam_id:e.id})}">Results</a></div></article>`;}).join(''):'<div class="empty"><h2>Your next exam starts here</h2><p>Create an exam, approve its marking guide, then upload handwritten papers.</p><a class="button primary" href="assessments.html?create=1">Create exam</a></div>';}
  function activity(){$('dashboard-activity').innerHTML=jobs.length?jobs.slice(0,8).map(j=>`<div class="record-row"><div><strong data-i18n>${esc(({ocr_submission:'Reading handwriting',grade_submission:'Proposing grades',exam_setup_extraction:'Reading exam setup',material_ingestion:'Reading course material',source_question_drafts:'Drafting questions'})[j.job_type]||'Processing')}</strong><p data-i18n>${esc(MisraJobStatus.message(j))}</p></div><span data-i18n>${esc(MisraJobStatus.title(j))}</span></div>`).join(''):'<p>No recent processing jobs.</p>';}
  window.addEventListener('misra:language',()=>{render();activity();});
  $('dashboard-search').addEventListener('input',render);$('dashboard-refresh').addEventListener('click',load);
  ready.then(load).catch(e=>$('dashboard-error').textContent=e.message);
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
