const {test,expect}=require('@playwright/test');

async function fixture(page,{failRead=false,failConfirm=false,failRegrade=false,pending=false,automatic=false,graded=true}={}){
  const state={writes:[],revision:null,preview:null,box:null,regraded:false,autoDone:false};
  const original='W = 82 + 3 = 85 J';
  const question={id:'q',question_number:'1',question_text:'Calculate work for 82 N acting through 3 m.',max_score:2};
  const rubric={max_score:2,criteria:[{id:'method',title:'Method and result',description:'Use W = Fd and joules.',points:2}]};
  const submission=()=>({id:'s',exam_id:'e',extracted_student_name:'Synthetic Student A',extracted_student_number:'TEST01',page_count:2,status:'graded',readiness:{bulk_grading_allowed:true},grading_summary:{complete:true,recorded_score:1,max_score:2,review_count:1,graded_count:1,expected_count:1}});
  const answer=()=>({id:'a',question_id:'q',score:graded?(state.regraded?2:0):null,teacher_override_score:graded?1:null,max_score:2,needs_review:true,review_status:'overridden',raw_ocr_text:original,llm_confidence:80,criteria_scores:[{criterion_id:'method',max_points:2,points_earned:state.regraded?2:0,feedback:'Synthetic proposal',evidence_refs:['source:seg'],reference_refs:['key:k']}],grading_raw_response:{grading_run_id:state.regraded?'new-run':'old-run',grading_package:{rubric,answer_key:{mode:'reference',reference_text:'W = Fd = 246 J.'},policy:{},student_evidence:[],course_references:{mode:'disabled',passages:[]},selected_answer_areas:state.regraded?[state.revision]:[]}}});
  const areaJob={id:'area-job',submission_id:'s',job_type:'ocr_submission',operation:'read_answer_area',status:'completed'};
  const gradeJob={id:'grade-job',exam_id:'e',submission_id:'s',job_type:'grade_submission',operation:'regrade_corrected_answer',status:'queued'};
  if(pending){state.box={x:.1,y:.6,width:.8,height:.15};state.preview={text:original,language:'en',legibility:'clear'};}
  await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),path=url.pathname.replace('/api','');let body={};
    if(req.method()!=='GET')state.writes.push({path,body:req.postDataJSON()});
    if(path==='/auth/me')body={id:'u',role:'teacher'};
    else if(path==='/exams')body=[{id:'e',title:'Synthetic grading test',course_code:'TEST',submission_count:1}];
    else if(path==='/courses')body=[];
    else if(path==='/submissions')body=[submission()];
    else if(path==='/jobs')body={items:state.writes.some(w=>w.path.endsWith('regrade-corrected'))?[gradeJob]:[],active_count:0};
    else if(path.endsWith('/jobs'))body=[];
    else if(path==='/results/s')body={submission:submission(),answers:[answer()],latest_review_labels:[{answer_id:'a',grading_run_id:'old-run',human_criteria_scores:[{criterion_id:'method',points_earned:1}]}]};
    else if(path.endsWith('/extraction-review'))body={submission:submission(),questions:[{question,answer:answer(),sources:[{id:'seg',answer_id:'a',page_index:0,segment_index:0,extracted_text:original,ocr_segment:{bounding_box:{x:.1,y:.2,width:.8,height:.1}},area_revision:state.revision,pending_area_job_id:state.preview&&!state.revision?'area-job':null}],mapping_flags:[]}],unmatched_segments:[],coverage:{issues:[]},readiness:{bulk_grading_allowed:true,can_reprocess:false,blocking_reasons:[]}};
    else if(path.endsWith('/source-locations'))body={page_index:Number(url.searchParams.get('page_index')),sources:state.revision?{seg:{status:'located',method:'instructor_confirmed_area',bounding_box:state.revision.bounding_box}}:automatic?(state.autoDone?{seg:{status:'located',method:'vision_grid',bounding_box:{x:.05,y:.6,width:.85,height:.12}}}:{}):{seg:{status:'located',method:'native_pdf_text',bounding_box:{x:.1,y:.6,width:.8,height:.16}}}};
    else if(path.endsWith('/locate-answers'))body={job:{id:'auto',submission_id:'s',job_type:'ocr_submission',operation:'locate_answers',page_index:0,status:'queued'}};
    else if(path==='/jobs/auto'){state.autoDone=true;body={id:'auto',submission_id:'s',status:'completed'};}
    else if(path==='/answer-sources/seg/area-preview'){
      if(failRead)return route.fulfill({status:409,json:{detail:'Synthetic current paper task is running'}});
      state.box=req.postDataJSON().bounding_box;state.preview={text:original,language:'en',legibility:'clear'};body={job:areaJob};
    }
    else if(path==='/answer-sources/seg/area-preview/area-job/confirm'){
      if(failConfirm)return route.fulfill({status:409,json:{detail:'Synthetic newer area correction saved'}});
      state.revision={id:'area-job',source_id:'seg',page_index:0,bounding_box:state.box,text:req.postDataJSON().text,revision_number:1};body={revision:state.revision,answer_id:'a',requires_regrade:true};
    }
    else if(path==='/answer-sources/seg/area-preview/area-job')body={job:areaJob,source_id:'seg',page_index:0,bounding_box:state.box,preview:state.preview,expected_revision_id:null};
    else if(path==='/answers/a/regrade-corrected'){
      if(failRegrade)return route.fulfill({status:409,json:{detail:'Synthetic newer grading run'}});
      body={job:gradeJob,answer_id:'a'};
    }
    else if(path.endsWith('/setup-readiness'))body={ready:true,questions:[]};
    else if(path.includes('/pages/'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="white"/><g font-family="serif" font-size="20" fill="black"><text x="30" y="55">Synthetic Student A · TEST01</text><text x="30" y="160">Question 1: Calculate work.</text><text x="30" y="510">W = F × d</text><text x="30" y="550">W = 82 × 3 = 246 J</text><text x="30" y="750">Full original page retained</text></g></svg>'});
    await route.fulfill({json:body});
  });
  await page.goto('/app/extraction.html?exam_id=e&submission_id=s');
  await expect(page.locator('#adjust-highlight')).toBeVisible();
  return state;
}

async function selectArea(page){
  await page.locator('#adjust-highlight').click();
  await page.locator('#evidence-boxes').press('ArrowDown');
}
async function readArea(page){await selectArea(page);await page.locator('#read-answer-area').click();await expect(page.locator('#area-text')).toBeVisible();}
async function saveArea(page){await readArea(page);await page.locator('#area-text').fill('W = 82 × 3 = 246 J');await page.locator('#complete-area').check();await page.locator('#save-highlight').click();await expect(page.locator('[data-source="seg"]')).toContainText('Corrected extraction saved.');}

test('selected area is read, reviewed and saved in Extraction, then explicitly regraded',async({page})=>{
  const state=await fixture(page);await readArea(page);
  await expect(page.locator('#save-highlight')).toBeDisabled();
  await page.locator('#area-text').fill('W = 82 × 3 = 246 J');await page.locator('#complete-area').check();await page.locator('#save-highlight').click();
  await expect(page.locator('.evidence-box.adjusted')).toHaveCount(1);
  await expect(page.locator('[data-source="seg"] textarea')).toHaveValue('W = 82 × 3 = 246 J');
  expect(state.writes.some(w=>w.path.includes('regrade-corrected'))).toBeFalsy();
  await page.reload();await expect(page.locator('#location-note')).toContainText('instructor-selected');
  await page.getByRole('link',{name:'Review & regrade',exact:true}).click();
  await expect(page.locator('#instructor-score')).toHaveValue('1');
  await expect(page.locator('#adjust-highlight')).toHaveCount(0);
  page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'Regrade corrected answer',exact:true}).click();
  await expect.poll(()=>state.writes.filter(w=>w.path==='/answers/a/regrade-corrected').length).toBe(1);
  const request=state.writes.find(w=>w.path==='/answers/a/regrade-corrected').body;
  expect(request).toMatchObject({expected_run_id:'old-run',revision_ids:['area-job']});expect(request.request_id).toMatch(/^[\da-f-]{36}$/);
  await expect(page.locator('[data-regrade-corrected]')).toBeDisabled();
  await expect(page.locator('#instructor-grade')).toHaveAttribute('inert','');
  state.regraded=true;await page.reload();
  await expect(page.locator('#instructor-score')).toHaveValue('1');
  await expect(page.locator('#save-status')).toContainText('Instructor grade retained');
  await page.locator('#use-ai-proposal').click();await expect(page.locator('#instructor-score')).toHaveValue('2');
  await expect(page.locator('#save-status')).toContainText('Unsaved');
});

test('read failure retains geometry and never claims extraction was saved',async({page})=>{
  const state=await fixture(page,{failRead:true});await selectArea(page);const box=await page.locator('.editing').getAttribute('style');
  await page.locator('#read-answer-area').click();await expect(page.locator('#highlight-status')).toContainText('current paper task');
  await expect(page.locator('.editing')).toHaveAttribute('style',box);await expect(page.locator('#read-answer-area')).toBeEnabled();
  expect(state.revision).toBeNull();await expect(page.locator('[data-source="seg"] textarea')).toHaveValue('W = 82 + 3 = 85 J');
});

test('failed confirmation retains edited transcription and complete-answer check',async({page})=>{
  const state=await fixture(page,{failConfirm:true});await readArea(page);await page.locator('#area-text').fill('Retain this correction');await page.locator('#complete-area').check();await page.locator('#save-highlight').click();
  await expect(page.locator('#highlight-status')).toContainText('newer area correction');await expect(page.locator('#area-text')).toHaveValue('Retain this correction');await expect(page.locator('#complete-area')).toBeChecked();await expect(page.locator('#save-highlight')).toBeEnabled();expect(state.revision).toBeNull();
});

test('unsaved area guards page navigation and grading, while cancel restores original',async({page})=>{
  const state=await fixture(page,{graded:false});await selectArea(page);
  page.once('dialog',d=>d.dismiss());await page.locator('#page-next').click();await expect(page.locator('#extraction-page')).toHaveText('Page 1 / 2');
  page.once('dialog',d=>d.dismiss());await page.locator('#go-grading').click();await expect(page).toHaveURL(/extraction.html/);
  await page.locator('#start-grading').click();await expect(page.locator('#native-page-notice')).toContainText('Save your extraction');
  await page.locator('#cancel-highlight').click();await expect(page.locator('.evidence-box.editing')).toHaveCount(0);expect(state.writes).toHaveLength(0);
  await page.locator('#page-next').click();await expect(page.locator('#extraction-page')).toHaveText('Page 2 / 2');
});

test('dragging selects a new normalized answer region for extraction',async({page})=>{
  const state=await fixture(page);await page.locator('#adjust-highlight').click();
  await page.locator('#paper-viewport').scrollIntoViewIfNeeded();
  await page.locator('#paper-viewport').evaluate(el=>{el.scrollTop=el.querySelector('img').height*.6-el.clientHeight/2;});
  const rect=await page.locator('#evidence-boxes').boundingBox();
  await page.mouse.move(rect.x+rect.width*.05,rect.y+rect.height*.6);await page.mouse.down();
  await page.mouse.move(rect.x+rect.width*.9,rect.y+rect.height*.75,{steps:5});await page.mouse.up();
  await page.locator('#read-answer-area').click();await expect(page.locator('#area-text')).toBeVisible();
  expect(state.box.y).toBeCloseTo(.6,2);expect(state.box.height).toBeCloseTo(.15,2);
});

test('refresh resumes a durable preview without repeating the model request',async({page})=>{
  const state=await fixture(page,{pending:true});await page.locator('#continue-area').click();await expect(page.locator('#area-text')).toHaveValue('W = 82 + 3 = 85 J');
  expect(state.writes).toHaveLength(0);await page.locator('#cancel-highlight').click();
  await page.reload();await page.locator('#continue-area').click();await expect(page.locator('#area-text')).toBeVisible();expect(state.writes).toHaveLength(0);
});

test('changing the region invalidates the prior transcription preview',async({page})=>{
  await fixture(page);await readArea(page);await page.locator('#evidence-boxes').press('ArrowDown');
  await expect(page.locator('#area-text')).toHaveCount(0);await expect(page.locator('#read-answer-area')).toBeEnabled();await expect(page.locator('#highlight-status')).toContainText('Read selected area again');
});

test('automatic location cannot replace an instructor region draft',async({page})=>{
  await fixture(page,{automatic:true});await selectArea(page);const box=await page.locator('.editing').getAttribute('style');
  await expect(page.locator('#highlight-status')).toContainText('Your manual selection is unchanged',{timeout:10000});
  await expect(page.locator('.editing')).toHaveAttribute('style',box);
});

test('Extraction controls fit both themes, Arabic and zoom with aligned evidence',async({page},info)=>{
  await fixture(page);await readArea(page);
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>MisraTheme.set(theme),theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:`.impeccable/review/extraction-area-${theme}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  }
  await page.locator('#app-language').click();await expect(page.locator('#save-highlight')).toHaveText('حفظ الاستخراج المصحح');
  await page.locator('#page-zoom').click();
  expect(await page.evaluate(()=>{const image=document.getElementById('extraction-image').getBoundingClientRect(),overlay=document.getElementById('evidence-boxes').getBoundingClientRect();return Math.abs(image.width-overlay.width)<1&&Math.abs(image.height-overlay.height)<1;})).toBeTruthy();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:`.impeccable/review/extraction-area-rtl-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});

test('regrade failure keeps the saved instructor grade and correction',async({page})=>{
  await fixture(page,{failRegrade:true});await saveArea(page);await page.getByRole('link',{name:'Review & regrade',exact:true}).click();
  page.once('dialog',dialog=>dialog.accept());await page.locator('[data-regrade-corrected]').click();
  await expect(page.locator('#error')).toContainText('newer grading run');await expect(page.locator('#instructor-score')).toHaveValue('1');await expect(page.locator('[data-regrade-corrected]')).toBeEnabled();
});

test('regrading cannot discard unsaved instructor marks',async({page})=>{
  const state=await fixture(page);await saveArea(page);await page.getByRole('link',{name:'Review & regrade',exact:true}).click();
  await page.locator('#instructor-score').fill('1.5');await page.locator('[data-regrade-corrected]').click();
  await expect(page.locator('#error')).toContainText('Save or discard your edits');
  await expect(page.locator('#instructor-score')).toHaveValue('1.5');expect(state.writes.some(w=>w.path.endsWith('/regrade-corrected'))).toBeFalsy();
});
