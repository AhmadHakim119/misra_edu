const {test,expect}=require('@playwright/test');

async function fixture(page,{templateFails=0,moduleFails=0,navigationFails=0}={}){
  const calls={template:0,module:0,navigation:0};
  await page.route('**/app/workspace-template.html',async route=>{
    calls.template++;if(calls.template<=templateFails)return route.abort('connectionreset');
    await route.fulfill({contentType:'text/html',body:'<!doctype html><html><head><script src="probe.js"></script></head><body><main><h1>Recovered synthetic workspace</h1></main></body></html>'});
  });
  await page.route('**/app/probe.js',async route=>{
    calls.module++;if(calls.module<=moduleFails)return route.abort('connectionreset');
    await route.fulfill({contentType:'text/javascript',body:'window.syntheticModuleRuns=(window.syntheticModuleRuns||0)+1;'});
  });
  await page.route('**/app/workspace-navigation.js',async route=>{
    calls.navigation++;if(calls.navigation<=navigationFails)return route.abort('connectionreset');
    await route.fulfill({contentType:'text/javascript',body:'window.syntheticNavigationRuns=(window.syntheticNavigationRuns||0)+1;'});
  });
  await page.goto('/app/grading.html?exam_id=synthetic');return calls;
}

test('a failed workspace template download reconnects once before mounting',async({page})=>{
  const calls=await fixture(page,{templateFails:1});
  await expect(page.getByRole('heading',{name:'Recovered synthetic workspace'})).toBeVisible();
  await expect.poll(()=>page.evaluate(()=>window.syntheticNavigationRuns)).toBe(1);
  expect(calls).toEqual({template:2,module:1,navigation:1});
});

test('a failed module download reconnects without executing successful modules twice',async({page})=>{
  const calls=await fixture(page,{moduleFails:1,navigationFails:1});
  await expect.poll(()=>page.evaluate(()=>window.syntheticNavigationRuns)).toBe(1);
  expect(await page.evaluate(()=>window.syntheticModuleRuns)).toBe(1);
  expect(calls).toEqual({template:1,module:2,navigation:2});
  await expect(page.locator('script[src="probe.js"]')).toHaveCount(1);
});

test('persistent module failure remains visible after one bounded retry',async({page})=>{
  const calls=await fixture(page,{moduleFails:3});
  await expect(page.getByRole('alert')).toHaveText('A workspace module failed to load. Reload to retry.');
  expect(calls).toEqual({template:1,module:2,navigation:0});
  expect(await page.evaluate(()=>window.syntheticModuleRuns||0)).toBe(0);
});

test('persistent template failure never mounts a partial workspace',async({page})=>{
  const calls=await fixture(page,{templateFails:3});
  await expect(page.getByRole('alert')).toBeVisible();
  expect(calls).toEqual({template:2,module:0,navigation:0});
  await expect(page.getByRole('heading',{name:'Recovered synthetic workspace'})).toHaveCount(0);
});
