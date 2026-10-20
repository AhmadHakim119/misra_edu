/* Native ledger tasks; approvals and persisted jobs remain backend authority. */
(function () {
  'use strict';
  const $=id=>document.getElementById(id);
  const esc=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  window.MisraUI=window.MisraUI || {escapeHTML:esc};
  window.MisraUI.badge=window.MisraUI.badge || ((text)=>`<span class="status">${esc(text)}</span>`);
  window.showToast=window.showToast || ((message,type)=>{const target=$('ledger-notice');target.hidden=false;target.textContent=message;target.classList.toggle('form-error',type==='error');});
  let exam=null, epoch=0, checkSequence=0, sending=false, files=[], mode='single', ready=false, checking=false, ambiguous=false, accepted=null, recoveryId='',pollTimer=null;
  const active=new Set(['queued','processing','retrying']);
  const setupLink=()=>`setup.html?exam_id=${encodeURIComponent(exam?.id || '')}&tab=sources#import-existing-quiz`;
  function error(message) { $('upload-error').hidden=!message; $('upload-error').textContent=message || ''; }
  function sync() {
    const locked=sending || ambiguous || Boolean(accepted);
    $('ledger-files').disabled=locked || files.length>0;
    $('upload-drop').classList.toggle('selected',files.length>0);
    $('upload-drop').classList.toggle('locked',locked || files.length>0);
    $('upload-drop').setAttribute('aria-disabled',String(locked || files.length>0));
    $('upload-selection').innerHTML=files.map((f,i)=>`<li><span>${esc(f.name)} <small>${(f.size/1048576).toFixed(2)} MB</small></span><button type="button" data-remove="${i}" ${locked ? 'disabled' : ''}>Remove ${esc(f.name)}</button></li>`).join('');
    $('upload-hint').textContent=accepted ? 'Upload accepted. Choose Upload another selection before adding more papers.' : files.length ? 'Selection locked. Remove or clear these files to choose different papers.' : 'Choose files or drop them here. PDF, PNG, JPEG and WebP.';
    $('clear-upload').hidden=!files.length; $('clear-upload').disabled=locked;
    $('ledger-upload-submit').disabled=!exam || !ready || checking || locked || !files.length;
    $('ledger-upload-submit').textContent=sending ? 'Uploading…' : mode==='batch' ? 'Upload batch & start OCR' : 'Upload paper & start OCR';
    document.querySelectorAll('[data-ledger-upload-mode]').forEach(b=>{b.disabled=locked || files.length>0;b.setAttribute('aria-pressed',String(b.dataset.ledgerUploadMode===mode));});
    $('ledger-files').multiple=mode==='batch'; $('split-field').hidden=mode!=='batch'; $('ledger-split').disabled=locked;
    $('upload-another').hidden=!accepted && !ambiguous; $('upload-another').disabled=sending;
    $('upload-another').textContent=ambiguous ? 'I checked activity; choose a new selection' : 'Upload another selection';
    $('ledger-upload-form').setAttribute('aria-busy',String(sending));
    $('refresh-ledger-checks').disabled=checking || sending; $('refresh-upload-checks').disabled=checking || sending;
  }
  function select(list) {
    if(sending || ambiguous || accepted || files.length) return;
    const incoming=[...list];
    if(!incoming.length) return;
    if(incoming.some(f=>!(/\.(pdf|png|jpe?g|webp)$/i.test(f.name)))) {error('Choose only PDF, PNG, JPEG or WebP files. No files were selected.');$('ledger-files').value='';return;}
    if(mode==='single' && incoming.length!==1) {error('Choose Batch before selecting several files.');$('ledger-files').value='';return;}
    files=incoming; error(''); sync();
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches) $('upload-selection').animate([{opacity:.75,transform:'translateY(-3px)'},{opacity:1,transform:'none'}],{duration:180,easing:'cubic-bezier(.16,1,.3,1)'});
  }
  function hasUnsaved() {return sending || files.length>0 || ambiguous || Boolean(window.MisraAssessmentSources?.hasUnsaved()) || Boolean(window.MisraLedgerEditors?.hasUnsaved()) || Boolean(window.MisraTeaching?.hasUnsaved());}
  function canLeave() {
    if(window.MisraTeaching?.canLeave()===false) return false;
    if(sending || window.MisraAssessmentSources?.isBusy() || window.MisraLedgerEditors?.isBusy()) {error('Wait for the current upload or approval to finish.');return false;}
    if(window.MisraLedgerEditors?.canLeave()===false) return false;
    if(window.MisraAssessmentSources?.canLeave()===false) return false;
    return !(files.length || ambiguous) || window.confirm(ambiguous ? 'Upload acceptance is uncertain. Check background activity before uploading this paper again. Leave this assessment?' : 'Discard the selected files? Nothing has been uploaded yet.');
  }
  async function checks() {
    if(!exam) return;
    const current=epoch,id=exam.id,sequence=++checkSequence; ready=false;checking=true;sync();
    $('ledger-readiness').textContent='Checking approved assessment setup…';
    try {
      const value=await MisraAPI.setupReadiness(id); if(current!==epoch || sequence!==checkSequence) return;
      if(typeof value?.ready!=='boolean') throw new Error('Incomplete setup response. Reload checks before uploading.');
      ready=value.ready; $('ledger-readiness').textContent=value.message || (ready ? 'Setup checked. Student papers can be uploaded.' : 'Resolve the setup checks before uploading.');
      window.dispatchEvent(new CustomEvent('misra:assessment-readiness',{detail:{examId:id,ready}}));
      $('setup-overview').innerHTML=`<p>${esc(value.message || 'Assessment setup checks')}</p><p class="muted">These checks verify approved definitions, not AI marking accuracy.</p>${(value.questions || []).length ? `<ul class="setup-question-list">${value.questions.map(q=>`<li><div><strong>Question ${esc(q.question_number)} · ${esc(q.max_score)} marks</strong><p>${q.approved ? `Approved rubric` : q.definition_ready ? 'Existing rubric accepted' : 'Rubric needs approval'}${q.answer_key_version ? ` · Approved answer key` : ''}</p>${[...(q.errors || []),...(q.warnings || [])].map(t=>`<p>${esc(t)}</p>`).join('')}</div><button type="button" data-author-question="${esc(q.question_id)}">Edit marking guide</button></li>`).join('')}</ul>` : '<p>Add your first question below before uploading student papers.</p>'}`;
    } catch(failure) { if(current===epoch && sequence===checkSequence) {$('ledger-readiness').textContent='Could not verify setup. Upload stays closed; refresh checks.';$('setup-overview').innerHTML=`<p role="alert">Could not check setup: ${esc(failure.message)}</p>`;} }
    finally {if(current===epoch && sequence===checkSequence) {checking=false;sync();}}
  }
  function show(view) {window.dispatchEvent(new CustomEvent('misra:ledger-task',{detail:{view}})); if(view==='upload') {$('ledger-upload-title').focus({preventScroll:true});checks();} else if(view==='setup') {checks();} }
  function loadExam(value) {
    ++epoch;clearTimeout(pollTimer); exam=value;ready=false;checking=false; files=[];ambiguous=false;accepted=null;recoveryId='';$('ledger-files').value='';$('ledger-split').value='';error('');$('upload-accepted').innerHTML='';
    $('original-studio').href=setupLink();window.MisraLedgerEditors?.reset(exam);
    window.MisraAssessmentSources?.reset();
    if(exam.course_id) window.dispatchEvent(new CustomEvent('misra:assessment-loaded',{detail:{examId:exam.id,courseId:exam.course_id}}));
    else $('assessment-sources-host').innerHTML='<p>Course information is unavailable. Check assessment setup in the full Rubric Studio.</p>';
    $('setup-overview').innerHTML='<p>Open Sources &amp; rubric to check the approved assessment definitions.</p>';sync();
  }
  function restoreJobs(items,wanted) {
    if(!exam || accepted || sending || files.length || ambiguous) return;
    const owned=items.filter(j=>j.exam_id===exam.id && !['locate_answers','read_answer_area'].includes(j.operation) && ['ocr_submission','ocr_batch'].includes(j.job_type));
    const job=wanted ? owned.find(j=>j.id===wanted) : owned.find(j=>active.has(j.status));
    if(job) {accepted=job;mode=job.job_type==='ocr_batch' ? 'batch' : 'single';sync();poll();}
    else if(wanted) {recoveryId=wanted;ambiguous=true;error('The saved upload is not in recent activity. Check the paper list and full activity history before uploading it again.');sync();}
  }
  async function poll() {
    if(!accepted || !exam) return;
    clearTimeout(pollTimer); const current=epoch,record=accepted;
    try {
      const job=await MisraAPI.job(record.id); if(current!==epoch || record!==accepted) return;
      if(job?.id!==record.id || !['queued','processing','retrying','completed','failed'].includes(job.status)) throw new Error('Incomplete job status.');
      const pct=Number(job.progress_percent);
      $('upload-accepted').innerHTML=`<h3>${job.status==='completed' ? 'Extraction job completed' : job.status==='failed' ? 'Extraction stopped' : 'Upload accepted · OCR '+esc(job.status)}</h3>${active.has(job.status) ? `<progress max="100" value="${Number.isFinite(pct) ? Math.min(100,Math.max(0,pct)) : 0}" aria-label="OCR progress"></progress>` : ''}<p>${esc(job.error_message || job.progress_message || 'Open the papers list to inspect extracted answers. A completed job does not certify extraction or marks.')}</p>${job.status==='completed' && (job.submission_id || record.submission_id) ? `<button class="primary" type="button" data-open-saved-paper="${esc(job.submission_id || record.submission_id)}">Open extracted paper</button>` : '<button type="button" data-show-papers>View papers &amp; extraction</button>'}${job.status==='failed' ? '<p>Use Retry safely in background activity. Do not upload the paper again.</p>' : ''}`;
      window.dispatchEvent(new CustomEvent('misra:ledger-jobs-changed'));
      if(active.has(job.status)) pollTimer=setTimeout(poll,4000);
    } catch(_) {if(current===epoch) {$('upload-accepted').innerHTML='<h3>Progress connection interrupted</h3><p>The upload was accepted. OCR may still be running; do not upload it again.</p><button type="button" data-poll-upload>Reconnect progress</button>';}}
  }
  $('ledger-files').addEventListener('change',e=>select(e.target.files));
  ['dragover','dragenter'].forEach(name=>$('upload-drop').addEventListener(name,e=>{e.preventDefault();if(!files.length && !sending && !accepted && !ambiguous) $('upload-drop').classList.add('dragging');}));
  $('upload-drop').addEventListener('dragleave',()=>$('upload-drop').classList.remove('dragging'));
  $('upload-drop').addEventListener('drop',e=>{e.preventDefault();$('upload-drop').classList.remove('dragging');select(e.dataTransfer.files);});
  $('upload-selection').addEventListener('click',e=>{const b=e.target.closest('[data-remove]');if(b && !sending && !accepted && !ambiguous) {files.splice(Number(b.dataset.remove),1);$('ledger-files').value='';sync();}});
  $('clear-upload').addEventListener('click',()=>{if(sending || accepted || ambiguous) return;files=[];$('ledger-files').value='';sync();});
  document.querySelectorAll('[data-ledger-upload-mode]').forEach(b=>b.addEventListener('click',()=>{if(!files.length && !sending && !accepted && !ambiguous) {mode=b.dataset.ledgerUploadMode;sync();}}));
  $('refresh-ledger-checks').addEventListener('click',checks);$('refresh-upload-checks').addEventListener('click',checks);
  $('upload-another').addEventListener('click',()=>{if(sending) return;if(ambiguous && !window.confirm('Confirm you checked the papers list and background activity, and this upload was not accepted. Start a new selection?')) return;clearTimeout(pollTimer);accepted=null;recoveryId='';ambiguous=false;files=[];$('ledger-files').value='';$('upload-accepted').innerHTML='';error('');sync();window.dispatchEvent(new CustomEvent('misra:ledger-url-changed'));});
  $('ledger-upload-form').addEventListener('submit',async e=>{
    e.preventDefault();if(sending || ambiguous || accepted || !ready || !files.length || !exam || window.MisraAssessmentSources?.isBusy()) return;
    const split=$('ledger-split').value.trim();
    if(mode==='batch' && split && (!Number.isSafeInteger(Number(split)) || Number(split)<1 || files.length!==1 || !/\.pdf$/i.test(files[0].name))) {error('Pages per student must be a positive whole number for one combined PDF only.');return;}
    const body=new FormData();body.append('exam_id',exam.id);files.forEach(f=>body.append(mode==='batch' ? 'files' : 'file',f));if(mode==='batch' && split) body.append('pages_per_student',split);
    sending=true;error('');sync();const current=epoch;
    try {
      const value=mode==='batch' ? await MisraAPI.uploadBatch(body) : await MisraAPI.uploadExam(body);
      if(current!==epoch) return;
      const recordId=mode==='single' ? value?.submission?.id || value?.job?.submission_id : value?.batch_id || value?.job?.batch_id;
      const jobRecordId=mode==='single' ? value?.job?.submission_id : value?.job?.batch_id;
      if(typeof value?.job?.id!=='string' || !value.job.id || typeof recordId!=='string' || !recordId || jobRecordId && jobRecordId!==recordId) throw new Error('Upload response was incomplete.');
      accepted={...value.job,[mode==='single' ? 'submission_id' : 'batch_id']:recordId};files=[];$('ledger-files').value='';$('upload-accepted').innerHTML='<h3>Upload accepted · OCR queued</h3><p>Processing is saved in the background. You can return to Papers without re-uploading.</p><button type="button" data-show-papers>View papers &amp; extraction</button>';window.dispatchEvent(new CustomEvent('misra:ledger-url-changed'));window.dispatchEvent(new CustomEvent('misra:ledger-jobs-changed'));poll();
    } catch(failure) {if(current===epoch) {ambiguous=!failure.status || failure.status>=500;error(ambiguous ? `${failure.message} Could not confirm acceptance. It may be queued; check Papers and background activity before uploading again.` : `${failure.message} Your selection is retained; no automatic retry was sent.`);}}
    finally {if(current===epoch) {sending=false;sync();}}
  });
  document.addEventListener('click',e=>{if(e.target.closest('[data-poll-upload]')) poll();if(e.target.closest('[data-show-papers]')) show('papers');});
  window.addEventListener('beforeunload',e=>{if(hasUnsaved()) {e.preventDefault();e.returnValue='';}});
  window.addEventListener('misra:ledger-foundations-changed',checks);
  window.addEventListener('misra:answer-key-approved',checks);
  window.MisraLedgerWorkflows={loadExam,show,restoreJobs,currentJobId:()=>accepted?.id || recoveryId,hasUnsaved,canLeave,isBusy:()=>Boolean(window.MisraTeaching?.isBusy()) || sending || Boolean(window.MisraAssessmentSources?.isBusy()) || Boolean(window.MisraLedgerEditors?.isBusy())};
})();
