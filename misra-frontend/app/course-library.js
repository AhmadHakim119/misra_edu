(function(){
  'use strict';
  const {$,esc,operation}=MisraApp;
  let course='',generation=0,data=null,editor=null,uploadDirty=false,chapterDirty=false,uncertain=false,timer,pendingFiles=[];
  const active=new Set(['queued','processing','retrying']);
  const unsaved=()=>uploadDirty||chapterDirty||MisraMaterials.hasUnsaved();
  function dirty(){MisraApp.setDirty(unsaved());}
  function error(e){$('library-error').textContent=e.message;}
  async function refresh(force=false){
    if(!course)return;if(!force&&unsaved()){$('library-error').textContent='Save or clear your current edits before refreshing the library.';return;}
    const current=++generation;
    try{
      const result=await MisraAPI.courseLibrary(course,new URLSearchParams(location.search).get('exam_id'));
      if(current!==generation)return;if(!Array.isArray(result?.items))throw Error('Library response is incomplete.');
      data=result;$('library-summary').textContent=`${data.items.length} saved course material(s). These are available across this course’s assessments.`;
      if(!MisraMaterials.hasUnsaved())await MisraMaterials.load(course,null,[]);if(current!==generation)return;
      decorate();schedule();
    }catch(e){if(current===generation)error(e);}
  }
  function schedule(){clearTimeout(timer);if(data?.items.some(m=>m.versions.some(v=>active.has(v.job?.status||v.ingestion_status))))timer=setTimeout(()=>{if(!unsaved()&&!MisraApp.isBusy())refresh();else schedule();},4000);}
  function decorate(){
    if(!data)return;
    const list=$('library-material-host').querySelector('.material-library-list');
    if(list){
      const rows=[...list.children],chapter=m=>m?.catalogs?.find(c=>c.chapter_file)?.chapter_number;
      const sorted=[...rows].sort((a,b)=>{
        const ma=data.items.find(m=>m.id===a.querySelector('[data-material-review]')?.dataset.materialReview),mb=data.items.find(m=>m.id===b.querySelector('[data-material-review]')?.dataset.materialReview);
        const na=chapter(ma),nb=chapter(mb);
        return na!=null&&nb!=null?na-nb:na!=null?-1:nb!=null?1:0;
      });
      if(sorted.some((row,i)=>row!==rows[i]))list.append(...sorted);
    }
    document.querySelectorAll('#library-material-host .material-library-row').forEach(row=>{
      if(row.querySelector('.chapter-actions'))return;
      const review=row.querySelector('[data-material-review]'),material=data.items.find(m=>m.id===review?.dataset.materialReview);
      if(!material)return;
      const group=document.createElement('div');group.className='chapter-actions';
      group.innerHTML=(material.catalogs||[]).map(c=>`<div><p>${c.chapter_file?`${esc(c.chapters[0].title)} · Full PDF · ${c.version.page_count} pages`:`${c.chapters.length} chapter/section(s) · ${c.boundaries_reviewed?'boundaries checked':c.chapters[0]?.whole_document?'one document':'suggested boundaries — check before selecting'}`}</p>${c.chapter_file?'':`<button type="button" data-edit-chapters="${esc(material.id)}" data-index-version="${esc(c.version.id)}" ${active.has(c.version.job?.status||c.version.ingestion_status)?'disabled':''}>Review chapter boundaries${material.catalogs.length>1?` · ${esc(c.version.status)}`:''}</button>`}${c.version.status==='draft'&&c.version.media_type==='application/pdf'&&c.version.ingestion_status==='needs_transcription'?` <button type="button" data-read-scans="${esc(material.id)}" data-index-version="${esc(c.version.id)}">Read scanned pages</button>`:''}</div>`).join('');
      row.append(group);
    });
  }
  async function openIndex(materialId,versionId){
    if(chapterDirty&&!confirm('Discard unsaved chapter boundary edits?'))return;
    try{const catalog=await MisraAPI.materialChapters(materialId,versionId);editor={materialId,versionId,catalog};chapterDirty=false;renderIndex();dirty();}
    catch(e){error(e);}
  }
  function renderIndex(){
    const host=$('library-chapter-editor');host.hidden=false;
    host.innerHTML=`<h2>Check the book’s chapters</h2><p>Use PDF positions starting at 1. These boundaries organise the book; they do not approve its text for grading.</p>${editor.catalog.version.media_type==='text/plain'?'<p>Instructor-entered notes; no original document.</p>':`<a target="_blank" rel="noopener" href="${esc(MisraAPI.materialDocumentUrl(editor.materialId,editor.versionId))}">Open original book</a>`}<form id="chapter-boundaries"><div id="chapter-boundary-rows">${editor.catalog.chapters.map((c,i)=>row(c,i)).join('')}</div><button type="button" id="chapter-add">Add chapter</button><label class="check-row"><input id="chapter-checked" type="checkbox" required> I checked chapter names and page ranges against the original.</label><button type="submit" class="primary">Save checked chapter boundaries</button><button type="button" id="chapter-close">Close</button><p id="chapter-save-state" role="status"></p></form>`;
    const form=$('chapter-boundaries');form.addEventListener('input',()=>{chapterDirty=true;dirty();});
    $('chapter-add').addEventListener('click',()=>{const rows=$('chapter-boundary-rows');rows.insertAdjacentHTML('beforeend',row({title:'',start_page:1,end_page:1},rows.children.length));chapterDirty=true;dirty();});
    form.addEventListener('click',e=>{if(e.target.closest('[data-remove-chapter]')){e.target.closest('.chapter-boundary-row').remove();chapterDirty=true;dirty();}});
    $('chapter-close').addEventListener('click',()=>{if(!chapterDirty||confirm('Discard unsaved chapter boundary edits?')){host.hidden=true;editor=null;chapterDirty=false;dirty();}});
    form.addEventListener('submit',async e=>{
      e.preventDefault();const body={chapters:[...form.querySelectorAll('.chapter-boundary-row')].map(el=>({title:el.querySelector('[name=title]').value,start_page:Number(el.querySelector('[name=start_page]').value),end_page:Number(el.querySelector('[name=end_page]').value)})),expected_text_fingerprint:editor.catalog.text_fingerprint,confirm_boundaries_reviewed:$('chapter-checked').checked};
      await operation(form.querySelector('[type=submit]'),async()=>{try{editor.catalog=await MisraAPI.saveMaterialChapters(editor.materialId,editor.versionId,body);chapterDirty=false;dirty();$('chapter-save-state').textContent='Checked chapters saved. You can now select their approved pages in an assessment.';await refresh(true);}catch(failure){$('chapter-save-state').textContent=`${failure.message} Your entries remain here.`;throw failure;}});
    });host.scrollIntoView({block:'start'});
  }
  function row(c,i){return `<div class="chapter-boundary-row"><label>Chapter name<input name="title" value="${esc(c.title)}" maxlength="255" required></label><label>From PDF page<input name="start_page" type="number" min="1" max="${editor.catalog.version.page_count}" value="${c.start_page}" required></label><label>Through PDF page<input name="end_page" type="number" min="1" max="${editor.catalog.version.page_count}" value="${c.end_page}" required></label><button type="button" data-remove-chapter="${i}">Remove</button></div>`;}
  $('library-course').addEventListener('change',()=>{if(unsaved()&&!confirm('Discard unsaved library edits and switch courses?')){$('library-course').value=course;return;}MisraMaterials.reset();uploadDirty=chapterDirty=false;pendingFiles=[];uncertain=false;$('library-upload').querySelector('[type=submit]').disabled=false;editor=null;$('library-chapter-editor').hidden=true;$('library-upload').reset();course=$('library-course').value;history.replaceState(null,'',`course-library.html?course_id=${encodeURIComponent(course)}`);dirty();refresh(true);});
  $('library-refresh').addEventListener('click',()=>refresh());
  $('library-upload').addEventListener('input',()=>{uploadDirty=true;dirty();});
  $('library-files').addEventListener('change',()=>{pendingFiles=[...$('library-files').files];});
  $('library-clear').addEventListener('click',()=>{if(uncertain&&!confirm('Confirm you checked the saved library for accepted files before clearing this uncertain selection.'))return;pendingFiles=[];uncertain=uploadDirty=false;$('library-upload').reset();$('library-upload').querySelector('[type=submit]').disabled=false;dirty();$('library-upload-state').textContent='Selection cleared. Saved course files remain in the library.';refresh(true);});
  $('library-upload').addEventListener('submit',async e=>{
    e.preventDefault();if(uncertain)return;const files=[...pendingFiles],scan=$('library-scan-ocr').checked;
    if(files.length>25||files.reduce((n,f)=>n+f.size,0)>104857600){error(Error('Choose up to 25 PDF/PPTX files and 100 MB per upload.'));return;}
    let completed=0;await operation(e.submitter,async()=>{try{for(const file of files){const body=new FormData();body.append('file',file);body.append('title',file.name.replace(/\.(pdf|pptx)$/i,''));body.append('ocr_scans',String(scan));const result=await MisraAPI.uploadMaterial(course,body);if(!result?.id)throw Error('Upload response is incomplete.');completed++;$('library-upload-state').textContent=`${completed} of ${files.length} accepted.`;}e.target.reset();pendingFiles=[];uploadDirty=false;dirty();await refresh(true);}catch(failure){pendingFiles=files.slice(completed);uncertain=!failure.status||failure.status>=500;$('library-upload-state').textContent=`${completed} file(s) accepted. ${failure.message} ${uncertain?'Check the saved library before clearing this selection.':'Only the remaining files will be retried.'}`;await refresh(true);throw failure;}});
    $('library-upload').querySelector('[type=submit]').disabled=uncertain;
  });
  $('library-material-host').addEventListener('click',async e=>{
    const edit=e.target.closest('[data-edit-chapters]'),scan=e.target.closest('[data-read-scans]');
    if(edit)openIndex(edit.dataset.editChapters,edit.dataset.indexVersion);
    if(scan)await operation(scan,async()=>{await MisraAPI.readScannedMaterial(scan.dataset.readScans,scan.dataset.indexVersion);await refresh(true);});
  });
  new MutationObserver(decorate).observe($('library-material-host'),{childList:true});
  $('library-material-host').addEventListener('input',dirty);
  document.addEventListener('click',e=>{if(e.target.closest('a,#native-sign-out')&&MisraMaterials.hasUnsaved()&&!MisraMaterials.canLeave()){e.preventDefault();e.stopImmediatePropagation();}},true);
  MisraApp.ready.then(async()=>{const courses=await MisraAPI.courses();if(!Array.isArray(courses))throw Error('Course list is incomplete.');$('library-course').innerHTML=courses.map(c=>`<option value="${esc(c.id)}">${esc(c.course_code)} · ${esc(c.title)}</option>`).join('');const requested=MisraApp.params.get('course_id');course=courses.some(c=>c.id===requested)?requested:courses[0]?.id||'';$('library-course').value=course;MisraMaterials.mount($('library-material-host'));if(course){await refresh();const material=MisraApp.params.get('material_id'),version=MisraApp.params.get('version_id');if(material&&version){const button=[...$('library-material-host').querySelectorAll('[data-material-review]')].find(b=>b.dataset.materialReview===material&&b.dataset.version===version);if(button&&!button.disabled){button.click();button.scrollIntoView({block:'center'});}else error(Error('This source is unavailable or still being read. Check its library status.'));}}else $('library-summary').textContent='Create a course in Exams before adding its book.';}).catch(error);
})();
