(function(){
  'use strict';
  const $=id=>document.getElementById(id),esc=MisraUI.escapeHTML;
  let exams=[],courses=[],dirty=false,busy=false,uncertain=false,loaded=false;
  function render(){const query=$('manager-search').value.toLowerCase();const rows=exams.filter(e=>`${e.title} ${e.course_code || ''}`.toLowerCase().includes(query));$('manager-list').innerHTML=rows.length ? rows.map(e=>`<div class="manager-row"><div><h2>${esc(e.title)}</h2><p>${esc(e.course_code || 'Course')} · ${e.submission_count ?? 0} papers</p></div><button type="button" data-duplicate="${esc(e.id)}">Duplicate exam</button><a class="button" href="grading.html?exam_id=${encodeURIComponent(e.id)}">Open assessment</a></div>`).join('') : '<p>No matching assessments. Create one to start your marking workflow.</p>';}
  async function load(){const [a,c]=await Promise.all([MisraAPI.exams(),MisraAPI.courses()]);if(!Array.isArray(a)||!Array.isArray(c))throw new Error('Assessment data is incomplete. Reload before creating records.');exams=a;courses=c;$('manager-course').innerHTML=c.length ? c.map(course=>`<option value="${esc(course.id)}">${esc(course.course_code)} · ${esc(course.title)}</option>`).join('') : '<option value="">Add your first course</option>';render();}
  function controls(){document.querySelectorAll('#creation input,#creation select,#creation button,#open-creation').forEach(el=>el.disabled=!loaded || busy || uncertain);const signOut=$('native-sign-out');if(signOut)signOut.disabled=busy || uncertain;}
  function failureMessage(error){
    if(!Array.isArray(error.detail))return error.message;
    const labels={course_id:'Course',title:'Title',language:'Language',course_code:'Course code',term:'Term',instructor_name:'Instructor name'};
    const messages=error.detail.map(issue=>{
      const field=Array.isArray(issue.loc)?issue.loc.at(-1):null,label=labels[field];
      if(!label)return null;
      return `${label}: ${issue.type==='missing'?'This field was not sent. Refresh this page and try again.':String(issue.msg || 'Check this value.')}`;
    }).filter(Boolean);
    return messages.length?messages.join(' '):'The assessment details could not be validated. Refresh this page and check the selected course, title and language.';
  }
  $('manager-search').addEventListener('input',render);$('open-creation').addEventListener('click',()=>{$('creation').hidden=false;if(!courses.length)$('create-course').hidden=false;$('manager-title').focus();});$('add-course').addEventListener('click',()=>{$('create-course').hidden=false;$('manager-code').focus();});
  $('close-creation').addEventListener('click',()=>{if(!dirty || confirm('Discard the unsaved assessment details?')) {$('creation').hidden=true;$('create-course').hidden=true;document.querySelectorAll('#creation form').forEach(f=>f.reset());dirty=false;}});
  $('creation').addEventListener('input',()=>dirty=true);window.addEventListener('beforeunload',e=>{if(dirty||busy){e.preventDefault();e.returnValue='';}});
  // Capture before the shared sign-out handler can invalidate the session.
  document.addEventListener('click',e=>{if(!e.target.closest('a,#native-sign-out'))return;if(busy || dirty&&!confirm('Leave without saving these assessment details?')){e.preventDefault();e.stopImmediatePropagation();return;}dirty=false;},true);
  async function create(form,kind){if(busy||uncertain)return;const body=Object.fromEntries(new FormData(form));busy=true;controls();$('manager-status').textContent='Saving…';try {if(kind==='course'){body.term=body.term.trim()||null;const course=await MisraAPI.createCourse(body);if(!course?.id)throw new Error('Course response is incomplete.');await load();$('manager-course').value=course.id;form.reset();$('create-course').hidden=true;dirty=Boolean($('manager-title').value.trim());$('manager-status').textContent='Course saved. Finish the assessment details.';}else {const exam=await MisraAPI.createExam(body);if(!exam?.id)throw new Error('Assessment response is incomplete.');dirty=busy=false;location.href=`setup.html?exam_id=${encodeURIComponent(exam.id)}`;}}
    catch(e){uncertain=!e.status||e.status>=500;$('manager-status').textContent=failureMessage(e)+(uncertain ? ' Acceptance is uncertain. Reload and check existing records before creating again.' : ' Your entries remain here.');}finally{busy=false;controls();}}
  $('create-assessment').addEventListener('submit',e=>{e.preventDefault();create(e.currentTarget,'exam');});$('create-course').addEventListener('submit',e=>{e.preventDefault();create(e.currentTarget,'course');});
  $('manager-list').addEventListener('click',async e=>{const b=e.target.closest('[data-duplicate]');if(!b||busy)return;const title=prompt('Title for the duplicated exam');if(!title?.trim())return;busy=true;controls();try{await MisraAPI.duplicateExam(b.dataset.duplicate,{title:title.trim(),include_rubrics:true,include_grading_policies:true});await load();}catch(error){$('manager-status').textContent=error.message;}finally{busy=false;controls();}});
  controls();
  load().then(()=>{loaded=true;controls();if(new URLSearchParams(location.search).get('create')==='1')$('open-creation').click();}).catch(e=>{$('manager-status').textContent=e.message;controls();});
})();
