const {test,expect}=require('@playwright/test');

async function fixture(page,{failScope=false,failIndex=false,failSurvey=false,chapterFiles=false,combinedSources=false}={}){
  const version={id:'book-v',version_number:1,status:'approved',ingestion_status:'ready',page_count:500,approved_page_indices:Array.from({length:500},(_,i)=>i),media_type:'application/pdf',chunk_count:500};
  const chapters=Array.from({length:10},(_,i)=>({title:`Chapter ${i+1}`,start_page:i*50+1,end_page:(i+1)*50,key:`book-v:${i*50+1}-${(i+1)*50}`,page_indices:Array.from({length:50},(_,j)=>i*50+j),approved:true,selectable:true}));
  const catalog={version,chapters,text_fingerprint:'a'.repeat(64),boundaries_reviewed:true,index_available:true};
  const book={id:'book',title:'Synthetic physics course book',scope:'course',versions:[version],catalogs:[catalog]};
  const files=[7,2,10,5].map(n=>{
    const v={...version,id:`chapter-${n}-v`,page_count:28,approved_page_indices:n===5?[]:Array.from({length:28},(_,i)=>i),status:n===5?'draft':'approved'};
    return {id:`chapter-${n}`,title:`Chapter_${n}-Synthetic_Physics`,scope:'course',versions:[v],catalogs:[{version:v,chapter_file:true,chapter_number:n,boundaries_reviewed:false,chapters:[{title:`Chapter ${n}`,start_page:1,end_page:28,whole_document:true,page_indices:Array.from({length:28},(_,i)=>i),key:`${v.id}:1-28`,approved:n!==5,selectable:n!==5}]}]};
  });
  const items=chapterFiles?files:[book];
  const state={writes:[],scopes:{e:[],e2:[]},versions:[],extra:false};
  await page.route('**/api/**',async route=>{
    const req=route.request(),url=new URL(req.url()),p=url.pathname.replace('/api',''),method=req.method();let body={};
    if(p==='/auth/me')body={id:'u',institution_id:'i',full_name:'Synthetic instructor',role:'teacher'};
    else if(p==='/auth/settings')body={use_marking_preferences:true,has_approved_profile:state.versions.some(v=>v.status==='approved'),survey_completed:state.versions.some(v=>v.status==='approved'&&v.scenario_answers.length===12)};
    else if(p==='/courses')body=[{id:'c',course_code:'TEST',title:'Synthetic physics'}];
    else if(p==='/exams')body=[{id:'e',course_id:'c',course_code:'TEST',title:'Quiz 1'},{id:'e2',course_id:'c',course_code:'TEST',title:'Quiz 2'}];
    else if(p==='/submissions')body=[];
    else if(p==='/jobs')body={items:[],active_count:0};
    else if(p.endsWith('/setup-readiness'))body={ready:false,questions:[],message:'Prepare marking guide.'};
    else if(p.endsWith('/marking-guide/approve')){
      const request=req.postDataJSON();state.writes.push({path:p,body:request});
      const v=files.find(m=>m.id==='chapter-5').versions[0];v.status='approved';v.approved_page_indices=Array.from({length:28},(_,i)=>i);
      if(state.scopes.e[0])state.scopes.e[0].status='approved';
      body={exam_id:'e',approved_version_ids:['r','scope-e','chapter-5-v'],message:'Guide and selected sources approved.'};
    }
    else if(p.endsWith('/marking-guide')){
      const pending=combinedSources&&state.scopes.e[0]?.status==='draft';
      body={exam_id:p.includes('/e2/')?'e2':'e',review_token:'a'.repeat(64),questions:combinedSources?[{question_id:'q',question_number:'1',question_text:'Explain work.',max_score:1,rubric_status:'draft',rubric:{criteria:[{title:'Valid explanation',points:1}],policy:{}},answer_key:{mode:'no_fixed_answer'},sources:null,source_references:[],errors:[],warnings:[]}]:[],errors:[],warnings:[],can_approve:combinedSources,total_marks:combinedSources?1:0,pending_count:combinedSources?1:0,source_approvals:pending?[{version_id:'chapter-5-v',material_id:'chapter-5',version_number:1,title:'Chapter_5-Synthetic_Physics',page_indices:Array.from({length:28},(_,i)=>i),content_sha256:'b'.repeat(64)}]:[]};
    }
    else if(p.endsWith('/questions')||p.endsWith('/setup-imports'))body=[];
    else if(p==='/instructor-preference-versions'){
      if(method==='POST'){state.writes.push({path:p,body:req.postDataJSON()});if(failSurvey)return route.fulfill({status:422,json:{detail:'Synthetic survey rejection'}});state.versions=[{id:'profile',version_number:1,status:'draft',...req.postDataJSON(),derived_proposal:{method_credit:'full_if_valid'}}];body=state.versions[0];}else body=state.versions;
    }
    else if(p==='/instructor-preference-versions/profile/approve'){state.versions[0].status='approved';body=state.versions[0];}
    else if(p==='/instructor-preference-suggestions')body={suggestions:[]};
    else if(p.endsWith('/material-scopes')){const id=p.split('/')[2];if(method==='POST'){const request=req.postDataJSON();state.writes.push({path:p,body:request});if(failScope)return route.fulfill({status:422,json:{detail:'Synthetic source rejection'}});state.scopes[id]=[{id:'scope-'+id,version_number:1,status:'draft',...request}];body=state.scopes[id][0];}else body={versions:state.scopes[id]||[],questions:[]};}
    else if(p==='/courses/c/library')body={course_id:'c',metadata_available:true,items};
    else if(p==='/materials/book/versions/book-v/chapters'){
      if(method==='POST'){state.writes.push({path:p,body:req.postDataJSON()});if(failIndex)return route.fulfill({status:409,json:{detail:'Synthetic stale chapter ranges'}});catalog.chapters=req.postDataJSON().chapters.map((c,i)=>({...c,key:'chapter-'+i,page_indices:[],approved:true,selectable:true}));}body=catalog;
    }
    else if(p==='/materials/book/versions/book-v/pages')body={version,items:[{page_index:0,text:'Chapter 1\nSynthetic source text',text_sha256:'a'.repeat(64),origin:'native_text_unverified',chunks:[]}]};
    else if(p.endsWith('/materials')){
      if(method==='POST'){state.writes.push({path:p,body:req.postData()});state.extra=true;body={id:'extra',versions:[{id:'extra-v',status:'draft',version_number:1,ingestion_status:'queued'}]};}else body=items;
    }
    await route.fulfill({json:body});
  });return state;
}

test('chapter selection and source approval use one explicit whole-guide action',async({page},info)=>{
  const state=await fixture(page,{chapterFiles:true,combinedSources:true});
  await page.goto('/app/setup.html?exam_id=e');await page.locator('#guide-sources-tab').click();
  await page.locator('[data-chapter-key="chapter-5-v:1-28"]').check();
  await page.locator('#assessment-chapters').screenshot({path:`.impeccable/review/combined-source-before-${info.project.name}.png`});
  await page.locator('#assessment-chapters [data-guide-step="questions"]').click();
  await expect(page.locator('#guide-questions-stage')).toBeVisible();
  expect(state.writes.find(w=>w.path.endsWith('/material-scopes')).body.allow_pending_sources).toBe(true);
  expect(state.scopes.e[0].status).toBe('draft');
  await page.locator('#guide-review-tab').click();
  await expect(page.locator('#guide-source-approvals')).toContainText('Chapter_5-Synthetic_Physics');
  await expect(page.locator('#guide-source-approvals')).toContainText('28');
  await expect(page.locator('#guide-confirm-label')).toContainText('selected source pages');
  await expect(page.locator('#guide-approve')).toBeDisabled();
  await page.locator('#guide-confirm').check();
  for(const theme of ['light','dark']){
    await page.evaluate(value=>{document.documentElement.dataset.theme=value;},theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.locator('#guide-review').screenshot({path:`.impeccable/review/combined-source-${theme}-${info.project.name}.png`});
  }
  await page.locator('#guide-approve').click();
  await expect(page.locator('#guide-approval-state')).toContainText('approved');
  const approvals=state.writes.filter(w=>w.path.endsWith('/marking-guide/approve'));
  expect(approvals).toHaveLength(1);
  expect(approvals[0].body.approve_selected_sources).toBe(true);
  expect(state.writes.some(w=>/\/materials\/.*\/approve$/.test(w.path))).toBeFalsy();
});

test('quiz chapter checkboxes persist Chapters 1 and 2 and stay separate from Quiz 2',async({page},info)=>{
  const state=await fixture(page);await page.goto('/app/setup.html?exam_id=e');await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();await expect(page.locator('[data-chapter-key]')).toHaveCount(10);
  await page.locator('[data-chapter-key]').nth(0).check();await page.locator('[data-chapter-key]').nth(1).check();await page.locator('#chapter-save-selection').click();
  const body=state.writes.find(w=>w.path.endsWith('/material-scopes')).body;
  expect(body.bindings).toHaveLength(1);expect(body.bindings[0].page_indices).toEqual(Array.from({length:100},(_,i)=>i));
  expect(state.scopes.e[0].status).toBe('draft');
  await page.reload();await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();await expect(page.locator('[data-chapter-key]').nth(0)).toBeChecked();await expect(page.locator('[data-chapter-key]').nth(1)).toBeChecked();await expect(page.locator('[data-chapter-key]').nth(2)).not.toBeChecked();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/quiz-chapters-light-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#theme').click();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/quiz-chapters-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.goto('/app/setup.html?exam_id=e2');await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();await expect(page.locator('[data-chapter-key]')).toHaveCount(10);await expect(page.locator('[data-chapter-key]:checked')).toHaveCount(0);
});

test('separate chapter PDFs use filename order, full files and source approval',async({page},info)=>{
  const state=await fixture(page,{chapterFiles:true});await page.goto('/app/setup.html?exam_id=e');await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();
  await expect(page.locator('.chapter-files strong')).toHaveText(['Chapter 2','Chapter 5','Chapter 7','Chapter 10']);
  await expect(page.locator('[data-chapter-key]')).toHaveCount(4);
  await expect(page.locator('[data-chapter-key="chapter-5-v:1-28"]')).toBeEnabled();
  await expect(page.locator('.chapter-files')).toContainText('Full PDF · 28 pages');
  await page.locator('[data-chapter-key="chapter-7-v:1-28"]').check();await page.locator('#chapter-save-selection').click();
  expect(state.writes.find(w=>w.path.endsWith('/material-scopes')).body.bindings).toEqual([{version_id:'chapter-7-v',page_indices:Array.from({length:28},(_,i)=>i),criterion_id:null,chunk_ids:[]}]);
  await page.reload();await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();await expect(page.locator('[data-chapter-key="chapter-7-v:1-28"]')).toBeChecked();
  await expect(page.locator('#guide-sources-stage')).not.toContainText(/\bv1\b/);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:`.impeccable/review/chapter-files-light-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/chapter-files-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:`.impeccable/review/chapter-files-rtl-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.goto('/app/course-library.html?course_id=c');await expect(page.locator('#library-material-host')).toContainText('Chapter_7-Synthetic_Physics');
  await expect(page.locator('[data-edit-chapters]')).toHaveCount(0);await expect(page.locator('#library-material-host')).not.toContainText(/\bv1\b/);
  await expect(page.locator('[data-material-review]')).toHaveCount(4);
  await expect(page.locator('.material-library-row>div:first-child>strong')).toHaveText(['Chapter_2-Synthetic_Physics','Chapter_5-Synthetic_Physics','Chapter_7-Synthetic_Physics','Chapter_10-Synthetic_Physics']);
});

test('failed full chapter file selection retains the entire checked file',async({page})=>{
  await fixture(page,{chapterFiles:true,failScope:true});await page.goto('/app/setup.html?exam_id=e');await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();
  await page.locator('[data-chapter-key="chapter-7-v:1-28"]').check();await page.locator('#chapter-save-selection').click();
  await expect(page.locator('#assessment-sources-host')).toContainText('Synthetic source rejection');await expect(page.locator('[data-chapter-key="chapter-7-v:1-28"]')).toBeChecked();
});

test('unreviewed chapter files can be saved as pending drafts and idle save does nothing',async({page},info)=>{
  const state=await fixture(page,{chapterFiles:true});await page.goto('/app/setup.html?exam_id=e');await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();
  await expect(page.locator('#chapter-save-selection')).toBeDisabled();
  await page.evaluate(()=>document.getElementById('chapter-save-selection').dispatchEvent(new MouseEvent('click')));
  expect(state.writes).toHaveLength(0);await expect(page.locator('#chapter-selection-status')).not.toContainText('saved');
  await page.locator('[data-chapter-key="chapter-5-v:1-28"]').check();await page.locator('#chapter-save-selection').click();
  await expect(page.locator('#chapter-selection-status')).toContainText('1 chapter saved as a draft. Approve it with the whole marking guide.');
  expect(state.writes[0].body.allow_pending_sources).toBe(true);expect(state.writes[0].body.bindings[0].page_indices).toHaveLength(28);
  expect(state.scopes.e[0].status).toBe('draft');await expect(page.locator('#chapter-save-selection')).toBeDisabled();
  await page.reload();await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();await expect(page.locator('[data-chapter-key="chapter-5-v:1-28"]')).toBeChecked();
  await expect(page.locator('#chapter-selection-status')).toContainText('approved together with the marking guide');
  const geometry=await page.evaluate(()=>{const bar=document.querySelector('.app-bar').getBoundingClientRect(),nav=document.querySelector('#native-exam-navigation').getBoundingClientRect();return {height:bar.height,gap:nav.top-bar.bottom};});
  expect(geometry.height).toBeGreaterThanOrEqual(64);expect(geometry.gap).toBeLessThanOrEqual(12);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:`.impeccable/review/chapter-selection-light-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/chapter-selection-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');await page.screenshot({path:`.impeccable/review/chapter-selection-rtl-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});

test('chapter review link opens that material directly in the library reviewer',async({page})=>{
  await fixture(page,{chapterFiles:true});await page.route('**/api/materials/chapter-5/versions/chapter-5-v/pages*',route=>route.fulfill({json:{version:{id:'chapter-5-v',status:'draft',media_type:'application/pdf',page_count:28,ingestion_status:'ready',approved_page_indices:[]},items:[{page_index:0,text:'Synthetic source text',text_sha256:'a'.repeat(64),chunks:[]}]}}));
  await page.goto('/app/setup.html?exam_id=e');await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();
  await page.locator('.chapter-option').filter({has:page.locator('[data-chapter-key="chapter-5-v:1-28"]')}).getByRole('link',{name:'Preview source pages'}).click();
  await expect(page).toHaveURL(/material_id=chapter-5/);await expect(page.locator('#material-page-text')).toHaveValue('Synthetic source text');
});

test('failed chapter selection retains checked boxes and blocks leaving until discard',async({page})=>{
  await fixture(page,{failScope:true});await page.goto('/app/setup.html?exam_id=e');await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();await page.locator('[data-chapter-key]').first().check();await page.locator('#chapter-save-selection').click();
  await expect(page.locator('[data-chapter-key]').first()).toBeChecked();await expect(page.locator('#assessment-sources-host')).toContainText('Synthetic source rejection');
  page.once('dialog',d=>d.dismiss());await page.locator('#assessment-chapters a').click();await expect(page).toHaveURL(/setup.html/);await expect(page.locator('[data-chapter-key]').first()).toBeChecked();
});

test('course library shows the existing book without uploading and supports chapter review',async({page},info)=>{
  const state=await fixture(page);await page.goto('/app/course-library.html?course_id=c');await expect(page.locator('#library-summary')).toContainText('1 saved course material');await expect(page.locator('#library-material-host')).toContainText('Synthetic physics course book');
  await expect(page.locator('.chapter-actions')).toContainText('10 chapter/section');expect(state.writes).toHaveLength(0);
  await page.getByRole('button',{name:'Review chapter boundaries',exact:true}).click();await expect(page.locator('.chapter-boundary-row')).toHaveCount(10);
  await page.locator('#chapter-checked').check();await page.getByRole('button',{name:'Save checked chapter boundaries'}).click();await expect(page.locator('#chapter-save-state')).toContainText('Checked chapters saved');
  expect(state.writes[0].body.chapters[0]).toEqual({title:'Chapter 1',start_page:1,end_page:50});await page.locator('#chapter-close').click();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/course-library-light-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-theme').click();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/course-library-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');await expect(page.locator('#library-material-host')).toContainText('Synthetic physics course book');
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/course-library-rtl-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});

test('switching course mounts its source reviewer and exposes the original PDF',async({page},info)=>{
  await fixture(page);
  await page.route('**/api/courses',route=>route.fulfill({json:[{id:'c',course_code:'TEST',title:'Synthetic physics'},{id:'other',course_code:'OTHER',title:'Another synthetic course with a very long title for source browsing'}]}));
  const version={id:'other-v',version_number:1,status:'draft',ingestion_status:'ready',page_count:2,approved_page_indices:[],media_type:'application/pdf'};
  const material={id:'other-book',title:'Other course source',versions:[version],catalogs:[]};
  await page.route('**/api/courses/other/library',route=>route.fulfill({json:{items:[material]}}));
  await page.route('**/api/courses/other/materials',route=>route.fulfill({json:[material]}));
  await page.route('**/api/materials/other-book/versions/other-v/pages*',route=>route.fulfill({json:{version,items:[{page_index:0,text:'Other course source text',text_sha256:'a'.repeat(64),chunks:[]}]}}));
  await page.goto('/app/course-library.html?course_id=c');
  await expect(page.locator('#library-material-host')).toContainText('Synthetic physics course book');
  await page.locator('#library-course').selectOption('other');
  await page.screenshot({path:`.impeccable/review/source-course-switch-${info.project.name}.png`,animations:'disabled'});
  await expect(page.locator('#library-material-host')).toContainText('Other course source');
  await expect(page.locator('#library-material-host')).not.toContainText('Synthetic physics course book');
  await expect(page.getByRole('link',{name:'Open original PDF',exact:true})).toHaveAttribute('href',/materials\/other-book\/versions\/other-v\/document$/);
  await page.getByRole('button',{name:'Review source pages',exact:true}).click();
  await expect(page.locator('#material-page-text')).toHaveValue('Other course source text');
  await expect(page.locator('.material-page-grid iframe')).toHaveAttribute('src',/other-book\/versions\/other-v\/document#page=1$/);
  for(const theme of ['light','dark']){
    if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#app-theme').click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:`.impeccable/review/source-viewer-${theme}-${info.project.name}.png`,animations:'disabled'});
  }
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');
  await expect(page.getByRole('link',{name:'فتح ملف PDF الأصلي',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/source-viewer-rtl-${info.project.name}.png`,animations:'disabled'});
  await page.locator('#material-page-text').fill('Unsaved equation correction');
  page.once('dialog',dialog=>dialog.dismiss());await page.locator('#library-course').selectOption('c');
  await expect(page.locator('#library-course')).toHaveValue('other');
  await expect(page.locator('#material-page-text')).toHaveValue('Unsaved equation correction');
});

test('course change discards delayed chapter reads and failed loading recovers',async({page})=>{
  await fixture(page);
  await page.route('**/api/courses',route=>route.fulfill({json:[{id:'c',course_code:'TEST',title:'Synthetic physics'},{id:'empty',course_code:'EMPTY',title:'Empty course'}]}));
  let release;
  const held=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/materials/book/versions/book-v/chapters',async route=>{await held;return route.fulfill({json:{version:{id:'book-v',page_count:500,media_type:'application/pdf'},chapters:[]}});});
  let fail=true;
  await page.route('**/api/courses/empty/library',route=>fail?route.fulfill({status:503,json:{detail:'Synthetic library outage'}}):route.fulfill({json:{items:[]}}));
  await page.route('**/api/courses/empty/materials',route=>route.fulfill({json:[]}));
  await page.goto('/app/course-library.html?course_id=c');
  await page.getByRole('button',{name:'Review chapter boundaries',exact:true}).click();
  await page.locator('#library-course').selectOption('empty');
  await expect(page.locator('#library-error')).toContainText('Synthetic library outage');
  const oldResponse=page.waitForResponse('**/api/materials/book/versions/book-v/chapters');
  release();
  await (await oldResponse).finished();
  await expect(page.locator('#library-chapter-editor')).toBeHidden();
  await expect(page.locator('#library-material-host')).not.toContainText('Synthetic physics course book');
  await expect(page.locator('#library-summary')).toContainText('could not load');
  fail=false;await page.getByRole('button',{name:'Refresh library',exact:true}).click();
  await expect(page.locator('#library-error')).toHaveText('');
  await expect(page.locator('#library-summary')).toContainText('0 saved course material');
  await expect(page.locator('#library-material-host')).toContainText('Choose another course above');
});

test('stale chapter ranges keep the edited titles and page numbers',async({page})=>{
  await fixture(page,{failIndex:true});await page.goto('/app/course-library.html?course_id=c');await page.getByRole('button',{name:'Review chapter boundaries'}).click();
  await page.locator('.chapter-boundary-row [name=title]').first().fill('My checked chapter title');await page.locator('.chapter-boundary-row [name=end_page]').first().fill('49');await page.locator('#chapter-checked').check();await page.getByRole('button',{name:'Save checked chapter boundaries'}).click();
  await expect(page.locator('#chapter-save-state')).toContainText('Synthetic stale chapter ranges');await expect(page.locator('.chapter-boundary-row [name=title]').first()).toHaveValue('My checked chapter title');await expect(page.locator('.chapter-boundary-row [name=end_page]').first()).toHaveValue('49');
});

test('extra assessment upload uses the quiz attachment endpoint',async({page})=>{
  const state=await fixture(page);await page.goto('/app/setup.html?exam_id=e');await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();await page.locator('#lecture-upload summary').click();
  await page.locator('#lecture-files').setInputFiles({name:'Quiz1Slides.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-synthetic')});await page.getByRole('button',{name:'Upload material drafts',exact:true}).click();
  await expect(page.locator('#lecture-upload-status')).toContainText('1 material drafts accepted');expect(state.writes.some(w=>w.path==='/exams/e/materials')).toBeTruthy();expect(state.writes.some(w=>w.path==='/courses/c/materials')).toBeFalsy();
});

test('marking survey is offered after sign in and persists explicit scenario answers',async({page},info)=>{
  const state=await fixture(page);await page.goto('/app/dashboard.html');await expect(page.locator('#marking-survey-invitation')).toBeVisible();await page.getByRole('link',{name:'Start marking survey'}).click();
  const answers=[['valid_alternative_method','full_credit'],['minor_handwritten_syntax','full_credit'],['equivalent_notation','full_credit'],['carried_forward_error','single_penalty'],['language_quality_outside_criterion','ignore']];
  for(const [scenario,value] of answers)await page.locator(`[data-scenario="${scenario}"][value="${value}"]`).check();
  for(const scenario of ['correct_method_arithmetic_error','missing_units','rounding_difference','correct_result_without_working','illegible_handwriting','incomplete_solution','contradictory_answers'])await page.locator(`[data-scenario="${scenario}"]`).first().check();
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Save & approve profile'}).click();await expect(page.locator('#survey-saved')).toContainText('Survey done');
  expect(state.writes[0].body.scenario_answers).toHaveLength(12);
  await page.reload();await expect(page.locator('[data-scenario="valid_alternative_method"][value="full_credit"]')).toBeChecked();await expect(page.locator('[data-scenario="valid_alternative_method"][value="full_credit"]')).toBeDisabled();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/marking-survey-light-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#app-theme').click();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/marking-survey-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/marking-survey-rtl-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.goto('/app/dashboard.html');await expect(page.locator('#marking-survey-invitation')).toHaveCount(0);
});

test('rejected survey save retains choices and unsaved navigation is guarded',async({page})=>{
  await fixture(page,{failSurvey:true});await page.goto('/app/marking-survey.html');await page.locator('[data-scenario="valid_alternative_method"][value="full_credit"]').check();await page.getByRole('button',{name:'Save draft',exact:true}).click();await expect(page.locator('#marking-preferences')).toContainText('Synthetic survey rejection');await expect(page.locator('[data-scenario="valid_alternative_method"][value="full_credit"]')).toBeChecked();page.once('dialog',d=>d.dismiss());await page.locator('#survey-continue').click();await expect(page).toHaveURL(/marking-survey.html/);
});

test('course batch retry sends only files that were not accepted',async({page})=>{
  await fixture(page);let requests=0,fail=true;const names=[];
  await page.route('**/api/courses/c/materials',route=>{
    if(route.request().method()!=='POST')return route.fallback();
    requests++;const body=route.request().postData();names.push(body.includes('filename="A.pdf"')?'A.pdf':'B.pdf');
    if(names.at(-1)==='B.pdf'&&fail){fail=false;return route.fulfill({status:422,json:{detail:'Synthetic file validation error'}});}
    return route.fulfill({status:202,json:{id:'accepted-'+requests,versions:[]}});
  });
  await page.goto('/app/course-library.html?course_id=c');await page.getByText('Add a book or chapter PDFs to this course',{exact:true}).click();
  await page.locator('#library-files').setInputFiles(['A.pdf','B.pdf'].map(name=>({name,mimeType:'application/pdf',buffer:Buffer.from('%PDF-synthetic')})));
  await page.getByRole('button',{name:'Add to course library',exact:true}).click();await expect(page.locator('#library-upload-state')).toContainText('Only the remaining files will be retried');
  await page.getByRole('button',{name:'Add to course library',exact:true}).click();await expect(page.locator('#library-files')).toHaveValue('');expect(names).toEqual(['A.pdf','B.pdf','B.pdf']);
});

test('PowerPoint extra material is accepted by the assessment upload selector',async({page})=>{
  const state=await fixture(page);await page.goto('/app/setup.html?exam_id=e');await expect(page.locator('#guide-questions-stage')).toBeVisible();await page.locator('#guide-sources-tab').click();await page.locator('#lecture-upload summary').click();
  await page.locator('#lecture-files').setInputFiles({name:'Quiz1Slides.pptx',mimeType:'application/vnd.openxmlformats-officedocument.presentationml.presentation',buffer:Buffer.from('Synthetic PPTX bytes validated by backend tests')});await page.getByRole('button',{name:'Upload material drafts',exact:true}).click();
  await expect(page.locator('#lecture-upload-status')).toContainText('1 material drafts accepted');expect(state.writes.find(w=>w.path==='/exams/e/materials').body).toContain('Quiz1Slides.pptx');
});
