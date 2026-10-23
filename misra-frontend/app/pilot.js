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
    $('pilot-status').textContent=`${scope.length} saved papers · ${slots} answer slots · ${scope.filter(p=>p.review.needs_review).length} papers with recorded review concerns. No grades finalized.`;
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
    paper=null;imageUrl=null;$('pilot-image').removeAttribute('src');$('pilot-page').disabled=true;$('pilot-paper-summary').textContent='Loading saved paper summary…';
    const current=++request;$('pilot-error').textContent='';$('pilot-answer').disabled=true;$('pilot-image').hidden=true;$('pilot-page-link').hidden=true;$('pilot-answer-detail').textContent='Loading saved answer evidence…';
    try{
      const result=await MisraAPI.pilotPaper(studyId,id);if(current!==request)return;if(result.paper_id!==id||!Array.isArray(result.answers))throw Error('Saved paper response is incomplete.');paper=result;
      const url=new URL(location.href);url.searchParams.set('study_id',studyId);url.searchParams.set('paper_id',id);history.replaceState(null,'',url);
      $('pilot-paper-summary').innerHTML=`<div class="pilot-paper-heading"><h2>${esc(paper.label)} · ${paper.review.needs_review?'Needs review':'No recorded issue'}</h2><p>Saved total: ${range(paper.total)}</p></div><p>${paper.review.flagged_answer_count} answers have recorded concerns; ${paper.review.unresolved_answer_count} have unresolved marks. Saved totals include the study’s multiple-choice caps.</p><ul class="pilot-review-reasons">${paper.review.reasons.map(r=>`<li>${esc(reason(r.code))}: ${r.count}</li>`).join('')}</ul><p class="muted">Original proposals and explicit local review adjustments remain separate. Nothing here is an instructor-finalized grade.</p>`;
      $('pilot-answer').innerHTML=paper.answers.map(a=>`<option value="${esc(a.answer_id)}">${esc(a.number)} · ${a.score==null?'unresolved':number(a.score)+'/'+number(a.max_score)}${a.needs_review||a.rubric_changed_since_run?' · needs review':''}</option>`).join('');
      $('pilot-answer').disabled=!paper.answers.length;
      $('pilot-page').innerHTML=Array.from({length:paper.page_count},(_,i)=>`<option value="${i}">Page ${i+1} / ${paper.page_count}</option>`).join('');$('pilot-page').disabled=!paper.page_count;
      const first=paper.answers.find(a=>a.needs_review||a.score==null)||paper.answers[0];if(first){$('pilot-answer').value=first.answer_id;renderAnswer();}
    }catch(e){if(current===request){paper=null;$('pilot-error').textContent=e.message+' Select the paper again to retry.';$('pilot-answer-detail').textContent='Saved answer unavailable.';}}
  }
  function renderAnswer(){
    const a=paper?.answers.find(r=>r.answer_id===$('pilot-answer').value);if(!a)return;
    const changed=a.rubric_changed_since_run?'<p class="notice">The active rubric changed since this result. Compare the rubric versions before deciding; the saved grade was not recalculated.</p>':'';
    $('pilot-answer-detail').innerHTML=`<h3>${esc(a.number)}</h3><p dir="auto">${esc(a.question_text)}</p>${changed}${MisraReview.render(a)}<p><a class="button" href="setup.html?exam_id=${encodeURIComponent(paper.exam_id)}&rubric_question=${encodeURIComponent(a.question_id)}">View & edit this rubric</a></p><details open><summary>Student work used for this proposal</summary><pre class="pilot-text" dir="auto">${esc(a.student_text||'No checked transcription recorded. Read the original page; absence of text is not proof of a blank answer.')}</pre></details><h4>Recorded grading explanation</h4><p dir="auto">${esc(a.reasoning||a.feedback||'No model rationale was saved for this result. The score may come from a checked lookup or separately recorded local review.')}</p>${a.original_score!=null&&a.original_score!==a.score?`<p>Original proposal: ${number(a.original_score)}. Later local proposal: ${number(a.score)}. Authority: ${esc(a.proposal_authority)}.</p>`:''}<div class="table-scroll"><table class="data-table"><thead><tr><th>Rubric criterion used</th><th>Marks</th><th>Recorded explanation</th></tr></thead><tbody>${(a.rubric_snapshot?.criteria||[]).map(c=>{const decision=(a.criteria_scores||[]).find(r=>r.criterion_id===c.id);return `<tr><td>${esc(c.title||c.description)}</td><td>${number(decision?.points_earned)} / ${number(c.points)}</td><td>${esc(decision?.feedback||decision?.basis||'No individual decision recorded; no criterion mark has been invented.')}</td></tr>`;}).join('')}</tbody></table></div><details><summary>Saved key and marking policy</summary><p dir="auto">${esc(a.answer_key)}</p>${Object.entries(a.original_policy||{}).map(([k,v])=>`<p><strong>${esc(reason(k))}:</strong> ${esc(v)}</p>`).join('')}</details><details><summary>Course evidence used for this answer</summary>${(a.course_evidence||[]).map(p=>`<h4>${esc(p.title||p.source_id||'Saved course passage')}${p.page_index!=null?' · PDF page '+(p.page_index+1):''}</h4><p class="pilot-text" dir="auto">${esc(p.text||'Only a source identifier was retained; passage text is not available here.')}</p>`).join('')||'<p>No course passage snapshot was saved for this answer.</p>'}</details>`;
    showPage(Math.max(0,Math.min(paper.page_count-1,a.page_index||0)));
  }
  function showPage(index){if(!paper||index<0)return;const url=MisraAPI.pilotPageUrl(studyId,paper.paper_id,index);imageUrl=url;$('pilot-page').value=String(index);$('pilot-image-status').textContent='Loading original page…';$('pilot-image').hidden=true;$('pilot-page-link').hidden=true;$('pilot-image').src=url;$('pilot-page-link').href=url;}
  $('pilot-image').addEventListener('load',()=>{if(!imageUrl||!paper)return;$('pilot-image').hidden=false;$('pilot-page-link').hidden=false;$('pilot-image-status').textContent='';});
  $('pilot-image').addEventListener('error',()=>{$('pilot-image').hidden=true;$('pilot-page-link').hidden=true;$('pilot-image-status').textContent='Original page could not load. Select the page again to retry.';});
  $('pilot-refresh').addEventListener('click',()=>{if(!loading)load();});$('pilot-year').addEventListener('change',()=>selectPaperOptions());$('pilot-flagged').addEventListener('change',()=>selectPaperOptions());$('pilot-paper').addEventListener('change',e=>loadPaper(e.target.value));$('pilot-answer').addEventListener('change',renderAnswer);$('pilot-page').addEventListener('change',e=>showPage(Number(e.target.value)));
  $('pilot-flagged').checked=params.get('needs_review')==='1';
  ready.then(load).catch(e=>$('pilot-error').textContent=e.message);
})();
