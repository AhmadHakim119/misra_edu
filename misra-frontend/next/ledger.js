/* Parallel instructor ledger. Private drafts stay in memory; API records are authoritative. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value == null ? '—' : Number.isFinite(Number(value)) ? Number(value).toLocaleString(undefined,{maximumFractionDigits:2}) : '—';
  const score = answer => answer?.teacher_override_score ?? answer?.score ?? null;
  const active = new Set(['queued','processing','retrying']);
  const params = new URLSearchParams(location.search);
  let exams = [], papers = [], jobs = [], examId = '', paperId = '', questionId = '', pageIndex = 0;
  let results = null, extraction = null, epoch = 0, paperEpoch = 0, locationEpoch = 0, timer = null,currentView='papers';
  let dirty = false, busy = false, reviewOnly = false, jobsUnavailable = false, selectedJobSignature = '', lastPaperMarkup = '';
  let zoom = 100, nextAction={kind:'setup'}, setupReady=null,identityDirty=false,identityBusy=false;
  const viewerHome = document.createComment('Original paper viewer home');
  $('paper-viewer').before(viewerHome);
  const excerpt = value => { const text=String(value || ''); return esc(text.length>360 ? `${text.slice(0,360)}…` : text); };
  const reasons = {valid_alternative:'Valid alternative',minor_notation:'Minor notation',method_credit:'Method credit',carried_forward_error:'Error carried forward',language_tolerance:'Language tolerance',rubric_issue:'Rubric issue',ocr_or_mapping_error:'OCR or mapping error',unsupported_deduction:'Unsupported deduction',evidence_citation_error:'Evidence citation error',other:'Other marking decision'};
  const currentRow = () => extraction?.questions?.find(r=>r.question.id===questionId);
  const currentAnswer = () => results?.answers?.find(a=>a.question_id===questionId);
  const currentLabel = () => results?.latest_review_labels?.find(l=>l.answer_id===currentAnswer()?.id);
  function canLeave(workflow=false) { if (busy || identityBusy || window.MisraLedgerWorkflows?.isBusy() || window.MisraLedgerExport?.isBusy()) { showError('Wait for the current operation to finish.'); return false; } if(identityDirty && !confirm('Discard unsaved paper-identity changes?')) return false;if(dirty && !window.confirm('Discard unsaved instructor-grade changes?')) return false; return !workflow || window.MisraLedgerWorkflows?.canLeave()!==false; }
  function showError(message) { $('error').hidden=false; $('error').textContent=message; }
  function clearError() { $('error').hidden=true; $('error').textContent=''; }
  function updateNextAction() {
    const running=jobs.find(j=>j.exam_id===examId && active.has(j.status));
    const review=papers.find(p=>paperState(p).kind==='warning' || paperState(p).kind==='failed');
    const grade=papers.find(p=>p.readiness?.bulk_grading_allowed && !p.grading_summary?.complete);
    let message,label;
    if(running) {message='Processing continues in the background. Check progress—do not upload again.';label='View progress';nextAction={kind:'activity'};}
    else if(setupReady===false) {message='Finish the approved marking definitions before uploading student papers.';label='Finish setup';nextAction={kind:'setup'};}
    else if(review) {message='A paper needs evidence or grade review. Start with the flagged work.';label='Review next paper';nextAction={kind:'paper',id:review.id};}
    else if(grade) {message='An extracted paper is ready for grading.';label='Open ready paper';nextAction={kind:'paper',id:grade.id};}
    else if(papers.length && papers.every(p=>p.grading_summary?.complete)) {message='Recorded marks are available. Check export eligibility and roster identities.';label='Check export';nextAction={kind:'export'};}
    else {message=setupReady===null ? 'Check the assessment definitions before uploading papers.' : 'Your marking definitions are ready. Upload student papers next.';label=setupReady===null ? 'Check setup' : 'Upload papers';nextAction={kind:setupReady===null ? 'setup' : 'upload'};}
    $('next-action-copy').textContent=message;$('next-action').textContent=label;$('next-action').disabled=!examId;
  }
  function syncURL() {
    const query = new URLSearchParams(); if (examId) query.set('exam_id',examId); if (paperId) query.set('submission_id',paperId); if (questionId) query.set('question_id',questionId);
    if(currentView!=='papers') query.set('view',currentView); const job=window.MisraLedgerWorkflows?.currentJobId();if(job) query.set('job_id',job);
    history.replaceState(null,'',`${location.pathname}?${query}`);
  }
  function legacy(file, values={}) { return `../pages/${file}.html?${new URLSearchParams(values)}`; }
  function renderAssessments() {
    const query = $('assessment-search').value.trim().toLowerCase();
    const visible = exams.filter(e=>`${e.title} ${e.course_code || ''}`.toLowerCase().includes(query));
    $('assessment-list').innerHTML = visible.length ? visible.map(e=>`<button type="button" class="assessment-entry" data-exam="${esc(e.id)}" aria-current="${e.id===examId}"><strong>${esc(e.title)}</strong><small>${esc(e.course_code || 'Course')} · ${number(e.submission_count ?? 0)} papers</small></button>`).join('') : '<div class="empty"><p>No assessments match. Create or manage assessments in the original workspace.</p></div>';
  }
  function paperState(p) {
    if (active.has(p.latest_ocr_job?.status)) return {label:`OCR ${p.latest_ocr_job.status}`,kind:'processing'};
    if (active.has(p.latest_grading_job?.status)) return {label:`Grading ${p.latest_grading_job.status}`,kind:'processing'};
    if (p.latest_ocr_job?.status==='failed' || p.status==='error') return {label:'Extraction stopped',kind:'failed'};
    if (p.latest_grading_job?.status==='failed') return {label:'Grading stopped',kind:'failed'};
    if (p.grading_summary?.review_count > 0) return {label:'Needs review',kind:'warning'};
    if (p.grading_summary?.complete) return {label:'Grading complete',kind:''};
    if (p.readiness?.bulk_grading_allowed) return {label:'Ready to grade',kind:''};
    return {label:'Check extraction',kind:'warning'};
  }
  function renderPapers() {
    updateNextAction();
    const query = $('paper-search').value.trim().toLowerCase();
    const visible = papers.filter(p=>`${p.extracted_student_name || ''} ${p.extracted_student_number || ''} ${p.id}`.toLowerCase().includes(query) && (!reviewOnly || paperState(p).kind==='warning' || paperState(p).kind==='failed'));
    $('papers-title').textContent = reviewOnly ? 'Papers needing attention' : 'Student papers';
    if (!visible.length) {
      writePaperMarkup(`<div class="empty"><p>${papers.length ? 'No papers match this view. Clear the search or return to Papers.' : 'No student papers yet. Approve your sources and marking guide, then upload papers.'}</p></div>`); return;
    }
    const markup=`<table class="paper-table"><thead><tr><th scope="col">Student</th><th scope="col">Status</th><th scope="col">Recorded grade</th><th scope="col">Next action</th></tr></thead><tbody>${visible.map(p=> {
      const state=paperState(p), summary=p.grading_summary;
      const label=state.kind==='processing' ? 'View progress' : summary?.review_count ? 'Review grade' : summary?.complete ? 'View results' : 'Open paper';
      return `<tr class="${p.id===paperId ? 'selected' : ''}"><td><strong>${esc(p.extracted_student_name || 'Name missing')}</strong><small class="muted"><br>${esc(p.extracted_student_number || 'Student number missing')}</small></td><td><span class="status ${state.kind}">${esc(state.label)}</span><small class="muted"><br>${number(p.page_count)} pages${summary && !summary.complete && summary.graded_count ? ` · ${summary.graded_count}/${summary.expected_count} graded` : ''}</small></td><td class="score">${summary?.recorded_score != null ? `${number(summary.recorded_score)} / ${number(summary.max_score)}` : '—'}</td><td><button type="button" data-paper="${esc(p.id)}" class="${p.id===paperId ? 'primary' : ''}">${label}</button></td></tr>`;
    }).join('')}</tbody></table>`;
    writePaperMarkup(markup);
  }
  function writePaperMarkup(markup) {
    if(markup===lastPaperMarkup) return;
    const focus=$('paper-list').contains(document.activeElement) ? document.activeElement.dataset.paper : null;
    lastPaperMarkup=markup; $('paper-list').innerHTML=markup;
    if(focus) [...$('paper-list').querySelectorAll('[data-paper]')].find(el=>el.dataset.paper===focus)?.focus({preventScroll:true});
  }
  function renderJobs() {
    const relevant = jobs.filter(j=>j.exam_id===examId);
    $('background-activity').innerHTML = `${jobsUnavailable ? '<div class="notice">Progress connection interrupted. Jobs may still be running; do not upload again. <button type="button" data-reconnect>Reconnect progress</button></div>' : ''}${!relevant.length ? '<p>No recent activity for this assessment.</p>' : ''}${relevant.map(j=>`<div class="job-row"><strong>${esc(j.job_type?.replaceAll('_',' ') || 'Background job')}</strong> · ${esc(j.status)}${active.has(j.status) ? `<progress max="100" value="${Math.min(100,Math.max(0,Number(j.progress_percent)||0))}" aria-label="${esc(j.job_type)} progress"></progress>` : ''}<p>${esc(j.error_message || j.progress_message || '')}</p>${j.status==='failed' ? `<button type="button" data-retry="${esc(j.id)}">Retry safely</button>` : ''}${j.submission_id ? `<button type="button" data-open-saved-paper="${esc(j.submission_id)}">Open paper</button>` : ''}</div>`).join('')}`;
    updateNextAction();
  }
  async function loadJobs() {
    const current=epoch;
    try { const response=await MisraAPI.workspaceJobs(20); if(current!==epoch) return; if (!Array.isArray(response?.items)) throw new Error('Incomplete job response'); jobs=response.items; jobsUnavailable=false; }
    catch (_) { if(current!==epoch) return;jobsUnavailable=true; }
    renderJobs();
  }
  async function chooseExam(id, {initial=false}={}) {
    if (!initial && !canLeave(true)) return;
    const exam=exams.find(e=>e.id===id); if (!exam) return;
    const current=++epoch; ++paperEpoch; ++locationEpoch; clearTimeout(timer);
    examId=id; paperId=questionId=''; papers=[];jobs=[];setupReady=null;results=extraction=null; dirty=identityDirty=false; pageIndex=0; lastPaperMarkup=''; clearError(); renderAssessments();updateNextAction();
    $('exam-title').textContent=exam.title; $('exam-context').textContent=[exam.course_code,exam.course_title].filter(Boolean).join(' · ') || 'Assessment workspace';
    window.MisraLedgerExport?.loadExam(exam);
    window.MisraLedgerWorkflows?.loadExam(exam); setView('papers');
    $('upload-link').disabled=false; $('sources-link').disabled=false;$('export-link').disabled=false;$('paper-picker').open=true;$('selected-paper-copy').hidden=true;
    $('paper-list').innerHTML='<div class="empty" role="status">Loading student papers…</div>';
    $('question-detail').innerHTML='<div class="empty"><p>Select a paper to inspect its evidence and decisions.</p></div>'; resetEvidence();
    try {
      const value=await MisraAPI.submissions(id); if (current!==epoch) return;
      if (!Array.isArray(value)) throw new Error('Paper list is incomplete. Reload the assessment.');
      papers=value.filter(p=>p.exam_id===id); renderPapers();
      const wanted=initial ? params.get('submission_id') : null;
      const selected=papers.find(p=>p.id===wanted);
      if (selected) await choosePaper(selected.id,{initial,unguarded:true}); else syncURL();
    } catch (error) { if (current===epoch) { showError(error.message); $('paper-list').innerHTML='<div class="empty"><button type="button" data-reload-assessment>Reload assessment</button></div>'; } }
    if (current===epoch) { await loadJobs();if(current!==epoch) return;window.MisraLedgerWorkflows?.restoreJobs(jobs,initial ? params.get('job_id') : null);if(initial && ['setup','upload'].includes(params.get('view'))) window.MisraLedgerWorkflows?.show(params.get('view'));if(initial && ['export','activity'].includes(params.get('view'))) {setView(params.get('view'));if(currentView==='export') window.MisraLedgerExport?.show();}syncURL();schedule(); }
  }
  function resetEvidence() {
    $('page-controls').hidden=true; $('viewer-tools').hidden=true; zoom=100; $('paper-status').textContent=''; $('paper-name').textContent=''; $('grade-editor').innerHTML=''; $('location-note').textContent='';
    $('paper-viewport').innerHTML='<div class="empty"><p>Select a paper to view the full original page.</p></div>';
  }
  async function choosePaper(id,{initial=false,unguarded=false}={}) {
    if (!unguarded && !canLeave()) return;
    const previousQuestion=questionId, previousPage=pageIndex, retained=paperId===id && Boolean(results);
    const current=++paperEpoch, examCurrent=epoch; ++locationEpoch;
    paperId=id; dirty=identityDirty=false; clearError(); renderPapers();
    $('selected-paper-copy').hidden=false;$('selected-paper-copy').textContent='Selected paper: '+(papers.find(p=>p.id===id)?.extracted_student_name || 'Name missing');
    if(!initial && !unguarded) $('paper-picker').open=false;
    setView(currentView);
    if(!retained) { questionId=''; results=extraction=null; resetEvidence(); $('question-detail').innerHTML='<div class="empty" role="status">Reading the saved extraction and grades…</div>'; }
    syncURL();
    try {
      const [record,report]=await Promise.all([MisraAPI.results(id),MisraAPI.extractionReview(id)]);
      if (current!==paperEpoch || examCurrent!==epoch) return;
      if (record?.submission?.id!==id || report?.submission?.id!==id || record.submission.exam_id!==examId || !Array.isArray(report.questions) || !Array.isArray(record.answers)) throw new Error('Paper response is incomplete or belongs to another assessment. Reload before reviewing.');
      results=record; extraction=report;renderIdentity();
      const wanted=initial ? params.get('question_id') : retained ? previousQuestion : null;
      questionId=report.questions.find(r=>r.question.id===wanted)?.question.id || report.questions.find(r=>record.answers.find(a=>a.question_id===r.question.id)?.needs_review)?.question.id || report.questions[0]?.question.id || '';
      renderQuestion(); if(retained && questionId===previousQuestion && previousPage<Number(report.submission.page_count)) showPage(previousPage); syncURL();
      return true;
    } catch (error) { if (current===paperEpoch && examCurrent===epoch) { showError(error.message); if(!retained) $('question-detail').innerHTML='<div class="empty"><button type="button" data-reload-paper>Reload saved paper</button></div>'; else { const button=document.createElement('button'); button.type='button';button.dataset.reloadPaper='';button.textContent='Reload saved paper';$('error').append(' ',button); } } return false; }
  }
  function renderQuestion() {
    const row=currentRow(), answer=currentAnswer(), pack=answer?.grading_raw_response?.grading_package;
    const pageCount=Number(extraction?.submission.page_count) || 0;
    $('paper-name').textContent=extraction?.submission.extracted_student_name || 'Name missing';
    const paper=papers.find(p=>p.id===paperId);
    const ocrJob=paper?.latest_ocr_job, gradeJob=paper?.latest_grading_job;
    const ocrState=active.has(ocrJob?.status) ? ocrJob.status : ocrJob?.status==='failed' || paper?.status==='error' ? 'stopped' : extraction?.readiness?.bulk_grading_allowed ? 'ready' : 'check evidence';
    const gradeState=active.has(gradeJob?.status) ? gradeJob.status : gradeJob?.status==='failed' ? 'stopped' : paper?.grading_summary?.complete ? 'complete' : paper?.grading_summary?.graded_count ? 'partly graded' : 'not started';
    $('paper-status').innerHTML=`<span>Extraction: ${esc(ocrState)}</span><span>Grading: ${esc(gradeState)}</span>`;
    $('original-link').href=legacy('submission',{id:paperId});
    if (!row) { $('question-detail').innerHTML='<div class="empty"><h2>No paper-assessed questions</h2><p>Check assessment setup in Rubric Studio. External practical work is not graded here.</p></div>'; return; }
    const definitions=new Map((pack?.rubric?.criteria || []).map(c=>[c.id,c]));
    const human=new Map((currentLabel()?.human_criteria_scores || []).map(c=>[c.criterion_id,c]));
    const criteria=Array.isArray(answer?.criteria_scores) ? answer.criteria_scores : [];
    const pages=[...new Set((row.sources || []).map(s=>s.page_index))].filter(n=>Number.isInteger(n) && n>=0 && n<pageCount).sort((a,b)=>a-b);
    pageIndex=pages[0] ?? 0;
    const refs=pack?.course_references;
    const policyNames={method_credit:'Method credit',arithmetic_error_policy:'Arithmetic errors',units_policy:'Units',notation_policy:'Notation',custom_instructions:'Instructor instructions'};
    const policyBrief=Object.entries(policyNames).filter(([key])=>typeof pack?.policy?.[key]==='string' && pack.policy[key]).map(([key,label])=>`${label}: ${pack.policy[key].replaceAll('_',' ')}`).join(' · ');
    $('question-detail').innerHTML=`<div class="question-top"><h2>Question ${esc(row.question.question_number)}</h2><label class="visually-hidden" for="question-select">Question</label><select id="question-select">${extraction.questions.map(r=>`<option value="${esc(r.question.id)}" ${r.question.id===questionId ? 'selected' : ''}>Question ${esc(r.question.question_number)} · ${number(r.question.max_score)} marks</option>`).join('')}</select><a class="mobile-evidence-link" href="#evidence-title">See paper &amp; edit grade</a></div>
      <p class="question-copy" dir="auto">${esc(row.question.question_text)}</p>
      <div class="decision-context"><div><h3>Source context</h3>${refs?.scope_version_id || refs?.scope_version_number ? `<p>${refs.scope_origin==='assessment' ? 'Assessment default' : 'Question sources'} v${number(refs.scope_version_number)} · ${(refs.passages || []).map(r=>`${esc(r.title)} · p${Number(r.page_index)+1}`).join('; ')}</p>` : '<p class="muted">No course-source snapshot recorded for this run.</p>'}</div><div><h3>Marking guide used</h3><p dir="auto">${excerpt(pack?.answer_key?.mode==='no_fixed_answer' ? 'No fixed answer. Evaluate against the approved criteria.' : pack?.answer_key?.reference_text || pack?.answer_key?.text || (pack?.rubric?.criteria || []).map(c=>c.description).filter(Boolean).join(' ')) || 'No marking-guide excerpt recorded. Inspect the retained rules below.'}</p></div></div>
      ${criteria.length ? `<table class="criteria-table"><thead><tr><th>Criterion</th><th>Mark</th><th>AI feedback</th></tr></thead><tbody>${criteria.map(c=>`<tr><td><strong>${esc(definitions.get(c.criterion_id)?.title || definitions.get(c.criterion_id)?.description || 'Recorded criterion')}</strong><small>${esc(definitions.get(c.criterion_id)?.description || '')}</small></td><td class="score">${number(human.get(c.criterion_id)?.points_earned ?? c.points_earned)} / ${number(c.max_points)}${human.has(c.criterion_id) ? '<small>Instructor mark</small>' : ''}</td><td class="criterion-feedback">${esc(c.feedback)}${c.uncertainties?.length ? `<p class="muted">${esc(c.uncertainties.join('; '))}</p>` : ''}</td></tr>`).join('')}</tbody></table>` : `<div class="question-more"><p>${answer ? 'This answer has not been graded yet.' : 'No extracted answer is mapped to this question.'}</p></div>`}
      <div class="question-more">${policyBrief ? `<div class="rationale-preview"><h3>Scoring policy used</h3><p dir="auto">${excerpt(policyBrief)}</p></div>` : ''}<div class="rationale-preview"><h3>Why the AI awarded these marks</h3><p dir="auto">${excerpt(answer?.reasoning || answer?.feedback) || 'No recorded rationale yet.'}</p></div>${row.mapping_flags?.length ? `<p class="notice">${esc(row.mapping_flags.map(f=>f.message).join(' '))} <a href="${legacy('submission',{id:paperId})}">Check the highlighted evidence in full extraction</a></p>` : ''}
      ${extraction.grading_scope?.kind==='paper_only' ? '<p class="notice">Paper component only. External practical questions are excluded—not scored as zero.</p>' : ''}
      <details><summary>Extracted answer</summary><pre dir="auto">${esc(answer?.raw_ocr_text || row.answer?.raw_ocr_text || 'No extracted answer recorded.')}</pre></details>
      <details><summary>Approved rules &amp; references used</summary>${pack ? `<p>Rubric and policy version ${esc(pack.rubric_version_id || 'legacy')} · ${refs?.scope_origin==='assessment' ? 'Assessment default' : 'Question sources'} ${refs?.scope_version_number ? `v${refs.scope_version_number}` : ''}</p>${(refs?.passages || []).map(r=>`<details><summary>${esc(r.title)} · v${number(r.material_version_number)} · document page ${Number(r.page_index)+1}</summary><pre dir="auto">${esc(r.text)}</pre></details>`).join('')}<details><summary>Answer key &amp; scoring policy</summary><pre>${esc(JSON.stringify({answer_key:pack.answer_key,policy:pack.policy},null,2))}</pre></details>` : '<p>This older run has no complete package snapshot. Open history in the original workspace for retained records.</p>'}</details>
      <details><summary>AI rationale</summary><p dir="auto">${esc(answer?.reasoning || answer?.feedback || 'No rationale recorded.')}</p></details>
      <a href="${legacy('grade-results',{id:paperId})}">Full grading history and review tools</a></div>`;
    window.MisraTeaching?.showEvidence(pack,criteria);
    $('question-select').addEventListener('change',event=>{ const selected=event.target.value; if (!canLeave()) { event.target.value=questionId; return; } dirty=false; questionId=selected; renderQuestion(); syncURL(); });
    if (pageCount>0) {
      $('page-controls').hidden=false;
      $('viewer-tools').hidden=false;
      $('page-select').innerHTML=Array.from({length:pageCount},(_,n)=>`<option value="${n}">Page ${n+1} of ${pageCount}</option>`).join('');
      showPage(pageIndex);
    }
    renderEditor(answer,criteria,definitions,human);
  }
  function renderIdentity() {
    if(!extraction) {$('paper-identity').innerHTML='';return;}
    const submission=extraction.submission,missing=!submission.extracted_student_name || !submission.extracted_student_number;
    $('paper-identity').innerHTML=`<details class="identity-inline" ${missing ? 'open' : ''}><summary>${missing ? 'Student details need checking' : 'Student details · check against the paper'}</summary><p>These details identify the exported grade. Verify the name and student number against the original paper.</p><form id="native-identity-form"><div class="author-grid"><div class="field"><label for="native-student-name">Student name</label><input id="native-student-name" value="${esc(submission.extracted_student_name)}" maxlength="255"></div><div class="field"><label for="native-student-number">Student number / Blackboard username</label><input id="native-student-number" value="${esc(submission.extracted_student_number)}" maxlength="100"></div></div><button type="submit">Save student details</button><p id="identity-save-state" role="status">${missing ? 'Missing details can block export.' : 'Saved details shown. OCR identity is not automatically verified.'}</p></form></details>`;
    $('native-identity-form').addEventListener('input',()=>{identityDirty=true;$('identity-save-state').textContent='Unsaved student details';});
    $('native-identity-form').addEventListener('submit',async e=>{e.preventDefault();if(identityBusy || busy)return;identityBusy=true;const form=e.currentTarget;[...form.elements].forEach(el=>el.disabled=true);const id=paperId;try {const report=await MisraAPI.updateSubmissionMetadata(id,{student_name:$('native-student-name').value.trim() || null,student_number:$('native-student-number').value.trim() || null,instructor_name:submission.extracted_instructor_name || null});if(report?.submission?.id!==id)throw new Error('Identity response was incomplete. Check saved details before retrying.');Object.assign(submission,report.submission);identityDirty=false;renderIdentity();$('identity-save-state').textContent='Student details saved.';$('paper-name').textContent=submission.extracted_student_name || 'Name missing';$('selected-paper-copy').textContent='Selected paper: '+(submission.extracted_student_name || 'Name missing');await refreshPapers();}catch(error){$('identity-save-state').textContent=error.message+' Your entries remain here; check saved state before retrying.';}finally{identityBusy=false;[...form.elements].forEach(el=>el.disabled=false);}});
  }
  function setView(view) {
    currentView=view;
    const tasks=['setup','upload','export','activity','insights'];
    $('ledger-setup').hidden=view!=='setup'; $('ledger-upload').hidden=view!=='upload';
    $('ledger-export').hidden=view!=='export';$('ledger-activity').hidden=view!=='activity';
    $('ledger-insights').hidden=view!=='insights';
    document.querySelector('.paper-section').hidden=tasks.includes(view); $('question-detail').hidden=tasks.includes(view) || !paperId;
    $('paper-identity').hidden=tasks.includes(view) || !paperId;
    document.querySelector('.evidence-panel').hidden=tasks.includes(view) || !paperId;
    document.querySelector('.ledger-layout').classList.toggle('workflow-open',tasks.includes(view) || !paperId);
    ['sources-link','papers-tab','export-link','insights-link'].forEach(id=>$(id).removeAttribute('aria-current'));
    $(view==='setup' ? 'sources-link' : view==='insights' ? 'insights-link' : view==='export' ? 'export-link' : 'papers-tab').setAttribute('aria-current','page');
    syncURL();
  }
  async function showPage(index) {
    const count=Number(extraction?.submission.page_count)||0;
    if (!Number.isInteger(index) || index<0 || index>=count || !paperId) return;
    const current=++locationEpoch, selectedPaper=paperId;
    pageIndex=index; $('page-select').value=String(index); $('previous-page').disabled=index===0; $('next-page').disabled=index===count-1;
    $('paper-viewport').innerHTML=`<div class="paper-image"><img id="original-paper" alt="Full original submitted paper, page ${index+1}" src="${esc(MisraAPI.submissionPageUrl(selectedPaper,index))}"><div id="evidence-boxes"></div></div>`;
    const img=$('original-paper');
    setZoom(zoom);
    img.addEventListener('error',()=>{if(current===locationEpoch) $('paper-viewport').innerHTML='<div class="empty"><p>Original page could not load.</p><button type="button" data-reload-page>Reload this page</button></div>';});
    $('location-note').textContent='Full original page. Locating evidence does not verify the grade.';
    const sources=(currentRow()?.sources || []).filter(s=>s.page_index===index);
    let locations={}; try { locations=await MisraEvidence.pageLocations(selectedPaper,index); } catch (_) { /* Honest OCR fallback; the full original remains visible. */ }
    if (current!==locationEpoch || selectedPaper!==paperId || !$('evidence-boxes')) return;
    let matched=0, approximate=0;
    $('evidence-boxes').innerHTML=sources.map(s=>{ const location=MisraEvidence.location(s,locations); if(!location.box) return ''; location.verified ? matched++ : approximate++; const b=location.box; return `<span class="evidence-box ${location.verified ? '' : 'approximate'}" style="left:${b.x*100}%;top:${b.y*100}%;width:${b.width*100}%;height:${b.height*100}%" aria-hidden="true"></span>`; }).join('');
    $('location-note').textContent=`${matched} text-matched, ${approximate} approximate OCR regions. Full page retained; check the complete answer. Locations do not verify marks.`;
  }
  function setZoom(value) {
    zoom=Math.min(300,Math.max(100,value));
    const image=$('paper-viewport').querySelector('.paper-image'); if(image) image.style.width=`${zoom}%`;
    $('paper-zoom').value=`${zoom}%`; $('zoom-out').disabled=zoom===100; $('zoom-in').disabled=zoom===300;
  }
  function renderEditor(answer,criteria,definitions,human) {
    if (!answer || answer.score==null) {
      const partial=(results?.answers || []).some(a=>a.score!=null);
      const paper=papers.find(p=>p.id===paperId);
      const processing=active.has(paper?.latest_grading_job?.status) || jobs.some(j=>j.submission_id===paperId && active.has(j.status));
      const ready=extraction?.readiness?.bulk_grading_allowed && !partial && !processing;
      $('grade-editor').innerHTML=`<div class="notice"><p>${processing ? 'Background work is already running. Watch progress below; do not start another job.' : partial ? 'This paper already has recorded grades. Use the original grading tools to retry its existing job or deliberately regrade; this preview will not replace those marks automatically.' : ready ? 'Extraction is ready for AI grading. Approved questions, key, rubric, policy and source scope will be used.' : esc((extraction?.readiness?.blocking_reasons || []).join(' ') || 'Check extraction and approved assessment setup before grading.')}</p><button type="button" class="primary" data-grade ${ready ? '' : 'disabled'}>Grade paper with AI</button></div>`; return;
    }
    const confidence=answer.final_confidence ?? answer.llm_confidence;
    $('grade-editor').innerHTML=`<form id="instructor-grade" class="grade-form"><h3>Instructor grade · Question ${esc(currentRow().question.question_number)}</h3><div class="grade-row"><span class="recorded">${number(score(answer))} / ${number(answer.max_score)}</span><label class="visually-hidden" for="instructor-score">Instructor score</label><input type="number" id="instructor-score" min="0" max="${Number(answer.max_score)}" step="0.01" value="${Number(score(answer))}" required><button class="primary" type="submit">Save instructor grade</button></div>
      <p class="confidence">${confidence==null ? 'Model estimate not recorded' : `Model estimate ${number(confidence)}% · uncalibrated`}. Not a probability that this grade is correct. <strong>${answer.needs_review ? 'Instructor review required.' : 'Not flagged; still check the work.'}</strong></p>
      <label for="decision-reason">Decision reason <small>required for a changed grade</small></label><select id="decision-reason"><option value="">Choose a reason if changing the AI grade</option>${Object.entries(reasons).map(([id,label])=>`<option value="${id}">${label}</option>`).join('')}</select>
      <details class="criterion-edit"><summary>Adjust criterion marks (optional)</summary>${criteria.map(c=>`<label>${esc(definitions.get(c.criterion_id)?.title || definitions.get(c.criterion_id)?.description || 'Recorded criterion')} / ${number(c.max_points)}<input type="number" data-criterion="${esc(c.criterion_id)}" data-max="${Number(c.max_points)}" min="0" max="${Number(c.max_points)}" step="0.01" value="${Number(human.get(c.criterion_id)?.points_earned ?? c.points_earned)}" required></label>`).join('')}</details>
      <label for="instructor-note">Instructor note (optional)</label><textarea id="instructor-note" maxlength="1000"></textarea>
      <label><input type="checkbox" id="review-warranted" ${answer.needs_review ? 'checked' : ''}> This answer needed instructor review</label>
      <p role="status" id="save-status">${answer.teacher_override_score!=null ? 'Instructor override recorded' : 'AI grade recorded'} · AI suggested ${number(answer.score)} / ${number(answer.max_score)}</p><p role="alert" id="grade-error" class="form-error" hidden></p></form>`;
    const form=$('instructor-grade');
    form.addEventListener('input',event=>{
      dirty=true; $('save-status').textContent='Unsaved instructor-grade changes';
      if (event.target.matches('[data-criterion]')) { form.dataset.criteriaDirty='true'; $('instructor-score').value=[...form.querySelectorAll('[data-criterion]')].reduce((sum,input)=>sum+Number(input.value),0).toFixed(2); }
    });
    form.addEventListener('submit',saveGrade);
  }
  async function saveGrade(event) {
    event.preventDefault(); if(busy) return;
    if(identityBusy || identityDirty) {showError('Save the student details before saving this grade.');return;}
    const form=event.currentTarget, answer=currentAnswer(), targetPaper=paperId;
    const value=Number($('instructor-score').value), reason=$('decision-reason').value;
    const criterionChanged=form.dataset.criteriaDirty==='true';
    const override=criterionChanged || Math.abs(value-Number(answer.score))>.001;
    const show=message=>{ $('grade-error').hidden=false; $('grade-error').textContent=message; };
    if (!Number.isFinite(value) || value<0 || value>Number(answer.max_score)) { show('Enter a mark within this question’s score limits.'); return; }
    if (override && !reason) { show('Choose a decision reason before changing the AI grade.'); return; }
    const humanCriteria=criterionChanged ? [...form.querySelectorAll('[data-criterion]')].map(input=>({criterion_id:input.dataset.criterion,points_earned:Number(input.value),max_points:Number(input.dataset.max)})) : null;
    if(humanCriteria?.some(c=>!Number.isFinite(c.points_earned) || c.points_earned<0 || c.points_earned>c.max_points) || humanCriteria && Math.abs(humanCriteria.reduce((sum,c)=>sum+c.points_earned,0)-value)>.01) { show('Criterion marks must be valid and add up to the question total.'); return; }
    const body={action:override ? 'override' : 'approve',grading_run_id:answer.grading_raw_response?.grading_run_id || null,apply_as_current:true,human_score:override ? value : null,human_criteria_scores:humanCriteria,was_review_warranted:$('review-warranted').checked,review_reason_codes:override ? [reason] : [],review_reason_note:null,reviewer_notes:$('instructor-note').value.trim() || null};
    busy=true; $('grade-error').hidden=true; $('save-status').textContent='Saving instructor decision…'; [...form.elements].forEach(el=>el.disabled=true);
    let confirmed=false;
    try {
      const saved=await MisraAPI.resolveReview(answer.id,body);
      confirmed=true;
      if(saved?.answer) Object.assign(answer,saved.answer);
      dirty=false; $('save-status').textContent='Instructor decision saved. Refreshing recorded marks…'; busy=false;
      await choosePaper(targetPaper,{unguarded:true});
      await refreshPapers();
    } catch(error) { if(confirmed) showError(`Instructor decision saved, but the refreshed view could not load. ${error.message}`); else show(`${error.message} Your entries remain here. If the connection broke, check saved history before retrying.`); }
    finally { busy=false; [...form.elements].forEach(el=>el.disabled=false); }
  }
  async function refreshPapers() {
    const current=epoch,id=examId;
    const value=await MisraAPI.submissions(id);
    if(current!==epoch) return;
    if(Array.isArray(value)) { papers=value.filter(p=>p.exam_id===id); renderPapers(); }
  }
  function schedule() {
    clearTimeout(timer); if(!examId) return;
    const current=epoch;
    timer=setTimeout(async()=>{
      if(current!==epoch) return;
      try { await Promise.all([refreshPapers(),loadJobs()]); } catch(_) { jobsUnavailable=true; renderJobs(); }
      if(current!==epoch) return;
      const selected=papers.find(p=>p.id===paperId);
      const signature=JSON.stringify([selected?.latest_ocr_job?.id,selected?.latest_ocr_job?.status,selected?.latest_grading_job?.id,selected?.latest_grading_job?.status]);
      if(!dirty && !busy && !identityDirty && !identityBusy && paperId && signature!==selectedJobSignature && (selected?.latest_ocr_job || selected?.latest_grading_job)) { selectedJobSignature=signature; await choosePaper(paperId,{unguarded:true}); }
      schedule();
    },4000);
  }
  async function jobAction(button,retry=false) {
    if(busy || dirty || identityBusy || identityDirty || window.MisraLedgerWorkflows?.hasUnsaved() || window.MisraLedgerExport?.isBusy()) { showError('Save or finish the current operation before starting another.'); return; }
    busy=true; button.disabled=true; clearError();
    try { if(retry) await MisraAPI.retryJob(button.dataset.retry); else await MisraAPI.gradeSubmission(paperId,'auto'); await loadJobs(); await refreshPapers(); }
    catch(error) { showError(`${error.message} Check background activity before retrying.`); }
    finally { busy=false; if(currentAnswer()?.score==null && extraction) { const a=currentAnswer(); renderEditor(a,[],new Map(),new Map()); } else button.disabled=false; schedule(); }
  }
  $('assessment-list').addEventListener('click',e=>{const b=e.target.closest('[data-exam]'); if(b) chooseExam(b.dataset.exam);});
  $('paper-list').addEventListener('click',e=>{const b=e.target.closest('[data-paper]'); if(b) choosePaper(b.dataset.paper); else if(e.target.closest('[data-reload-assessment]')) chooseExam(examId);});
  document.addEventListener('click',e=>{
    if(e.target.closest('[data-reload-paper]')) choosePaper(paperId);
    if(e.target.closest('[data-reload-page]')) showPage(pageIndex);
    if(e.target.closest('[data-reconnect]')) loadJobs();
    const retry=e.target.closest('[data-retry]'), grade=e.target.closest('[data-grade]'); if(retry || grade) jobAction(retry || grade,Boolean(retry));
  });
  $('assessment-search').addEventListener('input',renderAssessments); $('paper-search').addEventListener('input',renderPapers);
  function showReview() {setView('papers');$('paper-picker').open=true;reviewOnly=true; $('review-tab').setAttribute('aria-pressed','true'); $('papers-tab').removeAttribute('aria-current'); renderPapers();}
  $('review-tab').addEventListener('click',showReview);$('review-nav').addEventListener('click',showReview);
  $('papers-tab').addEventListener('click',()=>{setView('papers');$('paper-picker').open=true;reviewOnly=false; $('review-tab').setAttribute('aria-pressed','false'); renderPapers();});
  $('upload-link').addEventListener('click',()=>window.MisraLedgerWorkflows?.show('upload'));
  $('sources-link').addEventListener('click',()=>window.MisraLedgerWorkflows?.show('setup'));
  $('activity-link').addEventListener('click',()=>{setView('activity');loadJobs();});
  $('export-link').addEventListener('click',()=>{if(dirty || identityDirty || identityBusy || window.MisraLedgerWorkflows?.hasUnsaved()) {showError('Save your grade, identity or marking-guide edits before exporting. Files use recorded marks, not unsaved edits.');return;}setView('export');window.MisraLedgerExport?.show();});
  $('toggle-assessments').addEventListener('click',()=>{const hidden=$('assessment-index').hidden=!$('assessment-index').hidden;$('toggle-assessments').setAttribute('aria-expanded',String(!hidden));document.querySelector('.ledger-layout').classList.toggle('index-hidden',hidden);});
  $('next-action').addEventListener('click',async()=>{if(nextAction.kind==='paper') {setView('papers');await choosePaper(nextAction.id);}else if(nextAction.kind==='export') {$('export-link').click();}else if(nextAction.kind==='activity') {$('activity-link').click();}else window.MisraLedgerWorkflows?.show(nextAction.kind);});
  window.addEventListener('misra:assessment-readiness',event=>{if(event.detail.examId===examId) {setupReady=event.detail.ready;updateNextAction();}});
  document.addEventListener('click',async event=>{const button=event.target.closest('[data-open-saved-paper]');if(button) {await refreshPapers();if(!papers.some(p=>p.id===button.dataset.openSavedPaper)) {showError('The saved paper is not yet listed. Refresh activity; do not upload again.');return;}setView('papers');await choosePaper(button.dataset.openSavedPaper);}});
  window.addEventListener('misra:ledger-task',event=>setView(event.detail.view));
  window.addEventListener('misra:ledger-url-changed',syncURL);
  window.addEventListener('misra:ledger-jobs-changed',()=>{Promise.all([refreshPapers(),loadJobs()]).catch(()=>{jobsUnavailable=true;renderJobs();});});
  $('previous-page').addEventListener('click',()=>showPage(pageIndex-1)); $('next-page').addEventListener('click',()=>showPage(pageIndex+1)); $('page-select').addEventListener('change',event=>showPage(Number(event.target.value)));
  $('zoom-in').addEventListener('click',()=>setZoom(zoom+25)); $('zoom-out').addEventListener('click',()=>setZoom(zoom-25)); $('fit-paper').addEventListener('click',()=>setZoom(100));
  $('expand-paper').addEventListener('click',()=>{ $('expanded-viewer-host').append($('paper-viewer')); $('expand-paper').hidden=true; $('expanded-paper').showModal(); });
  $('close-paper').addEventListener('click',()=>$('expanded-paper').close());
  $('expanded-paper').addEventListener('close',()=>{viewerHome.after($('paper-viewer')); $('expand-paper').hidden=false; $('expand-paper').focus({preventScroll:true});});
  document.addEventListener('click',event=>{const link=event.target.closest('a');if(link?.hasAttribute('download') && link.getAttribute('href')?.startsWith('blob:')) return; if(link && !link.getAttribute('href')?.startsWith('#') && (dirty || busy || identityDirty || identityBusy || window.MisraLedgerWorkflows?.hasUnsaved() || window.MisraLedgerExport?.isBusy()) && !canLeave(true)) event.preventDefault();});
  window.addEventListener('beforeunload',event=>{if(dirty || busy || identityDirty || identityBusy || window.MisraLedgerExport?.isBusy()) {event.preventDefault();event.returnValue='';}});
  function theme(value) {document.documentElement.dataset.theme=value; $('theme').textContent=value==='dark' ? 'Light theme' : 'Dark theme'; $('theme').setAttribute('aria-label',`Switch to ${value==='dark' ? 'light' : 'dark'} theme`);}
  const themeMedia=matchMedia('(prefers-color-scheme: dark)');
  function themePreference() {try{return localStorage.getItem('misra-theme') || 'system';}catch(_){return 'system';}}
  function applyPreference() {const value=themePreference();theme(value==='system' ? themeMedia.matches ? 'dark' : 'light' : value==='dark' ? 'dark' : 'light');}
  applyPreference(); themeMedia.addEventListener?.('change',applyPreference);
  window.addEventListener('storage',event=>{if(event.key==='misra-theme') applyPreference();});
  $('theme').addEventListener('click',()=>{const value=document.documentElement.dataset.theme==='dark' ? 'light' : 'dark';theme(value);try{localStorage.setItem('misra-theme',value);}catch(_){}});
  $('sign-out').addEventListener('click',async()=>{if(!canLeave(true)) return;busy=true;$('sign-out').disabled=true;try{await MisraAPI.logout();busy=dirty=false;location.replace('login.html');}catch(error){showError(error.message);busy=false;$('sign-out').disabled=false;}});
  (async()=>{try{const user=await MisraAPI.currentUser();if(user.must_change_password){location.replace('account.html?required=1');return;}const values=await MisraAPI.exams();if(!Array.isArray(values)) throw new Error('Assessment list is incomplete.');exams=values;renderAssessments();const selected=exams.find(e=>e.id===params.get('exam_id')) || exams[0];if(selected) await chooseExam(selected.id,{initial:true});else {$('exam-context').textContent='Create your first assessment to start.';$('paper-list').innerHTML='<a class="button primary" href="assessments.html">Create assessment</a>';}}catch(error){showError(error.status===401 ? 'Sign in to open your private instructor workspace.' : error.message);}})();
})();
