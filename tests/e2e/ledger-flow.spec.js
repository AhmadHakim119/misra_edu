const {test,expect}=require('@playwright/test');
async function fixture(page,{preflightFails=false}={}){
  const calls=[];let name='Synthetic A',number='TEST1';const student=()=>({id:'s',exam_id:'e',page_count:1,extracted_student_name:name,extracted_student_number:number});await page.route('**/api/**',async route=>{const req=route.request(),p=new URL(req.url()).pathname.replace('/api','');calls.push({p,method:req.method()});let body={};
    if(p==='/auth/me')body={id:'u',full_name:'Synthetic instructor',email:'synthetic@example.edu',role:'teacher'};
    else if(p==='/exams')body=[{id:'e',course_id:'c',title:'Synthetic physics assessment',course_code:'TEST',submission_count:1}];
    else if(p==='/courses')body=[{id:'c',course_code:'TEST',title:'Synthetic physics'}];
    else if(p==='/jobs')body={items:[]};
    else if(p==='/submissions')body=[{id:'s',exam_id:'e',extracted_student_name:'Synthetic A',extracted_student_number:'TEST1',page_count:1,readiness:{bulk_grading_allowed:true},grading_summary:{complete:true,recorded_score:0,max_score:2,review_count:0}}];
    else if(p==='/results/s')body={submission:student(),answers:[{id:'a',question_id:'q',score:0,max_score:2,needs_review:false,raw_ocr_text:'W = F + d',reasoning:'The formula does not multiply force and displacement.',grading_raw_response:{grading_run_id:'r',grading_package:{rubric:{criteria:[{id:'formula',title:'Correct work formula',description:'Use W = Fd'}]},answer_key:{reference_text:'W = Fd'},policy:{}}},criteria_scores:[{criterion_id:'formula',points_earned:0,max_points:2,feedback:'The work formula multiplies force and displacement.'}]}]};
    else if(p==='/submissions/s/extraction-review')body={submission:student(),questions:[{question:{id:'q',question_number:'1',question_text:'State the formula for work when force and displacement have the same direction.',max_score:2},sources:[{id:'seg',page_index:0,extracted_text:'W = F + d',ocr_segment:{}}],mapping_flags:[]}],readiness:{bulk_grading_allowed:true}};
    else if(p.endsWith('/metadata')){name=req.postDataJSON().student_name;number=req.postDataJSON().student_number;body={submission:student()};}
    else if(p.includes('/pages/'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="550" height="700"><rect width="550" height="700" fill="white"/><text x="40" y="50" font-size="18">Synthetic full paper</text><text x="40" y="200" font-size="18">Question 1: W = F + d</text></svg>'});
    else if(p.endsWith('/source-locations'))body={sources:{}};
    else if(p.endsWith('/material-scopes'))body={versions:[],questions:[]};
    else if(p.endsWith('/materials')||p.startsWith('/instructor-preference-'))body=[];
    else if(p.endsWith('/preflight')){if(preflightFails)return route.fulfill({status:503,json:{detail:'Synthetic preflight outage'}});body={grade_column:'Synthetic assessment [Total Pts: 2]',rows:[{submission_id:'s',student_name:'Synthetic A',username:'TEST1',score:0,max_score:2,issues:[]},{submission_id:'x',student_name:'Synthetic B',username:null,score:1,max_score:2,issues:[{code:'missing_identifier',blocking:true,message:'Student number is missing.'}]}]};}
    else if(p.endsWith('/grades.csv'))return route.fulfill({contentType:'text/csv',headers:{'content-disposition':'attachment; filename="synthetic.csv"','access-control-expose-headers':'Content-Disposition'},body:'Username,Grade\nTEST1,0\n'});
    else if(p.endsWith('/setup-readiness'))body={ready:true,questions:[],message:'Setup checked.'};
    else if(p==='/auth/login')body={user:{id:'u'}};
    else if(p==='/auth/forgot-password')body={message:'If an account exists, we sent a reset link.'};
    else if(p==='/auth/reset-password'||p==='/auth/change-password')body={};
    await route.fulfill({json:body});});return calls;
}
test('start is a clear paper list; selected paper enters focused mode with the real logo',async({page},info)=>{
  await fixture(page);await page.goto('/app/index.html?exam_id=e');await expect(page.locator('#paper-list')).toContainText('Synthetic A');await expect(page.locator('.evidence-panel')).toBeHidden();await expect(page.locator('#next-action')).toHaveText('Check export');await expect(page.locator('.logo-light')).toHaveAttribute('src','../assets/logo-transparent.png');
  await page.locator('[data-paper="s"]').click();await expect(page.locator('#paper-picker')).not.toHaveAttribute('open','');await expect(page.locator('.evidence-panel')).toBeVisible();await page.locator('#toggle-assessments').click();await expect(page.locator('#assessment-index')).toBeHidden();await page.locator('#papers-tab').click();await expect(page.locator('#paper-picker')).toHaveAttribute('open','');
  await page.locator('#paper-picker>summary').click();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/ledger-focus-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/ledger-focus-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});
test('native export makes zero marks and exclusions clear and downloads once',async({page},info)=>{
  const calls=await fixture(page);await page.goto('/app/index.html?exam_id=e');await page.locator('#export-link').click();await expect(page.locator('#native-export-checks')).toContainText('1 included · 1 excluded');await expect(page.locator('#native-export-checks')).toContainText('0 / 2');await expect(page.locator('#native-export-note')).toContainText('Username');const download=page.waitForEvent('download');await page.locator('#native-export-csv').click();expect((await download).suggestedFilename()).toBe('synthetic.csv');expect(calls.filter(c=>c.p.endsWith('/grades.csv'))).toHaveLength(1);await page.locator('#native-export-profile').selectOption('generic');await expect(page.locator('#native-export-checks')).toContainText('2 included · 0 excluded');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();const action=await page.locator('#native-export-checks [data-open-saved-paper="x"]').boundingBox();expect(action.x).toBeGreaterThanOrEqual(0);expect(action.x+action.width).toBeLessThanOrEqual((await page.viewportSize()).width);await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/ledger-export-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/ledger-export-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});
test('preflight outage keeps CSV closed and provides a recovery',async({page})=>{await fixture(page,{preflightFails:true});await page.goto('/app/index.html?exam_id=e&view=export');await expect(page.locator('#native-export-checks')).toContainText('Synthetic preflight outage');await expect(page.locator('#native-export-csv')).toBeDisabled();await expect(page.locator('#refresh-export')).toBeEnabled();});
test('native sign in returns to native workspace and reset does not expose accounts',async({page},info)=>{
  await fixture(page);await page.goto('/app/login.html');await page.locator('#login-email').fill('synthetic@example.edu');await page.locator('#login-password').fill('Synthetic test password');await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page).toHaveURL(/\/app\/dashboard.html/);await page.goto('/app/forgot-password.html');await page.locator('#forgot-email').fill('synthetic@example.edu');await page.getByRole('button',{name:'Send reset link'}).click();await expect(page.locator('[data-forgot-confirmation]')).toContainText('If an account exists');await page.goto('/app/login.html');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:`.impeccable/review/ledger-signin-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.evaluate(()=>MisraTheme.set('dark'));await page.screenshot({path:`.impeccable/review/ledger-signin-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});
test('native assessment list opens exact assessment, and settings retain optional preferences',async({page},info)=>{
  await fixture(page);await page.goto('/app/assessments.html');await expect(page.locator('#manager-list')).toContainText('Synthetic physics assessment');await expect(page.getByRole('link',{name:'Open assessment',exact:true})).toHaveAttribute('href','grading.html?exam_id=e');await page.locator('#open-creation').click();await expect(page.locator('#manager-course')).toHaveValue('c');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:`.impeccable/review/ledger-manager-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.evaluate(()=>MisraTheme.set('dark'));await page.screenshot({path:`.impeccable/review/ledger-manager-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.goto('/app/account.html');await expect(page.locator('#native-account-facts')).toContainText('Synthetic instructor');await page.locator('[data-theme-option][value=light]').check();await page.screenshot({path:`.impeccable/review/ledger-settings-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('[data-theme-option][value=dark]').check();await expect(page.locator('html')).toHaveAttribute('data-theme','dark');await expect(page.locator('#marking-preferences')).toBeHidden();await expect(page.locator('#native-settings-status')).toContainText('Theme saved');await page.screenshot({path:`.impeccable/review/ledger-settings-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});
test('identity can be corrected beside the paper without losing an unsaved grade',async({page})=>{
  await fixture(page);await page.goto('/app/index.html?exam_id=e&submission_id=s');await expect(page.locator('#instructor-score')).toHaveValue('0');await page.locator('#instructor-score').fill('1');await page.locator('.identity-inline>summary').click();await page.locator('#native-student-name').fill('Synthetic corrected');await page.locator('#native-student-number').fill('TEST2');await page.getByRole('button',{name:'Save student details',exact:true}).click();await expect(page.locator('#identity-save-state')).toContainText('saved');await expect(page.locator('#instructor-score')).toHaveValue('1');await expect(page.locator('#save-status')).toContainText('Unsaved');await page.locator('#export-link').click();await expect(page.locator('#error')).toContainText('unsaved edits');await expect(page.locator('#ledger-export')).toBeHidden();
});
test('cancelled sign out preserves assessment entries and never calls logout',async({page})=>{
  const calls=await fixture(page);await page.goto('/app/assessments.html');await page.locator('#open-creation').click();await page.locator('#manager-title').fill('Synthetic unsaved assessment');page.once('dialog',dialog=>dialog.dismiss());await page.locator('#native-sign-out').click();await expect(page.locator('#manager-title')).toHaveValue('Synthetic unsaved assessment');await expect(page).toHaveURL(/assessments.html/);expect(calls.filter(c=>c.p==='/auth/logout')).toHaveLength(0);
});
test('pending assessment creation blocks sign out before session invalidation',async({page})=>{
  const calls=await fixture(page);let release,started;const gate=new Promise(resolve=>release=resolve),saving=new Promise(resolve=>started=resolve);await page.route('**/api/exams',async(route)=>{if(route.request().method()!=='POST')return route.fallback();started();await gate;await route.fulfill({status:422,json:{detail:'Synthetic validation error'}});});await page.goto('/app/assessments.html');await page.locator('#open-creation').click();await page.locator('#manager-title').fill('Synthetic pending assessment');await page.getByRole('button',{name:'Create & prepare assessment'}).click();await saving;await expect(page.locator('#native-sign-out')).toBeDisabled();await page.evaluate(()=>document.getElementById('native-sign-out').dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true})));expect(calls.filter(c=>c.p==='/auth/logout')).toHaveLength(0);release();await expect(page.locator('#manager-status')).toContainText('Synthetic validation error');await expect(page.locator('#manager-title')).toHaveValue('Synthetic pending assessment');
});

test('assessment create link waits for courses and keeps optional course creation closed',async({page},info)=>{
  await fixture(page);
  let release,started;
  const gate=new Promise(resolve=>release=resolve),loading=new Promise(resolve=>started=resolve);
  await page.route('**/api/courses',async route=>{
    started();await gate;await route.fulfill({json:[{id:'c',course_code:'TEST',title:'Synthetic physics'}]});
  });
  await page.goto('/app/assessments.html?create=1');await loading;
  await expect(page.locator('#open-creation')).toBeDisabled();
  await expect(page.locator('#create-course')).toBeHidden();
  release();await expect(page.locator('#creation')).toBeVisible();
  await expect(page.locator('#manager-course')).toHaveValue('c');
  await expect(page.locator('#create-course')).toBeHidden();
  await page.locator('#manager-title').fill('Synthetic grading test');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:`.impeccable/review/assessment-create-light-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.evaluate(()=>MisraTheme.set('dark'));
  await page.screenshot({path:`.impeccable/review/assessment-create-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#add-course').click();await expect(page.locator('#create-course')).toBeVisible();
  await page.locator('#manager-code').fill('DRAFT');
  page.once('dialog',dialog=>dialog.dismiss());await page.locator('#close-creation').click();
  await expect(page.locator('#manager-code')).toHaveValue('DRAFT');
  page.once('dialog',dialog=>dialog.accept());await page.locator('#close-creation').click();
  await page.locator('#open-creation').click();
  await expect(page.locator('#create-course')).toBeHidden();
  await expect(page.locator('#manager-title')).toBeEmpty();
});

test('assessment creation exposes course setup only when no saved courses exist',async({page})=>{
  await fixture(page);await page.route('**/api/courses',route=>route.fulfill({json:[]}));
  await page.goto('/app/assessments.html?create=1');
  await expect(page.locator('#create-course')).toBeVisible();
  await expect(page.locator('#manager-course')).toHaveValue('');
  await expect(page.locator('#manager-title')).toBeFocused();
});

test('failed course creation retains both course and assessment entries',async({page})=>{
  await fixture(page);
  let payload;
  await page.route('**/api/courses',route=>{
    if(route.request().method()!=='POST')return route.fallback();
    payload=route.request().postDataJSON();
    return route.fulfill({status:422,json:{detail:'Synthetic course validation error'}});
  });
  await page.goto('/app/assessments.html?create=1');
  await page.locator('#manager-title').fill('Synthetic grading test');
  await page.locator('#add-course').click();
  await page.locator('#manager-code').fill('TEST2');
  await page.locator('#manager-course-title').fill('Synthetic course draft');
  await page.locator('#manager-instructor').fill('Synthetic instructor');
  await page.getByRole('button',{name:'Save course',exact:true}).click();
  await expect(page.locator('#manager-status')).toContainText('Synthetic course validation error');
  await expect(page.locator('#manager-title')).toHaveValue('Synthetic grading test');
  await expect(page.locator('#manager-code')).toHaveValue('TEST2');
  await expect(page.locator('#manager-course-title')).toHaveValue('Synthetic course draft');
  await expect(page.locator('#create-course')).toBeVisible();
  await expect(page.getByRole('button',{name:'Save course',exact:true})).toBeEnabled();
  expect(payload).toEqual({course_code:'TEST2',term:null,title:'Synthetic course draft',instructor_name:'Synthetic instructor'});
});

test('assessment creation sends selected course and entered title before locking controls',async({page})=>{
  await fixture(page);let payload;
  await page.route('**/api/exams',route=>{
    if(route.request().method()!=='POST')return route.fallback();
    payload=route.request().postDataJSON();
    return route.fulfill({status:422,json:{detail:'Synthetic assessment validation error'}});
  });
  await page.goto('/app/assessments.html?create=1');
  await page.locator('#manager-title').fill('Synthetic grading test');
  await page.getByRole('button',{name:'Create & prepare assessment',exact:true}).click();
  await expect(page.locator('#manager-status')).toContainText('Synthetic assessment validation error');
  expect(payload).toEqual({course_id:'c',title:'Synthetic grading test',language:'en'});
  await expect(page.locator('#manager-title')).toHaveValue('Synthetic grading test');
  await expect(page.getByRole('button',{name:'Create & prepare assessment',exact:true})).toBeEnabled();
});

test('assessment validation names rejected fields and retains unsaved entries',async({page})=>{
  await fixture(page);
  await page.route('**/api/exams',route=>route.request().method()==='POST'
    ? route.fulfill({status:422,json:{detail:[{type:'missing',loc:['body','course_id'],msg:'Field required'},{type:'string_too_short',loc:['body','title'],msg:'String should have at least 1 character',input:''}]}})
    : route.fallback());
  await page.goto('/app/assessments.html?create=1');
  await page.locator('#manager-title').fill('Synthetic grading test');
  await page.getByRole('button',{name:'Create & prepare assessment',exact:true}).click();
  await expect(page.locator('#manager-status')).toContainText('Course: This field was not sent. Refresh this page and try again.');
  await expect(page.locator('#manager-status')).toContainText('Title: String should have at least 1 character');
  await expect(page.locator('#manager-status')).not.toContainText('Request failed (422)');
  await expect(page.locator('#manager-title')).toHaveValue('Synthetic grading test');
  await expect(page.getByRole('button',{name:'Create & prepare assessment',exact:true})).toBeEnabled();
});
