/* One review and atomic approval for the assessment's exact saved foundations. */
(function(){
  'use strict';
  const routeScope=MisraWorkspace.page;
  const $=id=>document.getElementById(id),esc=value=>MisraUI.escapeHTML(String(value ?? ''));
  let exam=null,epoch=0,request=0,viewRequest=0,busy=false,loading=false,uncertain=false,data=null,stage='sources';
  let draftingState='';
  let draftingFailures=[];
  const safe=()=>!busy && !window.MisraTeaching?.hasUnsaved() && !window.MisraLedgerEditors?.hasUnsaved() && !window.MisraAssessmentSources?.hasUnsaved();
  function controls(){
    $('guide-approve').disabled=busy || loading || uncertain || !data?.can_approve || !data.pending_count || !$('guide-confirm').checked || !safe();
    $('guide-confirm').disabled=busy || loading || !data;
    $('guide-refresh').disabled=busy || loading;
    document.querySelectorAll('.guide-steps button,[data-guide-step],[data-guide-generate],[data-guide-question]').forEach(el=>el.disabled=busy);
    $('guide-review').setAttribute('aria-busy',String(busy || loading));
    const reopen=$('guide-reopen');if(reopen)reopen.disabled=busy||loading||uncertain||!data||!safe();
  }
  const sourceCopy=row=>row.sources && row.sources.mode!=='disabled' ? `${row.source_exception && row.source_exception.mode!=='inherit' ? 'Question exception' : 'Assessment sources'} · ${row.sources.bindings.length} reference(s)` : 'No course source selected';
  function sourcePages(indices){const ranges=[];for(const index of [...indices].sort((a,b)=>a-b)){const page=index+1,last=ranges.at(-1);if(last && page===last[1]+1)last[1]=page;else ranges.push([page,page]);}return ranges.map(([first,last])=>first===last?String(first):`${first}–${last}`).join(', ');}
  function focusEditor(editing) {
    $('guide-outline').hidden=editing;
    $('native-authoring').hidden=!editing;
    $('guide-questions-stage').dataset.editing=String(editing);
  }
  function criterionReview(c, exact) {
    const binary=c.scoring_type==='binary'||c.partial_credit_allowed===false;
    const levels=[...(c.performance_levels||[])].sort((a,b)=>b.points_earned-a.points_earned);
    const evidence=c.required_evidence||[], errors=c.common_errors||[], alternatives=c.alternative_methods||[];
    const details=evidence.length||errors.length||alternatives.length?`<details class="guide-credit-review"><summary>Evidence and common mistakes</summary>
      ${evidence.length?`<ul>${evidence.map(item=>`<li dir="auto">${esc(item)}</li>`).join('')}</ul>`:''}
      ${errors.length?`<dl>${errors.map(item=>`<div><dt>${esc(item.description)}</dt><dd>${esc(item.guidance)}</dd></div>`).join('')}</dl>`:''}
      ${alternatives.length?`<p data-i18n>Valid alternatives</p><ul>${alternatives.map(item=>`<li dir="auto">${esc(item)}</li>`).join('')}</ul>`:''}</details>`:'';
    const marks=binary?`<span data-i18n>Full or zero</span><p>${esc(c.points)} / 0</p>`:
      `<span data-i18n>${exact?'Defined credit levels':'Legacy scaled credit'}</span>${levels.length?`<ul>${levels.map(level=>`<li><strong>${esc(level.points_earned)}</strong> <span dir="auto">${esc(level.description)}</span></li>`).join('')}</ul>`:''}`;
    return `<tr><th scope="row" dir="auto">${esc(c.title||c.description)}</th><td>${esc(c.points)}</td><td><p dir="auto">${esc(c.description)}</p>${details}</td><td>${marks}</td></tr>`;
  }
  function reviewCriteria(rubric) {
    return `<table class="guide-review-criteria" aria-label="Credit awarded"><thead><tr><th scope="col">Criterion</th><th scope="col">Max marks</th><th scope="col">What earns credit</th><th scope="col">Credit levels</th></tr></thead><tbody>${(rubric.criteria||[]).map(c=>criterionReview(c,rubric.scoring_contract==='exact')).join('')}</tbody></table>`;
  }
  function retainedReview(row){
    const rubric=row.rubric,key=row.answer_key;
    const reference=rubric.reference_context && rubric.reference_context!==key.reference_text ? rubric.reference_context : '';
    const alternatives=(rubric.acceptable_answers || []).filter(a=>!(key.acceptable_answers || []).includes(a));
    if(!reference && !alternatives.length && !rubric.notes)return '';
    return `<details class="guide-credit-review"><summary>Retained rubric references &amp; notes</summary><p>Standalone answer keys take precedence over older rubric references. These retained fields are included in this saved version.</p>${reference ? `<h5>Rubric reference context</h5><p class="guide-reference" dir="auto">${esc(reference)}</p>` : ''}${alternatives.length ? `<h5>Retained acceptable answers</h5><ul>${alternatives.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>` : ''}${rubric.notes ? `<h5>Instructor notes</h5><p class="guide-reference" dir="auto">${esc(rubric.notes)}</p>` : ''}</details>`;
  }
  function previewCriteria(criteria) {
    if(!criteria?.length)return '';
    return `<details class="guide-criterion-preview"><summary><span data-i18n>Criteria</span> · ${criteria.length}</summary>
      <ul>${criteria.map(c=>`<li><span dir="auto">${esc(c.title||c.description)}</span><span>${esc(c.points)} marks</span></li>`).join('')}</ul></details>`;
  }
  function needsDraft(row){
    return row.needs_rubric_draft===true || row.rubric?.scoring_contract==='needs_exact_scoring';
  }
  function draftPanel(rows){
    const missing=rows.filter(needsDraft);
    if(!missing.length&&!draftingState)return '';
    const pendingIds = new Set(missing.map(row=>row.question_id));
    const failures = draftingFailures.filter(row=>pendingIds.has(row.id));
    return `<section class="guide-draft-panel" aria-label="Draft rubrics with AI">
      <div>${missing.length?`<h4>${missing.length===1?'One question needs a rubric':missing.length+' questions need rubrics'}</h4>
        <p>Generate scoring drafts from the saved questions and answer keys.</p>`:''}
        <p data-guide-draft-status role="status">${esc(draftingState)}</p>
        <div data-guide-draft-failures>${failures.length?`<ul>${failures.map(row=>`<li><strong>Question ${esc(row.number)}</strong>
          <p>${esc(row.message)}</p><button type="button" data-guide-question="${esc(row.id)}">Open question ${esc(row.number)}</button></li>`).join('')}</ul>`:''}</div></div>
      ${missing.length?'<button type="button" class="primary" data-guide-generate>Generate missing rubrics</button>':''}</section>`;
  }
  function render(){
    $('guide-total').textContent=data ? `${data.questions.length} questions · ${data.total_marks} marks · ${data.pending_count} saved draft definition(s)` : 'Loading saved definitions…';
    const rows=data?.questions || [];
    $('guide-outline').innerHTML=rows.length ? draftPanel(rows)+rows.map(row=>`<article class="guide-question-row"><div class="guide-question-number" dir="auto">${esc(row.question_number)}</div><div class="guide-question-content"><div><h4 dir="auto">${esc(row.question_text)}</h4><p class="guide-question-state">${needsDraft(row)?'Ready to draft':esc(row.rubric_status)} · ${esc(sourceCopy(row))}</p><p>${esc(row.answer_key.mode==='no_fixed_answer' ? 'No fixed answer — marked against criteria' : 'Reference solution recorded')}</p>${row.errors.length ? `<p class="form-error">${row.errors.map(esc).join(' ')}</p>` : ''}</div>${needsDraft(row)?'':previewCriteria(row.rubric.criteria)}</div><div class="guide-question-action"><strong>${esc(row.max_score)} marks</strong><button type="button" data-guide-question="${esc(row.question_id)}" aria-label="Edit criteria for question ${esc(row.question_number)}">${needsDraft(row)?'Open builder':'Edit criteria'}</button></div></article>`).join('') : '<p>Add an exam question to start its marking guide. Questions stay drafts until you review and approve the assessment.</p>';
    if(!data){controls();return;}
    $('guide-review-content').innerHTML=`${draftPanel(rows)}${data.errors.length ? `<div role="alert" class="form-error"><h4>Resolve before approval</h4><ul>${data.errors.map(e=>`<li>${esc(e)}</li>`).join('')}</ul></div>` : ''}${data.warnings.length ? `<p class="notice">${data.warnings.map(esc).join(' ')}</p>` : ''}<p><strong>${data.questions.length} questions · ${data.total_marks} marks.</strong> ${data.pending_count ? `${data.pending_count} saved draft definition(s) will become active together.` : 'All saved definitions are already approved or retained legacy definitions.'}</p>${rows.map(row=>`<details class="guide-review-question"><summary>Question ${esc(row.question_number)} · ${esc(row.max_score)} marks · ${esc(row.rubric_status)}</summary><p>${esc(row.question_text)}</p>${needsDraft(row)?'<p>Generate a scoring draft for this question before approval.</p>':'<h4>Credit awarded</h4>'+reviewCriteria(row.rubric)}<h4>Model answer</h4><p class="guide-reference" dir="auto">${esc(row.answer_key.mode==='no_fixed_answer' ? 'No fixed answer. Evaluate against the approved rubric.' : row.answer_key.reference_text || 'See the linked answer-key document.')}</p>${(row.answer_key.acceptable_answers || []).length ? `<h4>Acceptable alternatives</h4><ul>${row.answer_key.acceptable_answers.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>` : ''}${(row.answer_key.document_refs || []).map((ref,i)=>`<p><a target="_blank" rel="noopener" href="${esc(MisraAPI.setupDocumentUrl(exam.id,ref.job_id,ref.document_index || 0))}">Open reference document ${i+1}</a> · pages ${ref.page_indices.map(p=>p+1).join(', ')}</p>`).join('')}<details><summary>Scoring rules · ${esc(row.rubric.policy?.grading_approach || 'criterion-specific')}</summary><dl class="guide-rules">${Object.entries(row.rubric.policy || {}).filter(([,v])=>v!=null).map(([k,v])=>`<div><dt>${esc(k.replaceAll('_',' '))}</dt><dd>${esc(typeof v==='boolean' ? v ? 'Yes' : 'No' : String(v).replaceAll('_',' '))}</dd></div>`).join('')}</dl></details>${retainedReview(row)}<p>Grading input: ${esc((row.grading_input || 'adaptive').replaceAll('_',' '))}</p><h4>Source grounding</h4><p>${esc(sourceCopy(row))}</p>${row.sources ? `<ul>${(row.source_references || []).map(b=>`<li>${esc(b.title)} · document pages ${b.page_indices.map(n=>n+1).join(', ')}</li>`).join('')}</ul>` : ''}${row.warnings.map(w=>`<p class="notice">${esc(w)}</p>`).join('')}<button type="button" data-guide-question="${esc(row.question_id)}">Edit this part of the guide</button></details>`).join('')}`;
    const selectedSources=data.source_approvals || [];
    $('guide-confirm-label').textContent=selectedSources.length?'I reviewed the marking guide and approve the selected source pages listed below.':'I reviewed the questions, solutions, marking rules and selected sources for this assessment.';
    $('guide-approve').textContent=selectedSources.length?'Approve guide and selected sources':'Approve assessment guide';
    if(selectedSources.length)$('guide-review-content').insertAdjacentHTML('afterbegin',`<section id="guide-source-approvals"><h4>Selected source pages included in this approval</h4><p data-i18n>This same approval publishes the marking guide and these source pages for RAG. No separate chapter approval is needed.</p><ul>${selectedSources.map(source=>`<li><strong dir="auto">${esc(source.title)}</strong> · <span data-i18n>PDF pages</span> ${esc(sourcePages(source.page_indices))}</li>`).join('')}</ul></section>`);
    if(rows.some(row=>row.rubric_status==='approved'||row.rubric_status==='legacy')){
      $('guide-review-content').insertAdjacentHTML('beforeend','<p>Approved too early? Reopen the saved guide to correct it. Previous versions and grades remain traceable.</p><button type="button" id="guide-reopen">Reopen guide for corrections</button>');
      $('guide-reopen').addEventListener('click',async()=>{
        if(!safe()||loading||uncertain)return;
        if(!await MisraWorkspace.confirm('Reopen this guide? Existing text is copied into correction drafts. New grading is suspended until you approve again; previous grades and snapshots stay in history.'))return;
        const current=epoch;busy=true;controls();
        try{const result=await MisraAPI.reopenAssessmentGuide(exam.id,{review_token:data.review_token,confirm_reviewed:true});if(current!==epoch)return;$('guide-approval-state').textContent=result.message;window.MisraLedgerEditors.reset(exam);busy=false;await refresh();window.dispatchEvent(new CustomEvent('misra:ledger-foundations-changed'));}
        catch(error){if(current===epoch){uncertain=true;$('guide-approval-state').textContent=error.message+' Refresh the saved guide before trying again.';}}
        finally{if(current===epoch){busy=false;controls();}}
      });
    }
    controls();
  }
  async function refresh(){
    if(!exam || busy)return;const current=epoch,sequence=++request;loading=true;data=null;$('guide-confirm').checked=false;controls();$('guide-status').textContent='Reading the complete saved guide…';
    try{const value=await MisraAPI.assessmentGuide(exam.id);if(current!==epoch || sequence!==request)return;if(value?.exam_id!==exam.id || !Array.isArray(value.questions) || !Array.isArray(value.errors) || !Array.isArray(value.warnings) || !/^[a-f0-9]{64}$/.test(value.review_token))throw new Error('The guide review response is incomplete. Refresh before approving.');data=value;uncertain=false;$('guide-status').textContent=value.errors.length ? 'Some guide items need attention.' : value.questions.some(needsDraft) ? 'Draft the remaining rubrics before reviewing the whole guide.' : value.pending_count ? 'Saved drafts are ready for whole-assessment review.' : 'Saved guide loaded. Existing grades are unchanged.';render();}
    catch(e){if(current===epoch && sequence===request){$('guide-status').textContent=e.message;$('guide-review-content').innerHTML=`<p role="alert">${esc(e.message)} Refresh saved guide to reconnect.</p>`;}}
    finally{if(current===epoch && sequence===request){loading=false;controls();}}
  }
  async function show(next,questionId){
    if(busy)return;
    if(await window.MisraTeaching?.canLeave()===false)return;
    const current=epoch,sequence=++viewRequest;
    if(!await window.MisraLedgerEditors.saveEdits() || !await window.MisraAssessmentSources.saveDraft({allowPendingSources:true})){window.showToast('Some edits could not be saved. Resolve their error before continuing. Nothing was approved.','error');return;}
    if(current!==epoch || sequence!==viewRequest)return;
    stage=next;$('guide-sources-stage').hidden=next!=='sources';$('guide-questions-stage').hidden=next!=='questions';$('guide-review').hidden=next!=='review';
    [['guide-sources-tab','sources'],['author-rubrics','questions'],['guide-review-tab','review']].forEach(([id,value])=>$(id).setAttribute('aria-pressed',String(next===value)));
    if(next==='questions') {await window.MisraLedgerEditors.show('questions',questionId);if(current!==epoch || sequence!==viewRequest)return;focusEditor(Boolean(questionId));} else window.MisraLedgerEditors.hide();
    if(current!==epoch || sequence!==viewRequest)return;
    await refresh();controls();
    if(current===epoch && sequence===viewRequest && next==='questions' && questionId) {
      $('author-back').focus({preventScroll:true});
      $('native-authoring').scrollIntoView({block:'start'});
    }
  }
  async function generateMissing(){
    if(loading||!data||!safe())return;
    const rows=data.questions.filter(needsDraft);
    if(!rows.length)return;
    const current=epoch;
    busy=true;controls();
    draftingFailures=[];
    document.querySelectorAll('[data-guide-draft-failures]').forEach(node=>node.replaceChildren());
    let completed=0;
    function update(message){
      draftingState=message;
      document.querySelectorAll('[data-guide-draft-status]').forEach(node=>node.textContent=message);
    }
    try{
      for(const row of rows){
        if(current!==epoch||routeScope.signal.aborted)return;
        update('Drafting question '+row.question_number+' · '+(completed+draftingFailures.length+1)+' of '+rows.length);
        try{
          const result=await MisraAPI.draftMissingRubric(row.question_id);
          if(result?.rubric_version?.status!=='draft'||result.rubric_version.question_id!==row.question_id||
            result.rubric_version.rubric_json?.scoring_contract!=='exact')throw Error('Draft confirmation unavailable.');
          completed++;
        }catch(error){
          if(current!==epoch||routeScope.signal.aborted)return;
          const message=[409,422,502].includes(error.status)&&typeof error.detail==='string'
            ?error.detail:'Draft status could not be confirmed. Check saved questions before retrying.';
          draftingFailures.push({id:row.question_id,number:row.question_number,message});
        }
      }
    }finally{
      if(current===epoch&&!routeScope.signal.aborted){
        busy=false;
        update((completed===1?'1 rubric saved for review.':completed+' rubrics saved for review.')+
          (draftingFailures.length?' Still to check: '+draftingFailures.map(row=>row.number).join(', ')+'.':''));
        window.MisraLedgerEditors.reset(exam);
        window.dispatchEvent(new CustomEvent('misra:ledger-foundations-changed'));
      }
    }
  }
  $('guide-sources-tab').addEventListener('click',()=>show('sources'));
  $('author-rubrics').addEventListener('click',()=>show('questions'));
  $('guide-review-tab').addEventListener('click',()=>show('review'));
  $('manage-course-library').addEventListener('click',()=>window.MisraLedgerEditors.show('library'));
  $('ledger-setup').addEventListener('click',e=>{if(e.target.closest('[data-guide-generate]')){generateMissing();return;}const step=e.target.closest('[data-guide-step]'),question=e.target.closest('[data-guide-question]');if(step)show(step.dataset.guideStep);if(question)show('questions',question.dataset.guideQuestion);});
  $('guide-refresh').addEventListener('click',()=>{if(safe())refresh();else window.showToast('Save your current edits before refreshing saved definitions.','error');});
  $('guide-confirm').addEventListener('change',controls);
  $('guide-expand').addEventListener('click',()=>{const open=$('guide-expand').getAttribute('aria-expanded')!=='true';$('guide-review-content').querySelectorAll('.guide-review-question').forEach(el=>el.open=open);$('guide-expand').setAttribute('aria-expanded',String(open));$('guide-expand').textContent=open ? 'Collapse all questions' : 'Expand all questions';});
  $('guide-approval').addEventListener('submit',async e=>{
    e.preventDefault();if($('guide-approve').disabled || !safe())return;const current=epoch,id=exam.id,token=data.review_token;busy=true;controls();$('guide-approval-state').textContent='Approving the complete assessment guide…';
    try{const result=await MisraAPI.approveAssessmentGuide(id,{review_token:token,confirm_reviewed:true,...(data.source_approvals?.length?{approve_selected_sources:true}:{})});if(current!==epoch)return;if(result?.exam_id!==id || !Array.isArray(result.approved_version_ids))throw new Error('Approval response incomplete; reload the saved guide before another request.');$('guide-approval-state').textContent=result.message;window.dispatchEvent(new CustomEvent('misra:ledger-foundations-changed'));busy=false;window.MisraLedgerEditors.reset(exam);await window.MisraAssessmentSources.reload();await refresh();}
    catch(error){if(current===epoch){uncertain=true;$('guide-confirm').checked=false;$('guide-approval-state').textContent=`${error.message} Refresh the saved guide before another approval; do not repeat blindly.`;}}
    finally{if(current===epoch){busy=false;controls();}}
  });
  routeScope.listen(window,'misra:assessment-loaded',e=>{++epoch;++request;exam={id:e.detail.examId,course_id:e.detail.courseId};busy=loading=uncertain=false;data=null;draftingState='';draftingFailures=[];stage='sources';$('guide-confirm').checked=false;$('guide-approval-state').textContent='';$('guide-sources-stage').hidden=false;$('guide-questions-stage').hidden=true;$('guide-review').hidden=true;[['guide-sources-tab',true],['author-rubrics',false],['guide-review-tab',false]].forEach(([id,value])=>$(id).setAttribute('aria-pressed',String(value)));const wanted=MisraWorkspace.currentURL().searchParams.get('rubric_question');refresh().then(()=>{if(wanted&&data?.questions.some(row=>row.question_id===wanted))show('questions',wanted);});});
  routeScope.listen(window,'misra:ledger-foundations-changed',()=>{if(!busy && safe())refresh();});
  routeScope.listen(window,'misra:guide-editor-opened',()=>{++viewRequest;focusEditor(true);});
  routeScope.listen(window,'misra:guide-question-removed',()=>{focusEditor(false);$('guide-confirm').checked=false;$('guide-approval-state').textContent='';$('author-new-question').focus({preventScroll:true});});
  window.MisraAssessmentGuide={show,isBusy:()=>busy};
})();
