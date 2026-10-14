const {test,expect}=require('@playwright/test');
const file=name=>({name,mimeType:'application/pdf',buffer:Buffer.from('Synthetic API upload fixture; not a real PDF')});
async function fixture(page,{blocked=false,uploadStatus=202,holdUpload=false,holdSources=false,pollFails=false}={}) {
  const writes=[];let releaseUpload,releaseSources,knownJobs=[];
  const uploadGate=new Promise(r=>releaseUpload=r),sourceGate=new Promise(r=>releaseSources=r);
  const versions={e:[],e2:[]};
  await page.route('**/api/**',async route=>{
    const request=route.request(),p=new URL(request.url()).pathname.replace('/api','');let body={};
    if(p==='/auth/me') body={id:'u',role:'teacher'};
    else if(p==='/exams') body=[{id:'e',course_id:'c',title:'Work & energy',course_code:'TEST',submission_count:0},{id:'e2',course_id:'c',title:'Other assessment',submission_count:0}];
    else if(p==='/submissions') body=knownJobs.length ? [{id:'s',exam_id:'e',page_count:1,extracted_student_name:'Synthetic paper',grading_summary:{complete:false},readiness:{bulk_grading_allowed:false}}] : [];
    else if(p==='/results/s') body={submission:{id:'s',exam_id:'e',page_count:1},answers:[]};
    else if(p==='/submissions/s/extraction-review') body={submission:{id:'s',exam_id:'e',page_count:1},questions:[],readiness:{bulk_grading_allowed:false}};
    else if(p==='/jobs') body={items:knownJobs};
    else if(p==='/courses/c/materials') {if(holdSources) await sourceGate;body=[{id:'m',title:'Synthetic chapter',versions:[{id:'v',version_number:1,status:'approved',page_count:3,approved_page_indices:[0,1]}]}];}
    else if(p.endsWith('/setup-readiness')) body={ready:!blocked,message:blocked ? 'Rubric approval is missing.' : 'Approved definitions checked.',questions:[{question_id:'q',question_number:'1',max_score:2,approved:!blocked,rubric_version:1,answer_key_version:1,errors:blocked ? ['Approve the rubric first.'] : [],warnings:[]}]};
    else if(p.endsWith('/marking-guide'))body={exam_id:p.split('/')[2],review_token:'a'.repeat(64),can_approve:true,pending_count:versions[p.split('/')[2]].some(v=>v.status==='draft') ? 1 : 0,total_marks:2,errors:[],warnings:[],questions:[{question_id:'q',question_number:'1',question_text:'Synthetic work question',max_score:2,rubric_status:'approved',rubric:{criteria:[{title:'Work',description:'Use W=Fd',points:2}],policy:{}},answer_key:{mode:'no_fixed_answer'},source_exception:null,sources:null,source_references:[],errors:[],warnings:[]}]};
    else if(p.endsWith('/marking-guide/approve')){const id=p.split('/')[2];writes.push({kind:'approve',exam:id});versions[id][0].status='approved';body={exam_id:id,approved_version_ids:['scope'],message:'Assessment guide approved.'};}
    else if(p.includes('/material-scopes')) {
      const id=p.split('/')[2];
      if(request.method()==='GET') body={versions:versions[id],questions:[{question_number:'1',origin:versions[id].some(v=>v.status==='approved') ? 'assessment' : 'none'}]};
      else if(p.endsWith('/approve')) {writes.push({kind:'approve',exam:id});versions[id][0].status='approved';body=versions[id][0];}
      else {const value=request.postDataJSON();writes.push({kind:'source',exam:id,body:value});body={id:'scope',status:'draft',version_number:1,...value};versions[id].unshift(body);}
    } else if(p==='/upload-exam' || p==='/upload-batch') {
      writes.push({kind:'upload',path:p,body:request.postData()});if(holdUpload) await uploadGate;
      if(uploadStatus!==202) return route.fulfill({status:uploadStatus,json:{detail:'Synthetic upload rejection'}});
      body=p==='/upload-exam' ? {submission:{id:'s'},job:{id:'j',submission_id:'s',status:'queued'}} : {batch_id:'b',job:{id:'j',batch_id:'b',status:'queued'}};
      knownJobs=[{...body.job,exam_id:'e',job_type:p==='/upload-exam' ? 'ocr_submission' : 'ocr_batch',status:'completed'}];
    } else if(p==='/jobs/j') {if(pollFails) return route.fulfill({status:503,json:{detail:'Synthetic progress outage'}});body={id:'j',status:'completed',progress_percent:100,progress_message:'Inspect the saved results.'};}
    await route.fulfill({json:body});
  });
  await page.goto('/next/index.html?exam_id=e');await expect(page.locator('#exam-title')).toHaveText('Work & energy');
  return {writes,releaseUpload,releaseSources};
}
test('single upload stays in ledger, locks selection and does not upload again after acceptance',async({page})=>{
  const state=await fixture(page);await page.locator('#upload-link').click();
  await expect(page.locator('#ledger-readiness')).toContainText('Approved definitions');
  await page.locator('#ledger-files').setInputFiles(file('paper.pdf'));
  await expect(page.locator('#ledger-files')).toBeDisabled();await expect(page.locator('[data-ledger-upload-mode="batch"]')).toBeDisabled();
  await page.locator('#ledger-upload-submit').click();
  await expect(page.locator('#upload-accepted')).toContainText('Extraction job completed');
  await expect(page.locator('#ledger-upload-submit')).toBeDisabled();expect(state.writes.filter(w=>w.kind==='upload')).toHaveLength(1);
  await page.getByRole('button',{name:'Open extracted paper',exact:true}).click();await expect(page.locator('#ledger-upload')).toBeHidden();await expect(page.locator('#selected-paper-copy')).toContainText('Synthetic paper');
  await page.locator('#upload-link').click();await expect(page.locator('#upload-accepted')).toContainText('Extraction job completed');
  await expect(page).toHaveURL(/view=upload.*job_id=j/);await page.reload();await expect(page.locator('#ledger-upload')).toBeVisible();await expect(page.locator('#upload-accepted')).toContainText('Extraction job completed');await expect(page.locator('#ledger-files')).toBeDisabled();expect(state.writes.filter(w=>w.kind==='upload')).toHaveLength(1);
  await page.locator('#activity-link').click();await expect(page.locator('#ledger-upload')).toBeHidden();await expect(page.locator('#ledger-activity')).toBeVisible();
  await page.locator('#upload-link').click();await expect(page.locator('#upload-accepted')).toContainText('Extraction job completed');
  await page.locator('#upload-another').click();await expect(page.locator('#ledger-files')).toBeEnabled();
});
test('batch upload sends named files and accepts splitting only one combined PDF',async({page})=>{
  const state=await fixture(page);await page.locator('#upload-link').click();await page.locator('[data-ledger-upload-mode="batch"]').click();
  await page.locator('#ledger-files').setInputFiles([file('one.pdf'),file('two.pdf')]);await page.locator('#ledger-split').fill('2');await page.locator('#ledger-upload-submit').click();
  await expect(page.locator('#upload-error')).toContainText('one combined PDF');expect(state.writes).toHaveLength(0);
  await page.locator('#ledger-split').fill('');await page.locator('#ledger-upload-submit').click();
  await expect(page.locator('#upload-accepted')).toContainText('Extraction job completed');
  expect(state.writes[0].path).toBe('/upload-batch');expect(state.writes[0].body).toContain('name="files"');expect(state.writes[0].body).toContain('name="exam_id"');
});
test('pending upload prevents assessment switches and duplicate posts',async({page})=>{
  const state=await fixture(page,{holdUpload:true});await page.locator('#upload-link').click();await page.locator('#ledger-files').setInputFiles(file('paper.pdf'));await page.locator('#ledger-upload-submit').click();
  await expect(page.locator('#ledger-upload-submit')).toBeDisabled();await page.locator('[data-exam="e2"]').click();await expect(page.locator('#exam-title')).toHaveText('Work & energy');
  expect(state.writes).toHaveLength(1);state.releaseUpload();await expect(page.locator('#upload-accepted')).toContainText('Extraction job completed');
});
test('validation rejection retains selection; uncertain acceptance blocks replay',async({page})=>{
  await fixture(page,{uploadStatus:422});await page.locator('#upload-link').click();await page.locator('#ledger-files').setInputFiles(file('paper.pdf'));await page.locator('#ledger-upload-submit').click();
  await expect(page.locator('#upload-error')).toContainText('selection is retained');await expect(page.locator('#ledger-upload-submit')).toBeEnabled();
  await page.locator('#clear-upload').click();await page.unroute('**/api/**');const state=await fixture(page,{uploadStatus:503});await page.locator('#upload-link').click();await page.locator('#ledger-files').setInputFiles(file('paper.pdf'));await page.locator('#ledger-upload-submit').click();
  await expect(page.locator('#upload-error')).toContainText('may be queued');await expect(page.locator('#ledger-upload-submit')).toBeDisabled();await expect(page.locator('#clear-upload')).toBeDisabled();expect(state.writes).toHaveLength(1);
});
test('accepted upload with progress outage never becomes an upload-failure retry',async({page})=>{
  const state=await fixture(page,{pollFails:true});await page.locator('#upload-link').click();await page.locator('#ledger-files').setInputFiles(file('paper.pdf'));await page.locator('#ledger-upload-submit').click();
  await expect(page.locator('#upload-accepted')).toContainText('upload was accepted');await expect(page.locator('#ledger-upload-submit')).toBeDisabled();
  await page.getByRole('button',{name:'Reconnect progress',exact:true}).click();expect(state.writes).toHaveLength(1);
});
test('unapproved setup blocks upload and canceled navigation retains files',async({page})=>{
  await fixture(page,{blocked:true});await page.locator('#upload-link').click();await page.locator('#ledger-files').setInputFiles(file('paper.pdf'));
  await expect(page.locator('#ledger-upload-submit')).toBeDisabled();await expect(page.locator('#ledger-readiness')).toContainText('missing');
  page.once('dialog',d=>d.dismiss());await page.locator('[data-exam="e2"]').click();await expect(page.locator('#exam-title')).toHaveText('Work & energy');await expect(page.locator('#upload-selection')).toContainText('paper.pdf');
});
test('source defaults save a draft before explicit approval in the new shell',async({page},info)=>{
  const state=await fixture(page);await page.locator('#sources-link').click();await page.getByRole('button',{name:'Add assessment source',exact:true}).click();
  await page.locator('[data-default-version]').selectOption('v');await page.locator('[data-default-pages]').fill('1-2');await page.getByRole('button',{name:'Save assessment source draft',exact:true}).click();
  await expect(page.locator('[data-default-save-state]')).toContainText('not active yet');expect(state.writes.filter(w=>w.kind==='approve')).toHaveLength(0);
  await page.locator('#guide-review-tab').click();await page.locator('#guide-confirm').check();await page.locator('#guide-approve').click();await expect(page.locator('#guide-approval-state')).toContainText('approved');
  expect(state.writes.filter(w=>w.kind==='source')[0].body.bindings[0].page_indices).toEqual([0,1]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});await page.screenshot({path:`.impeccable/review/ledger-setup-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/ledger-setup-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});
test('setup source requests from a previous assessment cannot repopulate the new one',async({page})=>{
  const state=await fixture(page,{holdSources:true});await page.locator('[data-exam="e2"]').click();state.releaseSources();await page.locator('#sources-link').click();
  await expect(page.locator('#exam-title')).toHaveText('Other assessment');await page.getByRole('button',{name:'Add assessment source',exact:true}).click();await page.locator('[data-default-version]').selectOption('v');await page.locator('[data-default-pages]').fill('1');
  await page.getByRole('button',{name:'Save assessment source draft',exact:true}).click();await expect(page.locator('[data-default-save-state]')).toContainText('saved');expect(state.writes[0].exam).toBe('e2');
});
test('upload task uses the shared light and dark responsive shell',async({page},info)=>{
  await fixture(page);await page.locator('#upload-link').click();await page.locator('#ledger-files').setInputFiles(file('synthetic.pdf'));await expect(page.locator('#ledger-upload-submit')).toBeEnabled();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});
  await page.screenshot({path:`.impeccable/review/ledger-upload-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/ledger-upload-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});
