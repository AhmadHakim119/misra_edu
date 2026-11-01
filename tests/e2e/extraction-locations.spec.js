const {test,expect}=require('@playwright/test');

async function fixture(page,{nativeValues=false,missingNumbers=[],legacyZero=false}={}){
  const state={writes:[],requests:0,fail:false,delay:null,missingNumbers,reviewFailed:false,removedQuestions:[],excludedSources:[],failMutation:false,previewDelay:null,mutationDelay:null,graded:false};
  const sources=[
    {id:'zero',page_index:1,segment_index:0,extracted_text:'0',ocr_segment:{}},
    {id:'distance',page_index:1,segment_index:0,extracted_text:'100 km',ocr_segment:{}},
    {id:'working',page_index:1,segment_index:0,extracted_text:'W = 82 × 3',ocr_segment:{}},
    {id:'continuation',page_index:2,segment_index:1,extracted_text:'W = 246 J',ocr_segment:{}},
  ];
  const region=(y)=>({status:'located',method:'vision_grid',bounding_box:{x:.08,y,width:.75,height:.08}});
  state.locations={zero:region(.25),distance:region(.5),working:region(.7),continuation:region(.35)};
  if(nativeValues)for(const id of ['zero','distance'])state.locations[id]={...state.locations[id],method:'native_pdf_text'};
  state.sources=sources;
  sources.forEach(source=>source.removal_token='a'.repeat(64));
  const questions=[
    {id:'q0',question_number:'MCQ 1.1',question_text:'Choose the displacement.',max_score:1},
    {id:'q1',question_number:'MCQ 1.2',question_text:'Choose the distance.',max_score:1},
    {id:'q2',question_number:'2',question_text:'Calculate work and continue on the next page.',max_score:2},
  ];
  const original=`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900"><rect width="600" height="900" fill="white"/><g font-family="serif" font-size="18" fill="black"><text x="35" y="45">Synthetic original · no real student data</text><text x="35" y="155">MCQ 1.1 · displacement</text><text x="55" y="190">(a) 0    (b) 100 km    (c) 0</text><circle cx="65" cy="250" r="19" fill="none" stroke="black" stroke-width="3"/><text x="58" y="256">a</text><text x="35" y="380">MCQ 1.2 · distance</text><text x="55" y="415">(a) 100 km    (b) 0    (c) 100 km</text><path d="M50 475 l12 12 l25 -30" fill="none" stroke="black" stroke-width="3"/><text x="35" y="650">W = 82 × 3</text><text x="35" y="835">Full page preserved, including all printed options</text></g></svg>`;
  await page.route('**/api/**',async route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname.replace('/api','');let body={};
    if(req.method()!=='GET')state.writes.push({path,body:req.postDataJSON()});
    if(path==='/auth/me')body={id:'synthetic-user',role:'teacher'};
    else if(path==='/jobs'||path.endsWith('/jobs'))body={items:[]};
    else if(path.endsWith('/extraction-review')){
      if(state.reviewFailed)return route.fulfill({status:503,json:{detail:'Synthetic extraction review outage'}});
      body={submission:{id:'s',exam_id:'e',page_count:3,extracted_student_name:'Synthetic response locations'},questions:questions.map((question,index)=>({question,answer:(legacyZero||state.graded)&&index===0?{id:'zero-answer',score:0}:null,can_remove_sources:!(state.graded&&index===0),mapping_flags:[],sources:state.missingNumbers.includes(question.question_number)||legacyZero&&index===0?[]:sources.filter((source,i)=>(index===2?i>=2:i===index)&&!state.excludedSources.includes(source.id))})).filter(row=>!state.removedQuestions.includes(row.question.id)),removed_questions:questions.filter(q=>state.removedQuestions.includes(q.id)).map(q=>({...q})),excluded_segments:sources.filter(s=>state.excludedSources.includes(s.id)).map(s=>({...s,text:s.extracted_text,excluded_reason:'instructor_excluded'})),unmatched_segments:[],coverage:{issues:[]},readiness:{bulk_grading_allowed:!state.missingNumbers.length,can_reprocess:false,missing_question_numbers:state.missingNumbers,blocking_reasons:state.missingNumbers.length?[`${state.missingNumbers.length} expected question(s) have no mapped answer.`]:[]}};
    }
    else if(path.endsWith('/removal-preview')){
      const id=path.split('/')[2],question=questions.find(q=>q.id===id),action=url.searchParams.get('action');
      if(state.previewDelay){const gate=state.previewDelay;state.previewDelay=null;await gate;}
      const active=questions.filter(q=>!state.removedQuestions.includes(q.id)),remaining=action==='restore'?[...active,question]:active.filter(q=>q.id!==id);
      body={exam_id:'e',question_id:id,question_number:question.question_number,question_text:question.question_text,action,review_token:'b'.repeat(64),paper_count:2,previous_total_marks:active.reduce((s,q)=>s+q.max_score,0),revised_total_marks:remaining.reduce((s,q)=>s+q.max_score,0),remaining_questions:remaining.map(q=>({id:q.id,number:q.question_number,max_score:q.max_score}))};
    }
    else if(path.endsWith('/lifecycle')){
      if(state.mutationDelay)await state.mutationDelay;
      if(state.failMutation)return route.fulfill({status:409,json:{detail:'Synthetic stale guide; nothing changed'}});
      const id=path.split('/')[2],action=req.postDataJSON().action;
      if(action==='remove')state.removedQuestions.push(id);else state.removedQuestions=state.removedQuestions.filter(value=>value!==id);
      body={exam_id:'e',question_id:id,action,message:'Synthetic question list saved'};
    }
    else if(path.endsWith('/exclude')){
      if(state.failMutation)return route.fulfill({status:409,json:{detail:'Synthetic entry changed'}});
      const id=path.split('/')[2];state.excludedSources.push(id);state.missingNumbers.push(questions.find((q,index)=>sources[index]?.id===id)?.question_number);
      // Return the same checked report shape as a subsequent review read.
      body={submission:{id:'s',exam_id:'e',page_count:3},questions:questions.map((question,index)=>({question,answer:null,mapping_flags:[],sources:sources.filter((source,i)=>(index===2?i>=2:i===index)&&!state.excludedSources.includes(source.id))})),removed_questions:[],excluded_segments:sources.filter(s=>state.excludedSources.includes(s.id)).map(s=>({...s,text:s.extracted_text})),unmatched_segments:[],coverage:{issues:[]},readiness:{bulk_grading_allowed:false,can_reprocess:false,missing_question_numbers:state.missingNumbers,blocking_reasons:['Check missing answer']}};
    }
    else if(path.endsWith('/source-locations')){
      state.requests++;const index=Number(url.searchParams.get('page_index')),locations=Object.fromEntries(sources.filter(s=>s.page_index===index).map(s=>[s.id,state.locations[s.id]]).filter(([,v])=>v));
      if(state.delay){const gate=state.delay;state.delay=null;await gate;}
      if(state.fail)return route.fulfill({status:503,json:{detail:'Synthetic location outage'}});
      body={page_index:index,sources:locations};
    }else if(path.endsWith('/locate-answers'))body={job:{id:'location-job',submission_id:'s',operation:'locate_answers',page_index:Number(url.searchParams.get('page_index')),status:'failed'}};
    else if(path.includes('/pages/'))return state.imageFail?route.fulfill({status:503,body:'Synthetic image outage'}):route.fulfill({contentType:'image/svg+xml',body:original});
    await route.fulfill({json:body});
  });
  await page.goto(`/app/extraction.html?exam_id=e&submission_id=s&source_id=${legacyZero?'distance':'zero'}`);
  await expect(page.locator('#adjust-highlight')).toBeVisible();
  return state;
}

const show=(page,id)=>page.locator(`[data-source="${id}"] [data-show-page]`);

test('extraction removal actions have distinct paper and exam scope',async({page},info)=>{
  const state=await fixture(page);
  await expect(page.locator('#mapping-host .extraction-item')).toHaveCount(3);
  await expect(page.locator('[data-remove-question]')).toHaveCount(3);await expect(page.locator('[data-exclude-source]')).toHaveCount(4);
  for(const theme of ['light','dark'])for(const language of ['en','ar']){
    await page.evaluate(({theme,language})=>{MisraTheme.set(theme);localStorage.setItem('misra-language',language);MisraLocale.apply();window.dispatchEvent(new Event('misra:language'));},{theme,language});
    await page.screenshot({path:`.impeccable/review/extraction-removal-20261027/after-${theme}-${language}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
    await page.locator('[data-remove-question="q1"]').click();await expect(page.locator('#confirm-removal')).toBeEnabled();
    await expect(page.locator('#removal-preview bdi[dir="ltr"]')).toHaveText('4 → 3');
    await expect(page.locator('#cancel-removal')).toBeFocused();
    await page.screenshot({path:`.impeccable/review/extraction-removal-20261027/dialog-${theme}-${language}-${info.project.name}.png`,animations:'disabled'});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.keyboard.press('Escape');await expect(page.locator('[data-remove-question="q1"]')).toBeFocused();
  }
  expect(state.writes).toHaveLength(0);
});

test('removing one extracted entry keeps the question and exposes the missing answer',async({page})=>{
  const state=await fixture(page);await page.locator('[data-exclude-source="zero"]').click();
  await expect(page.locator('#removal-description')).toContainText('this paper only');await expect(page.locator('#removal-preview')).toContainText('0');
  await page.locator('#confirm-removal').click();await expect(page.locator('#extraction-remove-dialog')).not.toBeVisible();
  await expect(page.locator('#reading-question')).toBeFocused();
  await expect(page.locator('#mapping-host .extraction-item')).toHaveCount(3);await expect(page.locator('[data-source="zero"]')).toHaveCount(0);
  await expect(page.locator('#missing-answers')).toContainText('MCQ 1.1');await expect(page.locator('#removed-entries')).toBeVisible();
  expect(state.removedQuestions).toHaveLength(0);expect(state.writes.filter(w=>w.path.endsWith('/exclude'))).toHaveLength(1);
});

test('exam-wide question removal previews totals and is restorable on Extraction',async({page})=>{
  const state=await fixture(page);await page.locator('[data-remove-question="q1"]').click();
  await expect(page.locator('#removal-description')).toContainText('every paper');await expect(page.locator('#removal-preview')).toContainText('4 → 3');
  await page.locator('#confirm-removal').click();await expect(page.locator('#extracted-question-q1')).toHaveCount(0);await expect(page.locator('#mapping-host .extraction-item')).toHaveCount(2);
  await expect(page.locator('[data-source="zero"] textarea')).toHaveValue('0');await page.locator('#removed-questions summary').click();
  await page.locator('[data-restore-question="q1"]').click();await expect(page.locator('#confirm-removal')).toBeEnabled();await page.locator('#confirm-removal').click();
  await expect(page.locator('#mapping-host .extraction-item')).toHaveCount(3);expect(state.excludedSources).toHaveLength(0);
  expect(state.writes.filter(w=>w.path.endsWith('/lifecycle')).map(w=>w.body.action)).toEqual(['remove','restore']);
});

test('failed removal retains the question and genuine extraction edits block either scope',async({page})=>{
  const state=await fixture(page);state.failMutation=true;await page.locator('[data-remove-question="q1"]').click();await expect(page.locator('#confirm-removal')).toBeEnabled();await page.locator('#confirm-removal').click();
  await expect(page.locator('#removal-error')).toContainText('Synthetic stale guide');await expect(page.locator('#confirm-removal')).toBeDisabled();await expect(page.locator('#extracted-question-q1')).toHaveCount(1);
  await page.locator('#cancel-removal').click();await page.locator('[data-source="zero"] textarea').fill('Retain my unsaved edit');
  await page.locator('[data-exclude-source="zero"]').click();await expect(page.locator('#extraction-remove-dialog')).not.toBeVisible();
  await expect(page.locator('[data-source="zero"] textarea')).toHaveValue('Retain my unsaved edit');
});

test('late removal preview cannot replace a new question and pending change blocks replay',async({page})=>{
  const state=await fixture(page);let release;state.previewDelay=new Promise(resolve=>release=resolve);
  await page.locator('[data-remove-question="q0"]').click();await page.locator('#cancel-removal').click();await page.locator('[data-remove-question="q1"]').click();
  await expect(page.locator('#confirm-removal')).toBeEnabled();release();await expect(page.locator('#removal-preview h3')).toHaveText('MCQ 1.2');
  let complete;state.mutationDelay=new Promise(resolve=>complete=resolve);await page.locator('#confirm-removal').click();
  await expect(page.locator('#confirm-removal')).toBeDisabled();await expect(page.locator('#cancel-removal')).toBeDisabled();await page.keyboard.press('Escape');await expect(page.locator('#extraction-remove-dialog')).toBeVisible();
  complete();await expect(page.locator('#extracted-question-q1')).toHaveCount(0);expect(state.writes.filter(w=>w.path.endsWith('/lifecycle'))).toHaveLength(1);
});

test('graded evidence has an explained lock while exam-wide removal stays available',async({page})=>{
  const state=await fixture(page);state.graded=true;await page.locator('#extraction-refresh').click();
  await expect(page.locator('[data-exclude-source="zero"]')).toBeDisabled();await expect(page.locator('#extracted-question-q0 .removal-lock')).toContainText('grading history');
  await expect(page.locator('[data-remove-question="q0"]')).toBeEnabled();
});

test('removing the selected question clears its page and highlight context',async({page})=>{
  await fixture(page);await page.locator('#reading-question').selectOption('q2');await show(page,'continuation').click();await expect(page.locator('#extraction-page')).toHaveText('Page 3 / 3');
  await page.locator('[data-remove-question="q2"]').click();await expect(page.locator('#confirm-removal')).toBeEnabled();await page.locator('#confirm-removal').click();
  await expect(page.locator('#reading-question')).toHaveValue('q0');await expect(page.locator('#extraction-page')).toHaveText('Page 2 / 3');
  await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','zero');
});

test('extraction workbench keeps all answers and their original evidence in one view',async({page},info)=>{
  const state=await fixture(page);
  for(const theme of ['light','dark'])for(const language of ['en','ar']){
    await page.evaluate(({theme,language})=>{MisraTheme.set(theme);localStorage.setItem('misra-language',language);MisraLocale.apply();window.dispatchEvent(new Event('misra:language'));window.scrollTo(0,0);},{theme,language});
    await page.screenshot({path:`.impeccable/review/extraction-flow-20261026/after-${theme}-${language}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  }
  await page.evaluate(()=>{MisraTheme.set('light');localStorage.setItem('misra-language','en');MisraLocale.apply();window.dispatchEvent(new Event('misra:language'));});
  await expect(page.locator('#mapping-host .extraction-item')).toHaveCount(3);
  await expect(page.locator('#extracted-question-q2 .question-definition-link')).toHaveAttribute('href','setup.html?exam_id=e&rubric_question=q2');
  await expect(page.locator('[data-source="zero"] textarea')).toHaveValue('0');
  await expect(page.locator('#reading-question option')).toHaveCount(3);
  await expect(page.locator('#question-prev')).toBeDisabled();
  await page.locator('[data-source="zero"] textarea').fill('Keep this unsaved answer');
  await page.locator('#reading-question').selectOption('q2');
  await expect(page.locator('#extracted-question-q2 h3')).toBeFocused();
  await expect(page.locator('#question-next')).toBeDisabled();
  await expect(page.locator('#reading-position')).toHaveText('3 / 3');
  await expect(page.locator('[data-source="zero"] textarea')).toHaveValue('Keep this unsaved answer');
  await page.locator('#question-prev').click();
  await expect(page.locator('#reading-question')).toHaveValue('q1');
  await show(page,'distance').click();
  await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','distance');
  await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-label',/MCQ 1.2/);
  await expect.poll(()=>page.locator('.evidence-box.active').evaluate(box=>{const area=box.getBoundingClientRect(),frame=document.getElementById('paper-viewport').getBoundingClientRect();return area.top>=frame.top&&area.bottom<=frame.bottom;})).toBeTruthy();
  const viewport=await page.locator('#paper-viewport').boundingBox();expect(viewport.y).toBeLessThan(info.project.use.viewport.height);expect(viewport.y+viewport.height).toBeGreaterThan(0);
  if(info.project.name==='mobile-chromium'){
    await page.locator('#return-to-answer').click();await expect(page.locator('#extracted-question-q1 h3')).toBeFocused();
  }
  let prompts=0;page.on('dialog',dialog=>{prompts++;dialog.dismiss();});
  await page.locator('#go-grading').click();await expect(page).toHaveURL(/extraction.html/);expect(prompts).toBe(1);
  expect(state.writes).toHaveLength(0);
});

test('question deep links select the right saved answer without an extra extraction screen',async({page})=>{
  await fixture(page);await page.goto('/app/extraction.html?exam_id=e&submission_id=s&question_id=q2');
  await expect(page.locator('#reading-question')).toHaveValue('q2');
  await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','working');
  await expect(page.locator('#extraction-page')).toHaveText('Page 2 / 3');
});

test('a missing question clears the previous highlight and keeps the answer list usable',async({page})=>{
  await fixture(page,{missingNumbers:['MCQ 1.2']});
  await page.locator('#reading-question').selectOption('q1');
  await expect(page.locator('.evidence-box')).toHaveCount(0);
  await expect(page.locator('#location-note')).toContainText('No answer location is saved');
  await expect(page.locator('#reading-position')).toHaveText('2 / 3');
  await page.locator('#question-prev').click();
  await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','zero');
});

test('missing-answer notice names the exact question and jumps there without changing drafts',async({page},info)=>{
  const state=await fixture(page,{missingNumbers:['MCQ 1.2']});
  await expect(page.locator('#extraction-state')).toContainText('1 expected question');
  await page.screenshot({path:`.impeccable/review/missing-answer-20261026/before-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await expect(page.locator('#missing-answers')).toContainText('MCQ 1.2');
  await expect(page.locator('#missing-answers [data-missing-question]')).toHaveCount(1);
  await expect(page.locator('#start-grading')).toBeDisabled();
  await page.getByText('Student identity',{exact:true}).click();await page.locator('#identity-name').fill('Retain this unsaved identity correction');
  let prompts=0;page.on('dialog',dialog=>{prompts++;dialog.dismiss();});
  await page.locator('#missing-answers [data-missing-question]').focus();await page.keyboard.press('Enter');
  await expect(page.locator('#extracted-question-q1 h3')).toBeFocused();
  await expect(page.locator('#extracted-question-q1')).toContainText('No answer segment mapped');
  await expect(page.locator('#identity-name')).toHaveValue('Retain this unsaved identity correction');
  expect(prompts).toBe(0);
  for(const theme of ['light','dark'])for(const language of ['en','ar']){
    await page.evaluate(({theme,language})=>{MisraTheme.set(theme);localStorage.setItem('misra-language',language);MisraLocale.apply();},{theme,language});
    await expect(page.locator('#missing-answers-title')).toHaveText(language==='ar'?'أسئلة لم تُربط بها إجابة':'Questions without a mapped answer');
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:`.impeccable/review/missing-answer-20261026/after-${theme}-${language}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  }
  await page.locator('#go-grading').click();await expect(page).toHaveURL(/extraction\.html/);expect(prompts).toBe(1);
  expect(state.writes).toHaveLength(0);
});

test('missing list trusts server question numbers, preserves zero and escapes unknown labels',async({page})=>{
  const state=await fixture(page,{missingNumbers:['2','<img src=x>'],legacyZero:true});
  await expect(page.locator('#missing-answers')).toContainText('2');
  await expect(page.locator('#missing-answers')).toContainText('<img src=x>');
  await expect(page.locator('#missing-answers')).not.toContainText('MCQ 1.1');
  await expect(page.locator('#missing-answers [data-missing-question]')).toHaveCount(1);
  await expect(page.locator('#missing-answers img')).toHaveCount(0);
  await expect(page.locator('#start-grading')).toBeDisabled();expect(state.writes).toHaveLength(0);
});

test('missing-question notice survives a failed refresh and clears only after a checked response',async({page})=>{
  const state=await fixture(page,{missingNumbers:['MCQ 1.2']});state.reviewFailed=true;
  await page.locator('#extraction-refresh').click();await expect(page.locator('#extraction-error')).toContainText('Synthetic extraction review outage');
  await expect(page.locator('#missing-answers')).toContainText('MCQ 1.2');await expect(page.locator('#start-grading')).toBeDisabled();
  state.reviewFailed=false;state.missingNumbers=[];await page.locator('#extraction-refresh').click();
  await expect(page.locator('#missing-answers')).toHaveCount(0);await expect(page.locator('#start-grading')).toBeEnabled();
  await expect(page.locator('#extraction-error')).toBeEmpty();
  expect(state.writes).toHaveLength(0);
});

async function aligned(page,id,box){
  await expect.poll(()=>page.locator(`.evidence-box[data-source-id="${id}"]`).evaluate((el,expected)=>{
    const r=el.getBoundingClientRect(),image=document.getElementById('extraction-image').getBoundingClientRect();
    return Math.max(Math.abs((r.left-image.left)/image.width-expected.x),Math.abs((r.top-image.top)/image.height-expected.y),Math.abs(r.width/image.width-expected.width),Math.abs(r.height/image.height-expected.height));
  },box)).toBeLessThan(.01);
}

test('zero and repeated printed values select saved response regions on the same original page',async({page},info)=>{
  const state=await fixture(page);
  await page.screenshot({path:`.impeccable/review/usability-20261026/extraction-initial-${info.project.name}.png`,fullPage:true});
  await show(page,'distance').focus();await page.keyboard.press('Enter');
  await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','distance');
  await expect(page.locator('#location-note')).toContainText('MCQ 1.2');
  await expect(page.locator('.evidence-box.editing')).toHaveCount(0);
  await aligned(page,'distance',state.locations.distance.bounding_box);
  const reads=state.requests;
  await show(page,'zero').click();
  await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','zero');
  await expect(page.locator('[data-source="zero"] textarea')).toHaveValue('0');
  expect(state.requests).toBe(reads);expect(state.writes).toHaveLength(0);
  await page.locator('#toggle-highlights').click();await expect(page.locator('#evidence-boxes')).toBeHidden();
  await page.locator('#toggle-highlights').click();await expect(page.locator('#evidence-boxes')).toBeVisible();
  for(const theme of ['light','dark'])for(const language of ['en','ar']){
    await page.evaluate(({theme,language})=>{MisraTheme.set(theme);localStorage.setItem('misra-language',language);MisraLocale.apply();window.dispatchEvent(new Event('misra:language'));},{theme,language});
    await aligned(page,'zero',state.locations.zero.bounding_box);
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:`.impeccable/review/usability-20261026/extraction-${theme}-${language}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  }
  await page.locator('#page-zoom').click();await aligned(page,'zero',state.locations.zero.bounding_box);
});

test('pending and failed location reads clear stale rectangles and retain unsaved text',async({page})=>{
  const state=await fixture(page);await page.locator('[data-source="zero"] textarea').fill('Retain unsaved literal reading');
  let release;state.delay=new Promise(resolve=>release=resolve);
  await show(page,'continuation').click();
  await expect(page.locator('#extraction-page')).toHaveText('Page 3 / 3');
  await expect(page.locator('.evidence-box')).toHaveCount(0);
  await expect(page.locator('#location-note')).toContainText('Loading');
  await show(page,'distance').click();await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','distance');
  release();await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','distance');
  state.fail=true;await show(page,'continuation').click();
  await expect(page.locator('#highlight-status')).toContainText('could not load');
  await expect(page.locator('.evidence-box')).toHaveCount(0);
  await expect(page.locator('#retry-locations')).toBeEnabled();
  state.fail=false;await page.locator('#retry-locations').click();
  await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','continuation');
  await expect(page.locator('[data-source="zero"] textarea')).toHaveValue('Retain unsaved literal reading');
  expect(state.writes).toHaveLength(0);
});

test('printed short answers are not treated as response evidence and invalid locations are rejected',async({page})=>{
  const state=await fixture(page,{nativeValues:true});
  await expect(page.locator('.evidence-box[data-source-id="zero"]')).toHaveCount(0);
  await expect(page.locator('.evidence-box[data-source-id="distance"]')).toHaveCount(0);
  await show(page,'zero').click();await expect(page.locator('#highlight-status')).toContainText('response mark');
  expect(state.writes).toHaveLength(0);
  state.locations.zero={status:'located',method:'instructor_confirmed_area',revision_id:'old',bounding_box:{x:.1,y:.1,width:.6,height:.1}};
  state.sources[0].area_revision={id:'current',source_id:'zero',page_index:1,text:'0',bounding_box:{x:.08,y:.25,width:.75,height:.08}};
  state.locations.distance={status:'located',method:'vision_grid',bounding_box:{x:-1,y:.5,width:2,height:.1}};
  await page.reload();
  await expect(page.locator('.evidence-box.adjusted')).toHaveAttribute('data-source-id','zero');
  await aligned(page,'zero',state.sources[0].area_revision.bounding_box);
  await expect(page.locator('.evidence-box[data-source-id="distance"]')).toHaveCount(0);
  await expect(page.locator('[data-source="zero"] textarea')).toHaveValue('0');
  state.sources[0].area_revision.source_id='another-source';await page.reload();
  await expect(page.locator('.evidence-box[data-source-id="zero"]')).toHaveCount(0);
  await expect(page.locator('#highlight-status')).toContainText('needs review');
});

test('multi-page work and missing locations keep honest recovery states without repeated jobs',async({page})=>{
  const state=await fixture(page);state.locations.working={status:'stale',method:'vision_grid'};
  await page.reload();await show(page,'working').click();
  await expect(page.locator('.evidence-box[data-source-id="working"]')).toHaveCount(0);
  await expect(page.locator('#highlight-status')).toContainText('needs review');
  await show(page,'continuation').click();await expect(page.locator('#extraction-page')).toHaveText('Page 3 / 3');
  await aligned(page,'continuation',state.locations.continuation.bounding_box);
  delete state.locations.continuation;await page.reload();await show(page,'continuation').click();
  await expect(page.locator('#highlight-status')).toContainText('Select the area manually');
  const attempts=state.writes.length;
  await show(page,'zero').click();await show(page,'continuation').click();
  expect(state.writes).toHaveLength(attempts);
  await expect(page.locator('#extraction-image')).toBeVisible();
});

test('failed original image hides locations and retries without losing extraction edits',async({page})=>{
  const state=await fixture(page);await page.locator('[data-source="zero"] textarea').fill('Keep this unsaved answer');
  state.imageFail=true;await show(page,'continuation').click();
  await expect(page.locator('#highlight-status')).toContainText('Original page could not load');
  await expect(page.locator('#evidence-boxes')).toBeHidden();
  state.imageFail=false;await page.locator('#reload-original-page').click();
  await expect(page.locator('#evidence-boxes')).toBeVisible();
  await aligned(page,'continuation',state.locations.continuation.bounding_box);
  await expect(page.locator('#reveal-highlight')).toBeFocused();
  await expect(page.locator('[data-source="zero"] textarea')).toHaveValue('Keep this unsaved answer');
  expect(state.writes).toHaveLength(0);
});

test('a delayed original image cannot leave an overlay on the next selected question',async({page})=>{
  await fixture(page);let release;const gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/submissions/s/pages/2',async route=>{await gate;await route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="600"><rect width="100%" height="100%" fill="white"/></svg>'});});
  await show(page,'continuation').click();await expect(page.locator('#evidence-boxes')).toBeHidden();
  await show(page,'zero').click();await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','zero');
  release();await expect(page.locator('#extraction-image')).toHaveAttribute('src',/\/pages\/1$/);
  await expect(page.locator('.evidence-box.active')).toHaveAttribute('data-source-id','zero');
});
