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
  const state=await fixture(page);await page.goto('/app/marking-survey.html');await expect(page.locator('.preference-scenario')).toHaveCount(12);
  await page.locator('[data-scenario=valid_alternative_method]').first().check();await page.getByRole('button',{name:'Save & approve profile'}).click();await expect(page.locator('#marking-preferences')).toContainText('Answer all 12');expect(state.writes).toHaveLength(0);
  const ids=await page.locator('.preference-scenario').evaluateAll(rows=>rows.map(row=>row.querySelector('[data-scenario]').dataset.scenario));
  for(const id of ids)await page.locator(`[data-scenario="${id}"]`).first().check();
  await expect(page.locator('#marking-preferences [role=alert]')).toHaveCount(0);
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');await navFits(page);
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:`.impeccable/review/survey-twelve-rtl-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-language').click();page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'Save & approve profile'}).click();
  expect(state.writes[0].scenario_answers).toHaveLength(12);await expect(page.locator('#survey-saved')).toContainText('Survey done');
  await page.reload();await expect(page.locator('[data-scenario]:checked')).toHaveCount(12);await expect(page.locator('[data-scenario]').first()).toBeDisabled();
});

test('old approved profiles stay read-only and can seed the expanded survey',async({page})=>{
  const state=await fixture(page,{oldProfile:true});await page.goto('/app/marking-survey.html');await expect(page.locator('#marking-preferences')).toContainText('This earlier profile remains unchanged');
  await page.getByRole('button',{name:'Create new draft'}).click();await expect(page.locator('[data-scenario=valid_alternative_method]').first()).toBeChecked();await expect(page.locator('[data-scenario=missing_units]').first()).toBeEnabled();
  expect(state.versions[0].status).toBe('approved');expect(state.writes).toHaveLength(0);
});

test('survey completion preserves an existing opt out and survives refresh',async({page},info)=>{
  await fixture(page,{automaticPreferences:false});await page.goto('/app/marking-survey.html');
  const ids=await page.locator('.preference-scenario').evaluateAll(rows=>rows.map(row=>row.querySelector('[data-scenario]').dataset.scenario));
  for(const id of ids)await page.locator('[data-scenario="'+id+'"]').first().check();
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Save & approve profile'}).click();
  await expect(page.locator('#survey-saved')).toContainText('Survey done');await expect(page.locator('#survey-saved')).toContainText('Automatic preferences are off');
  await page.locator('#survey-saved').scrollIntoViewIfNeeded();await page.screenshot({path:'.impeccable/review/survey-completed-'+info.project.name+'.png',fullPage:true,animations:'disabled'});
  await page.reload();await expect(page.locator('#survey-saved')).toContainText('Automatic preferences are off');
});
