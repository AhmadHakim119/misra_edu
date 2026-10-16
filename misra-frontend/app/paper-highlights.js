/* Display corrections only: coordinates stay on this device, never in OCR/runs. */
(function () {
  'use strict';
  const $=id=>document.getElementById(id), esc=value=>MisraUI.escapeHTML(String(value??''));
  const prefix='misra-highlight:';
  const t=value=>window.MisraLocale?.text(value)||value;
  let context=null, selected='', editing=false, draft=null, changed=false, drag=null;
  const copy=box=>box?{...box}:null;
  const key=id=>prefix+context.paperId+':'+context.pageIndex+':'+id;
  function saved(id){try{const value=JSON.parse(localStorage.getItem(key(id)));return value?.version===1?MisraEvidence.validBox(value.box):null;}catch(_){return null;}}
  function base(source){return MisraEvidence.location(source,context.locations);}
  function boxStyle(box){return `left:${box.x*100}%;top:${box.y*100}%;width:${box.width*100}%;height:${box.height*100}%`;}
  function draw(){
    if(!context || !$('evidence-boxes'))return;
    let matched=0, approximate=0, adjusted=0, unavailable=0, unsaved=0;
    $('evidence-boxes').innerHTML=context.sources.map(source=>{
      const original=base(source), override=saved(source.id), isDraft=editing&&selected===source.id;
      const box=isDraft?draft:override||original.box;
      if(!box){unavailable++;return '';}
      if(isDraft&&changed)unsaved++;else if(override)adjusted++;else if(original.verified)matched++;else approximate++;
      const kind=isDraft?'editing':override?'adjusted':original.verified?'':'approximate';
      return `<span class="evidence-box ${kind}" style="${boxStyle(box)}" aria-hidden="true"></span>`;
    }).join('');
    $('location-note').innerHTML=`${matched} <span data-i18n>text-matched</span>, ${approximate} <span data-i18n>approximate OCR regions</span>${adjusted?`, ${adjusted} <span data-i18n>adjusted on this device</span>`:''}${unsaved?`, ${unsaved} <span data-i18n>unsaved adjustment</span>`:''}. <span data-i18n>Full page retained. Highlights do not verify marks.</span>${unavailable?' <span data-i18n>Highlight unavailable for some extracted parts.</span>':''}`;
    $('evidence-boxes').classList.toggle('highlight-drawing',editing);
    $('evidence-boxes').tabIndex=editing?0:-1;
    if(editing){$('evidence-boxes').setAttribute('role','group');$('evidence-boxes').setAttribute('aria-label',t('Draw answer highlight. Arrow keys move; Shift and arrow keys resize.'));}
    else{$('evidence-boxes').removeAttribute('role');$('evidence-boxes').removeAttribute('aria-label');}
    const save=$('save-highlight');if(save)save.disabled=!changed||!MisraEvidence.validBox(draft);
  }
  function controls(message=''){
    const host=$('highlight-tools');if(!host)return;
    host.hidden=!context?.sources.length;
    if(host.hidden){host.replaceChildren();return;}
    host.innerHTML=`<div class="inline-actions"><button type="button" id="adjust-highlight" ${editing?'hidden':''}>Adjust highlight</button>${!editing&&context.sources.some(s=>saved(s.id))?'<span class="muted" data-i18n>Adjusted on this device</span>':''}</div>${editing?`<div class="highlight-editor"><label for="highlight-part" ${context.sources.length===1?'hidden':''}>Extracted part</label><select id="highlight-part" ${context.sources.length===1?'hidden':''}>${context.sources.map((s,i)=>`<option value="${esc(s.id)}" ${s.id===selected?'selected':''}>${i+1}</option>`).join('')}</select><p data-i18n>Drag around the answer. Arrow keys move; Shift + arrows resize.</p><p class="muted" data-i18n>Display only. Saved on this device; text and grades stay unchanged.</p><div class="inline-actions"><button type="button" id="save-highlight" class="primary" disabled>Save highlight</button><button type="button" id="cancel-highlight">Cancel</button><button type="button" id="reset-highlight" ${saved(selected)?'':'hidden'}>Reset highlight</button></div></div>`:''}<p id="highlight-status" role="status" data-i18n>${esc(message)}</p>`;
    draw();
  }
  function start(id){selected=id;const source=context.sources.find(s=>s.id===id);draft=copy(saved(id)||base(source).box||{x:.1,y:.4,width:.8,height:.2});changed=false;drag=null;editing=true;controls();}
  function canLeave(){if(changed&&!confirm(t('Discard the unsaved highlight adjustment?')))return false;editing=false;changed=false;draft=null;drag=null;controls();return true;}
  function mount(value){context=value;selected=value.sources[0]?.id||'';editing=changed=false;draft=drag=null;controls();}
  function clear(){context=null;editing=changed=false;draft=drag=null;const host=$('highlight-tools');if(host){host.replaceChildren();host.hidden=true;}}
  function status(message){$('highlight-status').textContent=message;}
  $('highlight-tools').addEventListener('click',event=>{
    const id=event.target.closest('button')?.id;
    if(id==='adjust-highlight'){if(context.canEdit?.()===false){status('Wait for the current save to finish.');return;}start(selected||context.sources[0].id);$('evidence-boxes').focus({preventScroll:true});}
    if(id==='cancel-highlight'){editing=changed=false;draft=drag=null;controls();$('adjust-highlight').focus({preventScroll:true});}
    if(id==='save-highlight'&&changed&&MisraEvidence.validBox(draft)){
      try{localStorage.setItem(key(selected),JSON.stringify({version:1,box:draft}));editing=changed=false;draft=drag=null;controls('Highlight saved on this device.');$('adjust-highlight').focus({preventScroll:true});}
      catch(_){status('Could not save on this device. Your adjustment is still here; retry or cancel.');}
    }
    if(id==='reset-highlight'){
      try{localStorage.removeItem(key(selected));editing=changed=false;draft=drag=null;controls('Original OCR highlight restored.');}
      catch(_){status('Could not reset the highlight. Try again.');}
    }
  });
  $('highlight-tools').addEventListener('change',event=>{if(event.target.id!=='highlight-part')return;const id=event.target.value;if(changed&&!confirm(t('Discard the unsaved highlight adjustment?'))){event.target.value=selected;return;}start(id);});
  const point=event=>{const rect=$('evidence-boxes').getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))};};
  $('paper-viewport').addEventListener('pointerdown',event=>{
    if(!editing||event.button!==0||event.target!==$('evidence-boxes')||!event.target.getBoundingClientRect().height)return;
    event.preventDefault();drag={...point(event),pointer:event.pointerId,prior:copy(draft),priorChanged:changed};event.target.setPointerCapture(event.pointerId);
  });
  $('paper-viewport').addEventListener('pointermove',event=>{
    if(!drag||event.pointerId!==drag.pointer)return;const end=point(event);
    draft={x:Math.min(end.x,drag.x),y:Math.min(end.y,drag.y),width:Math.abs(end.x-drag.x),height:Math.abs(end.y-drag.y)};changed=true;draw();
  });
  function finish(event){if(!drag||event.pointerId!==drag.pointer)return;const rect=$('evidence-boxes').getBoundingClientRect();if(event.type==='pointercancel'||!draft||draft.width*rect.width<5||draft.height*rect.height<5){draft=drag.prior;changed=drag.priorChanged;}drag=null;draw();}
  $('paper-viewport').addEventListener('pointerup',finish);$('paper-viewport').addEventListener('pointercancel',finish);
  $('paper-viewport').addEventListener('keydown',event=>{
    if(!editing||event.target!==$('evidence-boxes'))return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();$('cancel-highlight').click();return;}
    if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
    event.preventDefault();const box=copy(draft),horizontal=['ArrowLeft','ArrowRight'].includes(event.key),delta=['ArrowRight','ArrowDown'].includes(event.key)?0.01:-0.01;
    if(event.shiftKey){const field=horizontal?'width':'height',start=horizontal?box.x:box.y;box[field]=Math.max(.01,Math.min(1-start,box[field]+delta));}
    else {const field=horizontal?'x':'y',size=horizontal?box.width:box.height;box[field]=Math.max(0,Math.min(1-size,box[field]+delta));}
    draft=box;changed=true;draw();
  });
  window.MisraPaperHighlights={mount,clear,canLeave,hasUnsaved:()=>changed};
  window.addEventListener('misra:language',draw);
})();
