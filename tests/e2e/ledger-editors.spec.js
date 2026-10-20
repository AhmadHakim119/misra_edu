const {test,expect}=require('@playwright/test');
async function fixture(page,{failSave=false,failApprove=false,holdSave=false,holdQuestion=false,failCreate=false,withSources=false,multipleCriteria=false,expandedProfile=null,automaticPreferences=true,initialDraft=false,failDelete=false,holdDelete=false}={}) {
  const writes=[];let releaseSave,releaseQuestion,releaseDelete;
  const saveGate=new Promise(r=>releaseSave=r),questionGate=new Promise(r=>releaseQuestion=r),deleteGate=new Promise(r=>releaseDelete=r);
  const base={schema_version:2,max_score:2,criteria:[{id:'work',title:'Work calculation',description:'Use W = Fd with units',points:2,scoring_type:'scaled',partial_credit_allowed:false,performance_levels:[{label:'Correct',description:'Correct result and units',points_earned:2}],common_errors:[{description:'Arithmetic error',guidance:'Follow method-credit policy'}],alternative_methods:['Equivalent rearrangement'],required_evidence:['Formula','Result']}],policy:{grading_approach:'strict',units_policy:'required',method_credit:'partial',arithmetic_error_policy:'criterion_specific',rounding_tolerance_percent:1,alternative_methods_allowed:false}};
  let qs=[{id:'q',question_number:'1',question_text:'Calculate work for 82 N acting through 3 m.',max_score:2}],vs=[{id:'r',version_number:1,status:'approved',rubric_json:base}],keys=[],materials=[];
  if(initialDraft)vs[0].status='draft';
  if(multipleCriteria) {
    base.criteria[0].points=1;base.criteria[0].performance_levels[0].points_earned=1;
    base.criteria.push({id:'units',title:'الوحدة الصحيحة — Correct units',description:'State the result in joules.',points:1,scoring_type:'binary',partial_credit_allowed:false,required_evidence:['Joules'],performance_levels:[],common_errors:[],alternative_methods:[]});
  }
  if(withSources){base.reference_context='Retained teaching reference: work is force times displacement.';base.acceptable_answers=['Equivalent force-distance product'];base.notes='Synthetic instructor note: retain the units rule.';}
  if(withSources){qs.push({id:'q-other',question_number:'2',question_text:'Explain why equal force-distance products do equal work.',max_score:2});vs[0].status='draft';keys=[{id:'k',version_number:1,status:'draft',mode:'reference',reference_text:'W = Fd = 246 J.',acceptable_answers:[],document_refs:[]}];materials=[{id:'m',title:'Synthetic chapter: work and energy',versions:[{id:'v',version_number:1,status:'approved',ingestion_status:'ready',page_count:1,approved_page_indices:[0]}]}];}
  await page.route('**/api/**',async route=>{
    const req=route.request(),p=new URL(req.url()).pathname.replace('/api',''),method=req.method();let body={};
    if(p==='/auth/me') body={id:'u',role:'teacher'};
    else if(p==='/auth/settings')body={use_marking_preferences:automaticPreferences,has_approved_profile:Boolean(expandedProfile),survey_completed:Boolean(expandedProfile)};
    else if(p==='/exams') body=[{id:'e',course_id:'c',title:'Synthetic physics pilot',course_code:'TEST'},{id:'e2',course_id:'c2',title:'Other assessment'}];
    else if(p==='/submissions') body=[];
    else if(p==='/jobs') body={items:[]};
    else if(p==='/instructor-preference-versions') body=expandedProfile?[expandedProfile]:[];
    else if(p.endsWith('/setup-readiness')) body={ready:true,questions:[{question_id:'q',question_number:'1',max_score:2,approved:true,rubric_version:1}],message:'Approved definitions checked.'};
    else if(p.endsWith('/marking-guide'))body={exam_id:p.split('/')[2],review_token:'a'.repeat(64),can_approve:true,pending_count:vs[0].status==='draft'||keys[0]?.status==='draft' ? 1 : 0,total_marks:qs.length*2,errors:[],warnings:[],questions:(p.includes('/e2/') ? [{id:'q2',question_number:'2',question_text:'Other wording',max_score:2}] : qs).map(q=>({question_id:q.id,question_number:q.question_number,question_text:q.question_text,max_score:2,grading_input:'image_text_required',rubric_status:vs[0].status,rubric:vs[0].rubric_json,answer_key:keys[0] || {mode:'no_fixed_answer'},sources:withSources?{mode:'required',bindings:[{version_id:'v',page_indices:[0]}]}:null,source_exception:null,source_references:withSources?[{title:'Synthetic chapter: work and energy',version_id:'v',version_number:1,page_indices:[0]}]:[],errors:[],warnings:[]}))};
    else if(p.endsWith('/marking-guide/approve')){writes.push({kind:'approve'});if(failApprove)return route.fulfill({status:503,json:{detail:'Synthetic approval outage'}});vs[0].status='approved';if(keys[0])keys[0].status='approved';body={exam_id:'e',approved_version_ids:['d'],message:'Assessment guide approved.'};}
    else if(p.startsWith('/exams/') && p.endsWith('/material-scopes')) body={versions:withSources?[{id:'ds',version_number:1,status:'draft',mode:'required',bindings:[{version_id:'v',page_indices:[0]}]}]:[],questions:[]};
    else if(p.endsWith('/questions')) {
      if(method==='GET') {if(holdQuestion && p.includes('/e/')) await questionGate;body=p.includes('/e2/') ? [{id:'q2',question_number:'2',question_text:'Other wording',max_score:2}] : qs;}
      else {writes.push({kind:'question',body:req.postDataJSON()});if(failCreate) return route.fulfill({status:503,json:{detail:'Synthetic interrupted creation'}});const q={id:'new',question_number:'2',question_text:req.postDataJSON().question_text,max_score:2};qs.push(q);vs=[{id:'new-r',version_number:1,status:'draft',rubric_json:{...base,criteria:req.postDataJSON().criteria}}];body=q;}
    } else if(method==='DELETE'&&/^\/questions\/[^/]+$/.test(p)){
      writes.push({kind:'delete',id:p.split('/')[2]});if(holdDelete)await deleteGate;
      if(failDelete)return route.fulfill({status:failDelete==='uncertain'?503:409,json:{detail:failDelete==='uncertain'?'Synthetic deletion interruption':'Papers already exist for this assessment. This question cannot be deleted.'}});
      qs=qs.filter(q=>q.id!==p.split('/')[2]);return route.fulfill({status:204});
    } else if(p.endsWith('/rubric')) body={rubric:base,rubric_version_id:'r'};
    else if(p.endsWith('/rubric-versions')) {
      if(method==='GET') body=vs;
      else {writes.push({kind:'draft',body:req.postDataJSON()});const rubric=structuredClone(req.postDataJSON().rubric);if(req.postDataJSON().apply_instructor_preferences&&automaticPreferences&&expandedProfile)Object.assign(rubric.policy,expandedProfile.derived_proposal);body={id:'d',version_number:2,status:'draft',rubric_json:rubric};vs=[body,...vs];}
    } else if(p.startsWith('/rubric-versions/')) {
      if(holdSave && method==='PUT') await saveGate;
      if(p.endsWith('/approve')) {writes.push({kind:'approve'});if(failApprove) return route.fulfill({status:503,json:{detail:'Synthetic approval outage'}});vs[0].status='approved';body={message:'Approved'};}
      else {writes.push({kind:'save',body:req.postDataJSON()});if(failSave) return route.fulfill({status:422,json:{detail:'Synthetic validation rejection'}});vs[0].rubric_json=req.postDataJSON().rubric;body=vs[0];}
    } else if(p.endsWith('/suggest-rubric-version')) {writes.push({kind:'suggest',body:req.postDataJSON()});body={id:'ai',version_number:2,status:'draft',rubric_json:base};vs=[body,...vs];}
    else if(p.endsWith('/grading-policy')) {if(method==='PUT') writes.push({kind:'routing',body:req.postDataJSON()});body={mode:'adaptive'};}
    else if(p.includes('/answer-key-versions')) {
      if(method==='GET') body=keys;
      else if(p.endsWith('/approve')) {writes.push({kind:'key-approve'});keys[0].status='approved';body=keys[0];}
      else {writes.push({kind:'key-save',body:req.postDataJSON()});body={id:'k',version_number:1,status:'draft',...req.postDataJSON()};keys=[body];}
    } else if(p.endsWith('/materials/text')) {writes.push({kind:'material',body:req.postDataJSON()});body={id:'m',title:req.postDataJSON().title,versions:[{id:'v',version_number:1,status:'draft',ingestion_status:'ready',media_type:'text/plain',page_count:1,approved_page_indices:[]}]};materials=[body];}
    else if(p.endsWith('/materials')) body=materials;
    else if(p.includes('/materials/') && p.endsWith('/pages')) body={version:materials[0].versions[0],items:[{page_index:0,text:'W = Fd.',text_sha256:'a'.repeat(64),chunks:[]}]};
    else if(p.includes('/materials/') && method==='PUT') {writes.push({kind:'page',body:req.postDataJSON()});body={};}
    else if(p.includes('/materials/') && p.endsWith('/approve')) {writes.push({kind:'material-approve',body:req.postDataJSON()});materials[0].versions[0].status='approved';materials[0].versions[0].approved_page_indices=[0];body=materials[0].versions[0];}
    else if(p.endsWith('/material-scopes')) body=[];
    else if(p.endsWith('/effective-material-scope')) body={origin:'none'};
    await route.fulfill({json:body});
  });
  await page.goto('/app/index.html?exam_id=e');await expect(page.locator('#exam-title')).toHaveText('Synthetic physics pilot');await page.locator('#sources-link').click();
  return {writes,releaseSave,releaseQuestion,releaseDelete};
}
async function edit(page) {await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();await expect(page.locator('#ac-0-title')).toHaveValue('Work calculation');await page.getByRole('button',{name:'Create editable draft',exact:true}).click();await expect(page.getByRole('button',{name:'Save draft',exact:true})).toBeVisible();}

test('delete question cancels without losing edits, then removes only the chosen draft',async({page})=>{
  const state=await fixture(page,{withSources:true});await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();
  await page.locator('#ac-0-title').fill('Unsaved selected question edit');
  page.once('dialog',d=>d.dismiss());await page.getByRole('button',{name:'Delete question',exact:true}).click();
  await expect(page.locator('#ac-0-title')).toHaveValue('Unsaved selected question edit');expect(state.writes).toHaveLength(0);
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Delete question',exact:true}).click();
  await expect(page.locator('#guide-outline')).toBeVisible();await expect(page.locator('[data-guide-question="q"]')).toHaveCount(0);
  await expect(page.locator('#guide-outline [data-guide-question="q-other"]')).toBeVisible();await expect(page.locator('#guide-total')).toContainText('1 questions · 2 marks');
  expect(state.writes).toEqual([{kind:'delete',id:'q'}]);await expect(page.locator('#author-new-question')).toBeFocused();
  await page.reload();await page.locator('#sources-link').click();await page.locator('#author-rubrics').click();await expect(page.locator('[data-guide-question="q"]')).toHaveCount(0);
});

test('deleting the last draft question leaves an actionable empty guide',async({page})=>{
  const state=await fixture(page,{initialDraft:true});await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Delete question',exact:true}).click();
  await expect(page.locator('#guide-outline')).toContainText('Add an exam question');await expect(page.locator('#guide-total')).toContainText('0 questions · 0 marks');
  expect(state.writes).toEqual([{kind:'delete',id:'q'}]);await expect(page.locator('#author-new-question')).toBeEnabled();
});

test('rejected deletion keeps the draft, unsaved criterion and original key text',async({page})=>{
  const state=await fixture(page,{withSources:true,failDelete:true});await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();
  await page.locator('#ac-0-title').fill('Keep this unsaved criterion');page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Delete question',exact:true}).click();
  await expect(page.locator('#author-error')).toContainText('Papers already exist');await expect(page.locator('#ac-0-title')).toHaveValue('Keep this unsaved criterion');
  await expect(page.locator('#native-authoring')).toBeVisible();await expect(page.locator('#author-state')).toContainText('Unsaved');expect(state.writes).toEqual([{kind:'delete',id:'q'}]);
});

test('unconfirmed question deletion requires a reload before another write',async({page})=>{
  const state=await fixture(page,{initialDraft:true,failDelete:'uncertain'});await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Delete question',exact:true}).click();
  await expect(page.locator('#author-error')).toContainText('Synthetic deletion interruption');await expect(page.locator('#author-state')).toContainText('Change not confirmed');
  await expect(page.locator('[data-author-delete]')).toBeDisabled();await expect(page.locator('#author-new-question')).toBeDisabled();await expect(page.locator('#author-reload')).toBeEnabled();
  expect(state.writes).toEqual([{kind:'delete',id:'q'}]);await page.locator('#author-reload').click();await expect(page.locator('[data-author-delete]')).toBeEnabled();
});

test('discard question removes an unsaved addition without an API write',async({page})=>{
  const state=await fixture(page);await edit(page);const before=state.writes.length;await page.locator('#author-new-question').click();await page.locator('#author-question-text').fill('Accidental unsaved question');
  page.once('dialog',d=>d.dismiss());await page.getByRole('button',{name:'Discard question',exact:true}).click();await expect(page.locator('#author-question-text')).toHaveValue('Accidental unsaved question');
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Discard question',exact:true}).click();await expect(page.locator('#guide-outline')).toBeVisible();
  expect(state.writes.length).toBe(before);await expect(page.locator('#guide-total')).toContainText('1 questions · 2 marks');
});

test('approved question history disables deletion and explains why',async({page})=>{
  await fixture(page);await edit(page);await expect(page.getByRole('button',{name:'Delete question',exact:true})).toBeDisabled();
  await expect(page.locator('#question-delete-help')).toHaveText('Only unused draft questions can be deleted.');
});

test('pending question deletion locks duplicate actions and navigation',async({page})=>{
  const state=await fixture(page,{initialDraft:true,holdDelete:true});await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Delete question',exact:true}).click();
  await expect(page.locator('[data-author-delete]')).toBeDisabled();await expect(page.locator('#author-new-question')).toBeDisabled();
  await page.locator('#author-back').click();await expect(page.locator('#native-authoring')).toBeVisible();expect(state.writes.filter(w=>w.kind==='delete')).toHaveLength(1);
  state.releaseDelete();await expect(page.locator('#guide-outline')).toBeVisible();
});

test('delete question action fits the question editor in both themes and Arabic',async({page},info)=>{
  await fixture(page,{initialDraft:true});await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();
  for(const variant of ['light','dark','rtl']){
    if(variant==='dark')await page.locator('#theme').click();if(variant==='rtl')await page.locator('#app-language').click();
    await expect(page.locator('[data-author-delete]')).toBeEnabled();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'.impeccable/review/question-delete-after-'+variant+'-'+info.project.name+'.png',fullPage:true,animations:'disabled'});
  }
});

test('expanded approved preferences apply to a rubric draft with explicit confirmation',async({page})=>{
  const state=await fixture(page,{expandedProfile:{id:'expanded',status:'approved',version_number:2,derived_proposal:{units_policy:'do_not_penalize',rounding_tolerance_percent:0,evidence_requirement:'complete_reasoning',illegible_response_policy:'manual_review',arithmetic_error_policy:'single_penalty',custom_instructions:'Flag contradictory answers for instructor review.'}}});
  await edit(page);await page.locator('[data-author-section=options]>summary').click();page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'Use my approved profile',exact:true}).click();
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  const policy=state.writes.filter(w=>w.kind==='save').at(-1)?.body.rubric.policy;
  expect(policy).toMatchObject({units_policy:'do_not_penalize',rounding_tolerance_percent:0,evidence_requirement:'complete_reasoning',illegible_response_policy:'manual_review'});
  expect(policy.custom_instructions).toContain('Flag contradictory answers');expect(state.writes.some(w=>w.kind==='approve')).toBeFalsy();
});

test('new drafts automatically use survey rules while approved rules stay unchanged',async({page})=>{
  const state=await fixture(page,{expandedProfile:{id:'profile',status:'approved',derived_proposal:{units_policy:'do_not_penalize',rounding_tolerance_percent:0}}});
  await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();
  await expect(page.locator('#ap-units_policy')).toHaveValue('required');
  await page.getByRole('button',{name:'Create editable draft',exact:true}).click();
  await expect(page.locator('#ap-units_policy')).toHaveValue('do_not_penalize');await expect(page.locator('#ap-rounding')).toHaveValue('0');
  expect(state.writes.find(w=>w.kind==='draft').body.apply_instructor_preferences).toBeTruthy();expect(state.writes.some(w=>w.kind==='approve')).toBeFalsy();
  await page.locator('#author-new-question').click();await expect(page.locator('#ap-units_policy')).toHaveValue('do_not_penalize');
});

test('opting out keeps standard rules in newly created drafts',async({page})=>{
  await fixture(page,{expandedProfile:{id:'profile',status:'approved',derived_proposal:{units_policy:'do_not_penalize'}},automaticPreferences:false});
  await edit(page);await expect(page.locator('#ap-units_policy')).toHaveValue('required');
  await page.locator('#author-new-question').click();await expect(page.locator('#ap-units_policy')).toHaveValue('required_when_applicable');
});

test('optional survey reminder does not block rubric work and stays dismissed for the session',async({page},info)=>{
  const state=await fixture(page);await edit(page);
  await expect(page.locator('.survey-reminder')).toContainText('Personalize your marking rules · Optional');
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'.impeccable/review/rubric-survey-optional-'+info.project.name+'.png',fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'Not now',exact:true}).click();await expect(page.locator('.survey-reminder')).toHaveCount(0);
  await page.getByRole('button',{name:'Save draft',exact:true}).click();expect(state.writes.some(w=>w.kind==='save')).toBeTruthy();
  await page.reload();await page.locator('#sources-link').click();await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();
  await expect(page.locator('.survey-reminder')).toHaveCount(0);
});

test('taking the survey saves an edited rubric first and stays on failed save',async({page})=>{
  const state=await fixture(page,{failSave:true});await edit(page);await page.locator('#ac-0-title').fill('Unsaved synthetic criterion');
  await page.getByRole('button',{name:'Take survey',exact:true}).click();
  await expect(page.locator('#author-error')).toContainText('Synthetic validation rejection');await expect(page.locator('#ac-0-title')).toHaveValue('Unsaved synthetic criterion');
  await expect(page).not.toHaveURL(/marking-survey.html/);expect(state.writes.some(w=>w.kind==='save')).toBeTruthy();
});

test('taking the survey saves valid edits and returns to the same assessment',async({page})=>{
  const state=await fixture(page);await edit(page);await page.locator('#ac-0-title').fill('Saved before survey');
  await page.getByRole('button',{name:'Take survey',exact:true}).click();await expect(page).toHaveURL(/marking-survey.html\?return_exam_id=e/);
  expect(state.writes.filter(w=>w.kind==='save').at(-1).body.rubric.criteria[0].title).toBe('Saved before survey');
  await expect(page.locator('#survey-continue')).toHaveAttribute('href','setup.html?exam_id=e');
});

test('a new untouched question can open the optional survey without a blank-question validation error',async({page})=>{
  const state=await fixture(page);await edit(page);await page.locator('#author-new-question').click();
  await page.getByRole('button',{name:'Take survey',exact:true}).click();await expect(page).toHaveURL(/marking-survey.html\?return_exam_id=e/);
  expect(state.writes.filter(w=>w.kind==='question')).toHaveLength(0);
});

test('rubric workspace visual evidence',async({page},info)=>{
  await fixture(page,{withSources:true});
  await page.locator('#author-rubrics').click();
  await expect(page.locator('#guide-outline')).toContainText('equal force-distance');
  const phase=process.env.MISRA_CAPTURE_PHASE || 'after';
  for(const theme of ['light','dark']) {
    if(await page.locator('html').getAttribute('data-theme')!==theme) await page.locator('#theme').click();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:`.impeccable/review/rubric-${phase}-outline-${theme}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  }
  await page.locator('[data-guide-question="q"]').first().click();
  await expect(page.locator('#ac-0-title')).toHaveValue('Work calculation');
  for(const theme of ['light','dark']) {
    if(await page.locator('html').getAttribute('data-theme')!==theme) await page.locator('#theme').click();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:`.impeccable/review/rubric-${phase}-editor-${theme}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  }
});

test('focused question replaces the outline and returning saves without approval',async({page})=>{
  const state=await fixture(page,{withSources:true});
  await page.locator('#author-rubrics').click();
  await page.locator('#guide-outline [data-guide-question="q"]').click();
  await expect(page.locator('#guide-outline')).toBeHidden();
  await expect(page.locator('#author-back')).toBeFocused();
  await page.locator('#ac-0-title').fill('Credit for work and units');
  await page.locator('#author-back').click();
  await expect(page.locator('#native-authoring')).toBeHidden();
  await expect(page.locator('#guide-outline')).toContainText('Credit for work and units');
  expect(state.writes.filter(w=>w.kind==='save')).toHaveLength(1);
  expect(state.writes.some(w=>w.kind==='approve')).toBeFalsy();
  await page.locator('#author-new-question').click();
  await expect(page.locator('#guide-outline')).toBeHidden();
  await expect(page.locator('#author-question-text')).toBeFocused();
  await expect(page.locator('#author-question')).toHaveValue('');
});

test('failed return to whole guide retains the focused question and its edits',async({page})=>{
  const state=await fixture(page,{withSources:true,failSave:true});
  await page.locator('#author-rubrics').click();
  await page.locator('#guide-outline [data-guide-question="q"]').click();
  await page.locator('#ac-0-title').fill('Keep this draft');
  await page.locator('#author-back').click();
  await expect(page.locator('#guide-outline')).toBeHidden();
  await expect(page.locator('#ac-0-title')).toHaveValue('Keep this draft');
  await expect(page.locator('#author-error')).toContainText('Synthetic validation rejection');
  await expect(page.locator('#author-state')).toContainText('Unsaved');
  expect(state.writes.some(w=>w.kind==='approve')).toBeFalsy();
});

test('collapsed criteria retain credit rules and add/remove restores keyboard focus',async({page})=>{
  const state=await fixture(page,{multipleCriteria:true});await edit(page);
  const second=page.locator('[data-criterion-panel="units"]');
  await expect(second).not.toHaveAttribute('open','');
  await second.locator(':scope > summary').focus();await page.keyboard.press('Enter');
  await expect(second).toHaveAttribute('open','');
  await page.locator('#ac-1-description').fill('Award this mark for joules (J).');
  await second.locator(':scope > summary').click();
  await page.getByRole('button',{name:'Add criterion',exact:true}).click();
  await expect(page.locator('#ac-2-title')).toBeFocused();
  await page.locator('#ac-2-title').fill('Temporary criterion');
  await page.locator('[data-author-remove="2"]').click();
  await expect(second.locator(':scope > summary')).toBeFocused();
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await expect(page.locator('#author-state')).toContainText('Draft saved');
  const saved=state.writes.find(w=>w.kind==='save').body.rubric;
  expect(saved.criteria).toHaveLength(2);
  expect(saved.criteria[1]).toMatchObject({id:'units',scoring_type:'binary',partial_credit_allowed:false,required_evidence:['Joules'],description:'Award this mark for joules (J).'});
  expect(saved.criteria[0].performance_levels).toHaveLength(1);
  expect(saved.policy.units_policy).toBe('required');
  expect(state.writes.some(w=>w.kind==='approve')).toBeFalsy();
});

test('native rubric draft preserves detailed rules and approval is explicit',async({page})=>{
  const state=await fixture(page);await edit(page);await page.locator('#ac-0-title').fill('Correct work and units');await page.getByRole('button',{name:'Save draft',exact:true}).click();await expect(page.locator('#author-state')).toContainText('Draft saved');
  const body=state.writes.find(w=>w.kind==='save').body.rubric;
  expect(body.policy.grading_approach).toBe('strict');expect(body.policy.rounding_tolerance_percent).toBe(1);expect(body.policy.alternative_methods_allowed).toBe(false);
  expect(body.criteria[0].partial_credit_allowed).toBe(false);expect(body.criteria[0].performance_levels).toHaveLength(1);expect(body.criteria[0].common_errors).toHaveLength(1);expect(body.criteria[0].id).toBe('work');expect(state.writes.some(w=>w.kind==='approve')).toBeFalsy();
  await page.locator('#guide-review-tab').click();await page.locator('#guide-confirm').check();await page.locator('#guide-approve').click();await expect(page.locator('#guide-approval-state')).toContainText('approved');expect(state.writes.filter(w=>w.kind==='approve')).toHaveLength(1);
});
test('failed save retains inputs and invalid totals cannot be sent',async({page})=>{
  const state=await fixture(page,{failSave:true});await edit(page);await page.locator('#ac-0-points').fill('1');await page.getByRole('button',{name:'Save draft',exact:true}).click();await expect(page.locator('#ledger-notice')).toContainText('Criteria total');expect(state.writes.some(w=>w.kind==='save')).toBeFalsy();
  await page.locator('#ac-0-points').fill('2');await page.locator('#ac-0-title').fill('Retained edit');await page.getByRole('button',{name:'Save draft',exact:true}).click();await expect(page.locator('#rubric-workspace [role="alert"]')).toContainText('Synthetic validation');await expect(page.locator('#ac-0-title')).toHaveValue('Retained edit');await expect(page.locator('#author-state')).toContainText('Unsaved');
});
test('approval failure keeps saved draft and does not falsely report approval',async({page})=>{
  await fixture(page,{failApprove:true});await edit(page);await page.locator('#guide-review-tab').click();await page.locator('#guide-confirm').check();await page.locator('#guide-approve').click();await expect(page.locator('#guide-approval-state')).toContainText('Synthetic approval outage');await expect(page.locator('#guide-approve')).toBeDisabled();await page.locator('#guide-refresh').click();await expect(page.locator('#guide-confirm')).not.toBeChecked();
});
test('busy and unsaved rubric states protect assessment and task changes',async({page})=>{
  const state=await fixture(page,{holdSave:true});await edit(page);await page.locator('#ac-0-title').fill('Protected');page.once('dialog',d=>d.dismiss());await page.locator('[data-exam="e2"]').click();await expect(page.locator('#native-authoring')).toBeVisible();
  await page.getByRole('button',{name:'Save draft',exact:true}).click();await page.locator('[data-exam="e2"]').click();await expect(page.locator('#exam-title')).toHaveText('Synthetic physics pilot');await expect(page.locator('#author-foundations')).toHaveAttribute('disabled','');state.releaseSave();await expect(page.locator('#author-state')).toContainText('Draft saved');
});
test('new question requests a real initial draft, not approval',async({page})=>{
  const state=await fixture(page);await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();await expect(page.locator('#ac-0-title')).toBeVisible();await page.locator('#author-new-question').click();await page.locator('#author-question-text').fill('Calculate work for the given force and distance.');await page.locator('#author-max').fill('2');await page.locator('#ac-0-title').fill('Calculation');await page.locator('#ac-0-description').fill('Use the formula and give units');await page.locator('#ac-0-points').fill('2');await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await expect(page.locator('#author-question')).toHaveValue('new');expect(state.writes.find(w=>w.kind==='question').body.approve_initial_rubric).toBe(false);expect(state.writes.some(w=>w.kind==='approve')).toBeFalsy();
});
test('answer key is independently saved, guarded and explicitly approved',async({page})=>{
  const state=await fixture(page);await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();await expect(page.locator('#ac-0-title')).toBeVisible();await page.locator('#author-key-section>summary').click();await expect(page.locator('#key-reference')).toBeVisible();await page.locator('#key-reference').fill('W = Fd = 246 J.');
  page.once('dialog',d=>d.dismiss());await page.locator('[data-exam="e2"]').click();await expect(page.locator('#key-reference')).toHaveValue('W = Fd = 246 J.');await page.getByRole('button',{name:'Save answer-key draft',exact:true}).click();await expect(page.locator('#answer-key-panel')).toContainText('draft');expect(state.writes.some(w=>w.kind==='key-approve')).toBeFalsy();
  await page.locator('#guide-review-tab').click();await page.locator('#guide-confirm').check();await page.locator('#guide-approve').click();await expect.poll(()=>state.writes.filter(w=>w.kind==='approve').length).toBe(1);expect(state.writes.filter(w=>w.kind==='key-approve')).toHaveLength(0);
});
test('native course library saves notes, reviews text and approves checked pages',async({page},info)=>{
  const state=await fixture(page);await page.locator('#manage-course-library').click();await page.locator('.material-add>summary').click();await page.locator('#material-title').fill('Synthetic teaching notes');await page.locator('#material-text').fill('W = Fd. Work is force times displacement in its direction.');await page.getByRole('button',{name:'Add material draft',exact:true}).click();await expect(page.locator('#native-library')).toContainText('Text draft saved');
  await page.getByRole('button',{name:'Review source pages',exact:true}).click();await expect(page.locator('#material-page-text')).toHaveValue('W = Fd.');await page.locator('#material-page-text').fill('Verified work: W = Fd.');await page.getByRole('button',{name:'Save page correction',exact:true}).click();await expect(page.locator('#native-library')).toContainText('Corrected transcription saved');await page.locator('#material-approved-pages').fill('1');await page.locator('[data-material-approval] [type=checkbox]').check();await page.getByRole('button',{name:'Approve selected source pages',exact:true}).click();await expect(page.locator('#native-library')).toContainText('Approved document pages: 1');expect(state.writes.find(w=>w.kind==='material-approve').body.page_indices).toEqual([0]);await expect(page.locator('#material-page-text')).toHaveAttribute('readonly','');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/ledger-library-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/ledger-library-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});
test('stale question load cannot replace a newly selected assessment',async({page})=>{
  const state=await fixture(page,{holdQuestion:true});await page.locator('#author-rubrics').click();await page.locator('[data-exam="e2"]').click();state.releaseQuestion();await expect(page.locator('#exam-title')).toHaveText('Other assessment');await page.locator('#sources-link').click();await page.locator('#author-rubrics').click();await page.locator('#guide-outline [data-guide-question="q2"]').click();await expect(page.locator('#author-question-text')).toHaveValue('Other wording');
});
test('native authoring is responsive in both themes',async({page},info)=>{
  await fixture(page);await edit(page);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});await page.screenshot({path:`.impeccable/review/ledger-authoring-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/ledger-authoring-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});
test('pending question read cannot overwrite the course-library task',async({page})=>{
  const state=await fixture(page,{holdQuestion:true});await page.locator('#author-rubrics').click();await page.locator('#guide-sources-tab').click();await page.locator('#manage-course-library').click();await expect(page.locator('#native-library')).toBeVisible();state.releaseQuestion();await expect(page.locator('#native-authoring')).toBeHidden();await page.locator('.material-add>summary').click();await page.locator('#material-title').fill('Retained library draft');await page.locator('#manage-course-library').click();await expect(page.locator('#material-title')).toHaveValue('Retained library draft');await expect(page.locator('#library-material-host')).not.toContainText('Sources for this question');
});
test('plain-language detailed credit controls preserve and validate scoring levels',async({page})=>{
  const state=await fixture(page);await edit(page);await page.locator('[data-author-criterion] details>summary').click();await page.locator('#al-0-0-points').fill('3');await page.getByRole('button',{name:'Save draft',exact:true}).click();await expect(page.locator('#author-error')).toContainText('Credit levels');expect(state.writes.some(w=>w.kind==='save')).toBeFalsy();await page.locator('#al-0-0-points').fill('2');await page.getByRole('button',{name:'Add common mistake',exact:true}).click();await page.locator('#ae-0-1-description').fill('Missing units');await page.locator('#ae-0-1-guidance').fill('Follow the units policy');await page.getByRole('button',{name:'Save draft',exact:true}).click();await expect(page.locator('#author-state')).toContainText('Draft saved');expect(state.writes.find(w=>w.kind==='save').body.rubric.criteria[0].common_errors).toHaveLength(2);
});
test('AI proposal is a draft, never automatic approval or policy relaxation',async({page})=>{
  const state=await fixture(page);await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();await expect(page.locator('#ac-0-title')).toBeVisible();await page.getByText('AI rubric suggestion',{exact:true}).click();await page.locator('#author-ai-method').fill('Use W = Fd');await page.getByRole('button',{name:'Generate AI draft',exact:true}).click();await expect(page.locator('#author-state')).toContainText('AI draft created');expect(state.writes.find(w=>w.kind==='suggest').body.policy.units_policy).toBe('required');expect(state.writes.some(w=>w.kind==='approve')).toBeFalsy();
});
test('uncertain new-question acceptance blocks duplicate creation until reloaded',async({page})=>{
  const state=await fixture(page,{failCreate:true});await page.locator('#author-rubrics').click();await page.locator('[data-guide-question="q"]').first().click();await expect(page.locator('#ac-0-title')).toBeVisible();await page.locator('#author-new-question').click();await page.locator('#author-question-text').fill('Synthetic new question');await page.locator('#ac-0-title').fill('Work');await page.locator('#ac-0-description').fill('Credit for the result');await page.getByRole('button',{name:'Save draft',exact:true}).click();await expect(page.locator('#author-state')).toContainText('Reload questions');await expect(page.getByRole('button',{name:'Save draft',exact:true})).toBeDisabled();expect(state.writes.filter(w=>w.kind==='question')).toHaveLength(1);
});

test('source-led whole guide has one approval and automatically saves edited credit',async({page},info)=>{
  const state=await fixture(page,{withSources:true});await expect(page.locator('#guide-sources-stage')).toBeVisible();await expect(page.locator('#assessment-sources-host')).toContainText('Synthetic chapter: work and energy');await expect(page.locator('[data-default-approve]')).toBeHidden();
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/assessment-guide-sources-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/assessment-guide-sources-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();
  await page.locator('#author-rubrics').click();await expect(page.locator('#guide-outline')).toContainText('equal force-distance');await expect(page.locator('#native-authoring')).toBeHidden();await expect(page.locator('#guide-total')).toContainText('2 questions');await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/assessment-guide-outline-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/assessment-guide-outline-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();
  await page.locator('#guide-outline [data-guide-question="q"]').click();await expect(page.locator('[data-author-approve]')).toHaveCount(0);await page.locator('#ac-0-title').fill('Correct method and units');await page.locator('#guide-review-tab').click();await expect(page.locator('#guide-review')).toBeVisible();expect(state.writes.filter(w=>w.kind==='save')).toHaveLength(1);expect(state.writes.filter(w=>w.kind==='approve')).toHaveLength(0);await expect(page.locator('#guide-approve')).toBeDisabled();await page.locator('#guide-expand').click();await expect(page.locator('#guide-expand')).toHaveAttribute('aria-expanded','true');await expect(page.locator('#guide-review-content')).toContainText('Synthetic chapter: work and energy');await expect(page.locator('#guide-review-content')).toContainText('Correct method and units');
  await page.locator('.guide-credit-review>summary').filter({hasText:'Detailed credit & evidence'}).first().click();await expect(page.locator('#guide-review-content')).toContainText('Partial credit: Not allowed');await expect(page.locator('#guide-review-content')).toContainText('Arithmetic error');await expect(page.locator('#guide-review-content')).toContainText('Equivalent rearrangement');await page.locator('.guide-credit-review>summary').filter({hasText:'Retained rubric references & notes'}).first().click();await expect(page.locator('#guide-review-content')).toContainText('Synthetic instructor note');await expect(page.locator('#guide-review-content')).toContainText('Equivalent force-distance product');await expect(page.locator('#guide-review-content')).toContainText('image text required');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/assessment-guide-review-${info.project.name}.png`,fullPage:true,animations:'disabled'});await page.locator('#theme').click();await page.screenshot({path:`.impeccable/review/assessment-guide-review-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#guide-confirm').check();await page.locator('#guide-approve').click();await expect(page.locator('#guide-approval-state')).toContainText('approved');expect(state.writes.filter(w=>w.kind==='approve')).toHaveLength(1);expect(state.writes.filter(w=>w.kind==='key-approve')).toHaveLength(0);
});

test('invalid unsaved criteria keep the instructor in editing and never approve',async({page})=>{
  const state=await fixture(page,{withSources:true});await page.locator('#author-rubrics').click();await page.locator('#guide-outline [data-guide-question="q"]').click();await page.locator('#ac-0-points').fill('1');await page.locator('#guide-review-tab').click();await expect(page.locator('#guide-review')).toBeHidden();await expect(page.locator('#author-error')).toContainText('Criteria total');await expect(page.locator('#ac-0-points')).toHaveValue('1');expect(state.writes.filter(w=>w.kind==='approve')).toHaveLength(0);
});
