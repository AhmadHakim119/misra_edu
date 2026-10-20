const {test,expect}=require('@playwright/test');

test('expired instructor session returns to the main app login and keeps the return URL',async({page})=>{
  await page.route('**/api/**',route=>route.fulfill({status:401,json:{detail:'Synthetic expired session'}}));
  await page.goto('/app/dashboard.html?exam_id=synthetic');
  await expect(page).toHaveURL(/\/app\/login.html\?next=/);
  expect(new URL(page.url()).searchParams.get('next')).toBe('/app/dashboard.html?exam_id=synthetic');
  await expect(page.getByRole('button',{name:'Sign in',exact:true})).toBeVisible();
  await expect(page.locator('body')).not.toContainText('Original workspace');
});

test('required password change stays in the main app',async({page})=>{
  await page.route('**/api/**',route=>{
    if(route.request().url().endsWith('/auth/me'))return route.fulfill({json:{id:'synthetic',role:'teacher',must_change_password:true}});
    return route.fulfill({json:[]});
  });
  await page.goto('/app/dashboard.html');
  await expect(page).toHaveURL(/\/app\/account.html\?required=1/);
  await expect(page.locator('#password-required')).toBeVisible();
});
