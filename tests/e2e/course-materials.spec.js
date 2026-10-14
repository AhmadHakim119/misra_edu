const { test, expect } = require('@playwright/test');

async function fixture(page, { fail = false, draft = false } = {}) {
  const writes = [];
  const rubric = {schema_version:2,max_score:4,criteria:[{id:'work',title:'Work against gravity',description:'Use W = mgh',points:4}],policy:{grading_approach:'balanced'}};
  let material = {id:'m',course_id:'c',title:'Synthetic work and energy chapter',versions:[{id:'v',version_number:1,status:draft ? 'draft' : 'approved',ingestion_status:'ready',page_count:4,approved_page_indices:[0,1,2,3],media_type:'text/plain'}]};
  let scopes = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api',''), method = route.request().method(); let body = {};
    if (path === '/auth/me') body = {id:'u',full_name:'Synthetic Instructor',role:'teacher'};
    else if (path === '/health') body = {status:'ok'};
    else if (path === '/jobs') body = {items:[],active_count:0};
    else if (path === '/exams') body = [{id:'e',course_id:'c',title:'Synthetic assessment'},{id:'e2',course_id:'c2',title:'Second assessment'}];
    else if (path.endsWith('/questions')) body = [{id:'q',question_number:'1',question_text:'Calculate work lifting a mass.',max_score:4}];
    else if (path.endsWith('/setup-imports') || path.endsWith('/answer-key-versions')) body = [];
    else if (path.endsWith('/setup-readiness')) body = {ready:true,question_count:1,rubric_count:1,questions:[]};
    else if (path.endsWith('/rubric')) body = {rubric,rubric_version_id:'r'};
    else if (path.endsWith('/rubric-versions')) body = [{id:'r',version_number:1,status:'approved',rubric_json:rubric}];
    else if (path.endsWith('/grading-policy')) body = {mode:'adaptive'};
    else if (path.endsWith('/materials')) body = [material];
    else if (path.endsWith('/pages') && method === 'GET') body = {version:material.versions[0],items:[{page_index:0,text:'The work is W = mgh.',text_sha256:'a'.repeat(64),printed_page_label:'196',chunks:[{id:'chunk',char_start:0,char_end:20}]}]};
    else if (path.endsWith('/approve') && path.includes('/materials/')) { material.versions[0].status = 'approved'; material.versions[0].approved_page_indices = route.request().postDataJSON().page_indices; body = material.versions[0]; }
    else if (path.endsWith('/material-scopes')) {
      if (method === 'GET') body = scopes;
      else { writes.push(route.request().postDataJSON()); if (fail) return route.fulfill({status:503,json:{detail:'Synthetic temporary save failure'}});
        body = {...writes.at(-1),id:'scope',version_number:1,status:'draft'}; scopes = [body]; }
    } else if (path.includes('/material-scopes/') && path.endsWith('/approve')) { scopes[0].status = 'approved'; body = scopes[0]; }
    else if (path.endsWith('/material-retrieval-preview')) body = {status:'retrieved',passages:[{id:'material:chunk',title:material.title,material_version_number:1,page_index:1,printed_page_label:'197',text:'W = mgh.',criterion_ids:['work'],selection:'bm25'}]};
    await route.fulfill({json:body});
  });
  await page.goto('/pages/rubric-studio.html?exam_id=e');
  await page.locator('[data-rubric-panel="sources"] > summary').click();
  await expect(page.getByRole('heading',{name:'Sources for this question'})).toBeVisible();
  return writes;
}

test('reference pages use one-based UI; draft and approval are separate; retrieval is previewed',async ({page},info) => {
  const writes = await fixture(page);
  await page.getByRole('button',{name:'Add reference',exact:true}).click();
  await page.locator('#source-version-0').selectOption('v');
  await page.locator('#source-pages-0').fill('2-3');
  await page.locator('#source-criterion-0').selectOption('work');
  await page.getByRole('button',{name:'Save source draft',exact:true}).click();
  await expect(page.locator('#course-material-panel')).toContainText('Source draft saved');
  expect(writes[0]).toEqual({mode:'required',bindings:[{version_id:'v',page_indices:[1,2],criterion_id:'work',chunk_ids:[]}]});
  await expect(page.getByRole('button',{name:'Preview active retrieval'})).toBeDisabled();
  page.once('dialog',d => d.accept());
  await page.getByRole('button',{name:'Save & approve sources',exact:true}).click();
  await expect(page.getByRole('button',{name:'Preview active retrieval'})).toBeEnabled();
  await page.getByRole('button',{name:'Preview active retrieval'}).click();
  await expect(page.getByRole('heading',{name:'What the next grading run can retrieve'})).toBeVisible();
  await page.evaluate(() => document.documentElement.dataset.theme = 'dark');
  await page.locator('[data-rubric-panel="sources"]').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  const captureStyle = '.workspace-topbar, .workspace-header, .workspace-sidebar, .rubric-toolbar, .skip-link { visibility: hidden !important; }';
  await page.locator('[data-rubric-panel="sources"]').screenshot({path:`.impeccable/review/course-sources-panel-${info.project.name}.png`,scale:'css',style:captureStyle});
  await page.evaluate(() => document.documentElement.dataset.theme = 'light');
  await page.locator('[data-rubric-panel="sources"]').screenshot({path:`.impeccable/review/course-sources-light-${info.project.name}.png`,scale:'css',style:captureStyle});
});

test('failed source save keeps typed pages; navigation cancellation and remove work',async ({page}) => {
  await fixture(page,{fail:true});
  await page.getByRole('button',{name:'Add reference',exact:true}).click();
  await page.locator('#source-version-0').selectOption('v');
  await page.locator('#source-pages-0').fill('2, 4');
  await page.getByRole('button',{name:'Save source draft',exact:true}).click();
  await expect(page.locator('#course-material-panel [role="alert"]')).toContainText('Synthetic temporary save failure');
  await expect(page.locator('#source-pages-0')).toHaveValue('2, 4');
  page.once('dialog',d => d.dismiss()); await page.locator('#rubric-exam').selectOption('e2');
  await expect(page.locator('#rubric-exam')).toHaveValue('e');
  await page.getByRole('button',{name:'Remove reference',exact:true}).click();
  await expect(page.locator('[data-source-binding]')).toHaveCount(0);
});

test('source approval requires reviewed pages, and approved content becomes read-only',async ({page}) => {
  await fixture(page,{draft:true});
  await page.locator('.material-library > summary').click();
  await page.getByRole('button',{name:'Review v1'}).click();
  await expect(page.locator('#material-page-text')).toHaveValue('The work is W = mgh.');
  await page.locator('#material-approved-pages').fill('1, 3');
  await page.getByRole('button',{name:'Approve selected source pages'}).click();
  await expect(page.locator('#material-page-text')).toBeEditable();
  await page.getByLabel('I checked these pages against the original').check();
  await page.getByRole('button',{name:'Approve selected source pages'}).click();
  await expect(page.locator('#material-page-text')).not.toBeEditable();
  await expect(page.locator('.material-page-review')).toContainText('Approved document pages: 1, 3');
});

test('failed material approval retains pages and confirmation with navigation protection',async ({page}) => {
  await fixture(page,{draft:true});
  await page.route('**/api/materials/m/versions/v/approve',route => route.fulfill({status:409,json:{detail:'Synthetic approval conflict'}}));
  await page.locator('.material-library > summary').click();
  await page.getByRole('button',{name:'Review v1'}).click();
  await page.locator('#material-approved-pages').fill('2-3');
  await page.getByLabel('I checked these pages against the original').check();
  await page.getByRole('button',{name:'Approve selected source pages'}).click();
  await expect(page.locator('#course-material-panel [role="alert"]')).toContainText('Synthetic approval conflict');
  await expect(page.locator('#material-approved-pages')).toHaveValue('2-3');
  await expect(page.getByLabel('I checked these pages against the original')).toBeChecked();
  page.once('dialog',d => d.dismiss()); await page.locator('#rubric-exam').selectOption('e2');
  await expect(page.locator('#rubric-exam')).toHaveValue('e');
});

test('failed replacement upload retains selected PDF and protects it from navigation',async ({page}) => {
  await fixture(page);
  await page.route('**/api/materials/m/versions',route => route.fulfill({status:503,json:{detail:'Synthetic queue outage'}}));
  await page.locator('.material-library > summary').click();
  await page.getByText('Upload a new version',{exact:true}).click();
  await page.locator('[data-revision-form] input').setInputFiles({name:'synthetic-replacement.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF synthetic mock')});
  await page.getByRole('button',{name:'Upload draft version'}).click();
  await expect(page.locator('#course-material-panel [role="alert"]')).toContainText('Synthetic queue outage');
  expect(await page.locator('[data-revision-form] input').evaluate(el => el.files[0]?.name)).toBe('synthetic-replacement.pdf');
  page.once('dialog',d => d.dismiss()); await page.locator('#rubric-exam').selectOption('e2');
  await expect(page.locator('#rubric-exam')).toHaveValue('e');
});

test('failed next-page request retries the same page, never skips ahead',async ({page}) => {
  await fixture(page,{draft:true}); const offsets = []; let failed = false;
  await page.route('**/api/materials/m/versions/v/pages?**',async route => {
    const index = Number(new URL(route.request().url()).searchParams.get('offset')); offsets.push(index);
    if (index === 1 && !failed) { failed = true; return route.fulfill({status:503,json:{detail:'Synthetic page connection failure'}}); }
    await route.fulfill({json:{version:{id:'v',version_number:1,status:'draft',ingestion_status:'ready',page_count:4,media_type:'text/plain'},items:[{page_index:index,text:`Synthetic page ${index + 1}`,text_sha256:'a'.repeat(64),chunks:[]}]}});
  });
  await page.locator('.material-library > summary').click(); await page.getByRole('button',{name:'Review v1'}).click();
  await expect(page.locator('#material-page-text')).toHaveValue('Synthetic page 1');
  await page.getByRole('button',{name:'Next page',exact:true}).click();
  await expect(page.locator('#course-material-panel [role="alert"]')).toContainText('Synthetic page connection failure');
  await expect(page.locator('#material-page-text')).toHaveValue('Synthetic page 1');
  await page.getByRole('button',{name:'Next page',exact:true}).click();
  await expect(page.locator('#material-page-text')).toHaveValue('Synthetic page 2');
  expect(offsets).toEqual([0,1,1]);
});
