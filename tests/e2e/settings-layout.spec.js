const {test,expect}=require('@playwright/test');
async function fixture(page,{healthFailure=false}={}){
  const writes=[];
  await page.route('**/api/**',route=>{
    const p=new URL(route.request().url()).pathname.replace('/api','');
    if(p==='/auth/settings')return route.fulfill({json:{use_marking_preferences:true,has_approved_profile:false,survey_completed:false}});
    if(p==='/health')return route.fulfill({status:healthFailure?503:200,json:healthFailure?{detail:'Synthetic service status unavailable'}:{verification_enabled:true,agents:{extraction:{provider:'gemini',model:'Synthetic vision model'},assessment:{provider:'openrouter_free',model:'Synthetic assessment model'},verification:{provider:'openrouter_free',model:'Synthetic verification model'}}}});
    if(route.request().method()==='POST'){writes.push(p);return route.fulfill({status:422,json:{detail:'Synthetic password rejection'}});}
    return route.fulfill({json:p==='/auth/me'?{id:'synthetic',full_name:'Synthetic instructor',email:'synthetic@example.edu',role:'teacher'}:[]});
  });
  await page.goto('/app/account.html');return writes;
}

test('settings removes model configuration and keeps a readable compact layout in both themes and RTL',async({page},info)=>{
  await fixture(page);await page.locator('#ai-settings summary').click();await expect(page.locator('#native-ai-agents .record-row')).toHaveCount(3);
  await expect(page.getByText('Model configuration',{exact:true})).toHaveCount(0);await expect(page.locator('#native-ai-config')).toHaveCount(0);
  await expect(page.locator('#native-ai-agents')).toContainText('Verification agent');
  const sections=await page.locator('.settings-content>.settings-section').evaluateAll(elements=>elements.map(el=>({top:el.getBoundingClientRect().top,bottom:el.getBoundingClientRect().bottom})));
  expect(sections).toHaveLength(5);
  for(let i=1;i<sections.length;i++)expect(sections[i].top-sections[i-1].bottom).toBeLessThanOrEqual(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:`.impeccable/review/settings-spacing-light-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('[data-theme-option][value=dark]').check();await expect(page.locator('#native-settings-status')).toContainText('Theme saved');
  await expect(page.locator('#app-theme')).toHaveText('Light theme');
  await page.screenshot({path:`.impeccable/review/settings-spacing-dark-${info.project.name}.png`,fullPage:true,animations:'disabled'});
  await page.locator('#app-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:`.impeccable/review/settings-spacing-rtl-${info.project.name}.png`,fullPage:true,animations:'disabled'});
});

test('settings service failure remains visible and rejected password changes retain unsaved fields',async({page})=>{
  const writes=await fixture(page,{healthFailure:true});await expect(page.locator('#native-ai-status')).toContainText('Synthetic service status unavailable');
  await page.locator('#native-password summary').click();
  await page.locator('#current-password').fill('Synthetic current password');await page.locator('#new-password').fill('Synthetic replacement password');await page.locator('#confirm-password').fill('Synthetic replacement password');
  await page.getByRole('button',{name:'Change password',exact:true}).click();await expect(page.locator('#native-password-error')).toContainText('Synthetic password rejection');
  expect(writes).toEqual(['/auth/change-password']);await expect(page.locator('#new-password')).toHaveValue('Synthetic replacement password');
  page.once('dialog',dialog=>dialog.dismiss());await page.getByRole('link',{name:'Dashboard',exact:true}).click();await expect(page).toHaveURL(/account.html/);
});
