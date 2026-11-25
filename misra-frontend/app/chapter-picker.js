/* Chapter choices are drafts. Checked source pages and guide approval remain separate. */
(function(){
  'use strict';
  const routeScope=MisraWorkspace.page;
  const $=id=>document.getElementById(id),esc=MisraUI.escapeHTML;
  let exam='',course='',generation=0,catalog=null,failure='',selectionError='',feedback='',loaded=false;
  const host=document.createElement('section');host.id='assessment-chapters';host.className='assessment-chapters';
  $('assessment-source-catalog').append(host);
  const preferred=m=>m.catalogs.find(c=>c.version.status==='approved')||m.catalogs[0];
  const libraryUrl=(material,version)=>'course-library.html?'+new URLSearchParams({course_id:course,exam_id:exam,...(material?{material_id:material,version_id:version}:{})});
  function selected(){
    selectionError='';
    try{return MisraAssessmentSources.selection();}catch(e){selectionError=e.message;return null;}
  }
  function pickable(c,ch){
    return ch.selectable || c.version.status==='draft' && ['ready','needs_transcription'].includes(c.version.ingestion_status) && ch.page_indices.length>0 && (c.boundaries_reviewed||ch.whole_document);
  }
  function choice(m,c,ch,selection,filename=''){
    const bound=selection?.bindings.find(b=>b.version_id===c.version.id),set=new Set(bound?.page_indices||[]),count=ch.page_indices.filter(n=>set.has(n)).length;
    const ready=pickable(c,ch),pending=!ch.approved;
    const state=pending?count?'Included in guide approval':'Not yet approved':!ch.selectable?'Check chapter boundaries':'Source pages approved';
    return `<div class="chapter-option"><label class="chapter-choice"><input type="checkbox" data-chapter-key="${esc(ch.key)}" ${count===ch.page_indices.length&&count?'checked':''} ${!ready||!selection?.ready||MisraAssessmentSources.isBusy()?'disabled':''} ${count&&count!==ch.page_indices.length?'data-partial="true"':''}><span><strong dir="auto">${esc(ch.title)}</strong>${filename&&filename!==ch.title?`<small class="chapter-filename" dir="auto">${esc(filename)}</small>`:''}<small>${c.chapter_file?`Full PDF · ${c.version.page_count} pages`:`PDF pages ${ch.start_page}–${ch.end_page}`} · <span data-i18n>${state}</span></small>${!ready?'<small>Check the chapter boundaries in the course library.</small>':''}</span></label><a class="chapter-review-link" href="${esc(libraryUrl(m.id,c.version.id))}">Preview source pages</a></div>`;
  }
  function groups(selection){
    const files=catalog.items.filter(m=>m.scope!=='assessment'&&preferred(m)?.chapter_file).sort((a,b)=>preferred(a).chapter_number-preferred(b).chapter_number||a.title.localeCompare(b.title,undefined,{numeric:true}));
    const rest=catalog.items.filter(m=>!files.includes(m));
    return (files.length?`<fieldset class="chapter-group chapter-files"><legend>Course chapters</legend>${files.map(m=>{const c=preferred(m);return c.chapters.map(ch=>choice(m,c,ch,selection,m.title)).join('');}).join('')}</fieldset>`:'')+rest.map(m=>{
      const c=preferred(m);
      if(!c)return `<p>${esc(m.title)} · Waiting for chapter inventory.</p>`;
      return `<fieldset class="chapter-group"><legend>${esc(m.title)}${m.scope==='assessment'?' · Only this assessment':''}</legend>${c.chapters.map(ch=>choice(m,c,ch,selection)).join('')}</fieldset>`;
    }).join('');
  }
  function summary(selection){
    const selectedChapters=[];
    for(const m of catalog?.items||[]){const c=preferred(m);if(!c)continue;const pages=new Set(selection?.bindings.find(b=>b.version_id===c.version.id)?.page_indices||[]);
      for(const ch of c.chapters)if(ch.page_indices.length&&ch.page_indices.every(n=>pages.has(n)))selectedChapters.push(ch);
    }
    return {count:selectedChapters.length,pending:selectedChapters.some(ch=>!ch.approved)};
  }
  function render(){
    if(!exam)return;
    const focused=host.contains(document.activeElement)?document.activeElement.dataset.chapterKey:null;
    const selection=selected(),state=summary(selection),changed=MisraAssessmentSources.hasUnsaved(),busy=MisraAssessmentSources.isBusy();
    const status=feedback||(changed?'Unsaved source selection':state.pending?'Selected pages are pending whole-guide approval.':'');
    const error=failure||selectionError;
    host.innerHTML=`<header class="chapter-toolbar"><div><h3 data-i18n>Chapters covered by this assessment</h3><p data-i18n>Select the material students should be marked against.</p></div><a class="button" href="${esc(libraryUrl())}">Open course library</a></header>
      ${error?`<p role="alert" class="form-error">${esc(error)}</p>`:''}
      ${!loaded?'<p role="status">Loading the saved course library…</p>':catalog?.items.length?groups(selection):!failure?'<p data-i18n>Add a book, chapters or notes in the course library to select references here.</p>':''}
      <footer class="chapter-footer"><div><span data-i18n>Selected sources</span> <strong>${selection?.bindings.length??0}</strong><p id="chapter-selection-status" role="status">${esc(status)}</p></div><div class="inline-actions">
      <button type="button" id="chapter-refresh-selection" ${busy?'disabled':''}>Refresh saved library</button>
      <button type="button" id="chapter-save-selection" ${!selection?.ready||!changed||busy||selectionError?'disabled':''}>${busy?'Saving…':'Save chapter selection'}</button>
      <button type="button" class="primary" data-guide-step="questions">Continue to marking guide</button></div></footer>`;
    host.querySelectorAll('[data-partial]').forEach(input=>input.indeterminate=true);
    host.querySelectorAll('[data-chapter-key]').forEach(input=>input.addEventListener('change',()=>toggle(input)));
    $('chapter-save-selection').addEventListener('click',save);
    $('chapter-refresh-selection').addEventListener('click',()=>load());
    if(focused)[...host.querySelectorAll('[data-chapter-key]')].find(input=>input.dataset.chapterKey===focused)?.focus({preventScroll:true});
    window.MisraLocale?.apply();
  }
  async function save(){
    if(MisraAssessmentSources.isBusy())return;
    if(!MisraAssessmentSources.hasUnsaved()){feedback='No changes to save. Select a chapter first.';render();return;}
    const selection=selected();if(!selection?.ready)return;
    const state=summary(selection),current=exam;
    const saving=MisraAssessmentSources.saveDraft({allowPendingSources:true});feedback='Saving chapter selection…';render();
    const saved=await saving;if(current!==exam)return;
    feedback=!saved?'Selection could not be saved. Your choices remain here; check the source error below.':!selection.bindings.length?'Chapter selection cleared and saved as a draft. Publish the guide to apply this change.':`${state.count} chapter${state.count===1?'':'s'} saved as a draft. Approve it with the whole marking guide.`;
    if(!saved)$('assessment-sources-host').closest('details').open=true;
    render();if(saved)window.dispatchEvent(new CustomEvent('misra:ledger-foundations-changed'));
  }
  function toggle(input){
    const selection=selected();if(!selection?.ready||MisraAssessmentSources.isBusy()){render();return;}
    const material=catalog.items.find(m=>m.catalogs.some(c=>c.chapters.some(ch=>ch.key===input.dataset.chapterKey)));
    const c=material.catalogs.find(c=>c.chapters.some(ch=>ch.key===input.dataset.chapterKey)),chapter=c.chapters.find(ch=>ch.key===input.dataset.chapterKey);
    if(!pickable(c,chapter)){render();return;}
    const bindings=structuredClone(selection.bindings),index=bindings.findIndex(b=>b.version_id===c.version.id),pages=new Set(index<0?[]:bindings[index].page_indices);
    chapter.page_indices.forEach(page=>input.checked?pages.add(page):pages.delete(page));
    if(index>=0)bindings.splice(index,1);
    if(pages.size)bindings.push({version_id:c.version.id,page_indices:[...pages].sort((a,b)=>a-b),criterion_id:null,chunk_ids:[]});
    if(MisraAssessmentSources.chooseChapters(bindings,bindings.length?selection.mode==='disabled'?'required':selection.mode:'disabled'))feedback='';render();
  }
  async function load(){if(!course)return;const current=++generation;failure='';
    try{const value=await MisraAPI.courseLibrary(course,exam);if(current!==generation)return;if(!Array.isArray(value?.items))throw Error('Course library response is incomplete.');catalog=value;loaded=true;}
    catch(e){if(current===generation){failure=`${e.message} Your source selections are retained.`;loaded=true;}}
    if(current===generation)render();
  }
  routeScope.listen(window,'misra:assessment-loaded',e=>{exam=e.detail.examId;course=e.detail.courseId;catalog=null;loaded=false;feedback='';load();});
  routeScope.listen(window,'misra:assessment-sources-loaded',render);
  routeScope.listen(window,'misra:assessment-sources-changed',()=>{feedback='';render();});
  routeScope.listen(window,'misra:material-approved',()=>load());
  routeScope.listen(window,'misra:assessment-extra-uploaded',async()=>{if(!MisraAssessmentSources.hasUnsaved())await MisraAssessmentSources.reload();await load();});
})();
