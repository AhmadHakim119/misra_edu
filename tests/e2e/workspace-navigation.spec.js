const {answerWorkspaceDialog}=require('./fixtures/workspace-dialog');
const {test, expect} = require('@playwright/test');
const {staticWorkspace}=require('./fixtures/static-workspace');

async function fixture(page) {
  await staticWorkspace(page);
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const records = {
      '/api/auth/me': {id: 'synthetic', full_name: 'Synthetic instructor', role: 'admin'},
      '/api/exams': [{id: 'exam', title: 'Synthetic exam', course_id: 'course', course_code: 'TEST'}],
      '/api/courses': [{id: 'course', course_code: 'TEST', title: 'Synthetic course'}],
      '/api/jobs': {items: [], active_count: 0},
      '/api/auth/settings': {use_marking_preferences: false, has_approved_profile: false, survey_completed: false}
    };
    return route.fulfill({json: records[path] || []});
  });
  await page.goto('/app/dashboard.html');
  await expect(page.locator('#dashboard-exams')).toContainText('Synthetic exam');
  await page.evaluate(() => { window.testWorkspaceHeader = document.querySelector('.workspace-header'); });
}

test('workspace navigation keeps one navbar across all primary destinations and exam workflow pages', async ({page}, info) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await fixture(page);
  const nav = page.getByRole('navigation', {name: 'Workspace', exact: true});
  const selection = nav.locator('.workspace-selection');
  for (const [label, route] of [
    ['Exams', 'assessments'], ['Course library', 'course-library'], ['Review', 'reviews'],
    ['Activity', 'activity'], ['Settings', 'account'], ['Administration', 'admin'], ['Dashboard', 'dashboard']
  ]) {
    await nav.getByRole('link', {name: label, exact: true}).click();
    await expect(page).toHaveURL(new RegExp(`/app/${route}\\.html$`));
    await expect(nav.getByRole('link', {name: label, exact: true})).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('#workspace-content')).toHaveAttribute('aria-busy', 'false');
    await expect.poll(() => selection.evaluate(element => {
      const current = element.parentElement.querySelector('[aria-current]').getBoundingClientRect();
      const highlight = element.getBoundingClientRect();
      return Math.round(Math.abs(current.x - highlight.x) + Math.abs(current.y - highlight.y)
        + Math.abs(current.width - highlight.width));
    })).toBe(0);
    expect(await page.evaluate(() => window.testWorkspaceHeader === document.querySelector('.workspace-header'))).toBe(true);
  }
  await page.getByRole('link', {name: 'Open exam', exact: true}).click();
  await expect(page.locator('#exam-title')).toHaveText('Synthetic exam');
  await expect(nav.getByRole('link', {name: 'Exams', exact: true})).toHaveAttribute('aria-current', 'location');
  expect(await page.evaluate(() => window.testWorkspaceHeader === document.querySelector('.workspace-header'))).toBe(true);
  await page.locator('#native-exam-navigation').getByRole('link', {name: 'Upload papers'}).click();
  await expect(page).toHaveURL(/\/app\/upload\.html\?exam_id=exam/);
  await expect(page.locator('#ledger-upload')).toBeVisible();
  await page.evaluate(() => history.back());
  await expect(page).toHaveURL(/\/app\/grading\.html\?exam_id=exam/);
  await expect(page.locator('#exam-title')).toHaveText('Synthetic exam');
  expect(await page.evaluate(() => window.testWorkspaceHeader === document.querySelector('.workspace-header'))).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({path:`.impeccable/review/workspace-navigation-exam-${info.project.name}.png`, fullPage: true, animations: 'disabled'});
  await page.evaluate(() => history.forward());
  await expect(page).toHaveURL(/\/app\/upload\.html\?exam_id=exam/);
  await expect(page.locator('#ledger-upload')).toBeVisible();
});

test('workspace navigation preserves an unsaved exam when Back is canceled and recovers a failed page load', async ({page}) => {
  await fixture(page);
  const nav = page.getByRole('navigation', {name: 'Workspace', exact: true});
  await nav.getByRole('link', {name: 'Exams', exact: true}).click();
  await page.locator('#open-creation').click();
  const title = page.locator('#manager-title');
  await title.fill('Synthetic unsaved title');
  await page.evaluate(() => history.back());
  await answerWorkspaceDialog(page,'cancel');
  await expect(title).toHaveValue('Synthetic unsaved title');
  await expect(page).toHaveURL(/\/app\/assessments\.html$/);

  await page.route('**/app/reviews.html', route => route.abort(), {times: 1});
  await nav.getByRole('link', {name: 'Review', exact: true}).click();await answerWorkspaceDialog(page,'confirm');
  await expect(page.locator('.workspace-route-notice')).toContainText('The page could not load');
  await expect(title).toHaveValue('Synthetic unsaved title');
  await expect(page).toHaveURL(/\/app\/assessments\.html$/);

  await page.route('**/app/reviews.js', route => route.abort(), {times: 1});
  await nav.getByRole('link', {name: 'Review', exact: true}).click();await answerWorkspaceDialog(page,'confirm');
  await expect(page.locator('.workspace-route-notice')).toContainText('The page could not load');
  await expect(title).toHaveValue('Synthetic unsaved title');
  await expect(page).toHaveURL(/\/app\/assessments\.html$/);

  await nav.getByRole('link', {name: 'Review', exact: true}).click();await answerWorkspaceDialog(page,'confirm');
  await expect(page).toHaveURL(/\/app\/reviews\.html$/);
  await expect(page.locator('#workspace-content h1')).toHaveText('Instructor review queue');
  expect(await page.evaluate(() => window.testWorkspaceHeader === document.querySelector('.workspace-header'))).toBe(true);
});

test('workspace ignores a delayed result after leaving a page and redirects an expired session', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await fixture(page);
  await page.emulateMedia({reducedMotion: 'reduce'});
  await expect(page.locator('.workspace-selection')).toHaveCSS('transition-duration', '0s');
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  await page.route('**/api/jobs?*', async route => {
    await pending;
    await route.fulfill({status: 401, json: {detail: 'Synthetic expired Activity request'}});
  }, {times: 1});
  const nav = page.getByRole('navigation', {name: 'Workspace', exact: true});
  const jobs = page.waitForRequest('**/api/jobs?*');
  await nav.getByRole('link', {name: 'Activity', exact: true}).click();
  await jobs;
  await nav.getByRole('link', {name: 'Settings', exact: true}).click();
  await expect(page.locator('#workspace-content h1')).toHaveText('Settings');
  const delayed = page.waitForResponse('**/api/jobs?*');
  release();
  await delayed;
  await page.route('**/api/auth/me', route => route.fulfill({status: 401, json: {detail: 'Synthetic expired session'}}), {times: 1});
  await nav.getByRole('link', {name: 'Review', exact: true}).click();
  await expect(page).toHaveURL(/\/app\/login\.html\?next=/);
  expect(new URL(page.url()).searchParams.get('next')).toBe('/app/reviews.html');
  expect(errors).toEqual([]);
});

test('workspace restores a failed Back destination and accepts a bookmark with a malformed fragment', async ({page}) => {
  await fixture(page);
  await page.goto('/app/');
  await expect(page).toHaveURL(/\/app\/dashboard\.html$/);
  const nav = page.getByRole('navigation', {name: 'Workspace', exact: true});
  await nav.getByRole('link', {name: 'Activity', exact: true}).click();
  await expect(page.locator('#workspace-content h1')).toHaveText('Processing activity');

  const settings = nav.getByRole('link', {name: 'Settings', exact: true});
  await settings.evaluate(link => { link.hash = '%'; });
  await settings.click();
  await expect(page.locator('#workspace-content h1')).toHaveText('Settings');
  await expect(page).toHaveURL(/\/app\/account\.html#%$/);
  await page.route('**/app/activity.html', route => route.abort(), {times: 1});
  await page.evaluate(() => history.back());
  await expect(page.locator('.workspace-route-notice')).toContainText('The page could not load');
  await expect(page).toHaveURL(/\/app\/account\.html#%$/);
  await expect(settings).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('#workspace-content h1')).toHaveText('Settings');
});
