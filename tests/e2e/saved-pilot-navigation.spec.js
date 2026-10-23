const {test,expect}=require('@playwright/test');

async function fixture(page){
  const state={failStudy:false,writes:[]};
  const review={needs_review:true,flagged_answer_count:1,unresolved_answer_count:0,reasons:[{code:'criterion_uncertainty',count:1}]};
  const papers=['F23','F23','F24','F25'].map((year,i)=>({paper_id:'p'+i,label:year+' synthetic paper '+i,exam_version:year,exam_id:year,answer_count:1,total:{point_proposal:2,max_score:4},review}));
  const exams=['F23','F24','F25'].map(id=>({id,title:`Physics ${id} · saved pilot`,course_code:'SYN',submission_count:0}));
  exams.push({id:'live',title:'Ordinary uploaded exam',course_code:'SYN',submission_count:1});
  await page.route('https://fonts.googleapis.com/**',r=>r.abort());
  await page.route('**/api/**',route=>{
    const req=route.request(),p=new URL(req.url()).pathname;let body=[];
    if(req.method()!=='GET')state.writes.push(p);
    if(p==='/api/auth/me')body={id:'u',role:'teacher',full_name:'Synthetic instructor'};
    else if(p==='/api/auth/preferences')body={theme:'light',language:'en'};
    else if(p==='/api/jobs')body={items:[],active_count:0};
    else if(p==='/api/exams')body=exams;
    else if(p==='/api/courses')body=[{id:'c',title:'Synthetic physics',course_code:'SYN'}];
    else if(p==='/api/pilot-studies')body={items:[{study_id:'physics',title:'Synthetic physics study',paper_count:4,answer_count:4,exam_ids:['F23','F24','F25']}]};
    else if(p==='/api/pilot-studies/physics'){
      if(state.failStudy)return route.fulfill({status:409,json:{detail:'Synthetic saved-study failure'}});
      body={study_id:'physics',title:'Synthetic physics study',answer_count:4,papers,reference_comparison:[]};
    }else if(p.includes('/pages/'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="white"/><text x="40" y="100">Synthetic original page</text></svg>'});
    else if(p.startsWith('/api/pilot-studies/physics/papers/')){
      const paper=papers.find(row=>p.endsWith('/'+row.paper_id));
      body={...paper,page_count:1,answers:[{answer_id:'a'+paper.paper_id,question_id:'q',number:'1',score:2,max_score:4,needs_review:true,question_text:'Synthetic work calculation',rubric_snapshot:{criteria:[]},review_explanation:{status:'needs_review',items:[{title:'Check the calculation',reason:'The saved calculation is uncertain.',action:'Read the original page.',source:'rule_check'}]}}]};
    }
    return route.fulfill({json:body});
  });
  return state;
}

test('assessment rows show saved-paper counts and open the matching pilot exam',async({page},info)=>{
  const state=await fixture(page);await page.goto('/app/assessments.html');
  const row=page.locator('.manager-row').filter({has:page.getByRole('heading',{name:'Physics F24 · saved pilot',exact:true})});
  await expect(row).toContainText('1 saved pilot papers · 1 need review');
  await expect(row).not.toContainText('0 papers');
  await expect(row.getByRole('link',{name:'Edit marking guide'})).toHaveAttribute('href','setup.html?exam_id=F24');
  await expect(page.locator('.manager-row').filter({hasText:'Ordinary uploaded exam'}).getByRole('link',{name:'Open assessment'})).toHaveAttribute('href','grading.html?exam_id=live');
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>{MisraTheme.set(theme);window.scrollTo(0,0);},theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.screenshot({path:`.impeccable/review/saved-assessments-${theme}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  }
  await row.getByRole('link',{name:'Review saved papers'}).click();
  await expect(page.locator('#pilot-year')).toHaveValue('F24');
  await expect(page.locator('#pilot-paper option')).toHaveCount(1);
  await expect(page.locator('#pilot-status')).toContainText('1 saved papers · 1 answer slots');
  await expect(page.locator('#pilot-paper-summary')).toContainText('F24 synthetic paper');
  expect(state.writes).toEqual([]);
});

test('review queue includes saved concerns and links to the selected exam',async({page},info)=>{
  const state=await fixture(page);await page.goto('/app/reviews.html');
  await expect(page.locator('#review-count')).toContainText('4 saved pilot papers with review concerns');
  await expect(page.locator('#review-saved-pilots .record-row')).toHaveCount(3);
  await page.locator('#review-exam').selectOption('F24');
  await expect(page.locator('#review-count')).toContainText('1 saved pilot papers with review concerns');
  await expect(page.locator('#review-saved-pilots .record-row')).toHaveCount(1);
  await expect(page.locator('#review-saved-pilots')).toContainText('F24');
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>{MisraTheme.set(theme);window.scrollTo(0,0);},theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.screenshot({path:`.impeccable/review/saved-review-queue-${theme}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  }
  await page.locator('#review-saved-pilots').getByRole('link',{name:'Review saved papers'}).click();
  await expect(page.locator('#pilot-year')).toHaveValue('F24');
  await expect(page.locator('#pilot-flagged')).toBeChecked();
  await expect(page.locator('#pilot-image')).toBeVisible();
  expect(state.writes).toEqual([]);
});

test('saved-study failure stays unavailable and refresh recovers counts',async({page})=>{
  const state=await fixture(page);state.failStudy=true;await page.goto('/app/reviews.html');
  await expect(page.locator('#review-saved-pilots')).toContainText('Review count unavailable');
  await expect(page.locator('#review-count')).not.toContainText('0 saved pilot');
  state.failStudy=false;await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await expect(page.locator('#review-count')).toContainText('4 saved pilot papers with review concerns');
  expect(state.writes).toEqual([]);
});

test('a mismatched pilot exam link never opens another exams papers',async({page})=>{
  await fixture(page);await page.goto('/app/pilot.html?study_id=physics&exam_id=other');
  await expect(page.locator('#pilot-error')).toContainText('not part of the selected study');
  await expect(page.locator('#pilot-image')).toBeHidden();
  await expect(page.locator('#pilot-paper option')).toHaveCount(0);
});
