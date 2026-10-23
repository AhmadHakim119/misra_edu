const {test,expect}=require('@playwright/test');
async function fixture(page,{oldProfile=false,automaticPreferences=true}={}){
  const state={versions:oldProfile?[{id:'old',version_number:1,status:'approved',scenario_answers:[{scenario_id:'valid_alternative_method',selected_option:'full_credit'}],explicit_preferences:{},derived_proposal:{method_credit:'full_if_valid'}}]:[],writes:[]};
  await page.route('**/api/**',route=>{
    const p=new URL(route.request().url()).pathname.replace('/api',''),method=route.request().method();let body=[];
    if(p==='/auth/me')body={id:'synthetic',full_name:'Synthetic instructor',role:'admin'};
    else if(p==='/auth/settings')body={use_marking_preferences:automaticPreferences,has_approved_profile:state.versions.some(v=>v.status==='approved'),survey_completed:state.versions.some(v=>v.status==='approved'&&v.scenario_answers.length===12)};
    else if(p==='/jobs')body={items:[],active_count:0};
    else if(p==='/instructor-preference-suggestions')body={suggestions:[]};
    else if(p==='/instructor-preference-versions'){
      if(method==='POST'){state.writes.push(route.request().postDataJSON());body={id:'new',version_number:2,status:'draft',...state.writes.at(-1),derived_proposal:{units_policy:'required'}};state.versions.unshift(body);}else body=state.versions;
    }else if(p==='/instructor-preference-versions/new/approve'){state.versions[0].status='approved';body=state.versions[0];}
    return route.fulfill({json:body});
  });return state;
}

async function navFits(page){
  const bounds=await page.evaluate(()=>{
    const box=selector=>document.querySelector(selector).getBoundingClientRect().toJSON();
    return {bar:box('.app-bar'),nav:box('.app-bar nav'),account:box('.account'),mobile:innerWidth<=700,rtl:document.documentElement.dir==='rtl'};
  });
  if(bounds.mobile)expect(bounds.nav.top).toBeGreaterThanOrEqual(bounds.account.bottom);
  else if(bounds.rtl)expect(bounds.account.right).toBeLessThanOrEqual(bounds.nav.left);
  else expect(bounds.nav.right).toBeLessThanOrEqual(bounds.account.left);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await expect.poll(()=>page.evaluate(()=>Math.abs(parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-bar-height'))-document.querySelector('.app-bar').getBoundingClientRect().height))).toBeLessThan(1);
}

test('Arabic dashboard navbar separates navigation and account controls at supported widths',async({page},info)=>{
  await fixture(page);await page.goto('/app/dashboard.html');await expect(page.locator('#marking-survey-invitation')).toBeVisible();await navFits(page);
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');await expect(page.locator('#marking-survey-invitation')).toContainText('١٢');await navFits(page);
  await page.screenshot({path:`.impeccable/review/arabic-navbar-light-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-theme').click();await page.screenshot({path:`.impeccable/review/arabic-navbar-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.setViewportSize({width:1024,height:768});await navFits(page);
});

test('expanded survey saves twelve real choices and requires completion before approval',async({page},info)=>{
  const state=await fixture(page);await page.goto('/app/marking-survey.html');await expect(page.locator('.preference-scenarios .preference-scenario')).toHaveCount(12);
  await page.getByRole('checkbox',{name:'Calculations',exact:true}).check();
  await page.getByRole('checkbox',{name:'Multiple choice',exact:true}).check();
  await page.locator('[data-context="question_style_notes"]').fill('Connected physics problems with methods and results.');
  await page.locator('[data-scenario=valid_alternative_method]').first().check();await page.getByRole('button',{name:'Save & approve profile'}).click();await expect(page.locator('#marking-preferences')).toContainText('Answer all 12');expect(state.writes).toHaveLength(0);
  const ids=await page.locator('.preference-scenarios .preference-scenario').evaluateAll(rows=>rows.map(row=>row.querySelector('[data-scenario]').dataset.scenario));
  for(const id of ids)await page.locator(`[data-scenario="${id}"]`).first().check();
  await expect(page.locator('#marking-preferences [role=alert]')).toHaveCount(0);
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');await navFits(page);
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/survey-twelve-rtl-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-language').click();page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'Save & approve profile'}).click();
  expect(state.writes[0].scenario_answers).toHaveLength(12);
  expect(state.writes[0].explicit_preferences.teaching_context.question_types).toEqual(['calculation','multiple_choice']);
  await expect(page.locator('#survey-saved')).toContainText('Survey done');
  await page.reload();await expect(page.locator('[data-scenario]:checked')).toHaveCount(12);await expect(page.locator('[data-scenario]').first()).toBeDisabled();
  await expect(page.getByRole('checkbox',{name:'Calculations',exact:true})).toBeChecked();
  await expect(page.getByRole('checkbox',{name:'Multiple choice',exact:true})).toBeChecked();
  await expect(page.getByRole('checkbox',{name:'Multiple choice',exact:true})).toBeDisabled();
  await expect(page.locator('[data-context="question_style_notes"]')).toHaveValue('Connected physics problems with methods and results.');
});

test('survey explains structured validation errors and retains all entries for retry',async({page},info)=>{
  const state=await fixture(page);let reject=true;
  await page.route('**/api/instructor-preference-versions',route=>{
    if(route.request().method()==='POST'&&reject){reject=false;return route.fulfill({status:422,json:{detail:[
      {loc:['body','explicit_preferences','teaching_context','question_types',0],msg:'Select a supported question type.',input:'PRIVATE_INPUT_MUST_NOT_APPEAR',ctx:{private:'PRIVATE_CONTEXT_MUST_NOT_APPEAR'}},
      {loc:['body','explicit_preferences','teaching_context','rubric_style_notes'],msg:'Synthetic <script>window.injected=true</script> validation failure.'},
    ]}});}
    return route.fallback();
  });
  await page.goto('/app/marking-survey.html');
  const ids=await page.locator('.preference-scenarios .preference-scenario').evaluateAll(rows=>rows.map(row=>row.querySelector('[data-scenario]').dataset.scenario));
  for(const id of ids)await page.locator(`[data-scenario="${id}"]`).first().check();
  await page.locator('[data-context="subjects"]').fill('Physics');
  await page.locator('[data-context="marking_style_notes"]').fill('Credit valid method and follow-through.');
  await page.getByRole('checkbox',{name:'Diagrams',exact:true}).check();
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Question types: Select a supported question type.');
  await expect(page.getByRole('alert')).toContainText('How you prefer marking guides written:');
  await expect(page.getByRole('alert')).not.toContainText('PRIVATE_INPUT_MUST_NOT_APPEAR');
  await expect(page.getByRole('alert')).not.toContainText('PRIVATE_CONTEXT_MUST_NOT_APPEAR');
  await expect(page.locator('[data-scenario]:checked')).toHaveCount(12);
  await expect(page.getByRole('checkbox',{name:'Diagrams',exact:true})).toBeChecked();
  await expect(page.locator('[data-context="marking_style_notes"]')).toHaveValue('Credit valid method and follow-through.');
  expect(await page.evaluate(()=>window.injected)).toBeUndefined();
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>{MisraTheme.set(theme);window.scrollTo(0,0);},theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.screenshot({path:`.impeccable/review/profile-save-error-${theme}-${info.project.name}.png`,animations:'disabled'});
  }
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await expect(page.locator('#survey-saved')).toContainText('draft is saved');
  expect(state.writes[0].scenario_answers).toHaveLength(12);
  expect(state.writes[0].explicit_preferences.teaching_context.question_types).toEqual(['diagram']);
});

test('Arabic teaching profile preserves notes and choices through failed save, approval and reload',async({page},info)=>{
  const state=await fixture(page);let reject=true;
  await page.route('**/api/instructor-preference-versions',route=>{
    if(route.request().method()==='POST'&&reject){reject=false;return route.fulfill({status:422,json:{detail:[
      {loc:['body','explicit_preferences','teaching_context','exam_language'],msg:'Synthetic retry required.'},
    ]}});}
    return route.fallback();
  });
  await page.goto('/app/marking-survey.html');
  const ids=await page.locator('.preference-scenarios .preference-scenario').evaluateAll(rows=>rows.map(row=>row.querySelector('[data-scenario]').dataset.scenario));
  for(const id of ids)await page.locator(`[data-scenario="${id}"]`).first().check();
  const notes={subjects:'Physics, فيزياء',question_style_notes:'Use energy_method with clear diagrams.',
    marking_style_notes:'أمنح درجات للطريقة الصحيحة.',rubric_style_notes:'Keep method_and_result separate.',
    other_question_types:'تفسير التجارب العملية'};
  await page.getByRole('checkbox',{name:'Other',exact:true}).check();
  for(const [key,value]of Object.entries(notes))await page.locator(`[data-context="${key}"]`).fill(value);
  await page.locator('[data-context="exam_language"]').selectOption('ar');
  await page.locator('#app-language').click();
  await expect(page.locator('html')).toHaveAttribute('dir','rtl');
  const profile=page.locator('[data-preference-form] > .preference-scenario');
  for(const label of ['ملفك التدريسي','كيف تضع الأسئلة','كيف تمنح الدرجات الجزئية','كيف تفضّل صياغة أدلة التصحيح','لغة الاختبارات المعتادة'])await expect(profile).toContainText(label);
  await expect(page.getByRole('checkbox',{name:'أخرى',exact:true})).toBeChecked();
  await expect(page.getByRole('checkbox',{name:'اختيار من متعدد',exact:true})).toBeVisible();
  await expect(page.locator('[data-context="exam_language"] option:checked')).toHaveText('العربية');
  await expect(page.getByRole('combobox',{name:'أسلوب التصحيح المعتاد',exact:true})).toBeVisible();
  for(const [key,value]of Object.entries(notes))await expect(page.locator(`[data-context="${key}"]`)).toHaveValue(value);
  await expect(page.locator('[data-scenario]:checked')).toHaveCount(12);
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>MisraTheme.set(theme),theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    // Isolate the tall fieldset without a sticky header covering its middle.
    await profile.screenshot({path:`.impeccable/review/profile-arabic-${theme}-${info.project.name}.png`,animations:'disabled',style:'.app-bar { visibility:hidden; }'});
  }
  await page.getByRole('button',{name:'حفظ المسودة',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('لغة الاختبارات المعتادة: Synthetic retry required.');
  await expect(page.getByRole('alert')).toContainText('ما زالت بياناتك موجودة.');
  for(const [key,value]of Object.entries(notes))await expect(page.locator(`[data-context="${key}"]`)).toHaveValue(value);
  await page.locator('#app-language').click();
  await expect(page.locator('[data-context="exam_language"]')).toHaveValue('ar');
  await expect(page.locator('[data-context="exam_language"] option:checked')).toHaveText('Arabic');
  await expect(page.locator('[data-scenario]:checked')).toHaveCount(12);
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Save & approve profile',exact:true}).click();
  await expect(page.locator('#survey-saved')).toContainText('Survey done');
  expect(state.writes[0].explicit_preferences.teaching_context).toMatchObject({exam_language:'ar',question_types:['other'],...notes,subjects:['Physics','فيزياء']});
  await page.reload();
  await expect(page.locator('[data-context="exam_language"]')).toHaveValue('ar');
  await expect(page.locator('[data-context="exam_language"]')).toBeDisabled();
  await expect(page.locator('[data-scenario]:checked')).toHaveCount(12);
  for(const [key,value]of Object.entries(notes))await expect(page.locator(`[data-context="${key}"]`)).toHaveValue(value);
  await page.locator('#app-language').click();await page.reload();
  await expect(page.getByRole('checkbox',{name:'أخرى',exact:true})).toBeChecked();
  await expect(page.getByRole('combobox',{name:'لغة الاختبارات المعتادة',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'إنشاء مسودة جديدة',exact:true}).click();
  await expect(page.locator('[data-scenario]:checked')).toHaveCount(12);
  await expect(page.locator('[data-context="exam_language"]')).toHaveValue('ar');
  for(const [key,value]of Object.entries(notes))await expect(page.locator(`[data-context="${key}"]`)).toHaveValue(value);
  expect(state.versions[0].status).toBe('approved');expect(state.writes).toHaveLength(1);
});

test('Other description survives toggling but is omitted when unchecked',async({page})=>{
  const state=await fixture(page);await page.goto('/app/marking-survey.html');
  const other=page.getByRole('checkbox',{name:'Other',exact:true});
  await other.check();await page.locator('[data-context="other_question_types"]').fill('Laboratory interpretation');
  await other.uncheck();await expect(page.locator('#profile-other-question-types')).toBeHidden();
  await other.check();await expect(page.locator('[data-context="other_question_types"]')).toHaveValue('Laboratory interpretation');
  await other.uncheck();await page.locator('[data-context="exam_language"]').selectOption('mixed');
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await expect(page.locator('#survey-saved')).toContainText('draft is saved');
  expect(state.writes[0].explicit_preferences.teaching_context).toMatchObject({other_question_types:'',question_types:[],exam_language:'mixed'});
  await page.locator('#app-language').click();
  await expect(page.locator('#survey-saved')).toContainText('تم حفظ مسودة الاستبيان.');
  await page.reload();await expect(page.locator('[data-context="exam_language"]')).toHaveValue('mixed');
  await expect(page.locator('#profile-other-question-types')).toBeHidden();
});

test('survey validates subject limits before sending without losing scenario choices',async({page})=>{
  const state=await fixture(page);await page.goto('/app/marking-survey.html');
  await page.locator('[data-scenario="missing_units"]').last().check();
  const subjects=Array.from({length:13},(_,i)=>`Subject ${i+1}`).join(', ');
  await page.locator('[data-context="subjects"]').fill(subjects);
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('up to 12 subjects');
  await expect(page.locator('[data-context="subjects"]')).toHaveValue(subjects);
  await expect(page.locator('[data-scenario="missing_units"]').last()).toBeChecked();
  expect(state.writes).toHaveLength(0);
  await page.locator('[data-context="subjects"]').fill('Physics');
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await expect(page.locator('#survey-saved')).toContainText('draft is saved');
  expect(state.writes[0].scenario_answers).toEqual([{scenario_id:'missing_units',selected_option:'do_not_penalize'}]);
  expect(state.writes[0].explicit_preferences.teaching_context.question_types).toEqual([]);
});

test('old approved profiles stay read-only and can seed the expanded survey',async({page})=>{
  const state=await fixture(page,{oldProfile:true});await page.goto('/app/marking-survey.html');await expect(page.locator('#marking-preferences')).toContainText('This earlier profile remains unchanged');
  await page.getByRole('button',{name:'Create new draft'}).click();await expect(page.locator('[data-scenario=valid_alternative_method]').first()).toBeChecked();await expect(page.locator('[data-scenario=missing_units]').first()).toBeEnabled();
  expect(state.versions[0].status).toBe('approved');expect(state.writes).toHaveLength(0);
});

test('survey completion preserves an existing opt out and survives refresh',async({page},info)=>{
  await fixture(page,{automaticPreferences:false});await page.goto('/app/marking-survey.html');
  const ids=await page.locator('.preference-scenarios .preference-scenario').evaluateAll(rows=>rows.map(row=>row.querySelector('[data-scenario]').dataset.scenario));
  for(const id of ids)await page.locator('[data-scenario="'+id+'"]').first().check();
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Save & approve profile'}).click();
  await expect(page.locator('#survey-saved')).toContainText('Survey done');await expect(page.locator('#survey-saved')).toContainText('Automatic preferences are off');
  await page.locator('#survey-saved').scrollIntoViewIfNeeded();await page.screenshot({path:'.impeccable/review/survey-completed-'+info.project.name+'.png',fullPage:true,animations:'disabled'});
  await page.reload();await expect(page.locator('#survey-saved')).toContainText('Automatic preferences are off');
});
