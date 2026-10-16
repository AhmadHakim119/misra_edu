/* One shared workspace DOM/controller set, mounted by focused page entry points. */
(async function(){
  'use strict';
  try {
    const route=document.body.dataset.workspacePage;
    if(route==='dashboard'&&!new URLSearchParams(location.search).has('exam_id')){location.replace('dashboard.html');return;}
    const views={setup:'setup',upload:'upload',grading:'papers',results:'export',feedback:'insights',activity:'activity'};
    window.MisraWorkspacePage=route;
    if(views[route]){const url=new URL(location.href);url.searchParams.set('view',views[route]);history.replaceState(null,'',url);}
    const response=await fetch('workspace-template.html',{cache:'no-store'});if(!response.ok)throw Error('The workspace could not load. Reload to retry.');
    const template=new DOMParser().parseFromString(await response.text(),'text/html');
    document.body.replaceChildren(...[...template.body.childNodes].map(node=>document.importNode(node,true)));
    const main=document.querySelector('main');
    const nav=document.createElement('nav');nav.className='exam-navigation';nav.id='native-exam-navigation';nav.setAttribute('aria-label','Exam workflow');main.prepend(nav);
    for(const link of template.head.querySelectorAll('link'))if(!document.head.querySelector(`link[href="${link.getAttribute('href')}"]`))document.head.append(document.importNode(link,true));
    for(const source of template.head.querySelectorAll('script[src]')){const script=document.createElement('script');script.src=source.getAttribute('src').split('?')[0];await new Promise((resolve,reject)=>{script.onload=resolve;script.onerror=()=>reject(Error('A workspace module failed to load. Reload to retry.'));document.head.append(script);});}
    const script=document.createElement('script');script.src='workspace-navigation.js';document.head.append(script);
  }catch(e){const main=document.createElement('main');main.className='page-main';const p=document.createElement('p');p.setAttribute('role','alert');p.textContent=e.message;main.append(p);document.body.replaceChildren(main);}
})();
