(function(){
  'use strict';const {$,esc,number,link,params,ready}=MisraApp;
  let request=0;
  function savedPilots(catalog,examId){
    const host=$('review-saved-pilots');host.hidden=false;
    if(catalog.error){host.innerHTML='<h2>Saved pilot review unavailable</h2><p>Saved paper concerns could not load. Refresh to retry.</p>';return null;}
    const rows=(catalog.items||[]).flatMap(study=>study.exams ? study.exams.filter(e=>(!examId||e.exam_id===examId)&&e.review_count>0).map(e=>({...e,study_id:study.study_id,title:study.title}))
      : (!examId||study.exam_ids?.includes(examId))?[{study_id:study.study_id,exam_id:examId,title:study.title,review_count:null}]:[]);
    if(!rows.length){host.hidden=true;host.textContent='';return 0;}
    host.innerHTML='<h2>Saved pilot papers needing review</h2><p>Inspect recorded concerns, original pages and rubrics. These saved proposals have not been finalized as instructor grades.</p>'+rows.map(row=>`<div class="record-row"><div><h3>${esc(row.title||'Saved pilot')}${row.exam_version?' · '+esc(row.exam_version):''}</h3><p>${row.review_count==null?'Review count unavailable. Open the saved study to retry.':`${row.review_count} of ${row.paper_count} saved papers have recorded review concerns.`}</p></div><a class="button" href="${MisraPilots.href(row.study_id,row.exam_id,true)}">Review saved papers</a></div>`).join('');
    return rows.some(row=>row.review_count==null)?null:rows.reduce((sum,row)=>sum+row.review_count,0);
  }
  async function load(){const current=++request;$('review-list').innerHTML='';$('review-saved-pilots').hidden=true;$('review-saved-pilots').textContent='';$('review-list').setAttribute('aria-busy','true');$('review-count').textContent='Loading review queue…';$('review-error').textContent='';try{const [rows,papers,exams,pilots]=await Promise.all([MisraAPI.reviewQueue($('review-exam').value||undefined),MisraAPI.submissions(),MisraAPI.exams(),MisraPilots.load().catch(()=>({error:true}))]);if(current!==request)return;if(!Array.isArray(rows)||!Array.isArray(papers)||!Array.isArray(exams))throw Error('Review queue response is incomplete.');
    if(!$('review-exam').options.length){$('review-exam').innerHTML='<option value="">All exams</option>'+exams.map(e=>`<option value="${esc(e.id)}">${esc(e.title)}</option>`).join('');$('review-exam').value=params.get('exam_id')||'';if($('review-exam').value){return load();}}
    const savedCount=savedPilots(pilots,$('review-exam').value);
    $('review-list').innerHTML=rows.map(a=>{const p=papers.find(p=>p.id===a.submission_id);return `<div class="record-row"><div><h3>${esc(p?.extracted_student_name||'Student identity needs checking')}</h3><p>AI proposed ${number(a.score)} / ${number(a.max_score)} · ${esc(a.feedback||'Review the recorded evidence')}</p>${MisraReview.render(a)}</div><a class="button primary" href="${link('grading',{exam_id:p?.exam_id,submission_id:a.submission_id,question_id:a.question_id})}">Review evidence & mark</a></div>`;}).join('')||`<div class="empty"><h2>No flagged live grades awaiting review</h2><p>${savedCount?'Saved pilot concerns are listed above.':'Uploaded papers remain available in each exam’s grading workspace.'}</p></div>`;$('review-count').textContent=`${rows.length} answers awaiting review${savedCount?` · ${savedCount} saved pilot papers with review concerns`:''}`;$('review-error').textContent='';
  }catch(e){if(current===request){$('review-error').textContent=e.message;$('review-count').textContent='Review queue unavailable. Refresh to retry.';}}finally{if(current===request)$('review-list').setAttribute('aria-busy','false');}}
  $('review-exam').addEventListener('change',load);$('review-refresh').addEventListener('click',load);ready.then(load).catch(e=>$('review-error').textContent=e.message);
})();
