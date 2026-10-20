const {test,expect}=require('@playwright/test');
const unavailable='Selected free model is not in the current catalog. Choose another explicit free model.';
async function fixture(page){
  const state={status:'retrying',error:unavailable,writes:[]};
  await page.route('**/api/**',route=>{
    const request=route.request(),path=new URL(request.url()).pathname.replace('/api','');let body=[];
    if(path==='/auth/me')body={id:'synthetic',role:'teacher',full_name:'Synthetic instructor'};
    else if(path==='/jobs')body={active_count:state.status==='retrying'?1:0,items:[{id:'job',job_type:'grade_submission',exam_id:'exam',submission_id:'paper',status:state.status,progress_percent:0,progress_message:state.status==='retrying'?'Failed; waiting to retry':'Retry limit reached',error_message:state.error}]};
    else if(path==='/jobs/job/retry'){state.writes.push(path);state.status='retrying';body={id:'job',status:'retrying'};}
    return route.fulfill({json:body});
  });
  await page.goto('/app/activity.html?exam_id=exam');return state;
}

test('activity status visual evidence',async({page},info)=>{
  const state=await fixture(page);state.status='failed';await page.locator('#activity-refresh').click();
  await expect(page.locator('#activity-host')).toContainText(process.env.MISRA_CAPTURE_PHASE==='before'?'grade':'AI grading');
  const phase=process.env.MISRA_CAPTURE_PHASE||'after';
  for(const variant of ['light','dark','rtl']){
    if(variant==='dark')await page.locator('#app-theme').click();if(variant==='rtl')await page.locator('#app-language').click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.screenshot({path:'.impeccable/review/grading-job-status-'+phase+'-'+variant+'-'+info.project.name+'.png',fullPage:true,animations:'disabled'});
  }
});

test('invalid AI citations are not classified as an unavailable model',async({page},info)=>{
  const state=await fixture(page);state.status='failed';state.error='AI grading response failed validation: The model still supplied missing or invalid evidence citations after one correction attempt. A criterion cites an unavailable answer-key or course-source reference. No grade was saved for this answer.';
  await page.locator('#activity-refresh').click();const host=page.locator('#activity-host');
  await expect(host).toContainText('The AI response failed validation');await expect(host).not.toContainText('The grading model is unavailable');
  expect(state.writes).toHaveLength(0);
  for(const variant of ['light','dark','rtl']){
    if(variant==='dark')await page.locator('#app-theme').click();if(variant==='rtl')await page.locator('#app-language').click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.screenshot({path:'.impeccable/review/citation-failure-after-'+variant+'-'+info.project.name+'.png',fullPage:true,animations:'disabled'});
  }
});

test('automatic grading retries show processing and terminal failures show a useful reason',async({page})=>{
  const state=await fixture(page),host=page.locator('#activity-host');
  await expect(host).toContainText('Processing…');await expect(host).not.toContainText('Failed; waiting');await expect(host).not.toContainText('retrying');
  await expect(host.locator('[data-retry-job]')).toHaveCount(0);expect(state.writes).toHaveLength(0);
  state.status='failed';await page.locator('#activity-refresh').click();
  await expect(host).toContainText('Grading couldn’t finish');await expect(host).toContainText('The grading model is unavailable');
  await expect(host).not.toContainText('Retry limit reached');await expect(host.locator('progress')).toHaveCount(0);
  await host.locator('.job-error-details summary').click();await expect(host.locator('.job-error-details')).toContainText(unavailable);
  await page.getByRole('button',{name:'Retry safely',exact:true}).click();await expect(host).toContainText('Processing…');expect(state.writes).toEqual(['/jobs/job/retry']);
});

test('terminal grading failure is never displayed as active processing and translates to Arabic',async({page})=>{
  const state=await fixture(page);state.status='failed';await page.locator('#activity-refresh').click();await page.locator('#app-language').click();
  await expect(page.locator('#activity-host')).toContainText('تعذر إكمال التصحيح');await expect(page.locator('#activity-host')).not.toContainText('جارٍ المعالجة');
  expect(state.writes).toHaveLength(0);await expect(page.locator('#activity-host progress')).toHaveCount(0);
});
