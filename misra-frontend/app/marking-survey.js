(function(){
  'use strict';const {$}=MisraApp;
  const intro=document.querySelector('.page-heading p');intro.textContent='Twelve grading scenarios help MISRA remember your marking preferences.';intro.dataset.i18n='';MisraLocale.apply();
  const returnExam=MisraApp.params.get('return_exam_id');
  if(returnExam){const href=MisraApp.link('setup',{exam_id:returnExam});$('survey-continue').href=href;$('survey-continue').textContent=MisraLocale.text('Back to marking guide');document.querySelector('.page-heading a').href=href;}
  async function completion(){
    try {const settings=MisraMarkingProfile.validate(await MisraAPI.accountSettings());$('survey-saved').innerHTML=MisraMarkingProfile.completion(settings);if(settings.survey_completed){document.querySelector('.page-heading a').textContent=MisraLocale.text('Back to exams');}}
    catch(e){$('survey-saved').textContent=MisraLocale.text('Could not load marking settings. Open Settings to check whether automatic preferences are on.');}
  }
  MisraApp.ready.then(completion);
  window.addEventListener('misra:preferences-saved',async e=>{
    if(e.detail.approved)await completion();
    else $('survey-saved').textContent=MisraLocale.text('Your survey draft is saved. Approve the profile when you are ready to use its proposed defaults.');
  });
  const later=document.querySelector('.page-heading a');
  later.addEventListener('click',()=>{if(!MisraInstructorPreferences.isBusy()&&!MisraInstructorPreferences.hasUnsaved())MisraApp.ready.then(user=>sessionStorage.setItem(`misra-survey-later:${user.id}`,'1'));});
})();
