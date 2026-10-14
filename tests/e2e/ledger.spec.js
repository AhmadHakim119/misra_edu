const { test, expect } = require('@playwright/test');

async function fixture(page,{failSave=false,delayPaper=false,blockGrading=false}={}) {
  const writes=[];
  const questions=[{id:'q1',question_number:'1',question_text:'State the formula for work.',max_score:2},{id:'q2',question_number:'2',question_text:'A constant force of 82.0 N moves a box 3.00 m in the direction of the force. What is the work done?',max_score:2}];
  const papers=[{id:'s',exam_id:'e',extracted_student_name:'Pilot B',extracted_student_number:'TEST002',page_count:2,status:'graded',readiness:{bulk_grading_allowed:true},grading_summary:{recorded_score:3.5,max_score:4,complete:true,review_count:1,graded_count:2,expected_count:2}},{id:'other',exam_id:'e',extracted_student_name:'Pilot C',page_count:2,status:'extracted',readiness:{bulk_grading_allowed:!blockGrading},grading_summary:{recorded_score:null,max_score:4,complete:false,review_count:0}}];
  const criteria=[{criterion_id:'formula-id',points_earned:1,max_points:1,feedback:'Correct formula.'},{criterion_id:'calculation-id',points_earned:.5,max_points:1,feedback:'Correct units; arithmetic error.'}];
  const pack={rubric_version_id:'r',rubric:{criteria:[{id:'formula-id',title:'Formula',description:'Apply W = Fd'},{id:'calculation-id',title:'Calculation & units',description:'Compute 246 J'}]},course_references:{scope_origin:'assessment',scope_version_number:1,passages:[{title:'Chapter 7',text:'W = Fd.',material_version_number:1,page_index:1}]},answer_key:{mode:'reference',reference_text:'W = (82.0 N)(3.00 m) = 246 J.'},policy:{arithmetic_error_policy:'Partial credit for units'}};
  let answer={id:'a2',question_id:'q2',score:1.5,max_score:2,needs_review:true,llm_confidence:79,raw_ocr_text:'W = Fd. W = 82 × 3 = 200 J.',criteria_scores:criteria,reasoning:'Correct method, arithmetic error.',grading_raw_response:{grading_run_id:'run2',grading_package:pack}};
  pack.course_references.passages[0]= {...pack.course_references.passages[0],id:'material:cp',material_id:'m',material_version_id:'mv',criterion_ids:['formula-id','calculation-id']};
  pack.student_evidence=[{id:'source:src1',kind:'ocr_segment',page_index:1,segment_index:0,text:answer.raw_ocr_text}];
  criteria.forEach(c=>{c.reference_refs=['material:cp'];c.evidence_refs=['source:src1'];});
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname.replace('/api','');let body={};
    if(path==='/auth/me') body={id:'u',role:'teacher'};
    else if(path==='/exams') body=[{id:'e',title:'Work & energy',course_code:'GPHY171',course_title:'Synthetic demonstration',submission_count:2},{id:'e2',title:'Mechanics quiz',course_code:'TEST',submission_count:0}];
    else if(path==='/jobs') body={items:[]};
    else if(path==='/submissions') body=new URL(route.request().url()).searchParams.get('exam_id')==='e2' ? [] : papers;
    else if(path.startsWith('/results/')) { const id=path.split('/').at(-1); if(delayPaper && id==='s') await new Promise(resolve=>setTimeout(resolve,450)); const paper=papers.find(p=>p.id===id);body={submission:paper,answers:id==='s' ? [{id:'a1',question_id:'q1',score:2,max_score:2},answer] : [],latest_review_labels:[]}; }
    else if(path.endsWith('/extraction-review')) { const id=path.split('/')[2];body={submission:papers.find(p=>p.id===id),questions:questions.map((question,i)=>({question,sources:[{id:`src${i}`,page_index:i,extracted_text:i ? answer.raw_ocr_text:'W = Fd',ocr_segment:{bounding_box:{x:.1,y:.25,width:.6,height:.15}}}],mapping_flags:[]})),readiness:{bulk_grading_allowed:id==='s' || !blockGrading,blocking_reasons:blockGrading ? ['Original answer coverage needs checking.'] : []},grading_scope:{kind:'all'}}; }
    else if(path.endsWith('/source-locations')) body={page_index:Number(new URL(route.request().url()).searchParams.get('page_index')),sources:{src1:{status:'located',method:'native_pdf_text',bounding_box:{x:.06,y:.18,width:.8,height:.23}}}};
    else if(path.includes('/pages/')) return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="550" height="700"><rect width="550" height="700" fill="white"/><g font-family="serif" font-size="17" fill="black"><text x="45" y="50">Synthetic paper · full original page</text><text x="45" y="150">Question 2</text><text x="45" y="200">W = Fd</text><text x="45" y="235">W = 82 × 3 = 200 J</text><text x="45" y="640">Page end — evidence is not cropped</text></g></svg>'});
    else if(path.endsWith('/resolve-review')) { writes.push(route.request().postDataJSON());if(failSave) return route.fulfill({status:409,json:{detail:'Synthetic newer grading run'}});answer={...answer,teacher_override_score:writes.at(-1).human_score,needs_review:false,review_status:'overridden'};body={answer}; }
    else if(path.endsWith('/grade')) {writes.push({grade:true});body={job:{id:'job',status:'queued'}};}
    await route.fulfill({json:body});
  });
  await page.goto('/next/index.html?exam_id=e&submission_id=s&question_id=q2');
  if(!delayPaper) await expect(page.locator('#question-select')).toHaveValue('q2');
  return writes;
}

test('ledger puts real criterion titles, saved references and full paper beside grade controls',async({page},info)=>{
  await fixture(page);
  await expect(page.locator('.criteria-table')).toContainText('Formula');
  await expect(page.locator('.criteria-table')).not.toContainText('formula-id');
  await expect(page.locator('#page-select')).toHaveValue('1');
  await expect(page.getByAltText('Full original submitted paper, page 2')).toBeVisible();
  await expect(page.locator('#location-note')).toContainText('1 text-matched');
  await expect(page.locator('.confidence')).toContainText('79% · uncalibrated');
  await expect(page.locator('#paper-status')).toContainText('Extraction: ready');
  await expect(page.locator('#paper-status')).toContainText('Grading: complete');
  await expect(page.locator('.decision-context')).toContainText('246 J');
  await expect(page.locator('.rationale-preview').last()).toContainText('Correct method, arithmetic error.');
  await expect(page.locator('.question-more')).toContainText('Arithmetic errors: Partial credit for units');
  await page.getByText('Approved rules & references used',{exact:true}).click();
  await expect(page.locator('#question-detail')).toContainText('Assessment default v1');
  await expect(page.locator('#paper-list')).toContainText('3.5 / 4');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});
  await page.screenshot({path:`.impeccable/review/ledger-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'Switch to dark theme'}).click();
  await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});
  await page.screenshot({path:`.impeccable/review/ledger-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});

test('each criterion exposes the saved lecture passage and original source page',async({page},info)=>{
  await fixture(page);const trace=page.locator('.source-trace').first();await trace.locator('summary').click();await expect(trace).toContainText('W = Fd.');await expect(trace).toContainText('Chapter 7 · v1 · document page 2');await expect(trace).toContainText('Paper page 2, segment 1');await expect(trace.getByRole('link',{name:'Open original source'})).toHaveAttribute('href',/materials\/m\/versions\/mv\/document#page=2$/);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/lecture-evidence-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/lecture-evidence-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});

test('enlarging the original paper preserves highlights, page navigation and unsaved marks',async({page})=>{
  await fixture(page);
  await page.getByLabel('Instructor score',{exact:true}).fill('2');
  await page.getByRole('button',{name:'Zoom in original paper',exact:true}).click();
  await expect(page.locator('#paper-zoom')).toHaveText('125%');
  await expect(page.locator('.paper-image')).toHaveAttribute('style',/width:\s*125%/);
  await page.getByRole('button',{name:'Expand paper',exact:true}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog').getByAltText('Full original submitted paper, page 2')).toBeVisible();
  await expect(page.getByRole('dialog').locator('.evidence-box')).toHaveCount(1);
  await page.getByRole('button',{name:'Previous paper page',exact:true}).click();
  await expect(page.locator('#page-select')).toHaveValue('0');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.getByRole('button',{name:'Expand paper',exact:true})).toBeFocused();
  await expect(page.locator('#instructor-score')).toHaveValue('2');
  await page.getByRole('button',{name:'Fit width',exact:true}).click();
  await expect(page.locator('#paper-zoom')).toHaveText('100%');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('override requires a reason, pins the displayed run, and keeps the current question after saving',async({page})=>{
  const writes=await fixture(page);
  await page.getByLabel('Instructor score',{exact:true}).fill('2');
  await page.getByRole('button',{name:'Save instructor grade',exact:true}).click();
  await expect(page.locator('#grade-error')).toContainText('Choose a decision reason');expect(writes).toHaveLength(0);
  await page.locator('#decision-reason').selectOption('minor_notation');
  await page.getByRole('button',{name:'Save instructor grade',exact:true}).click();
  await expect(page.locator('#save-status')).toContainText('Instructor override recorded');
  await expect(page.locator('#question-select')).toHaveValue('q2');
  expect(writes[0]).toMatchObject({action:'override',human_score:2,grading_run_id:'run2',review_reason_codes:['minor_notation'],was_review_warranted:true});
});

test('failed override and cancelled question navigation retain the instructor draft',async({page})=>{
  await fixture(page,{failSave:true});await page.getByLabel('Instructor score',{exact:true}).fill('1');
  page.once('dialog',d=>d.dismiss());await page.locator('#question-select').selectOption('q1');
  await expect(page.locator('#question-select')).toHaveValue('q2');await expect(page.locator('#instructor-score')).toHaveValue('1');
  await page.locator('#decision-reason').selectOption('other');await page.getByRole('button',{name:'Save instructor grade',exact:true}).click();
  await expect(page.locator('#grade-error')).toContainText('Synthetic newer grading run');await expect(page.locator('#instructor-score')).toHaveValue('1');
});

test('criterion edits sum correctly and record criterion-level human scores',async({page})=>{
  const writes=await fixture(page);await page.getByText('Adjust criterion marks (optional)',{exact:true}).click();
  await page.locator('[data-criterion="calculation-id"]').fill('1');
  await expect(page.locator('#instructor-score')).toHaveValue('2.00');await page.locator('#decision-reason').selectOption('method_credit');
  await page.getByRole('button',{name:'Save instructor grade',exact:true}).click();
  await expect.poll(()=>writes.length).toBe(1);expect(writes[0].human_criteria_scores).toHaveLength(2);
});

test('a late paper response cannot replace a newly selected assessment',async({page})=>{
  await fixture(page,{delayPaper:true});await page.locator('[data-exam="e2"]').click();
  await expect(page.locator('#exam-title')).toHaveText('Mechanics quiz');await page.waitForTimeout(600);
  await expect(page.locator('#paper-list')).toContainText('No student papers');await expect(page.locator('#grade-editor')).toBeEmpty();
});

test('unsafe extraction blocks grading and the original tools remain accessible',async({page})=>{
  await fixture(page,{blockGrading:true});await page.locator('[data-paper="other"]').click();
  await expect(page.getByRole('button',{name:'Grade paper with AI'})).toBeDisabled();
  await expect(page.locator('#grade-editor')).toContainText('coverage needs checking');
  await page.locator('#sources-link').click();
  await expect(page.locator('#ledger-setup')).toBeVisible();
  await expect(page.locator('#original-studio')).toHaveAttribute('href','../pages/rubric-studio.html?exam_id=e');
  await expect(page.locator('#export-link')).toBeEnabled();
});

test('hero at the approved desktop dimensions retains ledger and evidence layout',async({page},info)=>{
  test.skip(info.project.name!=='desktop-chromium','The desktop comp has its own frame; mobile is covered separately.');
  await page.setViewportSize({width:1586,height:992});await fixture(page);
  await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});
  await page.screenshot({path:'.impeccable/review/hero-repro.png',animations:'disabled'});
});
