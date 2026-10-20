/* Shared native-page helpers; no student drafts or authentication tokens persisted. */
(function(){
  'use strict';
  const escapeHTML=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  window.MisraUI={escapeHTML,badge:text=>`<span class="status">${escapeHTML(text)}</span>`};
  window.MisraMarkingProfile={
    validate(value){if(!value || typeof value.use_marking_preferences!=='boolean' || typeof value.survey_completed!=='boolean' || typeof value.has_approved_profile!=='boolean')throw Error('Could not read saved marking settings. Reload to retry.');return value;},
    completion(value){if(!value.survey_completed)return '';return `<div class="survey-complete"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="m7 12 3 3 7-7"/></svg><div><strong data-i18n>Survey done</strong><p data-i18n>${value.use_marking_preferences?'Your preferences are on for new marking guides. You can turn them off in Settings.':'Your survey is saved. Automatic preferences are off in Settings.'}</p></div></div>`;}
  };
  window.showToast=(message,kind='info')=>{let target=document.getElementById('native-page-notice');if(!target){target=document.createElement('p');target.id='native-page-notice';document.querySelector('main').prepend(target);}target.setAttribute('role',kind==='error' ? 'alert' : 'status');target.className='native-page-notice'+(kind==='error' ? ' native-notice-error' : '');target.textContent=message;};
  if(document.body.dataset.nativeAuth) {if(document.body.dataset.nativeAuth==='login'&&new URLSearchParams(location.search).get('account_deleted')==='1'){const message=document.createElement('p');message.setAttribute('role','status');message.textContent='Account deleted. Institution academic history is retained.';document.querySelector('h1').after(message);}return;}
  const header=document.createElement('header');header.className='app-bar';header.innerHTML='<a class="brand" href="index.html" aria-label="MISRA EDU home"><img class="logo-light" src="../assets/logo-transparent.png" alt="MISRA EDU"><img class="logo-dark" src="../assets/logo-white.png" alt="" aria-hidden="true"></a><nav aria-label="Workspace"><a href="index.html">Marking workspace</a><a href="assessments.html">Assessments</a><a href="account.html">Settings</a></nav><div class="account"><button type="button" id="native-sign-out">Sign out</button></div>';document.body.prepend(header);
  document.getElementById('native-sign-out').addEventListener('click',async e=>{e.target.disabled=true;try {await MisraAPI.logout();location.replace('login.html');}catch(failure){window.showToast(failure.message,'error');e.target.disabled=false;}});
  window.MisraCurrentUser=MisraAPI.currentUser();
  window.MisraCurrentUser.then(user=>{if(user.must_change_password && !location.pathname.endsWith('/account.html')) location.replace('account.html?required=1');}).catch(()=>{});
})();
