const { test, expect } = require('@playwright/test');

async function fixture(page, { approved = true, failConfirm = false, failRequest = false, dark = false, confirmGate = null, secondProposal = false } = {}) {
  if (dark) await page.addInitScript(() => localStorage.setItem('misra-theme', 'dark'));
  const writes = [], questions = [], imports = [];
  const rubric = { schema_version:2,max_score:2,criteria:[{id:'method',title:'Method',description:'Use W = mgh',points:2}],policy:{grading_approach:'balanced'} };
  const data = { origin:'course_source_questions',job:{id:'job',job_type:'exam_setup',status:'completed',progress_total:1,progress_current:1},
    questions:[{source_draft_id:'saved-draft',question_number:'1',question_text:'Calculate the work lifting a 2 kg mass by 3 m. Use g = 10 m/s².',max_score:2,
      marking_guide:'Method (2 marks): Apply W = mgh',answer_mode:'reference',answer_key:'60 J',source_refs:['source:1'],citations:[{source_ref:'source:1',quote:'W = mgh'}]}],
    source_passages:[{id:'source:1',title:'Synthetic energy notes',version_number:1,version_id:'v',page_index:0,text:'The work against gravity is W = mgh.',chunk_id:'chunk'}],
    documents:[],warnings:['AI-generated proposals require instructor review.'] };
  if (secondProposal) data.questions.push({...data.questions[0],source_draft_id:'second-draft',question_number:'2'});
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api','');
    let body = {};
    if (path === '/auth/me') body = {id:'u',full_name:'Synthetic Instructor',role:'teacher'};
    else if (path === '/health') body = {status:'ok'};
    else if (path === '/jobs') body = {items:[],active_count:0};
    else if (path === '/exams') body = [{id:'e',course_id:'c',title:'Synthetic assessment'},{id:'other',course_id:'c',title:'Other assessment'}];
    else if (path.endsWith('/questions')) body = questions;
    else if (path.endsWith('/setup-readiness')) body = {ready:false,question_count:questions.length,pending_questions:[],questions:[]};
    else if (path.endsWith('/materials')) body = [{id:'m',title:'Synthetic energy notes',versions:[{id:'v',version_number:1,status:approved?'approved':'draft',ingestion_status:'ready',page_count:2,approved_page_indices:[0],media_type:'text/plain'}]}];
    else if (path.endsWith('/source-question-drafts')) {
      writes.push({path,body:route.request().postDataJSON()});
      if (failRequest) return route.fulfill({status:503,json:{detail:'Synthetic free-provider unavailable'}});
      imports.push(data); body = {...data,questions:[],job:{...data.job,status:'queued',progress_current:0}};
    } else if (path.endsWith('/setup-imports/job')) body = data;
    else if (path.endsWith('/setup-imports')) body = imports;
    else if (path.endsWith('/confirm')) {
      writes.push({path,body:route.request().postDataJSON()});
      if (confirmGate) await confirmGate;
      if (failConfirm) return route.fulfill({status:409,json:{detail:'Synthetic source snapshot changed'}});
      questions.push({...writes.at(-1).body.questions[0],id:'q'}); data.imported_question_ids=['q']; body={question_ids:['q']};
    } else if (path.endsWith('/rubric-versions')) body=[{id:'r',version_number:1,status:'draft',rubric_json:rubric}];
    else if (path.endsWith('/rubric')) return route.fulfill({status:409,json:{detail:'Approve the rubric first'}});
    else if (path.endsWith('/grading-policy')) body={mode:'adaptive'};
    else if (path.endsWith('/answer-key-versions') || path.endsWith('/material-scopes')) body=[];
    await route.fulfill({json:body});
  });
  await page.goto('/pages/rubric-studio.html?exam_id=e');
  await page.locator('#source-question-details > summary').click();
  return { writes, questions };
}

async function request(page) {
  await page.locator('#question-source-version').selectOption('v');
  await page.locator('#question-source-topic').fill('Work against gravity');
  await page.locator('#source-draft-count').fill('1');
  await page.locator('#source-draft-button').click();
}

test('approved source proposals are cited, editable and confirmed only as drafts', async ({ page }, info) => {
  const {writes,questions} = await fixture(page,{dark:true});
  await request(page);
  await expect(page.locator('#setup-status')).toContainText('Source-grounded question drafts are ready',{timeout:9000});
  expect(questions).toHaveLength(0);
  expect(writes[0].body.bindings).toEqual([{version_id:'v',page_indices:[0]}]);
  await page.locator('.source-question-evidence > summary').click();
  await expect(page.locator('.source-question-evidence')).toContainText('Synthetic energy notes · v1 · document page 1');
  await expect(page.locator('.source-question-evidence blockquote')).toHaveText('W = mgh');
  await page.locator('#import-text-0').fill('Instructor-reviewed work question.');
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo({top:0,behavior:'instant'}); });
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(0);
  await page.screenshot({path:info.outputPath('source-question-review.png'),fullPage:true,animations:'disabled'});
  await page.evaluate(() => { document.documentElement.dataset.theme = 'light'; });
  await page.screenshot({path:info.outputPath('source-question-review-light.png'),fullPage:true,animations:'disabled'});
  await page.locator('#setup-confirm-button').click();
  await expect(page.locator('#setup-status')).toContainText('Questions added');
  expect(writes.at(-1).body.questions[0].source_draft_id).toBe('saved-draft');
  expect(writes.at(-1).body.questions[0].question_text).toBe('Instructor-reviewed work question.');
  await expect(page.locator('#upload-link')).toHaveAttribute('aria-disabled','true');
});

test('unapproved sources cannot generate and empty assessments can access library without a question', async ({page}) => {
  await fixture(page,{approved:false});
  await expect(page.locator('#source-draft-button')).toBeDisabled();
  await expect(page.locator('#source-question-library-status')).toContainText('No approved sources');
  await page.locator('#manage-question-sources').click();
  await expect(page.locator('#setup-source-library')).toHaveAttribute('open','');
  await expect(page.locator('#setup-library-host')).toContainText('Question-specific source links are configured after you add a question');
  await expect(page.locator('#setup-library-host [data-source-save]')).toHaveCount(0);
});

test('failed generation request preserves form and canceled assessment navigation', async ({page}) => {
  await fixture(page,{failRequest:true});
  await request(page);
  await expect(page.locator('#source-draft-error')).toContainText('Your entries are still here');
  await expect(page.locator('#question-source-topic')).toHaveValue('Work against gravity');
  page.once('dialog',dialog=>dialog.dismiss());
  await page.locator('#rubric-exam').selectOption('other');
  await expect(page.locator('#rubric-exam')).toHaveValue('e');
});

test('failed source confirmation preserves edited proposals and exact draft identity', async ({page}) => {
  const {writes} = await fixture(page,{failConfirm:true});
  await request(page);
  await expect(page.locator('#setup-review')).toBeVisible({timeout:9000});
  await page.locator('#import-text-0').fill('Keep this correction');
  await page.locator('#setup-confirm-button').click();
  await expect(page.locator('#setup-confirm-error')).toContainText('Your edits are still here');
  await expect(page.locator('#import-text-0')).toHaveValue('Keep this correction');
  expect(writes.at(-1).body.questions[0].source_draft_id).toBe('saved-draft');
});

test('saving proposals freezes submitted fields and restores excluded states on failure', async ({page},info) => {
  let release;
  const confirmGate = new Promise(resolve=>{ release=resolve; });
  await fixture(page,{failConfirm:true,confirmGate,secondProposal:true});
  await request(page);
  await expect(page.locator('#setup-review')).toBeVisible({timeout:9000});
  await page.locator('[data-import-question="1"] [name="include"]').uncheck();
  await expect(page.locator('#import-text-1')).toBeDisabled();
  await page.locator('#import-text-0').fill('Keep the submitted snapshot');
  await page.locator('#setup-confirm-button').click();
  await expect(page.locator('#import-text-0')).toBeDisabled();
  await expect(page.locator('[data-import-question="0"] [name="include"]')).toBeDisabled();
  await expect(page.locator('#setup-approach')).toBeDisabled();
  await page.locator('#setup-confirm-form').screenshot({path:info.outputPath('source-confirmation-pending.png'),animations:'disabled'});
  release();
  await expect(page.locator('#setup-confirm-error')).toContainText('Your edits are still here');
  await expect(page.locator('#import-text-0')).toBeEnabled();
  await expect(page.locator('#import-text-0')).toHaveValue('Keep the submitted snapshot');
  await expect(page.locator('#import-text-1')).toBeDisabled();
  await expect(page.locator('[data-import-question="1"] [name="include"]')).toBeEnabled();
});

test('importing proposals does not erase a newly prepared generation request', async ({page},info) => {
  const {writes} = await fixture(page);
  await request(page);
  await expect(page.locator('#setup-review')).toBeVisible({timeout:9000});
  await page.locator('#source-question-details > summary').click();
  await page.locator('#question-source-topic').fill('Next request: kinetic energy');
  await page.locator('#setup-confirm-button').click();
  await expect(page.locator('#setup-status')).toContainText('Questions added');
  await expect(page.locator('#question-source-topic')).toHaveValue('Next request: kinetic energy');
  expect(writes.filter(item=>item.path.endsWith('/confirm'))).toHaveLength(1);
  await page.locator('#source-question-details').screenshot({path:info.outputPath('source-preserved-request.png'),animations:'disabled'});
});
