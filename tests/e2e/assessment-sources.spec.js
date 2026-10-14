const { test, expect } = require('@playwright/test');

async function fixture(page, { failApproval = false, missingUpgrade = false } = {}) {
  const writes = [];
  const rubric = {schema_version:2,max_score:2,criteria:[{id:'work',title:'Calculate work',description:'Apply W = Fd',points:2}],policy:{grading_approach:'balanced'}};
  const material = {id:'m',title:'Synthetic chapter',versions:[{id:'v',version_number:1,status:'approved',ingestion_status:'ready',page_count:4,approved_page_indices:[0,1,2,3]}]};
  let defaults = [], overrides = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api','');
    const method = route.request().method(); let body = {};
    const effective = () => ({question_id:'q',question_number:'1',origin:overrides.some(v=>v.status==='approved' && v.mode!=='inherit') ? 'question' : defaults.some(v=>v.status==='approved') ? 'assessment' : 'not_configured',scope:overrides.find(v=>v.status==='approved' && v.mode!=='inherit') || defaults.find(v=>v.status==='approved') || null});
    if (path === '/auth/me') body = {id:'u',full_name:'Synthetic Instructor',role:'teacher'};
    else if (path === '/health') body = {status:'ok'};
    else if (path === '/jobs') body = {items:[],active_count:0};
    else if (path === '/exams') body = [{id:'e',course_id:'c',title:'Synthetic assessment'},{id:'e2',course_id:'c',title:'Second assessment'}];
    else if (path.endsWith('/questions')) body = [{id:'q',question_number:'1',question_text:'Calculate work',max_score:2}];
    else if (path.endsWith('/setup-imports') || path.endsWith('/answer-key-versions')) body = [];
    else if (path.endsWith('/setup-readiness')) body = {ready:true,question_count:1,rubric_count:1,questions:[]};
    else if (path.endsWith('/rubric')) body = {rubric,rubric_version_id:'r'};
    else if (path.endsWith('/rubric-versions')) body = [{id:'r',version_number:1,status:'approved',rubric_json:rubric}];
    else if (path.endsWith('/grading-policy')) body = {mode:'adaptive'};
    else if (path.endsWith('/materials')) body = [material];
    else if (path.endsWith('/effective-material-scope')) body = effective();
    else if (path.startsWith('/exams/') && path.endsWith('/material-scopes')) {
      if (missingUpgrade) return route.fulfill({status:503,json:{detail:'Back up, then run upgrade_assessment_sources.py.'}});
      if (method === 'GET') body = {exam_id:'e',versions:defaults,questions:[effective()]};
      else { const value = route.request().postDataJSON(); writes.push(value); body = {...value,id:`default-${writes.length}`,version_number:writes.length,status:'draft'}; defaults.unshift(body); }
    } else if (path.startsWith('/exams/') && path.includes('/material-scopes/') && path.endsWith('/approve')) {
      if (failApproval) return route.fulfill({status:409,json:{detail:'Synthetic approval conflict'}});
      defaults.forEach(v=>v.status=v.id === path.split('/').at(-2) ? 'approved' : v.status === 'approved' ? 'superseded' : v.status);
      body = defaults.find(v=>v.status==='approved');
    } else if (path.startsWith('/questions/') && path.endsWith('/material-scopes')) {
      if (method === 'GET') body = overrides;
      else { body={...route.request().postDataJSON(),id:'override',version_number:1,status:'draft'}; overrides=[body]; }
    } else if (path.startsWith('/questions/') && path.includes('/material-scopes/') && path.endsWith('/approve')) { overrides[0].status='approved'; body=overrides[0]; }
    else if (path.endsWith('/material-retrieval-preview')) body = {status:'retrieved',passages:[]};
    await route.fulfill({json:body});
  });
  await page.goto('/pages/rubric-studio.html?exam_id=e');
  await page.locator('#assessment-sources-panel > summary').click();
  if (!missingUpgrade) await expect(page.getByLabel('How should references be used?')).toBeVisible();
  return writes;
}

async function addSource(page) {
  await page.getByRole('button',{name:'Add assessment source',exact:true}).click();
  await page.locator('#assessment-version-0').selectOption('v');
  await page.locator('#assessment-pages-0').fill('2-3');
}

test('assessment sources save drafts, approve explicitly and show inheritance', async ({page},info) => {
  const writes = await fixture(page);
  await addSource(page);
  await page.getByRole('button',{name:'Save assessment source draft',exact:true}).click();
  await expect(page.locator('#assessment-sources-host')).toContainText('Draft v1 saved—not active yet');
  expect(writes[0]).toEqual({mode:'required',bindings:[{version_id:'v',page_indices:[1,2],criterion_id:null,chunk_ids:[]}]});
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Save & approve assessment sources',exact:true}).click();
  await expect(page.locator('#assessment-sources-host')).toContainText('Assessment sources approved');
  await page.getByText('Question exceptions and inheritance',{exact:true}).click();
  await expect(page.locator('#assessment-sources-host')).toContainText('Question 1: uses assessment default');
  await expect(page.locator('#course-material-panel')).toContainText('Uses the approved assessment default');
  await page.locator('#assessment-sources-panel').scrollIntoViewIfNeeded();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  const captureStyle = '.workspace-topbar,.workspace-header,.workspace-sidebar,.skip-link {visibility:hidden!important}';
  await page.locator('#assessment-sources-panel').screenshot({path:`.impeccable/review/assessment-defaults-${info.project.name}.png`,style:captureStyle,scale:'css'});
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  await page.locator('#assessment-sources-panel').screenshot({path:`.impeccable/review/assessment-defaults-dark-${info.project.name}.png`,style:captureStyle,scale:'css'});
});

test('approval failure retains the saved draft and the selected pages', async ({page}) => {
  await fixture(page,{failApproval:true});
  await addSource(page);
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Save & approve assessment sources',exact:true}).click();
  await expect(page.locator('#assessment-sources-host [role="alert"]')).toContainText('Synthetic approval conflict');
  await expect(page.locator('#assessment-pages-0')).toHaveValue('2-3');
  await expect(page.locator('#assessment-sources-host')).toContainText('Approval requested');
  await expect(page.locator('#assessment-sources-host')).not.toContainText('Active default v1');
});

test('cancelled assessment navigation preserves dirty defaults; invalid pages do not send writes', async ({page}) => {
  const writes = await fixture(page);
  await addSource(page);
  page.once('dialog',d=>d.dismiss());
  await page.locator('#rubric-exam').selectOption('e2');
  await expect(page.locator('#rubric-exam')).toHaveValue('e');
  await expect(page.locator('#assessment-pages-0')).toHaveValue('2-3');
  await page.locator('#assessment-pages-0').fill('5');
  await page.getByRole('button',{name:'Save assessment source draft',exact:true}).click();
  await expect(page.locator('#assessment-sources-host [role="alert"]')).toContainText('between 1 and 4');
  expect(writes).toHaveLength(0);
});

test('an approved inheritance choice does not send question-specific bindings', async ({page}) => {
  await fixture(page);
  await page.locator('[data-rubric-panel="sources"] > summary').click();
  await page.locator('#source-retrieval-mode').selectOption('inherit');
  await expect(page.locator('[data-source-binding]')).toHaveCount(0);
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Save & approve sources',exact:true}).click();
  await expect(page.locator('#course-material-panel')).toContainText('Sources approved');
});

test('missing default-table upgrade does not hide existing question rubrics', async ({page}) => {
  await fixture(page,{missingUpgrade:true});
  await expect(page.locator('#assessment-sources-host [role="alert"]')).toContainText('upgrade_assessment_sources.py');
  await expect(page.locator('#rubric-workspace')).toContainText('Calculate work');
});

test('editing an approved default immediately reports unsaved changes', async ({page}) => {
  await fixture(page); await addSource(page);
  page.once('dialog',d=>d.accept()); await page.getByRole('button',{name:'Save & approve assessment sources',exact:true}).click();
  await expect(page.locator('[data-default-save-state]')).toContainText('Assessment sources approved');
  await page.locator('#assessment-pages-0').fill('1, 4');
  await expect(page.locator('[data-default-save-state]')).toHaveText('Unsaved assessment-source changes');
  await expect(page.locator('#assessment-pages-0')).toHaveValue('1, 4');
});

test('confirmed approval stays confirmed when the subsequent refresh fails', async ({page}) => {
  await fixture(page); await addSource(page);
  await page.route('**/api/exams/e/material-scopes',route=>route.request().method()==='GET' ? route.fulfill({status:503,json:{detail:'Synthetic refresh failure'}}) : route.fallback());
  page.once('dialog',d=>d.accept()); await page.getByRole('button',{name:'Save & approve assessment sources',exact:true}).click();
  await expect(page.locator('#assessment-sources-host [role="alert"]')).toContainText('Approval confirmed');
  await expect(page.locator('#assessment-sources-host [role="alert"]')).not.toContainText('not active yet');
});

test('question exceptions refresh without discarding an unsaved assessment source selection', async ({page}) => {
  await fixture(page); await addSource(page);
  await page.getByText('Question exceptions and inheritance',{exact:true}).click();
  await page.locator('[data-rubric-panel="sources"] > summary').click();
  await page.locator('#source-retrieval-mode').selectOption('disabled');
  page.once('dialog',d=>d.accept()); await page.getByRole('button',{name:'Save & approve sources',exact:true}).click();
  await expect(page.locator('[data-default-summary]')).toContainText('approved question exception (disabled)');
  await expect(page.locator('#assessment-pages-0')).toHaveValue('2-3');
  await expect(page.locator('[data-default-save-state]')).toContainText('Unsaved');
});
