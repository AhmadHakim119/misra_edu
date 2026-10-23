const {test,expect}=require('@playwright/test');
async function auth(page){
  await page.route('https://fonts.googleapis.com/**',r=>r.abort());
  await page.route('**/api/**',async route=>{
    const p=new URL(route.request().url()).pathname;let body=[];
    if(p==='/api/auth/me')body={id:'u',role:'teacher',full_name:'Synthetic instructor',must_change_password:false};
    else if(p==='/api/auth/preferences')body={theme:'light',language:'en'};
    else if(p==='/api/jobs')body={items:[],active_count:0};
    else if(p==='/api/exams')body=[{id:'e',title:'Synthetic physics pilot',course_code:'TEST',submission_count:1}];
    else if(p==='/api/submissions')body=[{id:'s',exam_id:'e',extracted_student_name:'Synthetic paper'}];
    else if(p==='/api/review-queue')body=[{id:'a',submission_id:'s',question_id:'q',score:2,max_score:4,needs_review:true,feedback:'Check the sign.',review_explanation:{status:'needs_review',items:[{code:'numeric_credit_outside_tolerance',title:'Numerical result conflicts with awarded credit',criterion_id:'result',reason:'The saved result has the opposite sign to the cited calculation.',action:'Read the minus sign on page 2 and compare the result criterion.',source:'rule_check'}]}}];
    await route.fulfill({json:body});
  });
}
test('review screen stays readable in both themes',async({page},info)=>{
  await auth(page);await page.goto('/app/reviews.html');await expect(page.locator('#review-count')).toHaveText('1 answers awaiting review');
  for(const theme of ['light','dark']){await page.evaluate(theme=>MisraTheme.set(theme),theme);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'.impeccable/review/review-after-'+theme+'-'+info.project.name+'.png',fullPage:true});}
});
test('review queue explains a specific high-confidence conflict',async({page})=>{
  await auth(page);await page.goto('/app/reviews.html');
  await expect(page.getByText('Numerical result conflicts with awarded credit',{exact:false})).toBeVisible();
  await expect(page.getByText('Read the minus sign on page 2 and compare the result criterion.',{exact:false})).toBeVisible();
  await expect(page.getByRole('link',{name:'Review evidence & mark'})).toHaveAttribute('href',/submission_id=s/);
});

test('review controls have names and text meets AA contrast in both themes',async({page})=>{
  await auth(page);await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto('/app/reviews.html');await expect(page.locator('#review-count')).toContainText('1 answers');
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>MisraTheme.set(theme),theme);
    for(const control of await page.locator('button,select,input,textarea').all()){
      if(await control.isVisible())await expect(control).toHaveAccessibleName(/\S/);
    }
    const failures=await page.evaluate(()=>{
      const rgb=value=>(value.match(/[\d.]+/g)||[]).map(Number);
      const luminance=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
      return [...document.querySelectorAll('main h1,main h2,main h3,main p,main a,main button,main label')].flatMap(el=>{
        if(!el.getClientRects().length||!el.textContent.trim())return [];
        const style=getComputedStyle(el);if(style.opacity!=='1'||el.disabled)return [];
        let bg=[255,255,255];
        for(let parent=el;parent;parent=parent.parentElement){const c=rgb(getComputedStyle(parent).backgroundColor);if(c.length===3||c[3]===1){bg=c;break;}}
        const fg=rgb(style.color),a=luminance(fg),b=luminance(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
        const large=parseFloat(style.fontSize)>=24||(parseFloat(style.fontSize)>=18.66&&Number(style.fontWeight)>=700);
        return ratio+.01<(large?3:4.5)?[{text:el.textContent.trim().slice(0,60),ratio}]:[];
      });
    });
    expect(failures,theme+' contrast').toEqual([]);
  }
});

for(const staleFailure of [false,true])test(`review queue ignores delayed ${staleFailure?'errors':'rows'} after changing exam`,async({page})=>{
  await auth(page);
  let releaseA,startedA;
  const started=new Promise(resolve=>startedA=resolve);
  const held=new Promise(resolve=>releaseA=resolve);
  await page.route('**/api/exams',r=>r.fulfill({json:[{id:'A',title:'Exam A'},{id:'B',title:'Exam B'}]}));
  await page.route('**/api/submissions',r=>r.fulfill({json:[{id:'sA',exam_id:'A',extracted_student_name:'Synthetic A'},{id:'sB',exam_id:'B',extracted_student_name:'Synthetic B'}]}));
  await page.route('**/api/review-queue**',async route=>{
    const exam=new URL(route.request().url()).searchParams.get('exam_id');
    if(exam==='A'){startedA();await held;if(staleFailure)return route.fulfill({status:503,json:{detail:'Stale A failure'}});}
    await route.fulfill({json:exam?[{id:'a'+exam,submission_id:'s'+exam,question_id:'q',score:1,max_score:2}]:[]});
  });
  await page.goto('/app/reviews.html');await expect(page.locator('#review-count')).toContainText('0 answers');
  await page.getByLabel('Exam',{exact:true}).selectOption('A');await started;
  await expect(page.locator('#review-list')).toBeEmpty();
  await expect(page.locator('#review-list')).toHaveAttribute('aria-busy','true');
  await page.getByLabel('Exam',{exact:true}).selectOption('B');
  await expect(page.locator('#review-list')).toContainText('Synthetic B');
  const response=page.waitForResponse(r=>r.url().includes('/review-queue?exam_id=A'));
  releaseA();await (await response).finished();
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await expect(page.locator('#review-list')).toContainText('Synthetic B');
  await expect(page.locator('#review-list')).not.toContainText('Synthetic A');
  await expect(page.locator('#review-error')).toBeEmpty();
  await expect(page.locator('#review-list')).toHaveAttribute('aria-busy','false');
});

test('review queue failure clears old rows and supports keyboard retry',async({page})=>{
  await auth(page);await page.goto('/app/reviews.html');await expect(page.locator('#review-list')).toContainText('Synthetic paper');
  await page.route('**/api/review-queue**',r=>r.fulfill({status:503,json:{detail:'Synthetic queue failure'}}));
  await page.getByRole('button',{name:'Refresh',exact:true}).focus();await page.keyboard.press('Enter');
  await expect(page.locator('#review-error')).toContainText('Synthetic queue failure');
  await expect(page.locator('#review-list')).toBeEmpty();
  await page.unroute('**/api/review-queue**');
  await page.keyboard.press('Enter');await expect(page.locator('#review-list')).toContainText('Synthetic paper');
});

async function pilotFixture(page,{failPaper=false}={}){
  await auth(page);
  const review={needs_review:true,flagged_answer_count:1,unresolved_answer_count:1,reasons:[{code:'unresolved_marks',count:1}]};
  const paper={paper_id:'p',label:'Synthetic paper',exam_version:'F23',exam_id:'e',answer_count:1,total:{point_proposal:null,lower:1,upper:4,max_score:4},review};
  const answer={answer_id:'a',question_id:'q',number:'1',score:null,max_score:4,needs_review:true,question_text:'Calculate speed.',
    student_text:'v = -12.8 or 12.88 (unclear)',reasoning:'A digit is obscured; no point grade established.',
    review_explanation:{status:'needs_review',items:[{title:'Lost credit rests on uncertain evidence',reason:'The final digit is obscured.',action:'Compare the original final-answer crop.',criterion_id:'speed',source:'rule_check'}]},
    rubric_snapshot:{criteria:[{id:'speed',title:'Speed result',points:4}]},criteria_scores:[],course_evidence:[{title:'Synthetic chapter',page_index:1,text:'v² = u² + 2as.'}],original_policy:{method_credit:'partial'},answer_key:'12.8 m/s'};
  await page.route('**/api/pilot-studies**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path.includes('/pages/'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="white"/><text x="30" y="100">Synthetic original: v = 12.8</text></svg>'});
    if(path.endsWith('/papers/p'))return failPaper?route.fulfill({status:409,json:{detail:'Synthetic saved-paper mismatch'}}):route.fulfill({json:{...paper,answers:[answer],page_count:1}});
    if(path.endsWith('/pilot'))return route.fulfill({json:{study_id:'pilot',title:'Synthetic pilot',answer_count:1,papers:[paper],reference_comparison:[{label:'Synthetic known check',exact_count:0,scheduled_count:1,disagreement_count:1,disagreements_flagged:0,review_count_among_scored:0,unavailable_count:0}]}});
    return route.fulfill({json:{items:[{study_id:'pilot'}]}});
  });
}

test('saved pilot preserves unknown marks, explanation, full page and rubric edit link',async({page},info)=>{
  await pilotFixture(page);await page.goto('/app/pilot.html?study_id=pilot');
  await expect(page.locator('#pilot-status')).toContainText('1 answer slots');
  await expect(page.locator('#pilot-paper-summary')).toContainText('1–4 / 4');
  await expect(page.locator('#pilot-answer')).toContainText('unresolved');
  await expect(page.getByText('Lost credit rests on uncertain evidence',{exact:false})).toBeVisible();
  await expect(page.getByRole('link',{name:'View & edit this rubric'})).toHaveAttribute('href','setup.html?exam_id=e&rubric_question=q');
  await expect(page.locator('#pilot-image')).toBeVisible();
  await page.getByText('Course evidence used for this answer',{exact:true}).click();
  await expect(page.locator('#pilot-answer-detail')).toContainText('v² = u² + 2as.');
  for(const theme of ['light','dark']){await page.evaluate(theme=>MisraTheme.set(theme),theme);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'.impeccable/review/pilot-'+theme+'-'+info.project.name+'.png',fullPage:true});}
});

test('saved paper failure keeps marks unavailable and provides retry',async({page})=>{
  await pilotFixture(page,{failPaper:true});await page.goto('/app/pilot.html?study_id=pilot');
  await expect(page.locator('#pilot-error')).toContainText('Synthetic saved-paper mismatch');
  await expect(page.locator('#pilot-answer')).toBeDisabled();await expect(page.locator('#pilot-image')).toBeHidden();
  await expect(page.locator('#pilot-refresh')).toBeEnabled();
});

test('teaching context survives a rejected save and is escaped when viewed',async({page},info)=>{
  await auth(page);let saved;
  await page.route('**/api/instructor-preference-versions',route=>{
    if(route.request().method()==='GET')return route.fulfill({json:[]});
    saved=route.request().postDataJSON();return route.fulfill({status:422,json:{detail:'Synthetic profile validation rejected'}});
  });
  await page.goto('/app/marking-survey.html');
  await page.locator('[data-context="subjects"]').fill('Physics, Big Data');
  await page.locator('[data-context="marking_style"]').selectOption('lenient');
  await page.locator('[data-context="question_style_notes"]').fill('<script>window.injected=true</script>');
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Synthetic profile validation rejected');
  await expect(page.locator('[data-context="subjects"]')).toHaveValue('Physics, Big Data');
  expect(saved.explicit_preferences.teaching_context.marking_style).toBe('lenient');
  expect(await page.evaluate(()=>window.injected)).toBeUndefined();
  for(const theme of ['light','dark']){await page.evaluate(theme=>MisraTheme.set(theme),theme);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'.impeccable/review/profile-'+theme+'-'+info.project.name+'.png',fullPage:true});}
});

test('dashboard previews the actual reason and links to the affected answer',async({page})=>{
  await auth(page);
  await page.route('**/api/review-queue',route=>route.fulfill({json:[{id:'a',submission_id:'s',question_id:'q',score:1,max_score:4,
    review_explanation:{items:[{code:'low_model_confidence',title:'Low estimate',source:'uncalibrated_heuristic',reason:'Generic estimate'},
      {code:'deduction_on_uncertain_evidence',title:'Lost credit rests on uncertain evidence',source:'rule_check',criterion_id:'result',reason:'The saved result has the opposite sign',action:'Read the minus sign'}]}}]}));
  await page.goto('/app/dashboard.html');
  await expect(page.locator('#dashboard-review-concerns')).toContainText('The saved result has the opposite sign');
  await expect(page.locator('#dashboard-review-concerns').getByRole('link',{name:'Review evidence',exact:true})).toHaveAttribute('href',/question_id=q/);
});

test('evaluation shows missed errors separately from matching flagged grades',async({page})=>{
  await auth(page);await page.route('**/api/evaluation**',route=>route.fulfill({json:{
    overall:{label_count:4,exact_agreement:.5,mae:.5,rmse:.707},per_question:{},
    review_safety_metrics:{known_review_snapshots:4,missing_review_snapshots:0,disagreements_caught:1,disagreements_missed:1,disagreement_recall:.5,review_rate:.5,flagged_matching_grades:1,unflagged_disagreement_rate:.5,disagreement_precision:.5}
  }}));
  await page.goto('/app/evaluation.html');
  await expect(page.locator('#evaluation-review')).toContainText('Disagreements missed');
  await expect(page.locator('#evaluation-review')).toContainText('1 matching grades were also flagged');
  await expect(page.locator('#evaluation-review')).toContainText('No matched instructor and AI criterion scores yet');
  await expect(page.locator('#evaluation-summary')).toContainText('Exact agreement');
});

test('history shows reopening reasons alongside retained decisions',async({page})=>{
  await auth(page);await page.route('**/api/results/s',route=>route.fulfill({json:{submission:{id:'s',exam_id:'e'},answers:[{id:'a',question_id:'q',score:1,max_score:4}]}}));
  await page.route('**/api/answers/a/review-events',route=>route.fulfill({json:[{id:'event',action:'grade_review_reopened',reason:'Check the scratched-out minus sign',created_at:'2026-10-23'}]}));
  await page.goto('/app/history.html?submission_id=s');
  await expect(page.locator('#history-decisions')).toContainText('Reopened for review');
  await expect(page.locator('#history-decisions')).toContainText('Check the scratched-out minus sign');
});
