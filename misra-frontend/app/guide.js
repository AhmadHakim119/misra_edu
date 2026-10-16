/* One review and atomic approval for the assessment's exact saved foundations. */
(function(){
  'use strict';
  const $=id=>document.getElementById(id),esc=value=>MisraUI.escapeHTML(String(value ?? ''));
  let exam=null,epoch=0,request=0,viewRequest=0,busy=false,loading=false,uncertain=false,data=null,stage='sources';
  const safe=()=>!busy && !window.MisraTeaching?.hasUnsaved() && !window.MisraLedgerEditors?.hasUnsaved() && !window.MisraAssessmentSources?.hasUnsaved();
  function controls(){
    $('guide-approve').disabled=busy || loading || uncertain || !data?.can_approve || !data.pending_count || !$('guide-confirm').checked || !safe();
    $('guide-confirm').disabled=busy || loading || !data;
    $('guide-refresh').disabled=busy || loading;
    document.querySelectorAll('.guide-steps button,[data-guide-step]').forEach(el=>el.disabled=busy);
    $('guide-review').setAttribute('aria-busy',String(busy || loading));
  }
  const sourceCopy=row=>row.sources && row.sources.mode!=='disabled' ? `${row.source_exception && row.source_exception.mode!=='inherit' ? 'Question exception' : 'Assessment sources'} · ${row.sources.bindings.length} reference(s)` : 'No course source selected';
  function focusEditor(editing) {
    $('guide-outline').hidden=editing;
    $('native-authoring').hidden=!editing;
    $('guide-questions-stage').dataset.editing=String(editing);
  }
  function criterionReview(c){
    return `<details class="guide-credit-review"><summary>Detailed credit &amp; evidence</summary><p>Scoring: ${c.scoring_type==='binary' ? 'Full credit or zero' : 'Scaled credit'}. Partial credit: ${c.partial_credit_allowed===false ? 'Not allowed' : 'Allowed'}.</p>${(c.required_evidence || []).length ? `<h5>Required evidence</h5><ul>${c.required_evidence.map(e=>`<li>${esc(e)}</li>`).join('')}</ul>` : ''}${(c.performance_levels || []).length ? `<h5>Credit levels</h5><ul>${c.performance_levels.map(l=>`<li><strong>${esc(l.label)} · ${esc(l.points_earned)} marks</strong><p>${esc(l.description)}</p></li>`).join('')}</ul>` : ''}${(c.common_errors || []).length ? `<h5>Common mistakes</h5><ul>${c.common_errors.map(e=>`<li><strong>${esc(e.description)}</strong><p>${esc(e.guidance)}</p></li>`).join('')}</ul>` : ''}${(c.alternative_methods || []).length ? `<h5>Valid alternative methods</h5><ul>${c.alternative_methods.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>` : ''}</details>`;
  }
  function retainedReview(row){
    const rubric=row.rubric,key=row.answer_key;
    const reference=rubric.reference_context && rubric.reference_context!==key.reference_text ? rubric.reference_context : '';
    const alternatives=(rubric.acceptable_answers || []).filter(a=>!(key.acceptable_answers || []).includes(a));
    if(!reference && !alternatives.length && !rubric.notes)return '';
    return `<details class="guide-credit-review"><summary>Retained rubric references &amp; notes</summary><p>Standalone answer keys take precedence over older rubric references. These retained fields are included in this saved version.</p>${reference ? `<h5>Rubric reference context</h5><p class="guide-reference" dir="auto">${esc(reference)}</p>` : ''}${alternatives.length ? `<h5>Retained acceptable answers</h5><ul>${alternatives.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>` : ''}${rubric.notes ? `<h5>Instructor notes</h5><p class="guide-reference" dir="auto">${esc(rubric.notes)}</p>` : ''}</details>`;
  }
  function render(){
    $('guide-total').textContent=data ? `${data.questions.length} questions · ${data.total_marks} marks · ${data.pending_count} saved draft definition(s)` : 'Loading saved definitions…';
    const rows=data?.questions || [];
    $('guide-outline').innerHTML=rows.length ? rows.map(row=>`<article class="guide-question-row"><div class="guide-question-number">${esc(row.question_number)}</div><div><h4 dir="auto">${esc(row.question_text)}</h4><p class="guide-question-state">${esc(row.rubric_status)} · ${esc(sourceCopy(row))}</p><ul class="guide-criterion-preview">${(row.rubric.criteria || []).map(c=>`<li><span dir="auto">${esc(c.title || c.description)}</span><span>${esc(c.points)} marks</span></li>`).join('')}</ul><p>${esc(row.answer_key.mode==='no_fixed_answer' ? 'No fixed answer — marked against criteria' : 'Reference solution recorded')}</p>${row.errors.length ? `<p class="form-error">${row.errors.map(esc).join(' ')}</p>` : ''}</div><div class="guide-question-action"><strong>${esc(row.max_score)} marks</strong><button type="button" data-guide-question="${esc(row.question_id)}" aria-label="Edit criteria for question ${esc(row.question_number)}">Edit criteria</button></div></article>`).join('') : '<p>Add an exam question to start its marking guide. Questions stay drafts until you review and approve the assessment.</p>';
    if(!data){controls();return;}
    $('guide-review-content').innerHTML=`${data.errors.length ? `<div role="alert" class="form-error"><h4>Resolve before approval</h4><ul>${data.errors.map(e=>`<li>${esc(e)}</li>`).join('')}</ul></div>` : ''}${data.warnings.length ? `<p class="notice">${data.warnings.map(esc).join(' ')}</p>` : ''}<p><strong>${data.questions.length} questions · ${data.total_marks} marks.</strong> ${data.pending_count ? `${data.pending_count} saved draft definition(s) will become active together.` : 'All saved definitions are already approved or retained legacy definitions.'}</p>${rows.map(row=>`<details class="guide-review-question"><summary>Question ${esc(row.question_number)} · ${esc(row.max_score)} marks · ${esc(row.rubric_status)}</summary><p>${esc(row.question_text)}</p><h4>Credit awarded</h4><ul>${(row.rubric.criteria || []).map(c=>`<li><strong>${esc(c.title || c.description)} — ${esc(c.points)} marks</strong><p>${esc(c.description)}</p>${criterionReview(c)}</li>`).join('')}</ul><h4>Reference answer</h4><p class="guide-reference" dir="auto">${esc(row.answer_key.mode==='no_fixed_answer' ? 'No fixed answer. Evaluate against the approved rubric.' : row.answer_key.reference_text || 'See the linked answer-key document.')}</p>${(row.answer_key.acceptable_answers || []).length ? `<h4>Accepted alternatives</h4><ul>${row.answer_key.acceptable_answers.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>` : ''}${(row.answer_key.document_refs || []).map((ref,i)=>`<p><a target="_blank" rel="noopener" href="${esc(MisraAPI.setupDocumentUrl(exam.id,ref.job_id,ref.document_index || 0))}">Open reference document ${i+1}</a> · pages ${ref.page_indices.map(p=>p+1).join(', ')}</p>`).join('')}<details><summary>Scoring rules · ${esc(row.rubric.policy?.grading_approach || 'criterion-specific')}</summary><dl class="guide-rules">${Object.entries(row.rubric.policy || {}).filter(([,v])=>v!=null).map(([k,v])=>`<div><dt>${esc(k.replaceAll('_',' '))}</dt><dd>${esc(typeof v==='boolean' ? v ? 'Yes' : 'No' : String(v).replaceAll('_',' '))}</dd></div>`).join('')}</dl></details>${retainedReview(row)}<p>Grading input: ${esc((row.grading_input || 'adaptive').replaceAll('_',' '))}</p><h4>Source grounding</h4><p>${esc(sourceCopy(row))}</p>${row.sources ? `<ul>${(row.source_references || []).map(b=>`<li>${esc(b.title)} · document pages ${b.page_indices.map(n=>n+1).join(', ')}</li>`).join('')}</ul>` : ''}${row.warnings.map(w=>`<p class="notice">${esc(w)}</p>`).join('')}<button type="button" data-guide-question="${esc(row.question_id)}">Edit this part of the guide</button></details>`).join('')}`;
    controls();
  }
  async function refresh(){
    if(!exam || busy)return;const current=epoch,sequence=++request;loading=true;data=null;$('guide-confirm').checked=false;controls();$('guide-status').textContent='Reading the complete saved guide…';
    try{const value=await MisraAPI.assessmentGuide(exam.id);if(current!==epoch || sequence!==request)return;if(value?.exam_id!==exam.id || !Array.isArray(value.questions) || !Array.isArray(value.errors) || !Array.isArray(value.warnings) || !/^[a-f0-9]{64}$/.test(value.review_token))throw new Error('The guide review response is incomplete. Refresh before approving.');data=value;uncertain=false;$('guide-status').textContent=value.errors.length ? 'Some definitions need attention. Nothing will be partially approved.' : value.pending_count ? 'Saved drafts are ready for whole-assessment review.' : 'Saved guide loaded. Existing grades are unchanged.';render();}
    catch(e){if(current===epoch && sequence===request){$('guide-status').textContent=e.message;$('guide-review-content').innerHTML=`<p role="alert">${esc(e.message)} Refresh saved guide to reconnect.</p>`;}}
    finally{if(current===epoch && sequence===request){loading=false;controls();}}
  }
  async function show(next,questionId){
    if(busy)return;
    if(window.MisraTeaching?.canLeave()===false)return;
    const current=epoch,sequence=++viewRequest;
    if(!await window.MisraLedgerEditors.saveEdits() || !await window.MisraAssessmentSources.saveDraft()){window.showToast('Some edits could not be saved. Resolve their error before continuing. Nothing was approved.','error');return;}
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
  $('guide-sources-tab').addEventListener('click',()=>show('sources'));
  $('author-rubrics').addEventListener('click',()=>show('questions'));
  $('guide-review-tab').addEventListener('click',()=>show('review'));
  $('manage-course-library').addEventListener('click',async()=>{if(!window.MisraLedgerEditors.canLeave())return;await window.MisraLedgerEditors.show('library');});
  $('ledger-setup').addEventListener('click',e=>{const step=e.target.closest('[data-guide-step]'),question=e.target.closest('[data-guide-question]');if(step)show(step.dataset.guideStep);if(question)show('questions',question.dataset.guideQuestion);});
  $('guide-refresh').addEventListener('click',()=>{if(safe())refresh();else window.showToast('Save your current edits before refreshing saved definitions.','error');});
  $('guide-confirm').addEventListener('change',controls);
  $('guide-expand').addEventListener('click',()=>{const open=$('guide-expand').getAttribute('aria-expanded')!=='true';$('guide-review-content').querySelectorAll('.guide-review-question').forEach(el=>el.open=open);$('guide-expand').setAttribute('aria-expanded',String(open));$('guide-expand').textContent=open ? 'Collapse all questions' : 'Expand all questions';});
  $('guide-approval').addEventListener('submit',async e=>{
    e.preventDefault();if($('guide-approve').disabled || !safe())return;const current=epoch,id=exam.id,token=data.review_token;busy=true;controls();$('guide-approval-state').textContent='Approving the complete assessment guide…';
    try{const result=await MisraAPI.approveAssessmentGuide(id,{review_token:token,confirm_reviewed:true});if(current!==epoch)return;if(result?.exam_id!==id || !Array.isArray(result.approved_version_ids))throw new Error('Approval response incomplete; reload the saved guide before another request.');$('guide-approval-state').textContent=result.message;window.dispatchEvent(new CustomEvent('misra:ledger-foundations-changed'));busy=false;window.MisraLedgerEditors.reset(exam);await window.MisraAssessmentSources.reload();await refresh();}
    catch(error){if(current===epoch){uncertain=true;$('guide-confirm').checked=false;$('guide-approval-state').textContent=`${error.message} Refresh the saved guide before another approval; do not repeat blindly.`;}}
    finally{if(current===epoch){busy=false;controls();}}
  });
  window.addEventListener('misra:assessment-loaded',e=>{++epoch;++request;exam={id:e.detail.examId,course_id:e.detail.courseId};busy=loading=uncertain=false;data=null;stage='sources';$('guide-confirm').checked=false;$('guide-approval-state').textContent='';$('guide-sources-stage').hidden=false;$('guide-questions-stage').hidden=true;$('guide-review').hidden=true;[['guide-sources-tab',true],['author-rubrics',false],['guide-review-tab',false]].forEach(([id,value])=>$(id).setAttribute('aria-pressed',String(value)));refresh();});
  window.addEventListener('misra:ledger-foundations-changed',()=>{if(!busy && safe())refresh();});
  window.addEventListener('misra:guide-editor-opened',()=>focusEditor(true));
  window.addEventListener('misra:guide-question-removed',()=>{focusEditor(false);$('guide-confirm').checked=false;$('guide-approval-state').textContent='';$('author-new-question').focus({preventScroll:true});});
  window.MisraAssessmentGuide={show,isBusy:()=>busy};
})();
