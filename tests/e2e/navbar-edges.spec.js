const {test,expect}=require('@playwright/test');

for(const routeName of ['grading','dashboard'])test(`${routeName} keeps account controls at the opposite navbar edge in both languages`,async({page},info)=>{
  await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname;
    const body=path==='/api/auth/me'?{id:'synthetic',role:'admin',full_name:'Synthetic instructor'}
      :path==='/api/jobs'?{items:[],active_count:0}:[];
    return route.fulfill({json:body});
  });
  await page.goto(`/app/${routeName}.html`);
  await expect(page.locator('.app-bar .account button')).toHaveCount(3);
  for(const lang of ['en','ar']){
    if(lang==='ar')await page.locator('#app-language').click();
    for(const theme of ['light','dark']){
      await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
      const rects=await page.evaluate(()=>{
        const bar=document.querySelector('.app-bar'),account=bar.querySelector('.account'),brand=bar.querySelector('.brand'),style=getComputedStyle(bar);
        return {bar:bar.getBoundingClientRect().toJSON(),account:account.getBoundingClientRect().toJSON(),brand:brand.getBoundingClientRect().toJSON(),padding:parseFloat(style.paddingInlineEnd)};
      });
      if(process.env.MISRA_NAV_CAPTURE!=='before'){
        if(lang==='en')expect(Math.abs(rects.bar.right-rects.padding-rects.account.right)).toBeLessThan(2);
        else expect(Math.abs(rects.bar.left+rects.padding-rects.account.left)).toBeLessThan(2);
        expect(rects.account.left>=rects.brand.right||rects.account.right<=rects.brand.left).toBeTruthy();
      }
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
      await page.locator('.app-bar').screenshot({path:`.impeccable/review/navbar-edges-${process.env.MISRA_NAV_CAPTURE||'after'}-${routeName}-${lang}-${theme}-${info.project.name}.png`});
    }
  }
  for(const width of [1024,360]){
    await page.setViewportSize({width,height:800});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    const overlap=await page.evaluate(()=>{const a=document.querySelector('.account').getBoundingClientRect();return [...document.querySelectorAll('.app-bar nav>*')].some(el=>{const b=el.getBoundingClientRect();return a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;});});
    expect(overlap).toBeFalsy();
  }
});
