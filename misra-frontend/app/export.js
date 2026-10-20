/* Assessment-scoped exports share the server's readiness and download contracts. */
(function () {
  'use strict';
  const $=id=>document.getElementById(id),esc=value=>MisraUI.escapeHTML(String(value ?? ''));
  let exam=null,epoch=0,sequence=0,busy=false,checking=false,data=null;
  const blackboard=()=>$('native-export-profile').value==='blackboard';
  function sync() {
    $('native-export-note').textContent=blackboard() ? 'Blackboard imports Username and one grade column. Student number is used as Username: confirm it matches your Blackboard roster. Incomplete, flagged or unidentified grades are excluded.' : 'Generic CSV is a report of recorded identity, marks, completion and review state. It may include incomplete or flagged records; map its columns to your LMS.';
    $('native-export-csv').disabled=busy || checking || !data || !data.rows.some(r=>!blackboard() || !r.issues.some(i=>i.blocking));
    $('native-export-xlsx').disabled=busy || !exam;
    $('native-export-profile').disabled=busy; $('refresh-export').disabled=busy || checking;
  }
  function loadExam(value) {exam=value;++epoch;++sequence;data=null;checking=false;$('native-export-checks').innerHTML='';$('native-export-status').textContent='';sync();}
  async function show() {
    if(!exam || busy) return;
    const current=epoch,request=++sequence;data=null;checking=true;sync();$('native-export-status').textContent='Checking recorded marks, review flags and student identity…';
    try {
      const result=await MisraAPI.gradeExportPreflight(exam.id,'student_number');if(current!==epoch || request!==sequence) return;
      if(!Array.isArray(result?.rows) || result.rows.some(r=>!Array.isArray(r.issues))) throw new Error('Incomplete export response. Refresh before downloading CSV.');
      data=result;render();$('native-export-status').textContent='Export checks loaded. Files use the server’s current recorded marks.';
    } catch(e) {if(current===epoch && request===sequence) {$('native-export-checks').innerHTML=`<p role="alert">${esc(e.message)}</p>`;$('native-export-status').textContent='CSV remains unavailable. Refresh checks or use Excel to inspect the recorded results.';}}
    finally {if(current===epoch && request===sequence) {checking=false;sync();}}
  }
  function render() {
    if(!data) return;
    const included=data.rows.filter(r=>!blackboard() || !r.issues.some(i=>i.blocking));
    $('native-export-checks').innerHTML=`<h3>${included.length} included · ${data.rows.length-included.length} excluded</h3><p>Grade column: <strong>${esc(data.grade_column)}</strong></p>${data.rows.length ? `<div class="export-table-wrap"><table class="paper-table"><thead><tr><th scope="col">Student / Username</th><th scope="col">Recorded mark</th><th scope="col">Included?</th><th scope="col">Next action</th></tr></thead><tbody>${data.rows.map(row=>{const excluded=blackboard() && row.issues.some(i=>i.blocking);return `<tr><td data-label="Student / Username"><strong>${esc(row.student_name || 'Name missing')}</strong><small><br>${esc(row.username || 'Student number missing')}</small></td><td data-label="Recorded mark">${row.score==null ? 'Not recorded' : esc(row.score)} / ${esc(row.max_score)}</td><td data-label="Included?">${excluded ? 'Excluded' : 'Included'}${row.issues.length ? `<p>${row.issues.map(i=>esc(i.message)).join(' · ')}</p>` : ''}</td><td data-label="Next action"><button type="button" data-open-saved-paper="${esc(row.submission_id)}">${row.issues.length ? 'Open paper to resolve' : 'View recorded grade'}</button></td></tr>`;}).join('')}</tbody></table></div>` : '<p>No submissions for this assessment yet.</p>'}`;
  }
  async function download(kind) {
    if(busy || !exam || kind==='csv' && $('native-export-csv').disabled) return;
    busy=true;sync();$('native-export-status').textContent='Preparing download…';
    try {
      const url=kind==='xlsx' ? MisraAPI.gradeExportXlsxUrl(exam.id) : MisraAPI.gradeExportCsvUrl(exam.id,$('native-export-profile').value,'student_number');
      const response=await fetch(url,{credentials:'include',cache:'no-store'});
      if(!response.ok) {const body=await response.json().catch(()=>({}));throw new Error(typeof body.detail==='string' ? body.detail : body.detail?.message || `Download failed (${response.status}).`);}
      const blob=await response.blob();if(!blob.size) throw new Error('The downloaded file is empty. Refresh checks before retrying.');
      const header=response.headers.get('content-disposition') || '',name=header.match(/filename="?([^";]+)"?/i)?.[1] || `grades.${kind==='xlsx' ? 'xlsx' : 'csv'}`;
      const object=URL.createObjectURL(blob),link=document.createElement('a');link.href=object;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(object),1000);
      const omitted=Number(response.headers.get('x-misra-omitted-rows') || 0);$('native-export-status').textContent=`File downloaded.${omitted ? ` ${omitted} rows withheld. Review exclusions before LMS import.` : ''}`;
    } catch(e) {$('native-export-status').textContent=e.message;window.showToast(e.message,'error');}
    finally {busy=false;sync();}
  }
  $('native-export-profile').addEventListener('change',()=>{render();sync();});$('refresh-export').addEventListener('click',show);
  $('native-export-csv').addEventListener('click',()=>download('csv'));$('native-export-xlsx').addEventListener('click',()=>download('xlsx'));
  window.MisraLedgerExport={loadExam,show,isBusy:()=>busy};
})();
