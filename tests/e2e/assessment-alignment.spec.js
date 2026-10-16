const {test,expect}=require('@playwright/test');

async function fixture(page){
  const exams=[
    'Synthetic grading test',
    'Synthetic source questions pilot',
    'Synthetic exams',
    'Synthetic database systems midterm — Spring term',
    'Synthetic Mathematics: Discrete Structures — Comprehensive Final Assignment (Autumn Term)',
  ].map((title,i)=>({id:`exam-${i}`,course_id:'synthetic-course',course_code:`TEST${i+1}`,title,submission_count:i}));
  await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname.replace('/api','');
    if(path.endsWith('/duplicate'))return route.fulfill({status:422,json:{detail:'Synthetic duplicate rejection'}});
    const body=path==='/auth/me'?{id:'synthetic-instructor',role:'teacher'}:path==='/exams'?exams:path==='/courses'?[{id:'synthetic-course',course_code:'TEST',title:'Synthetic course'}]:[];
    return route.fulfill({json:body});
  });
  await page.goto('/app/assessments.html');await expect(page.locator('.manager-row')).toHaveCount(exams.length);
}

async function aligned(page){
  const metrics=await page.locator('.manager-row').evaluateAll(rows=>rows.map(row=>{
    const [text,duplicate,open]=[...row.children].map(el=>el.getBoundingClientRect());
    return {text,duplicate,open,rtl:getComputedStyle(row).direction==='rtl',mobile:innerWidth<=700};
  }));
  for(const column of ['duplicate','open']){
    expect(Math.max(...metrics.map(m=>m[column].x))-Math.min(...metrics.map(m=>m[column].x))).toBeLessThan(1);
    expect(Math.max(...metrics.map(m=>m[column].width))-Math.min(...metrics.map(m=>m[column].width))).toBeLessThan(1);
  }
  for(const m of metrics){
    if(m.mobile)expect(m.duplicate.y).toBeGreaterThanOrEqual(m.text.bottom);
    else if(m.rtl)expect(m.open.right).toBeLessThanOrEqual(m.duplicate.x);
    else {expect(m.text.right).toBeLessThanOrEqual(m.duplicate.x);expect(m.duplicate.right).toBeLessThanOrEqual(m.open.x);}
    expect(Math.abs(m.duplicate.y-m.open.y)).toBeLessThan(1);
  }
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
}

test('assessment actions stay aligned for different title lengths in both themes and RTL',async({page},info)=>{
  await fixture(page);await aligned(page);
  await page.screenshot({path:`.impeccable/review/assessment-alignment-light-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-theme').click();await aligned(page);
  await page.screenshot({path:`.impeccable/review/assessment-alignment-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');await aligned(page);
  await page.screenshot({path:`.impeccable/review/assessment-alignment-rtl-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});

test('alignment survives filtering, rejected duplication and unsaved assessment edits',async({page})=>{
  await fixture(page);
  await page.locator('#manager-search').fill('mathematics');await expect(page.locator('.manager-row')).toHaveCount(1);await aligned(page);
  await expect(page.locator('.manager-row>a')).toHaveAttribute('href','grading.html?exam_id=exam-4');
  page.once('dialog',dialog=>dialog.accept('Synthetic copied assessment'));await page.locator('[data-duplicate]').click();
  await expect(page.locator('#manager-status')).toContainText('Synthetic duplicate rejection');await aligned(page);
  await page.locator('#manager-search').fill('');await expect(page.locator('.manager-row')).toHaveCount(5);await aligned(page);
  await page.locator('#open-creation').click();await page.locator('#manager-title').fill('Synthetic unsaved assessment');
  page.once('dialog',dialog=>dialog.dismiss());await page.locator('.manager-row>a').first().click();
  await expect(page).toHaveURL(/assessments.html/);await expect(page.locator('#manager-title')).toHaveValue('Synthetic unsaved assessment');
});
