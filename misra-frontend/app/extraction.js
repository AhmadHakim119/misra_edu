/* Extraction corrections use saved evidence APIs. Drafts stay in memory. */
(function(){
  'use strict';const {$,esc,number,link,params,ready,operation,setDirty}=MisraApp;
  let report=null,id=params.get('submission_id')||params.get('id'),page=0,dirty=false,timer,sequence=0,preview=null,previewPage=null,viewerSequence=0,requestedSourceApplied=false,activeSourceId=null;
  const drafts=new Map();
  let activeQuestionId=params.get('question_id');
  function updateQuestionNavigation(questionId){
    const index=report.questions.findIndex(row=>row.question.id===questionId);
    if(index<0)return;
    activeQuestionId=questionId;$('reading-question').value=questionId;
    $('go-grading').href=link('grading',{exam_id:report.submission.exam_id,submission_id:id,question_id:questionId});
    $('reading-position').textContent=`${index+1} / ${report.questions.length}`;
    $('question-prev').disabled=index===0;$('question-next').disabled=index===report.questions.length-1;
    document.querySelectorAll('#mapping-host .extraction-item').forEach(el=>el.classList.toggle('selected-answer',el.id==='extracted-question-'+questionId));
  }
  function revealQuestion(){
    const heading=document.getElementById('extracted-question-'+activeQuestionId)?.querySelector('h3');
    if(heading){heading.focus({preventScroll:true});heading.scrollIntoView({block:'start'});}
  }
  function unavailableLocation(){++viewerSequence;activeSourceId=null;MisraPaperHighlights.clear();$('location-note').textContent=MisraLocale.text('No answer location is saved for this question. Inspect the original pages and unmatched work.');}
  function chooseQuestion(questionId){
    if(!MisraPaperHighlights.canLeave()){$('reading-question').value=activeQuestionId;return;}
    const row=report.questions.find(row=>row.question.id===questionId);if(!row)return;
    updateQuestionNavigation(questionId);
    if(row.sources.length){page=row.sources[0].page_index;original(row.sources[0].id);}
    else unavailableLocation();
    revealQuestion();
  }
  function missingAnswers(){
    const numbers=Array.isArray(report.readiness.missing_question_numbers)?report.readiness.missing_question_numbers.filter(number=>typeof number==='string'):[];
    if(!numbers.length)return '';
    return `<section id="missing-answers" class="readiness-notice" aria-labelledby="missing-answers-title"><h2 id="missing-answers-title" data-i18n>Questions without a mapped answer</h2><ul>${numbers.map(number=>{const row=report.questions.find(row=>row.question.question_number===number),label=`<span data-i18n>Question</span> <bdi data-no-translate>${esc(number)}</bdi>`;return `<li>${row?`<button type="button" data-missing-question="${esc(row.question.id)}">${label}</button>`:label}</li>`;}).join('')}</ul><p data-i18n>Check the original paper and unmatched work before assigning or recovering an answer.</p></section>`;
  }
  const syncDirty=()=>setDirty(dirty||MisraPaperHighlights.hasUnsaved());
  const formKey=form=>form?.dataset.source?'source:'+form.dataset.source:form?.dataset.unmatched!=null?'fragment:'+form.dataset.fingerprint:form?.id;
  function markDirty(e){const form=e.target.closest('form');if(form)drafts.set(formKey(form),Object.fromEntries([...form.querySelectorAll('input,textarea,select')].filter(el=>el.name||el.id).map(el=>[el.name||el.id,el.value])));dirty=drafts.size>0;syncDirty();$('extraction-state').textContent='Unsaved extraction changes';}
  function restoreDrafts(){document.querySelectorAll('#extraction-workbench form').forEach(form=>{const values=drafts.get(formKey(form));if(values)form.querySelectorAll('input,textarea,select').forEach(el=>{if(Object.hasOwn(values,el.name||el.id))el.value=values[el.name||el.id];});});dirty=drafts.size>0;syncDirty();if(dirty)$('extraction-state').textContent='Unsaved extraction changes';}
  function clearPreview(){preview=null;previewPage=null;$('confirm-recovery').hidden=true;$('recovery-preview').textContent='';}
  const options=(selected='')=>report.questions.map(r=>`<option value="${esc(r.question.id)}" ${selected===r.question.id?'selected':''}>${esc(MisraLocale.text('Question'))} ${esc(r.question.question_number)}</option>`).join('');
  async function original(selectSourceId=null,editArea=false,force=false){if(!report)return;
    const row=report.questions.find(row=>row.sources.some(source=>source.id===selectSourceId));if(row)updateQuestionNavigation(row.question.id);
    if(!force&&!editArea&&selectSourceId&&MisraPaperHighlights.focusSource(selectSourceId)){activeSourceId=selectSourceId;return;}
    const viewer=++viewerSequence;MisraPaperHighlights.clear();if(previewPage!==null&&previewPage!==page)clearPreview();const total=Number(report.submission.page_count)||0;page=Math.max(0,Math.min(page,total-1));$('extraction-page').innerHTML=`<span data-i18n>Page</span> <bdi data-no-translate>${page+1} / ${total}</bdi>`;
    $('location-note').textContent=window.MisraLocale?.text('Loading saved answer locations…')||'Loading saved answer locations…';
    $('evidence-boxes').setAttribute('aria-busy','true');
    $('extraction-image').src=MisraAPI.submissionPageUrl(id,page);$('extraction-image').alt=`Full original paper, page ${page+1}`;
    $('page-prev').disabled=page===0;$('page-next').disabled=page>=total-1;
    const sources=report.questions.flatMap(row=>row.sources.map(source=>({...source,question_number:row.question.question_number,question_id:row.question.id}))).filter(source=>source.page_index===page);
    activeSourceId=sources.find(source=>source.id===(selectSourceId||activeSourceId||params.get('source_id')))?.id||sources[0]?.id||null;
    let locations={},locationsFailed=false;try{locations=await MisraEvidence.pageLocations(id,page);}catch(_){locationsFailed=true;}
    if(viewer!==viewerSequence)return;
    MisraPaperHighlights.mount({paperId:id,pageIndex:page,sources,locations,locationsFailed,editable:true,revealSelected:Boolean(selectSourceId),
      selectedSourceId:activeSourceId,canEdit:()=>!dirty&&!MisraApp.isBusy(),onRetryLocations:()=>original(activeSourceId,false,true),onRetryImage:()=>{$('extraction-image').src=MisraAPI.submissionPageUrl(id,page);},
      onDirtyChange:areaDirty=>setDirty(dirty||areaDirty),onAreaConfirmed:async()=>{await load();showToast('Corrected extraction saved. Review it before grading.');}});
    if(editArea&&selectSourceId)MisraPaperHighlights.selectSource(selectSourceId);
  }
  function render(){const s=report.submission;if(!requestedSourceApplied){const requested=report.questions.flatMap(row=>row.sources).find(source=>source.id===params.get('source_id'))||report.questions.find(row=>row.question.id===activeQuestionId)?.sources[0];if(requested){page=requested.page_index;activeSourceId=requested.id;activeQuestionId=report.questions.find(row=>row.sources.some(source=>source.id===requested.id))?.question.id;}requestedSourceApplied=true;}$('extraction-title').textContent=s.extracted_student_name||'Review extracted paper';
    $('identity-name').value=s.extracted_student_name||'';$('identity-number').value=s.extracted_student_number||'';
    $('extraction-state').textContent=report.readiness.bulk_grading_allowed?'Extraction is ready for grading.':(report.readiness.blocking_reasons||[]).join(' ');
    $('go-grading').href=link('grading',{exam_id:s.exam_id,submission_id:id});$('start-grading').disabled=!report.readiness.bulk_grading_allowed;$('start-grading').hidden=report.questions.some(row=>row.answer?.score!=null);
    $('reprocess-paper').disabled=!report.readiness.can_reprocess;
    $('mapping-host').innerHTML=report.questions.map(row=>`<section class="extraction-item" id="extracted-question-${esc(row.question.id)}"><h3 tabindex="-1"><span data-i18n>Question</span> <bdi data-no-translate>${esc(row.question.question_number)}</bdi></h3><div class="extraction-question-actions"><a class="question-definition-link" href="${link('setup',{exam_id:s.exam_id,rubric_question:row.question.id})}">Edit question details</a><button type="button" class="extraction-remove" data-remove-question="${esc(row.question.id)}">Remove question from exam</button></div><p dir="auto">${esc(row.question.question_text)}</p>${(row.mapping_flags||[]).map(f=>`<p class="page-error">${esc(f.message)}</p>`).join('')}${!row.sources.length?'<p>No answer segment mapped. Inspect unmatched work or recover this page.</p>':''}${row.sources.map(source=>`<form data-source="${esc(source.id)}"><label><span><span data-i18n>Extracted answer</span> · <span data-i18n>Page</span> <bdi data-no-translate>${source.page_index+1}</bdi></span><textarea dir="auto" name="text" ${row.answer?.score!=null||source.area_revision?'readonly':''}>${esc(source.area_revision?.text??source.extracted_text)}</textarea></label><div class="form-grid"><label>Belongs to<select name="question_id" ${row.answer?.score!=null?'disabled':''}>${options(row.question.id)}</select></label></div><div class="inline-actions"><button type="submit" ${row.answer?.score!=null?'disabled':''}>Save correction</button><button type="button" data-show-page="${source.page_index}">Show original page</button><button type="button" data-select-area="${esc(source.id)}">Select answer area</button><button type="button" class="extraction-remove" data-exclude-source="${esc(source.id)}" ${row.can_remove_sources===false||row.answer?.score!=null||row.answer?.teacher_override_score!=null?'disabled':''}>Remove extracted entry</button></div>${source.area_revision?`<p class="notice">Corrected extraction saved. <a href="${link('grading',{exam_id:s.exam_id,submission_id:id,question_id:row.question.id})}">Review &amp; regrade</a></p>`:''}${row.can_remove_sources===false||row.answer?.score!=null||row.answer?.teacher_override_score!=null?'<small class="removal-lock" data-i18n>This entry has grading history. Correct its answer area and explicitly regrade; its saved evidence cannot be deleted.</small>':''}</form>`).join('')}</section>`).join('');
    $('unmatched-host').innerHTML=(report.unmatched_segments||[]).map(seg=>`<form class="extraction-item" data-unmatched="${seg.unmatched_index}" data-fingerprint="${esc(JSON.stringify([seg.page_index,seg.text||seg.extracted_text]))}"><p dir="auto">${esc(seg.text||seg.extracted_text||'')}</p><div class="form-grid"><label>Question<select name="question_id">${options()}</select></label><label>Original page<input name="page" type="number" min="1" max="${s.page_count}" value="${Number(seg.page_index??0)+1}"></label></div><div class="inline-actions"><button name="assign" type="submit">Assign to question</button><button type="button" data-ignore="${seg.unmatched_index}">Exclude as non-answer</button></div></form>`).join('')||'<p>No unmatched fragments.</p>';
    const missing=missingAnswers(),coverage=(report.coverage?.issues||[]).map(issue=>`<p class="readiness-notice">${esc(issue.message||issue.code)}</p>`).join('');
    $('coverage-host').innerHTML=missing+coverage||'<p data-i18n>No outstanding coverage issues recorded. Inspect the original pages before grading.</p>';
    $('recovery-questions').innerHTML=report.questions.map(row=>`<label><input type="checkbox" value="${esc(row.question.question_number)}"> Question ${esc(row.question.question_number)}</label>`).join('');
    $('reading-navigation').hidden=!report.questions.length;$('reading-question').innerHTML=options();
    if(activeQuestionId&&!report.questions.some(row=>row.question.id===activeQuestionId)&&report.questions[0]?.sources[0]){page=report.questions[0].sources[0].page_index;activeSourceId=report.questions[0].sources[0].id;}
    updateQuestionNavigation(report.questions.some(row=>row.question.id===activeQuestionId)?activeQuestionId:report.questions[0]?.question.id);
    window.dispatchEvent(new Event('misra:extraction-rendered'));
    const selected=activeQuestionId;original().then(()=>{if(selected===activeQuestionId&&!report.questions.find(row=>row.question.id===selected)?.sources.length)unavailableLocation();});
  }
  async function load(){const request=++sequence;try{if(!id){const rows=await MisraAPI.submissions(params.get('exam_id'));if(!Array.isArray(rows))throw Error('Paper list is incomplete.');$('extraction-list').innerHTML=rows.map(s=>`<div class="record-row"><div><h3>${esc(s.extracted_student_name||'Name missing')}</h3><p>${esc(s.extracted_student_number||'Student number missing')} · ${esc(s.status)}</p></div><a class="button" href="${link('extraction',{exam_id:s.exam_id,submission_id:s.id})}">Review extraction</a></div>`).join('')||'<p>Upload student papers to review their extraction.</p>';$('extraction-workbench').hidden=true;return;}
      const data=await MisraAPI.extractionReview(id);if(request!==sequence)return;if(data?.submission?.id!==id||!Array.isArray(data.questions))throw Error('Extraction response is incomplete.');report=data;$('extraction-error').textContent='';render();restoreDrafts();
      const jobs=await MisraAPI.submissionJobs(id,'ocr_submission');const rows=Array.isArray(jobs)?jobs:jobs?.items||[];const running=rows.find(j=>!['locate_answers','read_answer_area'].includes(j.operation)&&['queued','processing','retrying'].includes(j.status));
      clearTimeout(timer);if(running){$('extraction-state').textContent=`Extraction agent: ${running.progress_message||running.status}`;timer=setTimeout(()=>{if(!dirty&&!MisraPaperHighlights.hasUnsaved())load();},5000);}
      return true;
    }catch(e){$('extraction-error').textContent=e.message;return false;}}
  async function save(button,fn){if(MisraPaperHighlights.hasUnsaved()){showToast('Save or cancel the answer area correction first.','error');return;}const key=formKey(button?.closest('form'));await operation(button,async()=>{await fn();if(key)drafts.delete(key);$('extraction-error').textContent='';await load();});}
  $('mapping-host').addEventListener('input',markDirty);$('identity-form').addEventListener('input',markDirty);
  $('unmatched-host').addEventListener('input',markDirty);
  $('coverage-host').addEventListener('click',event=>{const button=event.target.closest('[data-missing-question]');if(button)chooseQuestion(button.dataset.missingQuestion);});
  $('reading-question').addEventListener('change',event=>chooseQuestion(event.target.value));
  for(const [button,delta] of [['question-prev',-1],['question-next',1]])$(button).addEventListener('click',()=>{const index=report.questions.findIndex(row=>row.question.id===activeQuestionId);const next=report.questions[index+delta];if(next)chooseQuestion(next.question.id);});
  $('return-to-answer').addEventListener('click',revealQuestion);
  window.addEventListener('misra:language',()=>{if(report)document.querySelectorAll('#reading-question,select[name=question_id]').forEach(select=>{select.innerHTML=options(select.value);});});
  $('mapping-host').addEventListener('submit',e=>{e.preventDefault();const form=e.target,source=report.questions.flatMap(r=>r.sources).find(s=>s.id===form.dataset.source),target=new FormData(form);save(e.submitter,async()=>{
    if(target.get('text')!==(source.area_revision?.text??source.extracted_text)){await MisraAPI.correctSourceText(source.id,{text:target.get('text'),expected_text:source.extracted_text});source.extracted_text=target.get('text');}
    const current=report.questions.find(r=>r.sources.some(s=>s.id===source.id));if(target.get('question_id')!==current.question.id)await MisraAPI.moveAnswerSource(source.id,target.get('question_id'));
  });});
  $('identity-form').addEventListener('submit',e=>{e.preventDefault();save(e.submitter,()=>MisraAPI.updateSubmissionMetadata(id,{student_name:$('identity-name').value.trim()||null,student_number:$('identity-number').value.trim()||null}));});
  $('unmatched-host').addEventListener('submit',e=>{e.preventDefault();const form=e.target,data=new FormData(form);save(e.submitter,()=>MisraAPI.resolveUnmatchedSegment(id,Number(form.dataset.unmatched),{action:'assign',question_id:data.get('question_id'),page_index:Number(data.get('page'))-1}));});
  $('mapping-host').addEventListener('focusin',e=>{const sourceId=e.target.closest('form[data-source]')?.dataset.source;if(!sourceId||sourceId===activeSourceId||!e.target.matches('textarea,select')||MisraPaperHighlights.hasUnsaved())return;const source=report.questions.flatMap(row=>row.sources).find(item=>item.id===sourceId);if(source){page=source.page_index;original(sourceId);}});
  document.addEventListener('click',e=>{const p=e.target.closest('[data-show-page]'),ignore=e.target.closest('[data-ignore]'),remove=e.target.closest('[data-remove-source]'),area=e.target.closest('[data-select-area]');if(p&&MisraPaperHighlights.canLeave()){page=Number(p.dataset.showPage);const sourceId=p.closest('form[data-source]')?.dataset.source;original(sourceId).then(()=>MisraPaperHighlights.revealSource(sourceId));}if(area&&MisraPaperHighlights.canLeave()){const source=report.questions.flatMap(row=>row.sources).find(item=>item.id===area.dataset.selectArea);if(source){page=source.page_index;original(source.id,true);}}
    if(ignore&&confirm('Exclude this fragment as non-answer content? The stored original page remains available.'))save(ignore,()=>MisraAPI.resolveUnmatchedSegment(id,Number(ignore.dataset.ignore),{action:'ignore'}));
    if(remove&&confirm('Return this manually assigned fragment to unmatched evidence?'))save(remove,()=>MisraAPI.removeAnswerSource(remove.dataset.removeSource));});
  $('page-prev').addEventListener('click',()=>{if(MisraPaperHighlights.canLeave()){page--;original();}});$('page-next').addEventListener('click',()=>{if(MisraPaperHighlights.canLeave()){page++;original();}});$('page-zoom').addEventListener('click',()=>{const image=$('extraction-image');const zoomed=image.classList.toggle('zoomed');image.parentElement.style.width=zoomed?'180%':'100%';$('page-zoom').setAttribute('aria-pressed',String(zoomed));});
  $('extraction-refresh').addEventListener('click',()=>{if(MisraPaperHighlights.canLeave()&&(!dirty||confirm('Discard unsaved extraction edits and reload?'))){drafts.clear();load();}});
  $('start-grading').addEventListener('click',e=>{if(dirty||MisraPaperHighlights.hasUnsaved()){showToast('Save your extraction corrections first.','error');return;}operation(e.target,async()=>{const result=await MisraAPI.gradeSubmission(id);if(!result?.job?.id)throw Error('Grading acceptance is uncertain. Check activity before retrying.');location.href=link('grading',{exam_id:report.submission.exam_id,submission_id:id,job_id:result.job.id});});});
  $('reprocess-paper').addEventListener('click',e=>{if(dirty||MisraPaperHighlights.hasUnsaved()||!confirm('Re-extract this ungraded paper? Saved originals remain available.'))return;operation(e.target,async()=>{await MisraAPI.reprocessExtraction(id);await load();});});
  $('recover-page').addEventListener('click',e=>operation(e.target,async()=>{if(dirty||MisraPaperHighlights.hasUnsaved())throw Error('Save your edits before recovering a page.');clearPreview();const numbers=[...$('recovery-questions').querySelectorAll('input:checked')].map(i=>i.value);if(!numbers.length)throw Error('Select the questions visible on this page.');const candidate=await MisraAPI.previewPageRecovery(id,page,numbers);if(!Array.isArray(candidate?.segments)||!candidate.segments.length)throw Error('No answer segments returned. Inspect the page and try again.');preview=candidate;previewPage=page;$('recovery-preview').textContent=preview.segments.map(s=>`${s.question_number||'Unassigned'}: ${s.text}`).join('\n');$('confirm-recovery').hidden=false;}));
  $('confirm-recovery').addEventListener('click',e=>save(e.target,async()=>{if(dirty||MisraPaperHighlights.hasUnsaved())throw Error('Save your edits before applying recovery.');if(!preview||previewPage!==page)throw Error('Preview this page again.');await MisraAPI.confirmPageRecovery(id,previewPage,preview);clearPreview();}));
  window.MisraExtraction={report:()=>report,hasUnsaved:()=>dirty||MisraPaperHighlights.hasUnsaved(),refresh:load,applyReport:value=>{if(value?.submission?.id!==id||!Array.isArray(value.questions))throw Error('The updated extraction response is incomplete. Refresh before continuing.');report=value;render();restoreDrafts();}};
  ready.then(load).catch(e=>$('extraction-error').textContent=e.message);
})();
