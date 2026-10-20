/* Automatic locations and versioned, instructor-confirmed extraction corrections. */
(function () {
  'use strict';
  const $=id=>document.getElementById(id), esc=value=>MisraUI.escapeHTML(String(value??''));
  const prefix='misra-highlight:';
  const t=value=>window.MisraLocale?.text(value)||value;
  let context=null, selected='', editing=false, draft=null, changed=false, drag=null;
  let locating=false, locationTimer=null, locationEpoch=0, locationMessage='';
  let areaJob=null,areaPreview=null,areaText='',completeArea=false,areaBusy=false,areaTimer=null,areaEpoch=0;
  const copy=box=>box?{...box}:null;
  const key=id=>prefix+context.paperId+':'+context.pageIndex+':'+id;
  function saved(id){if(context?.locations[id]?.method==='instructor_confirmed_area')return null;try{const value=JSON.parse(localStorage.getItem(key(id)));return value?.version===1?MisraEvidence.validBox(value.box):null;}catch(_){return null;}}
  function base(source){return MisraEvidence.location(source,context.locations);}
  function boxStyle(box){return `left:${box.x*100}%;top:${box.y*100}%;width:${box.width*100}%;height:${box.height*100}%`;}
  function draw(){
    if(!context || !$('evidence-boxes'))return;
    let matched=0, approximate=0, located=0, confirmed=0, adjusted=0, unavailable=0, unsaved=0;
    $('evidence-boxes').innerHTML=context.sources.map(source=>{
      const original=base(source), override=saved(source.id), isDraft=editing&&selected===source.id;
      const box=isDraft?draft:override||original.box;
      if(!box){unavailable++;return '';}
      if(isDraft&&changed)unsaved++;else if(override)adjusted++;else if(original.confirmed)confirmed++;else if(original.verified)matched++;else if(context.locations[source.id]?.method==='vision_grid')located++;else approximate++;
      const kind=isDraft?'editing':override||original.confirmed?'adjusted':original.verified?'':'approximate';
      return `<span class="evidence-box ${kind}" style="${boxStyle(box)}" aria-hidden="true"></span>`;
    }).join('');
    $('location-note').innerHTML=`${matched} <span data-i18n>text-matched</span>, ${approximate} <span data-i18n>approximate OCR regions</span>${confirmed?`, ${confirmed} <span data-i18n>instructor-selected areas</span>`:''}${located?`, ${located} <span data-i18n>AI-located regions</span>`:''}${adjusted?`, ${adjusted} <span data-i18n>adjusted on this device</span>`:''}${unsaved?`, ${unsaved} <span data-i18n>unsaved adjustment</span>`:''}. <span data-i18n>Full page retained. Highlights do not verify marks.</span>${unavailable?' <span data-i18n>Highlight unavailable for some extracted parts.</span>':''}`;
    $('evidence-boxes').classList.toggle('highlight-drawing',editing);
    $('evidence-boxes').tabIndex=editing?0:-1;
    if(editing){$('evidence-boxes').setAttribute('role','group');$('evidence-boxes').setAttribute('aria-label',t('Draw answer highlight. Arrow keys move; Shift and arrow keys resize.'));}
    else{$('evidence-boxes').removeAttribute('role');$('evidence-boxes').removeAttribute('aria-label');}
    const save=$('save-highlight');if(save)save.disabled=!areaPreview||!completeArea||!areaText.trim()||areaBusy;
    for(const id of ['area-text','complete-area','cancel-highlight','highlight-part'])if($(id))$(id).disabled=areaBusy;
    context.onDirtyChange?.(changed||Boolean(areaPreview));
  }
  function controls(message=locationMessage){
    locationMessage=message;
    const host=$('highlight-tools');if(!host)return;
    host.hidden=!context?.sources.length;
    if(host.hidden){host.replaceChildren();return;}
    if(!context.editable){host.innerHTML=`<a href="${esc(context.extractionUrl||'extraction.html')}">Edit answer area in Extraction</a><p id="highlight-status" role="status" data-i18n>${esc(message)}</p>`;draw();return;}
    const pending=context.sources.find(source=>source.pending_area_job_id);
    host.innerHTML=`<div class="inline-actions"><button type="button" id="adjust-highlight" ${editing?'hidden':''}>Select answer area</button>${!editing&&pending?'<button type="button" id="continue-area">Continue area review</button>':''}</div>${editing?`<div class="highlight-editor"><label for="highlight-part" ${context.sources.length===1?'hidden':''}>Extracted part</label><select id="highlight-part" ${context.sources.length===1?'hidden':''} ${areaBusy?'disabled':''}>${context.sources.map((source,index)=>`<option value="${esc(source.id)}" ${source.id===selected?'selected':''}>${esc(source.area_label||String(index+1))}</option>`).join('')}</select><p data-i18n>Drag around the complete answer for this part.</p><div class="inline-actions"><button type="button" id="read-answer-area" ${areaBusy||areaPreview?'disabled':''}>Read selected area</button><button type="button" id="cancel-highlight">Cancel</button></div>${areaPreview?`<label for="area-text">Review extracted text<textarea id="area-text" dir="auto" maxlength="50000">${esc(areaText)}</textarea></label><label class="check-row"><input type="checkbox" id="complete-area" ${completeArea?'checked':''}> This area contains the complete answer for this part</label><button type="button" id="save-highlight" class="primary" disabled>Save corrected extraction</button>`:''}</div>`:''}<p id="highlight-status" role="status" data-i18n>${esc(message)}</p>`;
    draw();
  }
  function start(id){++areaEpoch;clearTimeout(areaTimer);areaJob=areaPreview=null;areaText='';completeArea=false;areaBusy=false;selected=id;const source=context.sources.find(s=>s.id===id);draft=copy(saved(id)||base(source).box||{x:.1,y:.4,width:.8,height:.2});changed=false;drag=null;editing=true;controls();}
  function canLeave(){if((changed||areaPreview)&&!confirm(t('Discard the unsaved highlight adjustment?')))return false;++areaEpoch;clearTimeout(areaTimer);areaPreview=areaJob=null;areaBusy=false;editing=false;changed=false;draft=null;drag=null;controls();return true;}
  function mount(value){locationMessage='';context=value;selected=value.sources.some(source=>source.id===value.selectedSourceId)?value.selectedSourceId:value.sources[0]?.id||'';editing=changed=false;draft=drag=null;controls();locate();}
  function clear(){++areaEpoch;clearTimeout(areaTimer);areaPreview=areaJob=null;areaBusy=false;context?.onDirtyChange?.(false);++locationEpoch;clearTimeout(locationTimer);locating=false;locationMessage='';context=null;editing=changed=false;draft=drag=null;const host=$('highlight-tools');if(host){host.replaceChildren();host.hidden=true;}}
  function status(message){$('highlight-status').textContent=t(message);}
  const samePage=value=>context&&context.paperId===value.paperId&&context.pageIndex===value.pageIndex;
  async function watchLocation(job,value,token){
    if(token!==locationEpoch||!samePage(value))return;
    if(['queued','processing','retrying'].includes(job.status)){
      locating=true;locationStatus('Locating the answer in the background. Your grades stay unchanged.');
      locationTimer=setTimeout(async()=>{try{const latest=await MisraAPI.job(job.id);if(latest?.id!==job.id)throw new Error('Location status was incomplete.');await watchLocation(latest,value,token);}catch(_){if(token===locationEpoch&&samePage(value)){locating=false;locationStatus('Location progress interrupted. Refresh to reconnect; your saved results are retained.');}}},3000);return;
    }
    locating=false;
    if(job.status==='completed'){
      try{const locations=await MisraEvidence.pageLocations(value.paperId,value.pageIndex);if(token!==locationEpoch||!samePage(value))return;context.locations=locations;
        locationStatus(editing?'Automatic highlighting finished. Your manual selection is unchanged.':context.sources.some(source=>saved(source.id))?'Your selected answer area is kept.':context.sources.some(source=>base(source).box)?'Answer areas selected automatically. You can correct them if needed.':'AI could not select an answer area. Select the area manually.');
        const box=$('evidence-boxes')?.querySelector('.evidence-box'),viewport=$('paper-viewport');if(!editing&&box&&viewport)viewport.scrollTop=Math.max(0,box.offsetTop-(viewport.clientHeight-box.offsetHeight)/2);}
      catch(_){if(token===locationEpoch&&samePage(value))locationStatus('Locations could not load. Refresh to retry.');}
    }else locationStatus('AI could not select an answer area. Select the area manually.');
  }
  function locationStatus(message){locationMessage=message;if(editing){draw();status(t(message));}else controls(message);}
  async function waitForTask(job,value,token){
    if(token!==locationEpoch||!samePage(value))return;
    locating=true;locationStatus('Answer areas will be located automatically when the current task finishes.');
    locationTimer=setTimeout(async()=>{try{const current=await MisraAPI.job(job.id);if(current?.id!==job.id)throw new Error('Invalid task status');
      if(token!==locationEpoch||!samePage(value))return;
      if(['queued','processing','retrying'].includes(current.status))waitForTask(current,value,token);
      else {locating=false;locate();}
    }catch(_){if(token===locationEpoch&&samePage(value)){locating=false;locationStatus('Automatic highlighting paused. You can select the answer area manually.');}}},3000);
  }
  async function locate(){
    if(!context?.sources.length||locating)return;
    if(context.sources.every(source=>saved(source.id)||base(source).confirmed||base(source).verified||context.locations[source.id]?.method==='vision_grid'))return;
    const value=context,token=++locationEpoch;clearTimeout(locationTimer);locating=true;
    locationStatus('Locating answer areas automatically…');
    try{const response=await MisraAPI.locateAnswers(value.paperId,value.pageIndex,true);
      if(token!==locationEpoch||!samePage(value))return;
      if(response?.waiting_for?.id){waitForTask(response.waiting_for,value,token);return;}
      const job=response?.job;
      if(!job?.id||job.submission_id!==value.paperId||job.operation!=='locate_answers'||job.page_index!==value.pageIndex)throw new Error('Automatic highlighting paused. You can select the answer area manually.');
      await watchLocation(job,value,token);
    }catch(_){if(token===locationEpoch&&samePage(value)){locating=false;locationStatus('Automatic highlighting paused. You can select the answer area manually.');}}
  }
  async function watchArea(value,token,sourceId,jobId){
    try{const record=await MisraAPI.answerAreaPreview(sourceId,jobId);if(token!==areaEpoch||!samePage(value))return;
      if(record?.source_id!==sourceId||record?.job?.id!==jobId)throw Error('Area response was incomplete. Refresh before retrying.');
      if(['queued','processing','retrying'].includes(record.job.status)){areaTimer=setTimeout(()=>watchArea(value,token,sourceId,jobId),3000);return;}
      areaBusy=false;
      if(record.job.status!=='completed'||!record.preview?.text)throw Error('Could not read this area. Adjust the selection and try again.');
      areaPreview=record;areaText=record.preview.text;completeArea=false;draft=MisraEvidence.validBox(record.bounding_box);changed=true;
      controls('Review the text, then save the corrected extraction.');
    }catch(error){if(token===areaEpoch&&samePage(value)){areaBusy=false;controls(error.message);}}
  }
  async function readArea(){
    if(!editing||areaBusy||!MisraEvidence.validBox(draft))return;
    if(context.canEdit?.()===false){status('Save other extraction edits first.');return;}
    const value=context,source=value.sources.find(item=>item.id===selected),token=++areaEpoch;
    areaBusy=true;areaPreview=null;completeArea=false;controls('Reading selected area…');
    try{const response=await MisraAPI.readAnswerArea(source.id,{bounding_box:draft,expected_text:source.extracted_text});
      if(token!==areaEpoch||!samePage(value))return;
      if(!response?.job?.id||response.job.operation!=='read_answer_area')throw Error('Could not confirm the area request. Check Activity before retrying.');
      areaJob=response.job.id;source.pending_area_job_id=areaJob;await watchArea(value,token,source.id,areaJob);
    }catch(error){if(token===areaEpoch&&samePage(value)){areaBusy=false;controls(error.message);}}
  }
  async function saveArea(){
    if(!areaPreview||areaBusy||!completeArea||!areaText.trim())return;
    if(context.canEdit?.()===false){status('Save other extraction edits first.');return;}
    const value=context,source=value.sources.find(item=>item.id===selected),token=areaEpoch;
    areaBusy=true;draw();
    try{const response=await MisraAPI.confirmAnswerArea(source.id,areaJob,{text:areaText,
      expected_preview_text:areaPreview.preview.text,expected_revision_id:areaPreview.expected_revision_id??null,complete_answer:true});
      if(token!==areaEpoch||!samePage(value))return;
      if(!response?.revision?.id||response.revision.source_id!==source.id)throw Error('Correction response was incomplete. Reload to check saved extraction.');
      source.area_revision=response.revision;source.pending_area_job_id=null;
      context.locations[source.id]={status:'located',method:'instructor_confirmed_area',bounding_box:response.revision.bounding_box,revision_id:response.revision.id};
      areaBusy=false;areaPreview=null;changed=editing=false;draft=null;
      controls(response.requires_regrade?'Corrected extraction saved. Regrade this answer to update its AI proposal.':'Corrected extraction saved. Ready for grading.');
      await value.onAreaConfirmed?.(response);
    }catch(error){if(token===areaEpoch&&samePage(value)){areaBusy=false;status(error.message);draw();}}
  }
  $('highlight-tools').addEventListener('click',event=>{
    const id=event.target.closest('button')?.id;
    if(id==='adjust-highlight'){if(context.canEdit?.()===false){status('Wait for the current save to finish.');return;}start(selected||context.sources[0].id);$('evidence-boxes').focus({preventScroll:true});}
    if(id==='continue-area'){const source=context.sources.find(item=>item.pending_area_job_id);if(source){start(source.id);areaJob=source.pending_area_job_id;areaBusy=true;controls('Reading selected area…');watchArea(context,++areaEpoch,source.id,areaJob);}return;}
    if(id==='cancel-highlight'){changed=false;areaPreview=null;canLeave();$('adjust-highlight')?.focus({preventScroll:true});return;}
    if(id==='read-answer-area'){readArea();return;}
    if(id==='save-highlight'){saveArea();return;}
  });
  $('highlight-tools').addEventListener('input',event=>{if(event.target.id==='area-text'){areaText=event.target.value;changed=true;draw();}if(event.target.id==='complete-area'){completeArea=event.target.checked;draw();}});
  $('highlight-tools').addEventListener('change',event=>{if(event.target.id!=='highlight-part')return;const id=event.target.value;if(changed&&!confirm(t('Discard the unsaved highlight adjustment?'))){event.target.value=selected;return;}start(id);});
  const point=event=>{const rect=$('evidence-boxes').getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))};};
  $('paper-viewport').addEventListener('pointerdown',event=>{
    if(!editing||areaBusy||event.button!==0||event.target!==$('evidence-boxes')||!event.target.getBoundingClientRect().height)return;
    event.preventDefault();if(areaPreview){areaPreview=null;areaText='';completeArea=false;controls('Area changed. Read selected area again.');}drag={...point(event),pointer:event.pointerId,prior:copy(draft),priorChanged:changed};event.target.setPointerCapture(event.pointerId);
  });
  $('paper-viewport').addEventListener('pointermove',event=>{
    if(!drag||event.pointerId!==drag.pointer)return;const end=point(event);
    draft={x:Math.min(end.x,drag.x),y:Math.min(end.y,drag.y),width:Math.abs(end.x-drag.x),height:Math.abs(end.y-drag.y)};changed=true;draw();
  });
  function finish(event){if(!drag||event.pointerId!==drag.pointer)return;const rect=$('evidence-boxes').getBoundingClientRect();if(event.type==='pointercancel'||!draft||draft.width*rect.width<5||draft.height*rect.height<5){draft=drag.prior;changed=drag.priorChanged;}drag=null;draw();}
  $('paper-viewport').addEventListener('pointerup',finish);$('paper-viewport').addEventListener('pointercancel',finish);
  $('paper-viewport').addEventListener('keydown',event=>{
    if(!editing||areaBusy||event.target!==$('evidence-boxes'))return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();$('cancel-highlight').click();return;}
    if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
    event.preventDefault();if(areaPreview){areaPreview=null;areaText='';completeArea=false;controls('Area changed. Read selected area again.');}const box=copy(draft),horizontal=['ArrowLeft','ArrowRight'].includes(event.key),delta=['ArrowRight','ArrowDown'].includes(event.key)?0.01:-0.01;
    if(event.shiftKey){const field=horizontal?'width':'height',start=horizontal?box.x:box.y;box[field]=Math.max(.01,Math.min(1-start,box[field]+delta));}
    else {const field=horizontal?'x':'y',size=horizontal?box.width:box.height;box[field]=Math.max(0,Math.min(1-size,box[field]+delta));}
    draft=box;changed=true;draw();
  });
  window.MisraPaperHighlights={mount,clear,canLeave,hasUnsaved:()=>changed||Boolean(areaPreview),selectSource:id=>{if(context?.editable&&context.sources.some(source=>source.id===id)&&canLeave()){start(id);$('evidence-boxes').focus({preventScroll:true});}}};
  window.addEventListener('misra:language',draw);
})();
