/* One shared workspace DOM/controller set, mounted by focused page entry points. */
(async function(){
  'use strict';
  const reconnect=()=>new Promise(resolve=>setTimeout(resolve,200));
  async function templateDocument(){
    for(let attempt=0;attempt<2;attempt++){
      try{const response=await fetch('workspace-template.html',{cache:'no-store'});if(!response.ok)throw Error('The workspace could not load. Reload to retry.');return new DOMParser().parseFromString(await response.text(),'text/html');}
      catch(error){if(attempt)throw error;await reconnect();}
    }
  }
  async function loadModule(source){
    for(let attempt=0;attempt<2;attempt++){
      const script=document.createElement('script');script.src=source;
      try{await new Promise((resolve,reject)=>{script.onload=resolve;script.onerror=()=>reject(Error('A workspace module failed to load. Reload to retry.'));document.head.append(script);});script.onload=script.onerror=null;return;}
      catch(error){script.onload=script.onerror=null;script.remove();if(attempt)throw error;await reconnect();}
    }
  }
  try {
    const route=document.body.dataset.workspacePage;
    if(route==='dashboard'&&!new URLSearchParams(location.search).has('exam_id')){location.replace('dashboard.html');return;}
    const views={setup:'setup',upload:'upload',grading:'papers',results:'export',feedback:'insights',activity:'activity'};
    window.MisraWorkspacePage=route;
    if(views[route]){const url=new URL(location.href);url.searchParams.set('view',views[route]);history.replaceState(null,'',url);}
    const template=await templateDocument();
    document.body.replaceChildren(...[...template.body.childNodes].map(node=>document.importNode(node,true)));
    const main=document.querySelector('main');
    const nav=document.createElement('nav');nav.className='exam-navigation';nav.id='native-exam-navigation';nav.setAttribute('aria-label','Exam workflow');main.prepend(nav);
    for(const link of template.head.querySelectorAll('link'))if(!document.head.querySelector(`link[href="${link.getAttribute('href')}"]`))document.head.append(document.importNode(link,true));
    for(const source of template.head.querySelectorAll('script[src]'))await loadModule(source.getAttribute('src').split('?')[0]);
    await loadModule('workspace-navigation.js');
  }catch(e){const main=document.createElement('main');main.className='page-main';const p=document.createElement('p');p.setAttribute('role','alert');p.textContent=e.message;main.append(p);document.body.replaceChildren(main);}
})();
