/* Native pages share navigation, locale, formatting and guarded async operations. */
(function(){
  'use strict';
  const $=id=>document.getElementById(id),esc=MisraUI.escapeHTML;
  const language=MisraLocale.language,locale=MisraLocale.apply;
  const number=value=>value==null||!Number.isFinite(Number(value))?'—':Number(value).toLocaleString(language()==='ar'?'ar':'en',{maximumFractionDigits:2});
  const link=(page,params={})=>`${page}.html?${new URLSearchParams(Object.entries(params).filter(([,v])=>v!=null&&v!==''))}`;
  const header=document.querySelector('.app-bar');
  if(header){header.querySelector('nav').innerHTML='<a href="dashboard.html" data-i18n="Dashboard">Dashboard</a><a href="assessments.html" data-i18n="Exams">Exams</a><a href="course-library.html" data-i18n="Course library">Course library</a><a href="reviews.html" data-i18n="Review">Review</a><a href="activity.html" data-i18n="Activity">Activity</a><a href="account.html" data-i18n="Settings">Settings</a>';
    const tools=header.querySelector('.account');tools.insertAdjacentHTML('afterbegin','<button id="app-theme" type="button">Dark theme</button>');
    const themeLabel=()=>{$('app-theme').textContent=document.documentElement.dataset.theme==='dark'?'Light theme':'Dark theme';locale();};
    themeLabel();$('app-theme').addEventListener('click',()=>{MisraTheme.set(document.documentElement.dataset.theme==='dark'?'light':'dark');themeLabel();});
    document.addEventListener('change',event=>{if(event.target.matches('[data-theme-option]'))themeLabel();});
}
  let busy=false,dirty=false;
  function guard(e){if(busy||dirty&&!confirm('Leave without saving your changes?')){e.preventDefault();e.stopImmediatePropagation();return;}dirty=false;}
  document.addEventListener('click',e=>{if(e.target.closest('a,#native-sign-out'))guard(e);},true);
  window.addEventListener('beforeunload',e=>{if(dirty||busy){e.preventDefault();e.returnValue='';}});
  async function operation(button,fn){if(busy)return;busy=true;const main=document.querySelector('main'),was=button?.disabled;if(main){main.inert=true;main.setAttribute('aria-busy','true');}if(button)button.disabled=true;try{await fn();}catch(e){window.showToast(e.message,'error');}finally{busy=false;if(main){main.inert=false;main.removeAttribute('aria-busy');}if(button?.isConnected)button.disabled=was||false;}}
  const params=new URLSearchParams(location.search);
  async function examNavigation(){const id=params.get('exam_id');document.querySelectorAll('[data-exam-route]').forEach(a=>a.href=link(a.dataset.examRoute,{exam_id:id}));if(!id)return;
    const nav=document.createElement('nav');nav.className='exam-navigation';nav.setAttribute('aria-label','Exam workflow');
    nav.innerHTML=[['setup','Rubric'],['upload','Upload papers'],['extraction','Extraction'],['grading','AI grading'],['feedback','Feedback'],['results','Results']].map(([route,title])=>`<a href="${link(route,{exam_id:id})}" data-i18n="${title}" ${location.pathname.endsWith('/'+route+'.html')?'aria-current="page"':''}>${title}</a>`).join('');document.querySelector('main').prepend(nav);locale();}
  const ready=window.MisraCurrentUser.then(user=>{if(user.must_change_password&&!location.pathname.endsWith('/account.html')){location.replace('account.html?required=1');return user;}if(user.role==='admin'){const a=document.createElement('a');a.href='admin.html';a.dataset.i18n='Administration';a.textContent='Administration';header?.querySelector('nav').append(a);}locale();return user;});
  ready.catch(e=>showToast(e.message,'error'));
  window.MisraApp={$,esc,number,link,params,ready,operation,locale,language,setDirty:value=>dirty=value,isBusy:()=>busy};
  locale();examNavigation();
})();
