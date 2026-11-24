const {answerWorkspaceDialog}=require('./fixtures/workspace-dialog');
const {test,expect}=require('@playwright/test');
const {staticWorkspace}=require('./fixtures/static-workspace');
async function fixture(page,{graded=true,failCorrection=false,admin=false,pageCount=1}={}){
  await staticWorkspace(page);
  const state={writes:[],graded,approved:true,reviewed:false,text:'W = F + d',name:'Synthetic student',number:'TEST01',teacherActive:true};
  const rubric={schema_version:2,max_score:2,criteria:[{id:'work',title:'Correct work calculation',description:'Use W = Fd and report joules.',points:2,scoring_type:'scaled',partial_credit_allowed:true,performance_levels:[],common_errors:[],alternative_methods:[],required_evidence:['Formula']}],policy:{grading_approach:'balanced'}};
  let version={id:'rv',version_number:1,status:'approved',rubric_json:rubric};
  const submission=()=>({id:'s',exam_id:'e',extracted_student_name:state.name,extracted_student_number:state.number,page_count:pageCount,status:state.graded?'graded':'extracted',identity_status:'matched'});
  const answer=()=>({id:'a',submission_id:'s',question_id:'q',score:state.graded?1:null,max_score:2,needs_review:state.graded&&!state.reviewed,review_status:state.reviewed?'approved':'pending',raw_ocr_text:state.text,reasoning:'The formula should multiply force and displacement.',feedback:'Check the formula.',criteria_scores:state.graded?[{criterion_id:'work',points_earned:1,max_points:2,feedback:'Method needs checking.',evidence_refs:['source:seg'],reference_refs:['key:k']}]:[],grading_raw_response:state.graded?{grading_run_id:'run',grading_package:{rubric,answer_key:{reference_text:'W = Fd = 246 J.'},policy:{},course_references:{mode:'disabled',passages:[]}},verification:{status:'needs_review',summary:'Check formula support.',criteria:[{criterion_id:'work',verdict:'needs_review',explanation:'The formula was not correctly applied.'}]}}:{}});
  const question={id:'q',question_number:'1',question_text:'Calculate work for 82 N acting through 3 m.',max_score:2};
  const job={id:'job',exam_id:'e',submission_id:'s',job_type:'ocr_submission',status:'completed',progress_percent:100,progress_message:'Synthetic extraction completed.'};
  const report=()=>({submission:submission(),questions:[{question,answer:answer(),sources:[{id:'seg',page_index:0,extracted_text:state.text,ocr_segment:{}}],mapping_flags:[]}],unmatched_segments:[],coverage:{issues:[]},readiness:{bulk_grading_allowed:true,can_reprocess:!state.graded,blocking_reasons:[]}});
  await page.route('**/api/**',async route=>{const req=route.request(),path=new URL(req.url()).pathname.replace('/api',''),method=req.method();let body={};
    if(method!=='GET')state.writes.push({path,body:req.headers()['content-type']?.includes('application/json')?req.postDataJSON():null});
    if(path==='/auth/me')body={id:'u',role:admin?'admin':'teacher',full_name:'Synthetic instructor'};
    else if(path==='/exams')body=method==='POST'?{id:'e'}:[{id:'e',course_id:'c',title:'Synthetic physics exam',course_code:'TEST',submission_count:1}];
    else if(path==='/courses')body=[{id:'c',course_code:'TEST',title:'Synthetic physics'}];
    else if(path==='/submissions')body=[{...submission(),latest_grading_job:state.gradingJob,readiness:{bulk_grading_allowed:true},grading_summary:{complete:state.graded,recorded_score:state.graded?1:null,max_score:2,graded_count:state.graded?1:0,expected_count:1,review_count:state.graded&&!state.reviewed?1:0}}];
    else if(path==='/jobs'){if(Number(new URL(req.url()).searchParams.get('limit'))>20)return route.fulfill({status:422,json:{detail:'Limit cannot exceed 20'}});body={items:[job],active_count:0};}
    else if(path.endsWith('/jobs'))body=[job];
    else if(path==='/jobs/job')body=job;
    else if(path==='/upload-exam')body={submission:submission(),job};
    else if(path.endsWith('/setup-readiness'))body={ready:state.approved,questions:[],message:'Guide ready.'};
    else if(path.endsWith('/marking-guide/approve')){state.approved=true;version.status='approved';body={exam_id:'e',approved_version_ids:['rv'],message:'Assessment guide approved.'};}
    else if(path.endsWith('/marking-guide'))body={exam_id:'e',review_token:'a'.repeat(64),can_approve:true,pending_count:version.status==='draft'?1:0,total_marks:2,errors:[],warnings:[],questions:[{question_id:'q',...question,rubric_status:version.status,rubric:version.rubric_json,answer_key:{mode:'reference',reference_text:'W = Fd = 246 J.'},sources:null,source_references:[],errors:[],warnings:[]}]};
    else if(path.endsWith('/questions'))body=[question];
    else if(path.endsWith('/rubric'))body={rubric:version.rubric_json,rubric_version_id:version.id};
    else if(path.endsWith('/rubric-versions')){if(method==='POST'){version={id:'draft',version_number:2,status:'draft',rubric_json:req.postDataJSON().rubric};}body=method==='GET'?[version]:version;}
    else if(path.startsWith('/rubric-versions/')){version.rubric_json=req.postDataJSON().rubric;body=version;}
    else if(path.endsWith('/grading-policy'))body={mode:'adaptive'};
    else if(path.endsWith('/answer-key-versions'))body=[{id:'k',version_number:1,status:'approved',mode:'reference',reference_text:'W = Fd = 246 J.',acceptable_answers:[],document_refs:[]}];
    else if(path.endsWith('/material-scopes'))body=path.startsWith('/exams/')?{versions:[],questions:[]}:[];
    else if(path.endsWith('/materials')||path.startsWith('/instructor-preference-'))body=[];
    else if(path.endsWith('/setup-imports'))body=[];
    else if(path==='/results/s')body={submission:submission(),answers:[answer()],latest_review_labels:[]};
    else if(path.endsWith('/extraction-review'))body=report();
    else if(path==='/answer-sources/seg/text'){if(failCorrection)return route.fulfill({status:409,json:{detail:'Synthetic transcription conflict'}});state.text=req.postDataJSON().text;body=report();}
    else if(path.endsWith('/metadata')){state.name=req.postDataJSON().student_name;state.number=req.postDataJSON().student_number;body={submission:submission()};}
    else if(path.endsWith('/reextract'))body={question_numbers:['1'],segments:[{question_number:'1',text:'Synthetic recovered answer'}],preview_signature:'synthetic-preview'};
    else if(path.endsWith('/confirm-reextract'))body=report();
    else if(path.includes('/pages/'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="white"/><text x="40" y="100" font-size="24">Synthetic handwriting: W = Fd</text></svg>'});
    else if(path.endsWith('/source-locations'))body={sources:{}};
    else if(path==='/submissions/s/grade'){state.graded=true;body={submission_id:'s',job:{...job,job_type:'grade_submission'}};}
    else if(path.endsWith('/resolve-review')){state.reviewed=true;body={answer:answer()};}
    else if(path==='/review-queue')body=state.reviewed?[]:[answer()];
    else if(path.endsWith('/review-history'))body=[];
    else if(path.endsWith('/grading-runs'))body=[{id:'run',model_name:'synthetic-model',mode:'text_only',score:1,max_score:2,created_at:'2026-10-14',criteria_scores:answer().criteria_scores,response_json:{verification:answer().grading_raw_response.verification}}];
    else if(path.endsWith('/learning-insights'))body={exam_id:'e',submission_count:1,notes:[],questions:[{question_number:'1',question_text:question.question_text,graded_count:1,average_percent:50,awaiting_review_count:state.reviewed?0:1,course_grounded_count:0,criteria:[]}]};
    else if(path.endsWith('/exports/preflight'))body={grade_column:'Synthetic exam',rows:[{submission_id:'s',student_name:state.name,username:state.number,score:1,max_score:2,issues:state.reviewed?[]:[{code:'needs_review',message:'Instructor review is pending',blocking:true}]}]};
    else if(path.endsWith('/grades.csv'))return route.fulfill({contentType:'text/csv',headers:{'content-disposition':'attachment; filename="synthetic-grades.csv"','access-control-expose-headers':'Content-Disposition'},body:'Username,Grade\nTEST01,1\n'});
    else if(path==='/admin/operations/health')body={services:{api:{status:'online',detail:'Synthetic API ready'}}};
    else if(path==='/admin/instructors')body=method==='GET'?[{id:'teacher',email:'synthetic@example.edu',full_name:'Synthetic teacher',is_active:state.teacherActive}]:{id:'new'};
    else if(path==='/admin/instructors/teacher'){state.teacherActive=req.postDataJSON().is_active;body={id:'teacher'};}
    else if(path.endsWith('/reset-password'))body={id:'teacher',must_change_password:true};
    else if(path==='/admin/operations/jobs/recover')body={checked:2,requeued:1,queue_available:true};
    else if(path==='/admin/operations/audit')body={items:[],total:0};
    await route.fulfill({json:body});
  });return state;
}

test('native rubric → upload → extraction correction → grading → feedback/results',async({page})=>{
  const state=await fixture(page,{graded:false});
  await page.goto('/app/setup.html?exam_id=e');await expect(page.locator('#guide-questions-stage')).toBeVisible();
  await page.locator('[data-guide-question="q"]').first().click();await page.locator('[data-author-draft]').click();await page.locator('#ac-0-title').fill('Correct formula and units');await page.locator('#guide-review-tab').click();await page.locator('#guide-confirm').check();await page.locator('#guide-approve').click();await expect(page.locator('#guide-approval-state')).toContainText('approved');
  await page.locator('#native-exam-navigation a[href^="upload"]').click();await expect(page.locator('#ledger-upload')).toBeVisible();
  await page.locator('#ledger-files').setInputFiles({name:'synthetic.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-synthetic')});await page.locator('#ledger-upload-submit').click();await expect(page.locator('#upload-accepted')).toContainText('completed');await page.locator('[data-open-saved-paper="s"]').first().click();await expect(page).toHaveURL(/\/app\/extraction.html/);
  await page.locator('[data-source="seg"] textarea').fill('W = Fd = 246 J.');await page.getByRole('button',{name:'Save correction',exact:true}).click();await expect(page.locator('#extraction-state')).toContainText('ready');expect(state.text).toBe('W = Fd = 246 J.');
  await page.locator('#start-grading').click();await expect(page).toHaveURL(/\/app\/grading.html/);await expect(page.locator('.agent-strip')).toContainText('Verification agent');await expect(page.getByRole('heading',{name:'Verification findings'})).toBeVisible();await expect(page.locator('#original-paper')).toBeVisible();if(await page.locator('#review-evidence-checked').count())await page.locator('#review-evidence-checked').check();await page.getByRole('button',{name:'Save instructor grade',exact:true}).click();await expect.poll(()=>state.reviewed).toBe(true);
  await page.locator('#native-exam-navigation a[href^="feedback"]').click();await expect(page.locator('#learning-insights')).toContainText('1 graded');
  await page.locator('#native-exam-navigation a[href^="results"]').click();await expect(page.locator('#native-export-checks')).toContainText('1 included');const download=page.waitForEvent('download');await page.locator('#native-export-csv').click();expect((await download).suggestedFilename()).toBe('synthetic-grades.csv');
  expect(state.writes.some(w=>w.path.endsWith('/marking-guide/approve'))).toBeTruthy();
  await expect(page.locator('a[href*="/pages/"]')).toHaveCount(0);
});

test('transcription conflict retains edits and prevents navigation on cancellation',async({page})=>{
  await fixture(page,{graded:false,failCorrection:true});await page.goto('/app/extraction.html?exam_id=e&submission_id=s');
  await page.locator('[data-source="seg"] textarea').fill('Keep this unsaved correction');await page.getByRole('button',{name:'Save correction',exact:true}).click();await expect(page.locator('#native-page-notice')).toContainText('conflict');await expect(page.locator('[data-source="seg"] textarea')).toHaveValue('Keep this unsaved correction');
  await page.locator('#go-grading').click();await answerWorkspaceDialog(page,'cancel');await expect(page).toHaveURL(/extraction.html/);
});

test('approved guide can be reopened without discarding its saved criteria',async({page})=>{
  const state=await fixture(page);
  await page.route('**/api/exams/e/marking-guide/reopen',async route=>{
    state.writes.push({path:'/exams/e/marking-guide/reopen',body:route.request().postDataJSON()});
    await route.fulfill({json:{exam_id:'e',draft_version_ids:['draft'],message:'Guide reopened with saved correction drafts.'}});
  });
  await page.goto('/app/setup.html?exam_id=e');await page.locator('#guide-review-tab').click();
  await page.locator('#guide-reopen').click();await answerWorkspaceDialog(page,'confirm');
  await expect(page.locator('#guide-approval-state')).toContainText('reopened');
  expect(state.writes.find(w=>w.path.endsWith('/reopen')).body).toEqual({review_token:'a'.repeat(64),confirm_reviewed:true});
});

test('dashboard, history and reviews use real API-shaped records with native destinations',async({page},info)=>{
  await fixture(page);await page.goto('/app/dashboard.html');await expect(page.locator('#dashboard-exams')).toContainText('Synthetic physics exam');await expect(page.locator('#dashboard-summary')).toContainText('Awaiting review');
  const exams=page.locator('#dashboard-exams');
  expect(await exams.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
  await page.screenshot({path:`.impeccable/review/native-dashboard-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-language').click();
  await expect(page.locator('html')).toHaveAttribute('dir','rtl');
  await page.locator('#app-theme').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await expect(exams.getByRole('link',{name:'فتح الاختبار'})).toBeVisible();
  expect(await exams.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
  await page.screenshot({path:`.impeccable/review/native-dashboard-rtl-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.goto('/app/reviews.html?exam_id=e');await expect(page.locator('#review-list')).toContainText('Synthetic student');await expect(page.locator('#review-list a')).toHaveAttribute('href',/grading.html/);
  await page.goto('/app/history.html?exam_id=e&submission_id=s');await expect(page.locator('#history-left')).toContainText('synthetic-model');await expect(page.locator('#history-right')).toContainText('1 / 2');await expect(page.locator('a[href*="/pages/"]')).toHaveCount(0);
});

test('dashboard exam search and refresh distinguish empty results from unavailable data',async({page})=>{
  const state=await fixture(page);
  let examResponse='unavailable';
  await page.route('**/api/exams',route=>{
    if(examResponse==='unavailable')return route.fulfill({status:503,json:{detail:'Synthetic outage'}});
    if(examResponse==='empty')return route.fulfill({json:[]});
    return route.fallback();
  });
  await page.goto('/app/dashboard.html');
  const list=page.locator('#dashboard-exams');
  const search=page.getByRole('searchbox',{name:'Find an exam'});
  const refresh=page.getByRole('button',{name:'Refresh',exact:true});
  const error=page.locator('#dashboard-error');
  await expect(error).toContainText('Use Refresh to try again');
  await expect(list).toBeEmpty();

  examResponse='available';
  await refresh.click();
  const openExam=list.getByRole('link',{name:'Open exam'});
  await expect(openExam).toHaveAttribute('href','grading.html?exam_id=e');
  await expect(list.getByRole('link')).toHaveCount(1);
  await search.fill('  test  ');
  await expect(openExam).toBeVisible();
  await search.fill('no matching exam');
  await expect(list.getByRole('heading')).toHaveText('No exams match your search');
  await expect(list.getByRole('link',{name:'Create exam'})).toHaveCount(0);
  await list.getByRole('button',{name:'Clear search'}).click();
  await expect(search).toBeFocused();
  await expect(search).toHaveValue('');
  await expect(openExam).toBeVisible();

  examResponse='unavailable';
  await refresh.click();
  await expect(error).toContainText('Showing the last loaded exams');
  await expect(openExam).toBeVisible();
  examResponse='empty';
  await refresh.click();
  await expect(error).toBeEmpty();
  await expect(list.getByRole('link',{name:'Create exam'})).toBeVisible();

  examResponse='available';
  await refresh.click();
  await openExam.click();
  await expect(page.locator('#next-action')).toHaveText('Review next paper');
  expect(state.writes).toEqual([]);
});

test('dashboard counts saved papers and keeps exam access during a review outage', async ({page}) => {
  const state = await fixture(page);
  let reviewsAvailable = false;
  await page.route('**/api/review-queue', route => reviewsAvailable
    ? route.fallback()
    : route.fulfill({status:503, json:{detail:'Synthetic review outage'}}));
  await page.route('**/api/submissions', route => route.fulfill({json:[
    {id:'s', exam_id:'e', extracted_student_name:'Synthetic <b>student</b>', grading_summary:{complete:true, review_count:2}},
    {id:'pending', exam_id:'e', grading_summary:{complete:false, review_count:0}},
  ]}));

  await page.goto('/app/index.html');
  await expect(page).toHaveURL(/\/app\/dashboard.html$/);
  await expect(page.locator('#dashboard-graded-total')).toHaveText('1 / 2');
  await expect(page.locator('#dashboard-review-count')).toHaveText('1');
  await expect(page.locator('#dashboard-exams progress')).toHaveAttribute('max', '2');
  const review = page.locator('#dashboard-review-concerns');
  await expect(review.getByRole('status')).toContainText('Could not load review concerns');
  await expect(review.getByRole('link', {name:'Open review queue'})).toBeVisible();
  await expect(page.getByRole('link', {name:'Open exam'})).toHaveAttribute('href', 'grading.html?exam_id=e');

  reviewsAvailable = true;
  await page.getByRole('button', {name:'Refresh', exact:true}).click();
  await expect(review.getByRole('heading', {level:3})).toContainText('Synthetic <b>student</b>');
  await expect(review.locator('h3 b')).toHaveCount(0);
  const evidence = review.getByRole('link', {name:'Review evidence'});
  await expect(evidence).toHaveAttribute(
    'href', 'grading.html?exam_id=e&submission_id=s&question_id=q');
  await evidence.click();
  await expect(page.locator('#question-detail')).toContainText('Calculate work for 82 N');
  expect(state.writes).toEqual([]);
});

test('removed exam question keeps accessible read-only grading history',async({page},info)=>{
  await fixture(page);
  await page.route('**/api/exams/e/questions',route=>route.fulfill({json:[]}));
  await page.route('**/api/results/s',route=>route.fulfill({json:{submission:{id:'s',exam_id:'e',extracted_student_name:'Synthetic student'},answers:[],removed_answers:[{id:'a',question_id:'q',score:1,max_score:2}],grading_scope:{removed_question_ids:['q'],removed_questions:[{id:'q',number:'p6.3'}]},latest_review_labels:[],external_answers:[]}}));
  await page.goto('/app/history.html?exam_id=e&submission_id=s&answer_id=a');
  await expect(page.locator('#history-question')).toHaveValue('a');await expect(page.locator('#history-question option')).toContainText('p6.3');
  await expect(page.locator('#history-left')).toContainText('synthetic-model');await expect(page.locator('#regrade-answer')).toBeDisabled();
  await expect(page.locator('#history-removed-note')).toContainText('Restore it in Extraction');
  await page.screenshot({path:`.impeccable/review/extraction-removal-20261027/history-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});

test('extraction and grading layouts fit desktop/mobile in both themes',async({page},info)=>{
  await fixture(page,{graded:false});await page.goto('/app/extraction.html?exam_id=e&submission_id=s');await expect(page.locator('[data-source="seg"]')).toBeVisible();
  for(const theme of ['light','dark']){await page.evaluate(theme=>MisraTheme.set(theme),theme);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:`.impeccable/review/native-extraction-${theme}-${info.project.name}.png`,fullPage:true,animations:'disabled'});}
  await page.goto('/app/grading.html?exam_id=e&submission_id=s');await expect(page.getByRole('button',{name:'Grade paper with AI'})).toBeEnabled();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('assessment workspace uses the available width and keeps grading input and progress above the question',async({page},info)=>{
  const mobile=info.project.name.startsWith('mobile');
  if(!mobile)await page.setViewportSize({width:1896,height:902});
  const state=await fixture(page,{graded:false});
  let policy={mode:'adaptive',audit_rate:.25};
  let failSave=true, activityUnavailable=false;
  await page.route('**/api/questions/q/grading-policy',async route=>{
    if(route.request().method()==='GET')return route.fulfill({json:policy});
    const body=route.request().postDataJSON();
    expect(body).toEqual({mode:'image_text_required',audit_rate:.25});
    if(failSave)return route.fulfill({status:503,json:{detail:'Synthetic policy save failure'}});
    policy=body;return route.fulfill({json:policy});
  });
  await page.route('**/api/submissions/s/grade',route=>{
    expect(route.request().postDataJSON()).toEqual({mode:'auto'});
    state.gradingProfile=route.request().headers()['x-misra-inference-profile'];
    state.gradingJob={id:'synthetic-grading',exam_id:'e',submission_id:'s',job_type:'grade_submission',status:'processing',progress_percent:40,progress_message:'Assessing the synthetic paper.'};
    return route.fulfill({status:202,json:{submission_id:'s',job:state.gradingJob}});
  });
  await page.route('**/api/jobs?*',route=>activityUnavailable?route.fulfill({status:503,json:{detail:'Synthetic activity outage'}}):route.fulfill({json:{items:state.gradingJob?[state.gradingJob]:[],active_count:state.gradingJob?1:0}}));
  const capture=async (surface,verify)=>{
    for(const theme of ['light','dark']){
      await page.evaluate(theme=>MisraTheme.set(theme),theme);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await verify();
      await page.screenshot({path:`.impeccable/review/exam-width/${surface}-${theme}-${info.project.name}.png`,animations:'disabled'});
    }
  };
  await page.goto('/app/setup.html?exam_id=e');
  await expect(page.locator('#guide-outline')).toContainText('Calculate work');
  await capture('rubric',async()=>{
    const bounds=await page.locator('#ledger-setup').boundingBox();
    expect(Math.abs(page.viewportSize().width-bounds.width-2*bounds.x)).toBeLessThan(4);
    if(!mobile)expect(bounds.width).toBeGreaterThan(1750);
  });
  await page.goto('/app/extraction.html?exam_id=e&submission_id=s');
  await page.getByRole('link',{name:'Choose grading input'}).click();
  const input=page.getByLabel('Grading input for this question');
  await expect(input).toHaveValue('adaptive');
  await input.selectOption('text_only');
  await page.getByRole('button',{name:'Discard change',exact:true}).click();
  await expect(input).toHaveValue('adaptive');
  await input.selectOption('image_text_required');
  const start=page.getByRole('button',{name:'Grade paper with AI'});
  await expect(start).toBeDisabled();
  const save=page.getByRole('button',{name:'Save grading input'});
  await save.click();
  await expect(page.locator('#grading-input-status')).toHaveText('Synthetic policy save failure');
  await expect(input).toHaveValue('image_text_required');
  await expect(start).toBeDisabled();
  failSave=false;
  await save.click();
  await expect(start).toBeEnabled();
  await page.goto('/app/extraction.html?exam_id=e&submission_id=s');
  await page.getByRole('button',{name:'Start AI grading'}).click();
  await expect(page.getByRole('heading',{name:'AI grading in progress'})).toBeVisible();
  await expect(page.locator('#grading-run progress')).toHaveAttribute('value','40');
  await expect(input).toHaveValue('image_text_required');
  await expect(input).toBeDisabled();
  await expect(start).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Review checks'})).toHaveCount(0);
  await expect(page.locator('#original-paper')).toBeVisible();
  await page.evaluate(()=>scrollTo(0,0));
  await capture('grading-in-progress',async()=>{
    expect((await page.locator('#grading-controls').boundingBox()).y).toBeLessThan((await page.locator('#question-detail').boundingBox()).y);
    if(!mobile)expect((await page.locator('#paper-viewport').boundingBox()).height).toBeGreaterThan(430);
  });
  await page.goto('/app/grading.html?exam_id=e');
  await page.locator('#paper-picker').getByRole('button',{name:'View progress'}).click();
  await expect(page.getByRole('heading',{name:'AI grading in progress'})).toBeVisible();
  activityUnavailable=true;
  state.gradingJob={...state.gradingJob,status:'failed',error_message:'Synthetic failure'};
  const freshStart=page.getByRole('button',{name:'Grade with current AI setup'});
  await expect(freshStart).toBeEnabled({timeout:7000});
  await expect(input).toBeEnabled();
  await expect(start).toHaveCount(0);
  await page.evaluate(()=>MisraAPI.setInferenceProfile('local_qwen_vision_gemini_v1'));
  await freshStart.click();
  await expect(page.getByRole('heading',{name:'AI grading in progress'})).toBeVisible();
  expect(state.gradingProfile).toBe('local_qwen_vision_gemini_v1');
});

test('View and grade resumes the stopped job from the paper',async({page},info)=>{
  const state=await fixture(page);
  state.gradingJob={id:'stopped-job',exam_id:'e',submission_id:'s',job_type:'grade_submission',status:'stopped'};
  let retries=0;
  await page.route('**/api/jobs/stopped-job/retry',route=>{
    if(++retries===1)return route.fulfill({status:409,json:{detail:'Synthetic retry conflict'}});
    state.gradingJob={...state.gradingJob,status:'queued'};
    return route.fulfill({status:202,json:state.gradingJob});
  });
  await page.goto('/app/grading.html?exam_id=e&submission_id=s');
  const resume=page.locator('#grading-run').getByRole('button',{name:'Resume grading'});
  await expect(resume).toBeEnabled();
  for(const theme of ['light','dark']){
    await page.evaluate(value=>MisraTheme.set(value),theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:`.impeccable/review/grading-resume-${theme}-${info.project.name}.png`,animations:'disabled'});
  }
  await resume.click();
  await expect(page.locator('#error')).toContainText('Synthetic retry conflict');
  await expect(resume).toBeEnabled();
  await resume.click();
  await expect(page.getByRole('heading',{name:'AI grading queued'})).toBeVisible();
  await expect(resume).toHaveCount(0);
  await expect(page.locator('#instructor-score')).toHaveValue('1');
  expect(state.writes.some(write=>write.path.endsWith('/grade'))).toBe(false);
  expect(retries).toBe(2);
});

test('one-answer grading advances through its phases and reloads saved marks after a failed poll',async({page},info)=>{
  const state=await fixture(page,{graded:false});
  let failedRefresh=false, staleRefresh=false;
  const job={id:'one-answer',exam_id:'e',submission_id:'s',job_type:'grade_submission',status:'processing',progress_current:0};
  state.gradingJob={...job,grading_stage:'assessing',progress_percent:20};
  await page.route('**/api/jobs?*',route=>route.fulfill({json:{items:[state.gradingJob],active_count:state.graded?0:1}}));
  await page.route('**/api/results/s',route=>{
    if(state.graded && !failedRefresh){failedRefresh=true;return route.fulfill({status:503,json:{detail:'Synthetic result refresh failure'}});}
    if(state.graded && !staleRefresh){staleRefresh=true;return route.fulfill({json:{submission:{id:'s',exam_id:'e'},answers:[]}});}
    return route.fallback();
  });
  await page.goto('/app/grading.html?exam_id=e&submission_id=s');
  const bar=page.locator('#grading-run progress');
  await expect(bar).toHaveAttribute('value','20');
  state.gradingJob={...job,grading_stage:'verifying',progress_percent:65};
  await expect(bar).toHaveAttribute('value','65',{timeout:7000});
  await expect(page.locator('#grading-run').getByText('The AI is checking the proposed marks…')).toBeVisible();
  for(const theme of ['light','dark']){
    await page.evaluate(value=>MisraTheme.set(value),theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:`.impeccable/review/grading-progress-${theme}-${info.project.name}.png`,animations:'disabled'});
  }
  state.graded=true;
  state.gradingJob={...job,status:'completed',progress_current:1,progress_percent:100};
  await expect(bar).toHaveAttribute('value','100',{timeout:7000});
  await expect(page.getByText('Saved grades are ready to review.')).toBeVisible({timeout:10000});
  await expect(page.locator('#instructor-score')).toHaveValue('1');
  expect(failedRefresh && staleRefresh).toBe(true);
});

test('administration is restricted and admin controls call existing endpoints',async({page})=>{
  await fixture(page);await page.goto('/app/admin.html');await expect(page.locator('#admin-error')).toContainText('Administrator');await expect(page.locator('#admin-content')).toBeHidden();
});

test('saving a transcription preserves a different unsaved identity form',async({page})=>{
  const state=await fixture(page,{graded:false});await page.goto('/app/extraction.html?exam_id=e&submission_id=s');
  await page.getByText('Student identity',{exact:true}).click();await page.locator('#identity-name').fill('Retained synthetic name');
  await page.locator('[data-source="seg"] textarea').fill('Corrected synthetic formula');await page.getByRole('button',{name:'Save correction',exact:true}).click();
  await expect(page.locator('#identity-name')).toHaveValue('Retained synthetic name');await expect(page.locator('#extraction-state')).toContainText('Unsaved');
  await page.locator('#start-grading').click();await expect(page.locator('#native-page-notice')).toContainText('Save your extraction');expect(state.writes.some(w=>w.path.endsWith('/grade'))).toBeFalsy();
  await page.getByRole('button',{name:'Save student details'}).click();await expect(page.locator('#extraction-state')).toContainText('ready');expect(state.name).toBe('Retained synthetic name');
});

test('page recovery must be previewed again after changing original pages',async({page})=>{
  const state=await fixture(page,{graded:false,pageCount:2});await page.goto('/app/extraction.html?exam_id=e&submission_id=s');
  await page.getByText('Recover missing answers on this page',{exact:true}).click();await page.locator('#recovery-questions input').check();await page.locator('#recover-page').click();
  await expect(page.locator('#confirm-recovery')).toBeVisible();await expect(page.locator('#recovery-preview')).toContainText('Synthetic recovered');await page.locator('#page-next').click();
  await expect(page.locator('#confirm-recovery')).toBeHidden();await expect(page.locator('#recovery-preview')).toBeEmpty();expect(state.writes.some(w=>w.path.endsWith('/confirm-reextract'))).toBeFalsy();
  await page.locator('#recover-page').click();await page.locator('#confirm-recovery').click();await expect.poll(()=>state.writes.some(w=>w.path.endsWith('/pages/1/confirm-reextract'))).toBe(true);
});

test('admin creates accounts, changes access, resets passwords and recovers jobs',async({page},info)=>{
  const state=await fixture(page,{admin:true});await page.goto('/app/admin.html');await expect(page.locator('#admin-instructors')).toContainText('Synthetic teacher');
  await page.getByText('Create instructor account',{exact:true}).click();await page.locator('#create-instructor [name=full_name]').fill('Synthetic new teacher');await page.locator('#create-instructor [name=email]').fill('new@example.edu');await page.locator('#create-instructor [name=temporary_password]').fill('Synthetic-Only-123');await page.getByRole('button',{name:'Create instructor',exact:true}).click();await expect(page.locator('#native-page-notice')).toContainText('created');
  await page.locator('[data-toggle-user]').click();await answerWorkspaceDialog(page,'confirm');await expect(page.locator('[data-toggle-user]')).toHaveText('Enable');
  await page.getByText('Reset password',{exact:true}).click();await page.locator('[data-reset-user] input').fill('Synthetic-Reset-123');await page.getByRole('button',{name:'Apply reset'}).click();await expect(page.locator('#native-page-notice')).toContainText('Temporary password set');
  await page.locator('#recover-jobs').click();await answerWorkspaceDialog(page,'confirm');await expect(page.locator('#native-page-notice')).toContainText('2 jobs checked');
  expect(state.writes.some(w=>w.path.endsWith('/reset-password'))).toBeTruthy();await page.screenshot({path:`.impeccable/review/native-admin-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});

test('native activity obeys the live API job limit',async({page})=>{
  await fixture(page);await page.goto('/app/activity.html?exam_id=e');await expect(page.locator('#activity-host')).toContainText('Synthetic extraction completed');await expect(page.locator('#activity-error')).toBeEmpty();
});

test('Activity stops a grading job once through an app dialog and keeps progress left-to-right',async({page},info)=>{
  await fixture(page);
  let state='processing', stops=0;
  const grading={id:'running',job_type:'grade_submission',submission_id:'s',exam_id:'e',progress_percent:0};
  await page.route('**/api/jobs?*',route=>route.fulfill({json:{items:[{...grading,status:state},
    {...grading,id:'old-failed',status:'failed'}],active_count:state==='stopped'?0:1}}));
  await page.route('**/api/jobs/running/stop',route=>{stops++;state='stopping';return route.fulfill({status:202,json:{...grading,status:state}});});
  await page.goto('/app/activity.html');
  const stop=page.getByRole('button',{name:'Stop grading'});
  await expect(page.getByRole('progressbar')).toHaveAttribute('value','0');
  await expect(page.getByRole('progressbar')).toHaveAttribute('dir','ltr');
  await expect(page.getByRole('button',{name:'Retry safely'})).toHaveCount(0);
  await stop.click();
  await expect(page.getByRole('dialog',{name:'Stop grading this paper?'})).toBeVisible();
  await page.screenshot({path:`.impeccable/review/grading-stop-${info.project.name}.png`,animations:'disabled'});
  await page.keyboard.press('Escape');
  await expect(stop).toBeFocused();expect(stops).toBe(0);
  await stop.click();await answerWorkspaceDialog(page,'confirm');
  await expect(page.getByText('Stopping…',{exact:true})).toBeVisible();
  await expect(stop).toHaveCount(0);expect(stops).toBe(1);
  state='stopped';await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await expect(page.getByRole('button',{name:'Resume grading'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Retry safely'})).toHaveCount(0);
});

test('Back closes an answer-action dialog without writing to the old page',async({page})=>{
  const state=await fixture(page);state.reviewed=true;
  await page.goto('/app/activity.html');
  await expect(page.getByRole('heading',{name:'Processing activity'})).toBeVisible();
  await page.evaluate(()=>location.assign('/app/grading.html?exam_id=e&submission_id=s'));
  await page.getByRole('button',{name:'Reopen saved decision for review'}).click();
  await expect(page.getByRole('dialog',{name:'Reopen this decision?'})).toBeVisible();
  await page.evaluate(()=>history.back());
  await expect(page).toHaveURL(/activity\.html/);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(state.writes.some(write=>write.path.includes('reopen'))).toBe(false);
});

test('grading controls switch to Arabic while evidence remains verbatim',async({page},info)=>{
  await fixture(page);await page.goto('/app/grading.html?exam_id=e&submission_id=s');await expect(page.locator('.agent-strip')).toBeVisible();
  for(const theme of ['light','dark']){await page.evaluate(theme=>{localStorage.setItem('misra-theme',theme);dispatchEvent(new StorageEvent('storage',{key:'misra-theme'}));},theme);await page.screenshot({path:`.impeccable/review/native-grading-${theme}-${info.project.name}.png`,fullPage:true,animations:'disabled'});}
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');await expect(page.locator('.agent-strip')).toContainText('وكيل التحقق');await expect(page.locator('.question-copy')).toContainText('Calculate work for 82 N');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:`.impeccable/review/native-grading-rtl-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});

test('focused setup, upload, feedback and results stay usable across themes and RTL',async({page},info)=>{
  const state=await fixture(page);state.reviewed=true;
  for(const [route,ready] of [['setup','#guide-outline'],['upload','#ledger-upload'],['feedback','#learning-insights'],['results','#native-export-checks']]){
    await page.goto(`/app/${route}.html?exam_id=e`);await expect(page.locator(ready)).toBeVisible();
    if(route==='setup')await expect(page.locator('[data-guide-question="q"]').first()).toBeVisible();
    if(route==='feedback')await expect(page.locator(ready)).toContainText('1 graded');
    if(route==='results')await expect(page.locator(ready)).toContainText('1 included');
    for(const theme of ['light','dark']){
      await page.evaluate(theme=>{localStorage.setItem('misra-theme',theme);dispatchEvent(new StorageEvent('storage',{key:'misra-theme'}));},theme);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
      await page.screenshot({path:`.impeccable/review/native-${route}-${theme}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
    }
    await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.locator('#app-language').click();
  }
});
