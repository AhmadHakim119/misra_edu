const {test,expect}=require('@playwright/test');

async function fixture(page,{completed=true,enabled=true,failSave=false,failLoad=false,failDelete=false}={}){
  const state={enabled,failSave,failLoad,writes:[]};
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname.replace('/api',''),method=request.method();
    let body=[];
    if(path==='/auth/me')body={id:'synthetic',full_name:'Synthetic instructor',email:'synthetic@example.edu',role:'teacher'};
    else if(path==='/auth/settings'){
      if(method==='PUT'){
        state.writes.push({path,body:request.postDataJSON()});
        if(state.failSave)return route.fulfill({status:503,json:{detail:'Synthetic settings outage'}});
        state.enabled=request.postDataJSON().use_marking_preferences;
      }else if(state.failLoad)return route.fulfill({status:503,json:{detail:'Synthetic settings unavailable'}});
      body={use_marking_preferences:state.enabled,survey_completed:completed,has_approved_profile:completed};
    }else if(path==='/auth/account'){
      state.writes.push({path,body:request.postDataJSON()});
      return failDelete?route.fulfill({status:400,json:{detail:'Current password is incorrect'}}):route.fulfill({status:204});
    }else if(path==='/health')body={verification_enabled:true,agents:{extraction:{provider:'gemini',model:'Synthetic vision'},assessment:{provider:'openrouter_free',model:'Synthetic assessment'},verification:{provider:'openrouter_free',model:'Synthetic verifier'}}};
    else if(path==='/jobs')body={items:[],active_count:0};
    await route.fulfill({json:body});
  });
  await page.goto('/app/account.html');return state;
}

test('survey preferences default on, opt out persists and can be enabled again',async({page})=>{
  const state=await fixture(page);const toggle=page.locator('#use-marking-preferences');
  await expect(toggle).toBeEnabled();await expect(toggle).toBeChecked();await expect(page.locator('#marking-completion')).toContainText('Survey done');
  await toggle.uncheck();await expect(page.locator('#marking-completion')).toContainText('Automatic preferences are off');
  expect(state.enabled).toBeFalsy();await page.reload();await expect(toggle).not.toBeChecked();
  await toggle.check();await expect(page.locator('#marking-completion')).toContainText('turn them off in Settings');
  expect(state.writes.map(w=>w.body)).toEqual([{use_marking_preferences:false},{use_marking_preferences:true}]);
});

test('no survey leaves standard rules available without a false completion badge',async({page})=>{
  await fixture(page,{completed:false});await expect(page.locator('#use-marking-preferences')).toBeEnabled();
  await expect(page.locator('#use-marking-preferences')).toBeChecked();await expect(page.locator('#marking-completion')).toBeEmpty();
  await expect(page.locator('#marking-settings-status')).toContainText('Complete and approve');
  await expect(page.locator('#settings-survey-link')).toHaveAttribute('href','marking-survey.html');
});

test('failed opt out keeps the choice, protects navigation and retries the same setting',async({page})=>{
  const state=await fixture(page,{failSave:true});await expect(page.locator('#use-marking-preferences')).toBeEnabled();
  await page.locator('#use-marking-preferences').uncheck();await expect(page.locator('#marking-settings-error')).toContainText('Save not confirmed');
  await expect(page.locator('#use-marking-preferences')).not.toBeChecked();expect(state.enabled).toBeTruthy();
  page.once('dialog',d=>d.dismiss());await page.getByRole('link',{name:'Exams',exact:true}).click();await expect(page).toHaveURL(/account.html/);
  state.failSave=false;await page.locator('#retry-marking-setting').click();await expect(page.locator('#marking-settings-error')).toBeEmpty();
  expect(state.enabled).toBeFalsy();await expect(page.locator('#retry-marking-setting')).toBeHidden();
});

test('unavailable settings cannot be mistaken for a saved opt in',async({page})=>{
  const state=await fixture(page,{failLoad:true});await expect(page.locator('#marking-settings-error')).toContainText('Synthetic settings unavailable');
  await expect(page.locator('#use-marking-preferences')).toBeDisabled();await expect(page.locator('#marking-completion')).toBeEmpty();
  state.failLoad=false;await page.locator('#reload-marking-setting').click();await expect(page.locator('#use-marking-preferences')).toBeEnabled();
});

test('account deletion explains retained history, needs typed confirmation and signs out',async({page})=>{
  const state=await fixture(page);await page.locator('#delete-account-panel summary').click();
  await expect(page.locator('#delete-account-panel')).toContainText('survey history and past decisions');
  await page.locator('#delete-password').fill('Synthetic password');await page.locator('#delete-confirmation').fill('no');
  await page.getByRole('button',{name:'Delete my account',exact:true}).click();expect(state.writes).toHaveLength(0);
  await page.locator('#delete-confirmation').fill('DELETE');await page.getByRole('button',{name:'Delete my account',exact:true}).click();
  await expect(page).toHaveURL(/login.html\?account_deleted=1/);await expect(page.getByRole('status')).toContainText('Account deleted');
  expect(state.writes).toEqual([{path:'/auth/account',body:{current_password:'Synthetic password',confirmation:'DELETE'}}]);
});

test('rejected deletion preserves entries and cancel clears them without deleting',async({page})=>{
  const state=await fixture(page,{failDelete:true});await page.locator('#delete-account-panel summary').click();
  await page.locator('#delete-password').fill('Synthetic wrong password');await page.locator('#delete-confirmation').fill('DELETE');
  await page.getByRole('button',{name:'Delete my account',exact:true}).click();await expect(page.locator('#delete-account-error')).toContainText('Current password is incorrect');
  await expect(page.locator('#delete-confirmation')).toHaveValue('DELETE');
  page.once('dialog',d=>d.dismiss());await page.getByRole('link',{name:'Exams',exact:true}).click();await expect(page).toHaveURL(/account.html/);
  await page.locator('#delete-account-form').getByRole('button',{name:'Cancel',exact:true}).click();await expect(page.locator('#delete-password')).toBeEmpty();await expect(page.locator('#delete-confirmation')).toBeEmpty();
  expect(state.writes).toHaveLength(1);await page.getByRole('link',{name:'Exams',exact:true}).click();await expect(page).toHaveURL(/assessments.html/);
});

test('settings has clear sections and responsive completion in both themes and Arabic',async({page},info)=>{
  await fixture(page);await expect(page.locator('#marking-completion')).toContainText('Survey done');
  await expect(page.locator('.settings-section')).toHaveCount(5);
  for(const variant of ['light','dark','rtl']){
    if(variant==='dark')await page.locator('[data-theme-option][value=dark]').check();
    if(variant==='rtl')await page.locator('#app-language').click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    if(variant==='rtl'){await expect(page.locator('#marking-completion')).toContainText('تم الاستبيان');await expect(page.locator('#marking-settings-title')).toHaveText('تفضيلات التصحيح');}
    await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'.impeccable/review/settings-account-'+variant+'-'+info.project.name+'.png',fullPage:true,animations:'disabled'});
  }
});
