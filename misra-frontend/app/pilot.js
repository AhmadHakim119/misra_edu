(function(){
  'use strict';
  const {$,esc,number,ready,params}=MisraApp;
  let studyId=params.get('study_id'),study=null,paper=null,request=0,loading=false,imageUrl=null;
  const range=total=>total?.point_proposal!=null?`${number(total.point_proposal)} / ${number(total.max_score)}`:total?`${number(total.lower)}–${number(total.upper)} / ${number(total.max_score)} · unresolved range`:'Unresolved';
  const reason=code=>code.replaceAll('_',' ');
  function metrics(){
    const rows=study.reference_comparison||[];if(!rows.length)return;
    $('pilot-metrics').hidden=false;
    $('pilot-metrics').innerHTML=`<details><summary>How useful were the flags in the checked examples?</summary><p>Reused, user-adjudicated answer comparisons. These are answer-level observations, not a measured error rate for all pilot papers. Error counts differ between models.</p><div class="pilot-metrics-table"><table class="data-table"><thead><tr><th>Model / check</th><th>Grade matches</th><th>Errors caught</th><th>Errors missed</th><th>Matching grades flagged</th><th>Unavailable</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.label)}</td><td>${r.exact_count}/${r.scheduled_count}</td><td>${r.disagreements_flagged}/${r.disagreement_count}</td><td>${r.disagreement_count-r.disagreements_flagged}</td><td>${r.review_count_among_scored-r.disagreements_flagged}</td><td>${r.unavailable_count}</td></tr>`).join('')}</tbody></table></div><p>A matching grade can still need evidence review. Unavailable responses require attention and are not zero grades. Different verification procedures limit comparisons of review workload.</p></details>`;
  }
  function selectPaperOptions(wanted){
    const scope=study.papers.filter(p=>!$('pilot-year').value||p.exam_version===$('pilot-year').value);
    const rows=scope.filter(p=>!$('pilot-flagged').checked||p.review.needs_review);
    $('pilot-paper').innerHTML=rows.map(p=>`<option value="${esc(p.paper_id)}">${esc(p.label)} · ${p.review.needs_review?'needs review':'no recorded issue'}</option>`).join('');
    $('pilot-paper').disabled=!rows.length;
    if(rows.some(p=>p.paper_id===wanted))$('pilot-paper').value=wanted;
    const slots=scope.every(p=>Number.isInteger(p.answer_count))?scope.reduce((sum,p)=>sum+p.answer_count,0):'Unknown';
    const stats=[['Saved papers',scope.length],['Answer slots',slots],['Flagged papers',scope.filter(p=>p.review.needs_review).length]];
    $('pilot-status').innerHTML=stats.map(([label,value])=>'<span data-i18n>'+label+'</span> <strong>'+esc(value)+'</strong>').join(' · ');
    if(!rows.length){++request;paper=null;$('pilot-paper-summary').textContent='No papers match these filters.';$('pilot-answer-detail').textContent='';$('pilot-answer').innerHTML='';$('pilot-answer').disabled=true;$('pilot-image').hidden=true;$('pilot-page').disabled=true;$('pilot-page-link').hidden=true;return;}
    loadPaper($('pilot-paper').value);
  }
  async function load(){
    $('pilot-error').textContent='';loading=true;$('pilot-refresh').disabled=true;
    try{
      const catalog=await MisraAPI.pilotStudies();const entry=(catalog.items||[]).find(r=>r.study_id===studyId)||(catalog.items||[])[0];
      if(!entry){$('pilot-status').textContent='No saved pilot imported for this institution.';return;}
      studyId=entry.study_id;study=await MisraAPI.pilotStudy(studyId);if(!Array.isArray(study.papers))throw Error('Saved paper list is incomplete.');
      const requestedExam=params.get('exam_id');const requested=study.papers.find(p=>p.exam_id===requestedExam);
      if(requestedExam&&!requested)throw Error('This saved exam is not part of the selected study.');
      const years=[...new Set(study.papers.map(p=>p.exam_version))];const year=$('pilot-year').value||requested?.exam_version||'';$('pilot-year').innerHTML='<option value="">All exams</option>'+years.map(y=>`<option>${esc(y)}</option>`).join('');$('pilot-year').value=year;
      metrics();selectPaperOptions(paper?.paper_id||params.get('paper_id'));
    }catch(e){$('pilot-error').textContent=e.message+' Refresh to retry. Previously loaded data is retained.';}
    finally{loading=false;$('pilot-refresh').disabled=false;}
  }
  async function loadPaper(id){
    const selectedAnswer=paper?.paper_id===id?$('pilot-answer').value:null;
    paper=null;imageUrl=null;$('pilot-image').removeAttribute('src');$('pilot-page').disabled=true;$('pilot-paper-summary').textContent='Loading saved paper summary…';
    const current=++request;$('pilot-error').textContent='';$('pilot-answer').disabled=true;$('pilot-image').hidden=true;$('pilot-page-link').hidden=true;$('pilot-answer-detail').textContent='Loading saved answer evidence…';
    try{
      const result=await MisraAPI.pilotPaper(studyId,id);if(current!==request)return;if(result.paper_id!==id||!Array.isArray(result.answers))throw Error('Saved paper response is incomplete.');paper=result;
      const url=MisraWorkspace.currentURL();url.searchParams.set('study_id',studyId);url.searchParams.set('paper_id',id);MisraWorkspace.replaceRoute(url);
      const review=paper.review;
      $('pilot-paper-summary').innerHTML='<div class="pilot-paper-heading"><div><h2 dir="auto">'+esc(paper.label)+'</h2><p><span data-i18n>Answers flagged</span> '+number(review.flagged_answer_count)+' · <span data-i18n>Unresolved</span> '+number(review.unresolved_answer_count)+'</p></div><div class="pilot-question-mark"><span data-i18n>Saved paper total</span><strong>'+range(paper.total)+'</strong><span data-i18n>Includes study multiple-choice caps.</span></div></div>'+
        (review.reasons.length?'<details class="pilot-paper-flags"><summary data-i18n>All paper flags</summary><ul>'+review.reasons.map(item=>'<li><span dir="auto">'+esc(reason(item.code))+'</span><strong>'+number(item.count)+'</strong></li>').join('')+'</ul></details>':'');
      $('pilot-answer').innerHTML=paper.answers.map(a=>`<option value="${esc(a.answer_id)}">${esc(a.number)} · ${a.score==null?'unresolved':number(a.score)+'/'+number(a.max_score)}${a.needs_review||a.rubric_changed_since_run?' · needs review':''}</option>`).join('');
      $('pilot-answer').disabled=!paper.answers.length;
      $('pilot-page').innerHTML=Array.from({length:paper.page_count},(_,i)=>`<option value="${i}">Page ${i+1} / ${paper.page_count}</option>`).join('');$('pilot-page').disabled=!paper.page_count;
      const first=paper.answers.find(a=>a.answer_id===selectedAnswer)||paper.answers.find(a=>a.needs_review||a.score==null)||paper.answers[0];if(first){$('pilot-answer').value=first.answer_id;renderAnswer();}
    }catch(e){if(current===request){paper=null;$('pilot-error').textContent=e.message+' Select the paper again to retry.';$('pilot-answer-detail').textContent='Saved answer unavailable.';}}
  }
  function renderAnswer(){
    const answer=paper?.answers.find(row=>row.answer_id===$('pilot-answer').value);
    if(!answer)return;
    const definitions=answer.rubric_snapshot?.criteria||[];
    const scores=answer.criteria_scores||[];
    const title=answer.score==null?'Unresolved marks':number(answer.score)+' / '+number(answer.max_score);
    const rubricLink='setup.html?'+new URLSearchParams({exam_id:paper.exam_id,rubric_question:answer.question_id});
    const changed=answer.rubric_changed_since_run?'<p class="notice" data-i18n>The current rubric differs from the guide used for this proposal.</p>':'';
    const original=answer.original_score!=null&&answer.original_score!==answer.score
      ? '<p class="pilot-proposal-history"><span data-i18n>Original proposal</span> '+number(answer.original_score)+' · <span data-i18n>Later local proposal</span> '+number(answer.score)+(answer.proposal_authority?' · '+esc(answer.proposal_authority):'')+'</p>' : '';
    const criteria=definitions.map(definition=>{
      const score=scores.find(row=>row.criterion_id===definition.id);
      return '<li><div><strong dir="auto">'+esc(MisraReview.criterionLabel(definition.id,definitions,scores))+'</strong><span class="pilot-criterion-score">'+number(score?.points_earned)+' / '+number(definition.points)+'</span></div><p dir="auto">'+esc(score?.feedback||score?.basis||'No criterion decision recorded.')+'</p></li>';
    }).join('');
    const policy=Object.entries(answer.original_policy||{}).map(([key,value])=>'<div><dt>'+esc(reason(key))+'</dt><dd dir="auto">'+esc(value)+'</dd></div>').join('');
    const sources=(answer.course_evidence||[]).map(passage=>'<li><strong dir="auto">'+esc(passage.title||passage.source_id||'Saved course passage')+(passage.page_index==null?'':' · <span data-i18n>Page</span> '+number(passage.page_index+1))+'</strong><p dir="auto">'+esc(passage.text||'Passage text is unavailable.')+'</p></li>').join('');
    $('pilot-answer-detail').innerHTML=
      '<header class="pilot-question-heading"><div><h3><span data-i18n>Question</span> <bdi>'+esc(answer.number)+'</bdi></h3><p dir="auto">'+esc(answer.question_text)+'</p></div><div class="pilot-question-mark"><span data-i18n>Saved proposal</span><strong data-i18n>'+esc(title)+'</strong></div></header>'+
      changed+original+'<a class="pilot-jump" href="#pilot-evidence" data-i18n>See original page</a>'+MisraReview.renderPilot(answer)+
      '<section class="pilot-marks"><header><h4 data-i18n>Criterion marks</h4><a href="'+esc(rubricLink)+'" data-i18n>View &amp; edit this rubric</a></header>'+(criteria?'<ul>'+criteria+'</ul>':'<p data-i18n>No criterion marks recorded.</p>')+'</section>'+
      '<div class="pilot-records"><details><summary data-i18n>Student work used for this proposal</summary><pre class="pilot-text" dir="auto">'+esc(answer.student_text||'Checked transcription unavailable. Inspect the original page.')+'</pre></details>'+
      '<details><summary data-i18n>Recorded grading explanation</summary><p dir="auto">'+esc(answer.reasoning||answer.feedback||'No model rationale was saved for this result.')+'</p></details>'+
      '<details><summary data-i18n>Saved key and marking policy</summary><p dir="auto">'+esc(answer.answer_key)+'</p>'+(policy?'<dl>'+policy+'</dl>':'')+'</details>'+
      '<details><summary data-i18n>Course evidence used for this answer</summary>'+(sources?'<ul>'+sources+'</ul>':'<p data-i18n>No course passage snapshot was saved for this answer.</p>')+'</details></div>';
    showPage(Math.max(0,Math.min(paper.page_count-1,answer.page_index||0)));
  }
  function showPage(index){if(!paper||index<0)return;const url=MisraAPI.pilotPageUrl(studyId,paper.paper_id,index);imageUrl=url;$('pilot-page').value=String(index);$('pilot-image-status').textContent='Loading original page…';$('pilot-image').hidden=true;$('pilot-page-link').hidden=true;$('pilot-image').src=url;$('pilot-page-link').href=url;}
  $('pilot-image').addEventListener('load',()=>{if(!imageUrl||!paper)return;$('pilot-image').hidden=false;$('pilot-page-link').hidden=false;$('pilot-image-status').textContent='';});
  $('pilot-image').addEventListener('error',()=>{$('pilot-image').hidden=true;$('pilot-page-link').hidden=true;$('pilot-image-status').textContent='Original page could not load. Select the page again to retry.';});
  $('pilot-refresh').addEventListener('click',()=>{if(!loading)load();});$('pilot-year').addEventListener('change',()=>selectPaperOptions());$('pilot-flagged').addEventListener('change',()=>selectPaperOptions());$('pilot-paper').addEventListener('change',e=>loadPaper(e.target.value));$('pilot-answer').addEventListener('change',renderAnswer);$('pilot-page').addEventListener('change',e=>showPage(Number(e.target.value)));
  $('pilot-flagged').checked=params.get('needs_review')==='1';
  ready.then(load).catch(e=>$('pilot-error').textContent=e.message);
})();
