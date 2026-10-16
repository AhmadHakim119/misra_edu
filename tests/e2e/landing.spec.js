const {test,expect}=require('@playwright/test');

test('landing presents the real brand, new app destinations and an explicitly synthetic example',async({page})=>{
  const requests=[];await page.route('**/api/**',route=>{requests.push(route.request().url());return route.abort();});
  await page.goto('/app/landing.html');
  await expect(page.locator('h1')).toContainText('Handwritten exams.');
  await expect(page.locator('.landing-header .logo-light')).toHaveAttribute('src','/assets/logo-transparent.png');
  await expect(page.getByRole('link',{name:'Open MISRA'}).first()).toHaveAttribute('href','/app/index.html');
  await expect(page.locator('.landing-account').getByRole('link',{name:'Sign in'})).toHaveAttribute('href','/app/login.html');
  await expect(page.locator('#example')).toContainText('Synthetic example');
  expect(await page.locator('a[href*="pages/"],a[href*="next/"]').count()).toBe(0);
  await page.getByRole('button',{name:'Rubric',exact:true}).click();await expect(page.locator('#example-caption')).toContainText('approved criteria');
  await page.getByRole('button',{name:'Paper',exact:true}).click();await expect(page.locator('#example')).toHaveAttribute('data-stage','paper');
  await page.getByRole('button',{name:'Review',exact:true}).click();await expect(page.locator('#example-caption')).toContainText('final mark');
  expect(requests).toHaveLength(0);
  await page.getByText('Who decides the final grade?',{exact:true}).click();await expect(page.locator('.faq details').first()).toHaveAttribute('open','');
});

test('landing language and theme persist and all supported widths fit',async({page},info)=>{
  await page.goto('/app/landing.html');
  if(info.project.name==='desktop-chromium')await page.setViewportSize({width:1435,height:1096});
  for(const lang of ['en','ar']){
    if(lang==='ar')await page.locator('#landing-language').click();
    for(const theme of ['light','dark']){
      const current=await page.locator('html').getAttribute('data-theme');if(current!==theme)await page.locator('#landing-theme').click();
      await expect(page.locator('#landing-theme')).not.toHaveAttribute('aria-pressed');
      await expect(page.locator('#landing-theme')).toHaveText(lang==='ar'?(theme==='dark'?'الوضع الفاتح':'الوضع الداكن'):(theme==='dark'?'Light theme':'Dark theme'));
      await expect(page.locator('html')).toHaveAttribute('dir',lang==='ar'?'rtl':'ltr');
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
      await expect(page.locator('.landing-header img:visible')).toHaveCount(1);
      const image=page.locator('.student-work img');await expect.poll(()=>image.evaluate(el=>el.complete&&el.naturalWidth>0)).toBeTruthy();
      await page.screenshot({path:`.impeccable/review/landing-${process.env.MISRA_LANDING_CAPTURE||'initial'}-${lang}-${theme}-${info.project.name}.png`,fullPage:true,animations:'disabled'});
      if(lang==='en'&&theme==='light'&&info.project.name==='desktop-chromium')await page.screenshot({path:'.impeccable/review/landing-hero-initial.png',animations:'disabled'});
    }
  }
  await page.reload();await expect(page.locator('html')).toHaveAttribute('dir','rtl');await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  for(const width of [1280,1024,768,412,360]){await page.setViewportSize({width,height:800});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();}
});

test('landing remains readable with native links and disclosures without JavaScript',async({browser})=>{
  const context=await browser.newContext({javaScriptEnabled:false,viewport:{width:390,height:844}}),page=await context.newPage();
  try{
    await page.goto('http://127.0.0.1:4173/app/landing.html');
    await expect(page.locator('h1')).toContainText('Handwritten exams.');await expect(page.locator('#landing-theme')).toBeHidden();await expect(page.locator('.example-switch')).toBeHidden();
    await page.getByText('Who decides the final grade?',{exact:true}).click();await expect(page.locator('.faq details').first()).toHaveAttribute('open','');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  }finally{await context.close();}
});

test('landing supports keyboard use, reduced motion and unavailable device storage',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.addInitScript(()=>{Storage.prototype.setItem=function(){throw new Error('Synthetic unavailable storage');};});
  await page.goto('/app/landing.html');await page.keyboard.press('Tab');await expect(page.locator('.skip-link')).toBeFocused();
  await page.locator('#landing-language').click();await expect(page.locator('html')).toHaveAttribute('dir','rtl');
  await page.locator('#landing-theme').click();await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  expect(await page.locator('.review-example').evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
});
