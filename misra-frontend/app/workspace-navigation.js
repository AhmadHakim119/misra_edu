(function(){
  'use strict';
  const routes={setup:'setup',upload:'upload',papers:'grading',export:'results',insights:'feedback',activity:'activity'};
  function render(){const id=new URLSearchParams(location.search).get('exam_id');if(!id)return;for(const [key,route] of [['recorded-agreement','evaluation'],['resolve-identities','identities']]){const a=document.getElementById(key);if(a)a.href=route+'.html?exam_id='+encodeURIComponent(id);}
    document.getElementById('native-exam-navigation').innerHTML=[['setup','Rubric'],['upload','Upload papers'],['extraction','Extraction'],['grading','View & grade'],['feedback','Feedback'],['results','Results']].map(([page,title])=>`<a href="${page}.html?exam_id=${encodeURIComponent(id)}" ${location.pathname.endsWith('/'+page+'.html')?'aria-current="page"':''}>${title}</a>`).join('');}
  render();window.addEventListener('misra:assessment-loaded',render);
  if(['setup','upload','grading','results','feedback'].includes(window.MisraWorkspacePage)) {
    document.getElementById('assessment-index').hidden=true;
    document.getElementById('toggle-assessments').setAttribute('aria-expanded','false');
    document.querySelector('.ledger-layout').classList.add('index-hidden');
    const targets={'sources-link':'setup','upload-link':'upload','papers-tab':'grading','review-tab':'reviews','review-nav':'reviews','export-link':'results','insights-link':'feedback','activity-link':'activity'};
    document.addEventListener('click',e=>{const button=e.target.closest('button');if(!button)return;
      if(button.dataset.exam){e.preventDefault();e.stopImmediatePropagation();if(window.MisraLedger?.canLeave(true)===false)return;location.href=location.pathname+'?'+new URLSearchParams({exam_id:button.dataset.exam});return;}
      const next=button.id==='next-action'?window.MisraLedger?.nextAction():null;
      const paper=button.dataset.openSavedPaper;
      const page=paper?(window.MisraWorkspacePage==='upload'?'extraction':'grading'):button.hasAttribute('data-show-papers')?'grading':next?(routes[next.kind]||'grading'):targets[button.id];
      if(!page||page===window.MisraWorkspacePage)return;
      e.preventDefault();e.stopImmediatePropagation();if(window.MisraLedger?.canLeave(true)===false)return;const exam=new URLSearchParams(location.search).get('exam_id');const query=new URLSearchParams({exam_id:exam||''});if(paper||next?.id)query.set('submission_id',paper||next.id);location.href=page+'.html?'+query;},true);
    const tab=document.querySelector('.task-tabs');tab.hidden=true;
  }
})();
