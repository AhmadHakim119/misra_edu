/* Two explicit removal scopes on Extraction. Never deletes originals or grades. */
(function(){
  'use strict';
  const {$,esc,operation}=MisraApp,t=value=>MisraLocale.text(value),dialog=$('extraction-remove-dialog');
  let pending=null,epoch=0,writing=false,opener=null,returnAfterWrite=null;
  function setTitle(value){$('removal-title').textContent=t(value);}
  function editable(){if(MisraApp.isBusy())return false;if(MisraExtraction.hasUnsaved()){showToast(t('Save or cancel your extraction edits before removing anything.'),'error');return false;}return true;}
  function confirmState(disabled=true){$('confirm-removal').disabled=disabled;$('cancel-removal').disabled=writing;dialog.setAttribute('aria-busy',String(writing));}
  function renderRemoved(){
    const report=MisraExtraction.report();if(!report)return;
    const questions=report.removed_questions||[],entries=report.excluded_segments||[];
    $('removed-questions').hidden=!questions.length;
    $('removed-questions-list').innerHTML=questions.map(q=>`<div><h3 dir="auto">${esc(q.question_number)}</h3><p dir="auto">${esc(q.question_text||'')}</p><div class="inline-actions"><button type="button" data-restore-question="${esc(q.id)}">Restore question to exam</button>${q.answer_id?`<a href="${MisraApp.link('history',{exam_id:report.submission.exam_id,submission_id:report.submission.id,answer_id:q.answer_id})}">View saved grading history</a>`:''}</div></div>`).join('');
    $('removed-entries').hidden=!entries.length;
    $('removed-entries-list').innerHTML=entries.map(entry=>`<div><p dir="auto">${esc(entry.text||entry.extracted_text||'')}</p><p><span data-i18n>Page</span> ${Number(entry.page_index??0)+1}</p></div>`).join('');
  }
  async function open(button,kind,id,action='remove'){
    if(!editable())return;
    const report=MisraExtraction.report(),row=report.questions.find(row=>row.question.id===id),sourceRow=kind==='source'?report.questions.find(row=>row.sources.some(source=>source.id===id)):null;
    const source=sourceRow?.sources.find(source=>source.id===id);
    const question=kind==='source'?sourceRow?.question:row?.question||(report.removed_questions||[]).find(q=>q.id===id);
    if(!question)return;
    const token=++epoch;opener=button;pending={kind,id,action,token:null,examId:report.submission.exam_id};
    $('removal-error').textContent='';$('removal-preview').textContent=t('Loading the effect of this change…');
    setTitle(kind==='source'?'Remove extracted entry':action==='restore'?'Restore question to exam':'Remove question from exam');
    $('removal-description').textContent=t(kind==='source'?'This affects this paper only. The question stays in the exam. A missing answer stays unresolved; it is not a zero.':action==='restore'?'This restores the question for every paper. Its prior approved rules are retained; unfinished drafts are not approved.':'This removes the question from every paper and from current exam totals. Original papers and saved results stay in history. Marked papers will need review.');
    $('confirm-removal').textContent=t(kind==='source'?'Remove from this paper':action==='restore'?'Restore for all papers':'Remove for all papers');
    confirmState();dialog.showModal();$('cancel-removal').focus();
    if(kind==='source'){
      $('removal-preview').innerHTML=`<h3 dir="auto">${esc(question.question_number)}</h3><pre dir="auto">${esc(source.area_revision?.text??source.extracted_text)}</pre>`;
      if(!/^[a-f0-9]{64}$/.test(source.removal_token||'')){$('removal-error').textContent=t('Removal cannot be verified. Load the updated API and refresh Extraction first.');return;}
      pending.token=source.removal_token;confirmState(false);return;
    }
    try{
      const preview=await MisraAPI.questionRemovalPreview(id,action);
      if(token!==epoch||!dialog.open)return;
      if(preview?.question_id!==id||preview.exam_id!==pending.examId||preview.action!==action||!/^[a-f0-9]{64}$/.test(preview.review_token)||!Array.isArray(preview.remaining_questions)||![preview.previous_total_marks,preview.revised_total_marks,preview.paper_count].every(value=>Number.isFinite(value)&&value>=0))throw Error('The removal preview is incomplete. Close and refresh Extraction.');
      if(preview.remaining_questions.some(q=>typeof q.id!=='string'||typeof q.number!=='string'||!Number.isFinite(q.max_score)||q.max_score<=0)||Math.abs(preview.remaining_questions.reduce((sum,q)=>sum+q.max_score,0)-preview.revised_total_marks)>.01)throw Error('The removal preview is incomplete. Close and refresh Extraction.');
      pending.token=preview.review_token;
      $('removal-preview').innerHTML=`<h3 dir="auto">${esc(preview.question_number)}</h3><p dir="auto">${esc(preview.question_text||'')}</p><p><span data-i18n>Exam total:</span> <bdi dir="ltr" data-no-translate>${esc(preview.previous_total_marks)} → ${esc(preview.revised_total_marks)}</bdi> <span data-i18n>marks</span> · ${esc(preview.paper_count)} <span data-i18n>papers</span></p><details><summary>Question list after this change</summary><ul>${preview.remaining_questions.map(q=>`<li dir="auto">${esc(q.number)} · ${esc(q.max_score)} <span data-i18n>marks</span></li>`).join('')}</ul></details>`;
      confirmState(false);
    }catch(error){if(token===epoch&&dialog.open){$('removal-preview').replaceChildren();$('removal-error').textContent=error.message;}}
  }
  dialog.addEventListener('cancel',event=>{if(writing)event.preventDefault();});
  dialog.addEventListener('close',()=>{++epoch;pending=null;const target=opener?.isConnected?opener:$('reading-question');if(MisraApp.isBusy())returnAfterWrite=target;else target?.focus({preventScroll:true});opener=null;});
  $('cancel-removal').addEventListener('click',()=>{if(!writing)dialog.close();});
  $('confirm-removal').addEventListener('click',()=>{
    if(!pending?.token||writing||$('confirm-removal').disabled||!editable())return;
    const change={...pending};writing=true;confirmState();$('removal-error').textContent='';
    operation($('confirm-removal'),async()=>{
      try{
        if(change.kind==='source'){
          const report=await MisraAPI.excludeExtractedSource(change.id,{review_token:change.token,confirm_reviewed:true});
          MisraExtraction.applyReport(report);writing=false;dialog.close();showToast(t('Extracted entry removed from this paper.'));
        }else{
          const result=await MisraAPI.changeQuestionLifecycle(change.id,{action:change.action,review_token:change.token,confirm_reviewed:true});
          if(result?.question_id!==change.id||result.exam_id!==change.examId||result.action!==change.action)throw Error('The change response is incomplete. Close and refresh Extraction before another action.');
          writing=false;dialog.close();const loaded=await MisraExtraction.refresh();
          if(!loaded)$('extraction-error').textContent=t('Change saved, but the list could not refresh. Refresh Extraction before continuing; do not repeat the removal.');
          else showToast(t(result.message));
        }
      }catch(error){$('removal-error').textContent=error.message+' '+t('Close and refresh Extraction before trying again.');}
      finally{writing=false;confirmState();}
    }).then(()=>{if(returnAfterWrite){(returnAfterWrite.isConnected?returnAfterWrite:$('reading-question'))?.focus({preventScroll:true});returnAfterWrite=null;}else if(dialog.open)$('cancel-removal').focus({preventScroll:true});});
  });
  document.addEventListener('click',event=>{
    const source=event.target.closest('[data-exclude-source]'),remove=event.target.closest('[data-remove-question]'),restore=event.target.closest('[data-restore-question]');
    if(source)open(source,'source',source.dataset.excludeSource);
    if(remove)open(remove,'question',remove.dataset.removeQuestion);
    if(restore)open(restore,'question',restore.dataset.restoreQuestion,'restore');
  });
  window.addEventListener('misra:extraction-rendered',renderRemoved);
  renderRemoved();
})();
