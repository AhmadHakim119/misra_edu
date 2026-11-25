/* Teaching material → optional quiz drafts → one guide → learning feedback. */
(function () {
  'use strict';
  const routeScope=MisraWorkspace.page;
  const $=id=>document.getElementById(id), esc=value=>MisraUI.escapeHTML(String(value ?? ''));
  const active=new Set(['queued','processing','retrying']);
  let exam='', course='', epoch=0, timer=null, busy=false, dirty=false, uncertain=false, uploadUncertain=false, selected=null, library=[], uploadFiles=[];
  let dirtyParts={upload:false,quiz:false,import:false,proposals:false};
  function setDirty(kind,value){dirtyParts[kind]=value;dirty=Object.values(dirtyParts).some(Boolean);}
  function clearDirty(){dirtyParts={upload:false,quiz:false,import:false,proposals:false};dirty=false;}
  const tools=document.createElement('section');tools.className='source-teaching-tools';
  const title=document.createElement('h3');title.textContent='Prepare questions';
  const host=document.createElement('div');host.id='teaching-tools';host.className='teaching-tools';
  tools.append(title,host);
  $('guide-sources-stage').append(tools);
  const insightsButton=document.createElement('button');insightsButton.id='insights-link';insightsButton.type='button';insightsButton.textContent='Class feedback';insightsButton.disabled=true;
  $('export-link').before(insightsButton);
  const num=value=>value==null ? 'Not available' : Number(value).toLocaleString(undefined,{maximumFractionDigits:1});
  const options=()=>library.map(m=>({m,v:(m.versions || []).filter(v=>v.status==='approved' && v.approved_page_indices?.length).sort((a,b)=>b.version_number-a.version_number)[0]})).filter(o=>o.v);
  function setBusy(value){if(busy===value)return;busy=value;host.setAttribute('aria-busy',String(value));host.querySelectorAll('button,input,select,textarea').forEach(el=>{if(value){el.dataset.wasDisabled=String(el.disabled);el.disabled=true;}else {el.disabled=el.dataset.wasDisabled==='true';delete el.dataset.wasDisabled;}});}
  function status(message,error=false){$('teaching-status').textContent=message;const feedback=$('teaching-proposal-feedback');if(feedback){feedback.textContent=message;feedback.classList.toggle('form-error',error);}}
  function validateProposals(form){
    const labels={question_number:'Question number',question_text:'Question text',max_score:'Marks',answer_key:'Reference solution',marking_guide:'Marking guide'},invalid=[];
    form.querySelectorAll('[data-proposal]').forEach(row=>{
      if(!row.querySelector('[name="include"]').checked)return;
      Object.keys(labels).forEach(name=>{const field=row.querySelector(`[name="${name}"]`);field.setCustomValidity('');
        if(name==='marking_guide')field.required=!row.querySelector('[name="answer_key"]').value.trim()&&!row.querySelector('[name="multiple_choice"]').checked;
        if(field.required && !field.value.trim())field.setCustomValidity(name==='marking_guide'?'Add a worked answer or marking guidance.':`Enter ${labels[name].toLowerCase()}.`);
        const id=`proposal-error-${row.dataset.proposal}-${name}`;let error=$(id);
        if(!field.checkValidity()){field.setAttribute('aria-invalid','true');field.setAttribute('aria-describedby',id);if(!error){error=document.createElement('span');error.id=id;error.className='form-error proposal-field-error';field.after(error);}error.textContent=field.validationMessage;invalid.push({field,row,name});}
        else {field.removeAttribute('aria-invalid');field.removeAttribute('aria-describedby');error?.remove();}
      });
    });
    if(!invalid.length)return true;
    const {field,row,name}=invalid[0];status(`Question ${row.querySelector('[name="question_number"]').value || Number(row.dataset.proposal)+1} — ${labels[name]}: ${field.validationMessage} ${invalid.length} field(s) need attention. Your edits are retained.`,true);
    for(let parent=field.parentElement;parent && parent!==form;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
    field.focus();field.scrollIntoView({block:'center'});return false;
  }
  function safe(ownLock=false){return (!busy || ownLock) && window.MisraLedgerEditors?.saveEdits && !window.MisraMaterials?.hasUnsaved();}
  function shell(){
    host.innerHTML=`<details id="lecture-upload"><summary>Add extra material for this assessment (optional)</summary><p>The course book is already in the course library above. Add slides or notes here only when they are specific to this assessment. PDF and PowerPoint (.pptx) files are supported. Export diagram-heavy slides as PDF to review their visual content.</p><form id="lecture-upload-form"><label for="lecture-files">Extra material PDFs</label><input id="lecture-files" type="file" accept=".pdf,.pptx" multiple required><p id="lecture-selection"></p><button id="lecture-clear" type="button">Clear files</button><button type="submit">Upload material drafts</button></form><p id="lecture-upload-status" role="status"></p><button id="lecture-reconcile" type="button" hidden>I checked the library; clear uncertain selection</button></details>
      <details id="quiz-from-lecture"><summary>Ask AI to draft a quiz from your teaching material (optional)</summary><p>Choose the material you taught and describe the topic. Review every proposal; AI never publishes a quiz or marking rule by itself.</p><button type="button" id="refresh-teaching-sources">Refresh checked materials</button><form id="lecture-quiz-form"><fieldset><legend>Taught material</legend><button type="button" id="lecture-select-all">Select all checked materials</button><div id="lecture-choices"></div></fieldset><label for="lecture-topic">What did this lecture cover?</label><textarea id="lecture-topic" rows="2" maxlength="500" required placeholder="e.g. work done by a constant force and perpendicular displacement"></textarea><div class="teaching-fields"><label>Questions per request<input name="count" type="number" min="1" max="5" value="3" required></label><label>Marks per question<input name="marks" type="number" min="0.01" max="100" step="0.01" value="2" required></label><label>Difficulty<select name="difficulty"><option value="introductory">Introductory</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label><label>Language<select name="language"><option value="en">English</option><option value="ar">Arabic</option><option value="mixed">Mixed</option></select></label></div><button type="submit">Draft questions from this lecture</button></form></details>
      <details id="import-existing-quiz"><summary>Use an existing quiz or exam instead</summary><p>Upload the exam, the answer key if it includes the questions, or both.</p><form id="teaching-import-form"><div class="teaching-fields"><label>Exam PDF or image<input name="exam" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp"></label><label>Answer key<input name="key" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp"></label></div><button type="submit">Read existing quiz &amp; key</button></form></details>
      <p id="teaching-status" role="status"></p><button type="button" id="refresh-teaching-history">Check saved quiz requests</button><div id="teaching-history"></div><div id="teaching-proposals"></div>`;
    $('lecture-files').addEventListener('change',()=>{uploadFiles=[...$('lecture-files').files];$('lecture-files').disabled=Boolean(uploadFiles.length);$('lecture-selection').textContent=uploadFiles.map(f=>f.name).join(', ');setDirty('upload',Boolean(uploadFiles.length));});
    $('lecture-clear').addEventListener('click',()=>{if(busy || uploadUncertain)return;uploadFiles=[];$('lecture-files').value='';$('lecture-files').disabled=false;$('lecture-selection').textContent='';setDirty('upload',false);});
    host.querySelectorAll('form').forEach(form=>form.addEventListener('input',()=>{setDirty(form.id==='lecture-upload-form'?'upload':form.id==='lecture-quiz-form'?'quiz':'import',true);}));
    $('lecture-upload-form').addEventListener('submit',upload);
    $('lecture-reconcile').addEventListener('click',async()=>{if(busy || !await MisraWorkspace.confirm('Confirm you checked the course library for the uncertain upload. Clear this selection; select only files that were not accepted.'))return;uploadUncertain=false;uploadFiles=[];setDirty('upload',false);$('lecture-files').value='';$('lecture-files').disabled=false;$('lecture-selection').textContent='';$('lecture-reconcile').hidden=true;status('Selection cleared. Accepted drafts remain in the course library.');});
    $('lecture-quiz-form').addEventListener('submit',generate);
    $('lecture-select-all').addEventListener('click',()=>{$('lecture-choices').querySelectorAll('input').forEach(input=>{input.checked=true;});setDirty('quiz',true);});
    $('teaching-import-form').addEventListener('submit',importQuiz);
    $('refresh-teaching-sources').addEventListener('click',()=>{if(!dirty && !busy)loadLibrary();else status('Keep your entries: finish or clear the current request before refreshing materials.');});
    $('refresh-teaching-history').addEventListener('click',()=>{if(!busy)history();});
  }
  async function loadLibrary(){const current=epoch,checked=new Set([...$('lecture-choices').querySelectorAll('input:checked')].map(input=>input.value));try{const data=await MisraAPI.courseMaterials(course);if(current!==epoch)return;if(!Array.isArray(data))throw Error('Material list is incomplete.');library=data;$('lecture-choices').innerHTML=options().map(({m,v})=>`<label class="lecture-choice"><input type="checkbox" value="${esc(v.id)}" ${checked.has(v.id)?'checked':''}><span>${esc(m.title)}<small> · ${v.approved_page_indices.length} checked page(s)</small></span></label>`).join('') || '<p>Add material, then check and approve its pages in the course library below. Uploaded-but-unchecked pages cannot be used.</p>';}
    catch(e){if(current===epoch)status(`${e.message} Refresh checked materials to retry.`);}}
  async function upload(e){e.preventDefault();if(busy || uploadUncertain || !uploadFiles.length)return;
    if(uploadFiles.length>25 || uploadFiles.some(f=>!(/\.(pdf|pptx)$/i.test(f.name)))){status('Choose up to 25 PDF or PPTX files.');return;}
    if(uploadFiles.reduce((n,f)=>n+f.size,0)>104857600){status('Choose at most 100 MB at a time.');return;}
    setBusy(true);const current=epoch,target=exam;let completed=0;
    try{for(const file of [...uploadFiles]){const body=new FormData();body.append('file',file);body.append('title',file.name.replace(/\.(pdf|pptx)$/i,''));$('lecture-upload-status').textContent=`Uploading ${completed+1} of ${uploadFiles.length}: ${file.name}`;const result=await MisraAPI.uploadAssessmentMaterial(target,body);if(!result?.id || !Array.isArray(result.versions))throw Error('Upload response incomplete.');if(current!==epoch)return;completed++;}
      uploadFiles=[];$('lecture-files').value='';$('lecture-selection').textContent='';setDirty('upload',false);$('lecture-upload-status').textContent=`${completed} material drafts accepted. Reading continues in background jobs. Open the course library for this assessment to review its extra pages.`;await loadLibrary();window.dispatchEvent(new CustomEvent('misra:assessment-extra-uploaded'));}
    catch(failure){if(current===epoch){uploadFiles=uploadFiles.slice(completed);uploadUncertain=!failure.status || failure.status>=500;status(`${completed} file(s) accepted. ${failure.message} ${uploadUncertain?'Acceptance of the next file is uncertain. Check the course library before retrying; no automatic retry was sent.':'Remaining files are retained.'}`);}}
    finally{if(current===epoch){setBusy(false);$('lecture-files').disabled=Boolean(uploadFiles.length);$('lecture-reconcile').hidden=!uploadUncertain;}}
  }
  async function prepare(ownLock=false){if(!safe(ownLock)){status('Save current page/material edits and finish pending operations before requesting quiz drafts.');return false;}return await window.MisraLedgerEditors.saveEdits() && await window.MisraAssessmentSources.saveDraft({allowPendingSources:true});}
  async function request(fn,kind){if(busy || uncertain)return;const discarding=dirtyParts.proposals;if(discarding && !await MisraWorkspace.confirm('Discard unsaved proposal edits before preparing another quiz?'))return;const origin=epoch;if(!await prepare() || origin!==epoch)return;setBusy(true);const current=epoch;status('Saving the quiz request…');
    try{const result=await fn();if(current!==epoch)return;if(!result?.job?.id)throw Error('Request response incomplete.');setDirty(kind,false);if(discarding)setDirty('proposals',false);selected=result;status('Request saved. Processing continues when you leave this page.');await history();watch(result);}
    catch(e){if(current===epoch){uncertain=!e.status || e.status>=500;status(`${e.message} Your entries remain. Check saved quiz requests before repeating this request.`);}}
    finally{if(current===epoch)setBusy(false);}}
  function generate(e){e.preventDefault();const form=e.currentTarget;const bindings=[...$('lecture-choices').querySelectorAll('input:checked')].map(input=>{const item=options().find(o=>o.v.id===input.value);return {version_id:item.v.id,page_indices:item.v.approved_page_indices};});if(!bindings.length){status('Choose at least one checked lecture or chapter.');return;}
    const body={bindings,topic:$('lecture-topic').value.trim(),count:Number(form.elements.count.value),points_per_question:Number(form.elements.marks.value),language:form.elements.language.value,difficulty:form.elements.difficulty.value};request(()=>MisraAPI.sourceQuestionDrafts(exam,body),'quiz');}
  function importQuiz(e){e.preventDefault();const form=e.currentTarget,body=new FormData();const examFile=form.elements.exam.files[0],key=form.elements.key.files[0];if(!examFile&&!key){status('Choose an exam or an answer key containing the questions.',true);return;}if(examFile)body.append('exam_file',examFile);if(key)body.append('answer_key',key);request(()=>MisraAPI.uploadSetup(exam,body),'import');}
  async function history(){const current=epoch;try{const rows=await MisraAPI.setupImports(exam);if(current!==epoch)return;if(!Array.isArray(rows))throw Error('Saved requests response incomplete.');uncertain=false;$('teaching-history').innerHTML=rows.map(row=>`<p><button type="button" data-quiz-job="${esc(row.job.id)}">${row.origin==='course_source_questions'?'Lecture question proposals':'Existing exam import'} · ${esc(row.job.status)}${row.imported_question_ids?.length?' · drafts added':''}</button></p>`).join('') || '<p>No saved quiz requests yet. You can use your existing questions without generating anything.</p>';
      if(!selected && rows.length && !dirty)watch(rows[0]);}
    catch(e){if(current===epoch)status(`${e.message} Check saved quiz requests to reconnect.`);}}
  async function watch(data){routeScope.cancelTimer(timer);selected=data;const current=epoch,id=data?.job?.id;if(!id)return;
    if(active.has(data.job.status)){status(`${data.job.status.replaceAll('_',' ')} · ${data.job.progress_message || 'Preparing quiz drafts. You may navigate away.'}`);timer=routeScope.later(async()=>{try{const value=await MisraAPI.setupImport(exam,id);if(current===epoch && selected?.job.id===id)watch(value);}catch(e){if(current===epoch)status(`${e.message} Processing may continue. Check saved quiz requests; do not upload again.`);}},3000);return;}
    if(data.job.status==='failed'){status(data.job.error_message || 'Quiz preparation failed.');$('teaching-proposals').innerHTML=`<button type="button" data-retry-quiz="${esc(id)}">Retry saved quiz request</button>`;return;}
    if(data.job.status!=='completed' || !Array.isArray(data.questions)){status('The saved request is not ready. Check saved quiz requests.');return;}
    if(data.imported_question_ids?.length){status('Questions are already added as drafts. Review the whole marking guide and approve once.');$('teaching-proposals').innerHTML='<button type="button" data-guide-step="questions">Open the marking guide</button>';return;}
    proposals(data);
  }
  function proposals(data){status('Proposals ready. Review solutions, marks and source quotations before adding drafts.');
    $('teaching-proposals').innerHTML=`<h3>Review your quiz before using it</h3>${(data.warnings || []).map(w=>`<p class="notice">${esc(w)}</p>`).join('')}<form id="add-teaching-questions" novalidate>${data.questions.map((q,i)=>`<fieldset data-proposal="${i}"><legend>Question ${esc(q.question_number)}</legend><label><input type="checkbox" name="include" checked> Add this question</label><label><input type="checkbox" name="multiple_choice"> Multiple choice (a separate marking guide is optional)</label><div class="teaching-fields"><label>Question number<input name="question_number" value="${esc(q.question_number)}" maxlength="20" required></label><label>Marks<input name="max_score" type="number" min="0.01" max="9999.99" step="0.01" value="${esc(q.max_score ?? '')}" required></label></div><label>Question text<textarea name="question_text" rows="3" required maxlength="20000">${esc(q.question_text)}</textarea></label>${q.wording_variants?.length?`<details><summary>Other wording found in setup documents</summary><p data-i18n>Compare these readings with the original and edit the question text above.</p>${q.wording_variants.map(variant=>`<blockquote dir="auto">${esc(variant.question_text)}</blockquote>`).join('')}</details>`:''}<details><summary>Solution, marking guide &amp; exact lecture evidence</summary><label>Reference solution<textarea name="answer_key" rows="3" maxlength="20000">${esc(q.answer_key)}</textarea></label><label>Marking guidance (optional with a worked answer)<textarea name="marking_guide" rows="3" maxlength="20000">${esc(q.marking_guide)}</textarea></label>${(q.citations || []).map(c=>{const p=(data.source_passages || []).find(p=>p.id===c.source_ref);return `<p>${p?`${esc(p.title)} · document page ${p.page_index+1}`:'Source unavailable—check before using'}</p><blockquote>${esc(c.quote)}</blockquote>`;}).join('')}</details></fieldset>`).join('')}<label>Initial marking approach<select id="teaching-approach"><option value="balanced">Balanced</option><option value="lenient">Lenient</option><option value="strict">Strict</option></select></label><p>These become drafts, not approved grading rules. Confirm the whole guide next.</p><p>For multiple-choice questions, missing marks start at 1. Check the correct option and marks before adding drafts.</p><p id="teaching-proposal-feedback" role="status"></p><button type="submit">Add selected questions to the marking guide</button></form>`;
    const form=$('add-teaching-questions');form.addEventListener('input',e=>{setDirty('proposals',true);form.querySelectorAll('[data-proposal]').forEach(row=>{const mcq=row.querySelector('[name="multiple_choice"]'),marks=row.querySelector('[name="max_score"]');if(e.target===mcq && mcq.checked && !marks.value.trim())marks.value='1';row.querySelector('[name="marking_guide"]').required=!mcq.checked&&!row.querySelector('[name="answer_key"]').value.trim();row.querySelector('[name="answer_key"]').required=mcq.checked;row.querySelectorAll('input:not([name="include"]),textarea').forEach(el=>{el.disabled=!row.querySelector('[name="include"]').checked;el.setCustomValidity('');el.removeAttribute('aria-invalid');el.removeAttribute('aria-describedby');});row.querySelectorAll('.form-error').forEach(el=>el.remove());});});
    form.addEventListener('submit',async e=>{e.preventDefault();if(busy)return;if(uncertain){status('Check saved quiz requests before retrying an uncertain confirmation.',true);return;}if(!validateProposals(form))return;const questions=[...form.querySelectorAll('[data-proposal]')].filter(row=>row.querySelector('[name="include"]').checked).map(row=>{const value=Object.fromEntries(['question_number','question_text','max_score','answer_key','marking_guide'].map(k=>[k,k==='max_score'?Number(row.querySelector(`[name="${k}"]`).value):row.querySelector(`[name="${k}"]`).value.trim()]));value.multiple_choice=row.querySelector('[name="multiple_choice"]').checked;if(data.origin==='course_source_questions')value.source_draft_id=data.questions[Number(row.dataset.proposal)].source_draft_id;return value;});if(!questions.length){status('Select at least one question.',true);return;}const body={questions,exact_scoring:true,grading_approach:$('teaching-approach').value},current=epoch;
      setBusy(true);status('Adding selected questions as drafts…');try{if(!await prepare(true) || current!==epoch)return;const result=await MisraAPI.confirmSetup(exam,data.job.id,body);if(current!==epoch)return;if(!Array.isArray(result?.question_ids) || !result.question_ids.length)throw Error('Confirmation response incomplete.');setDirty('proposals',false);data.imported_question_ids=result.question_ids;setBusy(false);watch(data);window.MisraLedgerEditors.reset({id:exam,course_id:course});window.dispatchEvent(new CustomEvent('misra:ledger-foundations-changed'));}
      catch(e){if(current===epoch){uncertain=!e.status || e.status>=500;status(`${e.message} Edits retained. Check saved requests before retrying an uncertain confirmation.`,true);}}finally{if(current===epoch)setBusy(false);}});
  }
  host.addEventListener('click',async e=>{const open=e.target.closest('[data-quiz-job]'),retry=e.target.closest('[data-retry-quiz]');if(!open && !retry)return;if(busy || dirty && !await MisraWorkspace.confirm('Discard unsaved quiz request/proposal edits?'))return;clearDirty();const current=epoch;setBusy(true);try{const id=(open || retry).dataset[open?'quizJob':'retryQuiz'];if(retry)await MisraAPI.retryJob(id);const data=await MisraAPI.setupImport(exam,id);if(current===epoch){uncertain=false;watch(data);}}catch(e){if(current===epoch)status(e.message);}finally{if(current===epoch)setBusy(false);}});
  const creditLabels=[['full_credit_count','Full credit'],['partial_credit_count','Partial credit'],['zero_credit_count','No credit']];
  function renderCriterion(criterion,title,heading){
    const counts=creditLabels.map(([key])=>Number.isInteger(criterion[key])&&criterion[key]>=0?criterion[key]:null);
    const pages=(criterion.source_pages||[]).filter(page=>Number.isInteger(page.page_index)&&page.page_index>=0);
    const sources=pages.map(page=>{
      const title=page.title?'<bdi>'+esc(page.title)+'</bdi>':'<span data-i18n>Course material</span>';
      const label=title+' · <span data-i18n>Page</span> '+num(page.page_index+1);
      if(!page.material_id||!page.material_version_id)return '<li>'+label+'</li>';
      const url=MisraAPI.materialDocumentUrl(page.material_id,page.material_version_id)+'#page='+(page.page_index+1);
      return '<li><a target="_blank" rel="noopener" href="'+esc(url)+'">'+label+'</a></li>';
    }).join('');
    const average=criterion.average_percent==null?'':num(criterion.average_percent)+'% <span data-i18n>average</span> · ';
    const summary=average+num(criterion.assessed_count)+' <span data-i18n>scored answers</span>';
    const bar=counts.every(value=>value!==null)&&counts.some(Boolean)
      ? '<div class="insight-distribution" aria-hidden="true">'+counts.map((count,i)=>count?'<span class="insight-credit-'+i+'" style="flex:'+count+'"></span>':'').join('')+'</div>' : '';
    const stats='<dl class="insight-credit-counts">'+creditLabels.map(([,label],i)=>'<div><dt data-i18n>'+label+'</dt><dd>'+num(counts[i])+'</dd></div>').join('')+'</dl>';
    return '<li class="insight-criterion"><div><'+heading+' dir="auto">'+esc(title)+'</'+heading+'><p class="muted">'+summary+'</p></div>'+
      '<div class="insight-credit">'+bar+stats+'</div>'+
      (sources?'<details class="insight-sources"><summary data-i18n>Cited course pages</summary><ul>'+sources+'</ul></details>':'')+'</li>';
  }
  function renderQuestionInsights(question){
    const groups=new Map(), ordinals=new Map();
    for(const criterion of question.criteria||[]){
      const version=criterion.rubric_version_id;
      if(!groups.has(version))groups.set(version,[]);
      groups.get(version).push(criterion);
      if(!ordinals.has(criterion.criterion_id))ordinals.set(criterion.criterion_id,ordinals.size+1);
    }
    const label=criterion=>{
      const title=String(criterion.title||'').trim();
      if(title&&title!==criterion.criterion_id)return title;
      if(/^[a-z][a-z_ -]{0,38}$/i.test(title)&&!title.startsWith('criterion_'))return title.charAt(0).toUpperCase()+title.slice(1).replaceAll('_',' ');
      return MisraLocale.text('Criterion')+' '+num(ordinals.get(criterion.criterion_id));
    };
    const multiSnapshot=groups.size>1;
    const snapshots=[...groups].sort(([a],[b])=>String(a??'').localeCompare(String(b??'')));
    const criteria=snapshots.map(([version,rows],index)=>{
      const entries=rows.slice().sort((a,b)=>(a.average_percent??Infinity)-(b.average_percent??Infinity));
      const first=entries[0], count=first.assessed_count;
      const low=entries.filter(row=>row.average_percent===first.average_percent);
      const focus=first.average_percent!=null&&first.average_percent<100&&count>0&&low.length<entries.length
        ? '<p class="insight-focus"><strong data-i18n>Lowest average</strong> <span dir="auto">'+low.map(row=>esc(label(row))).join(', ')+'</span> · '+num(first.average_percent)+'%</p>' : '';
      const snapshot=multiSnapshot?'<h4 class="insight-rubric-heading"><span data-i18n>Saved rubric snapshot</span> '+num(index+1)+'</h4>':'';
      const reference=multiSnapshot&&version?'<details class="insight-rubric-reference"><summary data-i18n>Rubric snapshot reference</summary><p><code dir="ltr">'+esc(version)+'</code></p></details>':'';
      return snapshot+focus+'<ul class="insight-criteria">'+entries.map(row=>renderCriterion(row,label(row),multiSnapshot?'h5':'h4')).join('')+'</ul>'+reference;
    }).join('');
    const average=question.average_percent==null?'': '<div><dt data-i18n>Average</dt><dd>'+num(question.average_percent)+'%</dd></div>';
    const evidence=question.graded_count>0&&Number.isInteger(question.course_grounded_count)
      ? '<p class="muted">'+num(question.course_grounded_count)+' / '+num(question.graded_count)+' <span data-i18n>with cited course evidence</span></p>' : '';
    const exclusions=question.criterion_override_excluded_count?'<p class="muted">'+num(question.criterion_override_excluded_count)+' <span data-i18n>total-only overrides excluded from criterion counts</span></p>':'';
    return '<section class="insight-question"><header><div><h3><span data-i18n>Question</span> <bdi>'+esc(question.question_number)+'</bdi></h3><p dir="auto">'+esc(question.question_text)+'</p></div>'+
      '<dl class="insight-question-stats"><div><dt data-i18n>Graded</dt><dd>'+num(question.graded_count)+'</dd></div>'+average+
      '<div><dt data-i18n>Awaiting review</dt><dd>'+num(question.awaiting_review_count)+'</dd></div></dl></header>'+
      (criteria||'<p class="insight-empty" data-i18n>Criterion counts appear when papers have recorded criterion marks.</p>')+evidence+exclusions+'</section>';
  }
  let insightsRequest=0;
  async function insights(){
    if(!exam)return;
    const request=++insightsRequest, selectedExam=exam, current=epoch;
    const target=$('learning-insights'), state=$('insights-state'), button=$('refresh-insights');
    const existing=target.dataset.exam===selectedExam;
    if(!existing){target.replaceChildren();delete target.dataset.exam;}
    button.disabled=true;target.setAttribute('aria-busy','true');
    state.className='';state.textContent=MisraLocale.text('Reading recorded class feedback…');
    try{
      const data=await MisraAPI.learningInsights(selectedExam);
      if(request!==insightsRequest||current!==epoch||routeScope.signal.aborted)return;
      if(data?.exam_id!==selectedExam||!Array.isArray(data.questions))throw Error('Class feedback response incomplete.');
      const examQuery=new URLSearchParams({exam_id:selectedExam});
      const needsReview=data.questions.some(question=>question.awaiting_review_count>0);
      const link=needsReview?'<a href="reviews.html?'+examQuery+'" data-i18n>Review flagged papers</a>' :
        '<a href="grading.html?'+examQuery+'" data-i18n>View papers</a>';
      const marks=data.questions.some(question=>question.graded_count>0);
      const notes=(data.notes||[]).filter(note=>typeof note==='string'&&note.trim());
      if(data.confidence_status==='uncalibrated')notes.unshift('Model confidence is uncalibrated.');
      target.innerHTML='<div class="insight-overview"><p><strong>'+num(data.submission_count)+'</strong> <span data-i18n>uploaded papers</span></p>'+link+'</div>'+
        (marks?data.questions.map(renderQuestionInsights).join(''):'<p class="insight-empty" data-i18n>Class feedback appears after the first paper is graded.</p>')+
        (notes.length&&marks?'<details class="insight-method"><summary data-i18n>How these observations are calculated</summary><ul>'+notes.map(note=>'<li data-i18n>'+esc(note)+'</li>').join('')+'</ul></details>':'');
      target.dataset.exam=selectedExam;state.textContent='';MisraLocale.apply();
    }catch(error){
      if(request===insightsRequest&&current===epoch&&!routeScope.signal.aborted){
        state.className='form-error';
        state.textContent=existing?MisraLocale.text('Refresh failed. Showing the last loaded feedback.')+' '+error.message :
          MisraLocale.text('Class feedback could not load. Try refreshing.')+' '+error.message;
      }
    }finally{
      if(request===insightsRequest&&!routeScope.signal.aborted){button.disabled=false;target.removeAttribute('aria-busy');}
    }
  }
  function showEvidence(pack,criteria){const table=$('question-detail').querySelector('.criteria-table');if(!table)return;[...table.querySelectorAll('tbody tr')].forEach((row,i)=>{const c=criteria[i],sources=(pack?.course_references?.passages || []).filter(p=>(c.reference_refs || []).includes(p.id));const details=document.createElement('details');details.className='source-trace';details.innerHTML=`<summary>Lecture evidence &amp; student references</summary>${sources.map(p=>`<p><strong>${esc(p.title)} · document page ${p.page_index+1}</strong> <a target="_blank" rel="noopener" href="${esc(MisraAPI.materialDocumentUrl(p.material_id,p.material_version_id))}#page=${p.page_index+1}">Open original source</a></p><p dir="auto">${esc(p.text)}</p>`).join('') || '<p>No course passage was cited for this recorded criterion. This older result is not evidence of lecture-grounded grading.</p>'}<p>Student evidence: ${esc((c.evidence_refs || []).map(id=>{const e=(pack?.student_evidence || []).find(e=>e.id===id);return e?.page_index!=null?`Paper page ${e.page_index+1}${e.segment_index!=null?`, segment ${e.segment_index+1}`:''}`:e?.kind==='combined_ocr'?'Combined extracted answer':'Saved student evidence';}).join('; ') || 'No citation recorded')}.</p><p>Applied marking rules: ${esc((c.policy_applied || []).join(', ') || 'No individual policy citation recorded')}.</p><small>Citation identity is validated; academic support still needs instructor review. Saved source versions are preserved.</small>`;row.lastElementChild.append(details);});}
  insightsButton.addEventListener('click',async()=>{if(!await window.MisraLedgerWorkflows.canLeave())return;window.dispatchEvent(new CustomEvent('misra:ledger-task',{detail:{view:'insights'}}));insights();});$('refresh-insights').addEventListener('click',insights);
  routeScope.listen(window,'misra:assessment-loaded',e=>{++epoch;routeScope.cancelTimer(timer);exam=e.detail.examId;course=e.detail.courseId;busy=uncertain=uploadUncertain=false;clearDirty();selected=null;uploadFiles=[];shell();insightsButton.disabled=false;loadLibrary();history();});
  routeScope.listen(window,'misra:material-approved',()=>{if(!dirty && !busy)loadLibrary();});
  routeScope.listen(window,'beforeunload',e=>{if(busy || dirty){e.preventDefault();e.returnValue='';}});
  window.MisraTeaching={isBusy:()=>busy,hasUnsaved:()=>busy || dirty,canLeave:async()=>!busy && (!dirty || await MisraWorkspace.confirm('Discard unsaved lecture/quiz edits? Saved background jobs remain available.')),showEvidence,insights};
})();
