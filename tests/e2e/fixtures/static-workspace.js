/* Real workspace assets, with no listening socket or application database. */
const path = require('node:path');
const root = path.resolve(__dirname, '../../../misra-frontend');
async function staticWorkspace(page) {
  await page.route('http://127.0.0.1:4173/**', async route => {
    const pathname = decodeURIComponent(new URL(route.request().url()).pathname);
    const file = path.resolve(root, `.${pathname}${pathname.endsWith('/') ? 'index.html' : ''}`);
    if (!file.startsWith(root + path.sep)) return route.fulfill({status: 404, body: ''});
    try { await route.fulfill({path: file, headers: {'Cache-Control': 'no-store'}}); }
    catch (_) { await route.fulfill({status: 404, body: ''}); }
  });
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({body: ''}));
  await page.route('https://fonts.gstatic.com/**', route => route.abort());
}
module.exports = {staticWorkspace};
