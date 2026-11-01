const {test,expect}=require('@playwright/test');

async function fixture(page,{materials=14,failUpload=false,failGenerate=false,failInsights=false,questions=null,savedImport=false,failConfirmOnce=false}={}){
  const writes=[],library=Array.from({length:materials},(_,i)=>({id:'m'+i,title:`Synthetic lecture ${i+1}`,versions:[{id:'v'+i,version_number:1,status:'approved',page_count:2,approved_page_indices:[0],ingestion_status:'ready'}]}));
  let rows=[],scope=[],selected=null;
  const proposal={job:{id:'job',status:'completed'},origin:'course_source_questions',documents:[],imported_question_ids:[],warnings:[],source_passages:[{id:'source:1',title:'Synthetic lecture 1',version_number:1,page_index:0,text:'Work is force times displacement.'}],questions:[{question_number:'1',question_text:'Calculate work for 10 N through 2 m.',max_score:2,answer_key:'20 J',marking_guide:'One mark formula, one result.',source_draft_id:'proposal',citations:[{source_ref:'source:1',quote:'Work is force times displacement.'}]}]};
  if(questions)proposal.questions=questions;
  if(savedImport){proposal.origin='uploaded_exam';rows=[proposal];}
  await page.route('**/api/**',async route=>{const req=route.request(),p=new URL(req.url()).pathname.replace('/api','');let body={};
    if(p==='/auth/me')body={id:'u',role:'teacher'};
    else if(p==='/exams')body=[{id:'e',title:'Synthetic lecture quiz',course_id:'c',course_code:'TEST'},{id:'e2',title:'Other quiz',course_id:'c2'}];
    else if(p==='/submissions')body=[];
    else if(p==='/jobs')body={items:[]};
    else if(p.endsWith('/setup-readiness'))body={ready:false,message:'Add questions and approve the guide.',questions:[]};
    else if(p.endsWith('/marking-guide'))body={exam_id:'e',review_token:'a'.repeat(64),questions:[],errors:[],warnings:[],can_approve:false,pending_count:0,total_marks:0};
    else if(p.endsWith('/questions'))body=[];
    else if(p.endsWith('/instructor-preference-versions'))body=[];
    else if(p.endsWith('/material-scopes')){if(req.method()==='POST'){writes.push({kind:'scope',body:req.postDataJSON()});scope=[{id:'default',status:'draft',version_number:1,...req.postDataJSON()}];body=scope[0];}else body={versions:scope,questions:[]};}
    else if(p.endsWith('/materials')){if(req.method()==='POST'){writes.push({kind:'material',body:req.postData()});if(failUpload)return route.fulfill({status:503,json:{detail:'Synthetic upload interruption'}});body={id:'new'+writes.length,versions:[{status:'draft'}]};}else body=library;}
    else if(p.endsWith('/source-question-drafts')){writes.push({kind:'generate',body:req.postDataJSON()});if(failGenerate)return route.fulfill({status:503,json:{detail:'Synthetic provider unavailable'}});rows=[proposal];body=proposal;}
    else if(p.endsWith('/setup-imports/job/confirm')){writes.push({kind:'confirm',body:req.postDataJSON()});if(failConfirmOnce){failConfirmOnce=false;return route.fulfill({status:422,json:{detail:'Synthetic correction required'}});}proposal.imported_question_ids=['new'];body={question_ids:['new']};}
    else if(p.endsWith('/setup-imports/job'))body=proposal;
    else if(p.endsWith('/setup-imports')){if(req.method()==='POST'){writes.push({kind:'import',body:req.postData()});proposal.origin='uploaded_exam';rows=[proposal];body=proposal;}else body=rows;}
    else if(p.endsWith('/learning-insights')){if(failInsights)return route.fulfill({status:503,json:{detail:'Synthetic feedback interruption'}});body={exam_id:'e',submission_count:2,confidence_status:'uncalibrated',notes:['Missing work is not scored zero.'],questions:[{question_id:'q',question_number:'1',question_text:'Calculate work.',graded_count:2,average_percent:75,awaiting_review_count:1,course_grounded_count:2,criterion_override_excluded_count:0,criteria:[{title:'Correct result',description:'Calculate the force-distance product and give joules.',rubric_version_id:'r1',assessed_count:2,average_percent:75,full_credit_count:1,partial_credit_count:1,zero_credit_count:0,source_pages:[{title:'Synthetic lecture 1',page_index:0}]}]}]};}
    await route.fulfill({json:body});});
  await page.goto('/app/index.html?exam_id=e');await expect(page.locator('#exam-title')).toHaveText('Synthetic lecture quiz');await page.locator('#sources-link').click();return writes;
}

test('one action selects all fourteen approved chapters without approving them',async({page})=>{
  const writes=await fixture(page);await page.getByRole('button',{name:'Use all currently approved course materials'}).click();await expect(page.locator('[data-default-row]')).toHaveCount(14);await page.getByRole('button',{name:'Save assessment source draft',exact:true}).click();const body=writes.find(w=>w.kind==='scope').body;expect(body.bindings).toHaveLength(14);expect(body.bindings.every(b=>b.page_indices.length===1 && b.page_indices[0]===0)).toBeTruthy();expect(body.mode).toBe('required');
});
test('lecture proposals show exact quotes then add drafts without approval',async({page})=>{
  const writes=await fixture(page);await page.locator('#quiz-from-lecture summary').click();await page.locator('#lecture-choices input').first().check();await page.locator('#lecture-topic').fill('Work done by a constant force');await page.getByRole('button',{name:'Draft questions from this lecture',exact:true}).click();await expect(page.locator('#teaching-proposals')).toContainText('Calculate work for 10 N');await page.locator('#teaching-proposals summary').click();await expect(page.locator('#teaching-proposals')).toContainText('Work is force times displacement.');await page.getByRole('button',{name:'Add selected questions to the marking guide'}).click();await expect(page.locator('#teaching-status')).toContainText('already added as drafts');expect(writes.find(w=>w.kind==='confirm').body.questions[0].source_draft_id).toBe('proposal');expect(writes.some(w=>w.kind==='approve')).toBeFalsy();
});
test('generation failure retains entries and saved-request check is explicit',async({page})=>{
  const writes=await fixture(page,{failGenerate:true});await page.locator('#quiz-from-lecture summary').click();await page.locator('#lecture-choices input').first().check();await page.locator('#lecture-topic').fill('Work and energy');await page.getByRole('button',{name:'Draft questions from this lecture',exact:true}).click();await expect(page.locator('#teaching-status')).toContainText('Synthetic provider unavailable');await expect(page.locator('#lecture-topic')).toHaveValue('Work and energy');await page.getByRole('button',{name:'Draft questions from this lecture',exact:true}).click();expect(writes.filter(w=>w.kind==='generate')).toHaveLength(1);
});
test('existing quiz import does not request new question generation',async({page})=>{
  const writes=await fixture(page);await page.locator('#import-existing-quiz summary').click();await page.locator('#teaching-import-form [name="exam"]').setInputFiles({name:'ExistingQuiz.pdf',mimeType:'application/pdf',buffer:Buffer.from('synthetic')});await page.getByRole('button',{name:'Read existing quiz & key',exact:true}).click();await expect(page.locator('#teaching-proposals')).toContainText('Calculate work for 10 N');expect(writes.some(w=>w.kind==='generate')).toBeFalsy();expect(writes.some(w=>w.kind==='import')).toBeTruthy();
});
test('different imported wording stays visible for review without replacing the chosen stem',async({page})=>{
  const primary='Find inertia about the x axis.',alternative='Find inertia about the y axis.';
  const writes=await fixture(page,{savedImport:true,questions:[{question_number:'p6.1',question_text:primary,max_score:2,answer_key:'Example key',marking_guide:'Method and result.',wording_variants:[{source_page:'1:9',question_text:alternative}]}]});
  await page.locator('#import-existing-quiz summary').click();await page.getByRole('button',{name:'Check saved quiz requests',exact:true}).click();await page.locator('[data-quiz-job]').first().click();
  await expect(page.locator('[name=question_text]')).toHaveValue(primary);
  await page.getByText('Other wording found in setup documents',{exact:true}).click();
  await expect(page.locator('#teaching-proposals blockquote')).toHaveText(alternative);
  await expect(page.locator('[name=question_text]')).toHaveValue(primary);expect(writes.some(w=>w.kind==='confirm')).toBeFalsy();
});
test('missing import fields are explained and collapsed marking guides open on validation',async({page},info)=>{
  const writes=await fixture(page,{savedImport:true,questions:[{question_number:'1',question_text:'Explain the method.',max_score:2,answer_key:'A valid method.',marking_guide:''}]});
  const row=page.locator('[data-proposal="0"]');
  await expect(row).toBeVisible();
  await page.locator('#teaching-proposals').screenshot({path:`.impeccable/review/import-validation-before-${info.project.name}.png`,style:'.app-bar,.skip-link{visibility:hidden !important;}'});
  await page.getByRole('button',{name:'Add selected questions to the marking guide',exact:true}).click();
  await expect(page.locator('#teaching-proposal-feedback')).toContainText('Question 1');
  await expect(row.locator('details')).toHaveAttribute('open','');
  await expect(row.locator('[name="marking_guide"]')).toBeFocused();
  expect(writes.filter(w=>w.kind==='confirm')).toHaveLength(0);
  for(const theme of ['light','dark']){
    await page.evaluate(value=>{document.documentElement.dataset.theme=value;},theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.locator('#teaching-proposals').screenshot({path:`.impeccable/review/import-validation-${theme}-${info.project.name}.png`,style:'.app-bar,.skip-link{visibility:hidden !important;}'});
  }
  await row.locator('[name="marking_guide"]').fill('Credit a valid method.');
  await page.getByRole('button',{name:'Add selected questions to the marking guide',exact:true}).click();
  await expect(page.locator('#teaching-status')).toContainText('already added as drafts');
  expect(writes.filter(w=>w.kind==='confirm')).toHaveLength(1);
});
test('instructor-selected MCQs allow blank guides, default missing marks to one and retain failed-save edits',async({page})=>{
  const writes=await fixture(page,{savedImport:true,failConfirmOnce:true,questions:[{question_number:'2',question_text:'Choose the SI unit of force. a) N b) J',max_score:null,answer_key:'a) N',marking_guide:''},{question_number:'3',question_text:'Excluded incomplete question.',max_score:null,answer_key:'',marking_guide:''}]});
  const row=page.locator('[data-proposal="0"]'),excluded=page.locator('[data-proposal="1"]');
  await excluded.locator('[name="include"]').uncheck();
  await row.locator('[name="multiple_choice"]').check();
  await expect(row.locator('[name="max_score"]')).toHaveValue('1');
  await page.getByRole('button',{name:'Add selected questions to the marking guide',exact:true}).click();
  await expect(page.locator('#teaching-proposal-feedback')).toContainText('Synthetic correction required');
  await expect(row.locator('[name="multiple_choice"]')).toBeChecked();
  await expect(row.locator('[name="marking_guide"]')).toHaveValue('');
  await expect(excluded.locator('[name="max_score"]')).toBeDisabled();
  await page.getByRole('button',{name:'Add selected questions to the marking guide',exact:true}).click();
  await expect(page.locator('#teaching-status')).toContainText('already added as drafts');
  const body=writes.filter(w=>w.kind==='confirm').at(-1).body;
  expect(body.questions).toHaveLength(1);expect(body.questions[0]).toMatchObject({multiple_choice:true,max_score:1,marking_guide:'',answer_key:'a) N'});
  expect(writes.some(w=>w.kind==='approve'||w.kind==='generate')).toBeFalsy();
});
test('MCQs require a reference answer and never replace an existing mark value',async({page})=>{
  const writes=await fixture(page,{savedImport:true,questions:[{question_number:'4',question_text:'Choose an option.',max_score:2,answer_key:'',marking_guide:''}]});
  const row=page.locator('[data-proposal="0"]');
  await row.locator('[name="multiple_choice"]').check();
  await expect(row.locator('[name="max_score"]')).toHaveValue('2');
  await page.getByRole('button',{name:'Add selected questions to the marking guide',exact:true}).click();
  await expect(page.locator('#teaching-proposal-feedback')).toContainText('Reference solution');
  await expect(row.locator('[name="answer_key"]')).toBeFocused();
  expect(writes.filter(w=>w.kind==='confirm')).toHaveLength(0);
  await row.locator('[name="answer_key"]').fill('b');
  await row.locator('[name="max_score"]').fill('0');
  await page.getByRole('button',{name:'Add selected questions to the marking guide',exact:true}).click();
  await expect(page.locator('#teaching-proposal-feedback')).toContainText('Marks');
  await expect(row.locator('[name="max_score"]')).toBeFocused();
  expect(writes.filter(w=>w.kind==='confirm')).toHaveLength(0);
  await row.locator('[name="max_score"]').fill('2');
  await row.locator('[name="max_score"]').press('Enter');
  await expect(page.locator('#teaching-status')).toContainText('already added as drafts');
});
test('confirmation locks proposals through preparation and sends one request',async({page})=>{
  const writes=await fixture(page,{savedImport:true});
  await page.evaluate(()=>{window.MisraLedgerEditors.saveEdits=()=>new Promise(resolve=>{window.finishSyntheticPrepare=()=>resolve(true);});});
  await page.getByRole('button',{name:'Add selected questions to the marking guide',exact:true}).click();
  await expect(page.getByRole('button',{name:'Add selected questions to the marking guide',exact:true})).toBeDisabled();
  await expect(page.locator('[data-proposal="0"] [name="max_score"]')).toBeDisabled();
  await page.locator('#add-teaching-questions').dispatchEvent('submit');
  expect(writes.filter(w=>w.kind==='confirm')).toHaveLength(0);
  await page.evaluate(()=>window.finishSyntheticPrepare());
  await expect(page.locator('#teaching-status')).toContainText('already added as drafts');
  expect(writes.filter(w=>w.kind==='confirm')).toHaveLength(1);
});
test('saved proposals survive reload and do not generate duplicate requests',async({page})=>{
  const writes=await fixture(page);await page.locator('#quiz-from-lecture summary').click();await page.locator('#lecture-choices input').first().check();await page.locator('#lecture-topic').fill('Work and energy');await page.getByRole('button',{name:'Draft questions from this lecture',exact:true}).click();await expect(page.locator('#teaching-proposals')).toContainText('Calculate work for 10 N');await page.reload();await page.locator('#sources-link').click();await expect(page.locator('#teaching-proposals')).toContainText('Calculate work for 10 N');expect(writes.filter(w=>w.kind==='generate')).toHaveLength(1);
});
test('class feedback failure offers an explicit reconnect instead of fake counts',async({page})=>{
  await fixture(page,{failInsights:true});await page.locator('#insights-link').click();await expect(page.locator('#learning-insights')).toContainText('Synthetic feedback interruption');await expect(page.locator('#learning-insights')).not.toContainText('average 75');await expect(page.locator('#refresh-insights')).toBeVisible();
});
test('multi-chapter upload preserves each chapter and locks file selection',async({page})=>{
  const writes=await fixture(page);await page.locator('#lecture-upload summary').click();await page.locator('#lecture-files').setInputFiles([{name:'Chapter7.pdf',mimeType:'application/pdf',buffer:Buffer.from('synthetic')},{name:'Lecture8.pdf',mimeType:'application/pdf',buffer:Buffer.from('synthetic')}]);await expect(page.locator('#lecture-files')).toBeDisabled();await page.getByRole('button',{name:'Upload material drafts',exact:true}).click();await expect(page.locator('#lecture-upload-status')).toContainText('2 material drafts accepted');expect(writes.filter(w=>w.kind==='material')).toHaveLength(2);await expect(page.locator('#lecture-files')).toBeEnabled();
});
test('ambiguous material upload does not repeat accepted or uncertain files',async({page})=>{
  const writes=await fixture(page,{failUpload:true});await page.locator('#lecture-upload summary').click();await page.locator('#lecture-files').setInputFiles({name:'Chapter7.pdf',mimeType:'application/pdf',buffer:Buffer.from('synthetic')});await page.getByRole('button',{name:'Upload material drafts',exact:true}).click();await expect(page.locator('#teaching-status')).toContainText('Check the course library before retrying');await page.getByRole('button',{name:'Upload material drafts',exact:true}).click();expect(writes.filter(w=>w.kind==='material')).toHaveLength(1);
});
test('clearing lecture files cannot discard unsaved quiz topic or proposal edits',async({page})=>{
  await fixture(page);await page.locator('#quiz-from-lecture summary').click();await page.locator('#lecture-topic').fill('Keep this topic');await page.locator('#lecture-upload summary').click();await page.locator('#lecture-files').setInputFiles({name:'Lecture.pdf',mimeType:'application/pdf',buffer:Buffer.from('synthetic')});await page.locator('#lecture-clear').click();page.once('dialog',d=>d.dismiss());await page.locator('[data-exam="e2"]').click();await expect(page.locator('#exam-title')).toHaveText('Synthetic lecture quiz');await expect(page.locator('#lecture-topic')).toHaveValue('Keep this topic');expect(await page.evaluate(()=>{const e=new Event('beforeunload',{cancelable:true});dispatchEvent(e);return e.defaultPrevented;})).toBeTruthy();
});
test('successful material upload retains unrelated checked quiz inputs',async({page})=>{
  await fixture(page);await page.locator('#quiz-from-lecture summary').click();await page.locator('#lecture-topic').fill('Keep this topic');await page.locator('#lecture-choices input').first().check();await page.locator('#lecture-upload summary').click();await page.locator('#lecture-files').setInputFiles({name:'Lecture.pdf',mimeType:'application/pdf',buffer:Buffer.from('synthetic')});await page.getByRole('button',{name:'Upload material drafts',exact:true}).click();await expect(page.locator('#lecture-upload-status')).toContainText('1 material drafts accepted');await expect(page.locator('#lecture-choices input').first()).toBeChecked();page.once('dialog',d=>d.dismiss());await page.locator('[data-exam="e2"]').click();await expect(page.locator('#exam-title')).toHaveText('Synthetic lecture quiz');
});
test('generation success retains an unrelated existing-exam file selection',async({page})=>{
  await fixture(page);await page.locator('#import-existing-quiz summary').click();await page.locator('#teaching-import-form [name="exam"]').setInputFiles({name:'ExistingQuiz.pdf',mimeType:'application/pdf',buffer:Buffer.from('synthetic')});await page.locator('#quiz-from-lecture summary').click();await page.locator('#lecture-choices input').first().check();await page.locator('#lecture-topic').fill('Work');await page.getByRole('button',{name:'Draft questions from this lecture',exact:true}).click();await expect(page.locator('#teaching-proposals')).toContainText('Calculate work for 10 N');page.once('dialog',d=>d.dismiss());await page.locator('[data-exam="e2"]').click();await expect(page.locator('#exam-title')).toHaveText('Synthetic lecture quiz');expect(await page.locator('#teaching-import-form [name="exam"]').evaluate(el=>el.files[0].name)).toBe('ExistingQuiz.pdf');
});
test('adding proposals retains a newly edited generation request',async({page})=>{
  await fixture(page);await page.locator('#quiz-from-lecture summary').click();await page.locator('#lecture-choices input').first().check();await page.locator('#lecture-topic').fill('Work');await page.getByRole('button',{name:'Draft questions from this lecture',exact:true}).click();await expect(page.locator('#teaching-proposals')).toContainText('Calculate work for 10 N');await page.locator('#lecture-topic').fill('A second unsaved lecture request');await page.getByRole('button',{name:'Add selected questions to the marking guide'}).click();await expect(page.locator('#teaching-status')).toContainText('already added as drafts');page.once('dialog',d=>d.dismiss());await page.locator('[data-exam="e2"]').click();await expect(page.locator('#exam-title')).toHaveText('Synthetic lecture quiz');await expect(page.locator('#lecture-topic')).toHaveValue('A second unsaved lecture request');
});
test('teaching and class feedback render in the inherited themes',async({page},info)=>{
  await fixture(page,{materials:2});await page.locator('#quiz-from-lecture summary').click();await expect(page.locator('#lecture-choices')).toContainText('Synthetic lecture 1');await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/teaching-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/teaching-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#insights-link').click();await expect(page.locator('#ledger-insights')).toBeVisible();await expect(page.locator('#learning-insights')).toContainText('1 awaiting review');await expect(page.locator('#learning-insights')).toContainText('Correct result');await expect(page.locator('#learning-insights')).toContainText('uncalibrated');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/insights-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/insights-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});
