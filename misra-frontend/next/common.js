/* Shared native-page helpers; no student drafts or authentication tokens persisted. */
(function(){
  'use strict';
  const escapeHTML=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  window.MisraUI={escapeHTML,badge:text=>`<span class="status">${escapeHTML(text)}</span>`};
  window.showToast=(message,kind='info')=>{let target=document.getElementById('native-page-notice');if(!target){target=document.createElement('p');target.id='native-page-notice';document.querySelector('main').prepend(target);}target.setAttribute('role',kind==='error' ? 'alert' : 'status');target.className='native-page-notice'+(kind==='error' ? ' native-notice-error' : '');target.textContent=message;};
  if(document.body.dataset.nativeAuth) return;
  const header=document.createElement('header');header.className='app-bar';header.innerHTML='<a class="brand" href="index.html" aria-label="MISRA EDU home"><img class="logo-light" src="../assets/logo-transparent.png" alt="MISRA EDU"><img class="logo-dark" src="../assets/logo-white.png" alt="" aria-hidden="true"></a><nav aria-label="Workspace"><a href="index.html">Marking workspace</a><a href="assessments.html">Assessments</a><a href="account.html">Settings</a></nav><div class="account"><button type="button" id="native-sign-out">Sign out</button></div>';document.body.prepend(header);
  document.getElementById('native-sign-out').addEventListener('click',async e=>{e.target.disabled=true;try {await MisraAPI.logout();location.replace('login.html');}catch(failure){window.showToast(failure.message,'error');e.target.disabled=false;}});
  MisraAPI.currentUser().then(user=>{if(user.must_change_password && !location.pathname.endsWith('/account.html')) location.replace('account.html?required=1');}).catch(()=>{});
})();
