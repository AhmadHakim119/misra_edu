/* Native pages share navigation, locale, formatting and guarded async operations. */
(function(){
  'use strict';
  const $=id=>document.getElementById(id),esc=MisraUI.escapeHTML;
  const language=MisraLocale.language,locale=MisraLocale.apply;
  const page=MisraWorkspace.page;
  const number=value=>value==null||!Number.isFinite(Number(value))?'—':Number(value).toLocaleString(language()==='ar'?'ar':'en',{maximumFractionDigits:2});
  const link=(page,params={})=>`${page}.html?${new URLSearchParams(Object.entries(params).filter(([,v])=>v!=null&&v!==''))}`;
  MisraWorkspace.refreshThemeLabel();
  let busy=false,dirty=false;
  page.listen(window,'beforeunload',e=>{if(dirty||busy){e.preventDefault();e.returnValue='';}});
  page.guard(()=>busy,()=>dirty);
  async function operation(button,fn){if(busy)return;busy=true;const main=document.querySelector('main'),was=button?.disabled;if(main){main.inert=true;main.setAttribute('aria-busy','true');}if(button)button.disabled=true;try{await fn();}catch(e){window.showToast(e.message,'error');}finally{busy=false;if(main){main.inert=false;main.removeAttribute('aria-busy');}if(button?.isConnected)button.disabled=was||false;}}
  const params=new URLSearchParams(location.search);
  async function examNavigation(){const id=params.get('exam_id');document.querySelectorAll('[data-exam-route]').forEach(a=>a.href=link(a.dataset.examRoute,{exam_id:id}));if(!id)return;
    const nav=document.createElement('nav');nav.className='exam-navigation';nav.setAttribute('aria-label','Exam workflow');
    nav.innerHTML=[['setup','Rubric'],['upload','Upload papers'],['extraction','Extraction'],['grading','View & grade'],['feedback','Feedback'],['results','Results']].map(([route,title])=>`<a href="${link(route,{exam_id:id})}" data-i18n="${title}" ${location.pathname.endsWith('/'+route+'.html')?'aria-current="page"':''}>${title}</a>`).join('');document.querySelector('main').prepend(nav);locale();}
  const ready=window.MisraCurrentUser.then(user=>{locale();return user;});
  ready.catch(e=>showToast(e.message,'error'));
  window.MisraApp={$,esc,number,link,params,ready,operation,locale,language,setDirty:value=>dirty=value,isBusy:()=>busy};
  locale();examNavigation();
})();
