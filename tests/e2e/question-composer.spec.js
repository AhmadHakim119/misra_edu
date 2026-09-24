const { test, expect } = require('@playwright/test');

async function setup(page, { existing = false, failSave = false } = {}) {
  const questions = existing ? [{ id: 'q1', question_number: '1', question_text: 'Explain the concept.', max_score: 5 }] : [];
  const posted = [];
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    let body;
    if (path === '/auth/me') body = { id: 'test-instructor', full_name: 'Test Instructor', role: 'instructor' };
    else if (path === '/health') body = { status: 'ok', model: 'test-model' };
    else if (path === '/exams') body = [{ id: 'exam1', title: 'Test assessment', course_code: 'TEST101' }, { id: 'exam2', title: 'Another assessment' }];
    else if (/^\/exams\/[^/]+\/questions$/.test(path)) {
      if (route.request().method() === 'POST') {
        posted.push(route.request().postDataJSON());
        if (failSave) return route.fulfill({ status: 503, json: { detail: 'Service temporarily unavailable.' } });
        body = { ...posted.at(-1), id: `q${questions.length + 1}` };
        questions.push(body);
      } else body = questions;
    } else if (path.endsWith('/rubric-versions')) body = [];
    else if (path.endsWith('/grading-policy')) body = { mode: 'adaptive' };
    else if (path.endsWith('/rubric')) body = { rubric: { max_score: 5, criteria: [] } };
    else return route.fulfill({ status: 404, json: { detail: 'Not mocked' } });
    await route.fulfill({ json: body });
  });
  await page.goto('/pages/rubric-studio.html');
  await expect(page.locator('#open-question-form')).toBeEnabled();
  return posted;
}

async function fill(page, number = '2a') {
  await page.getByLabel('Question number', { exact: true }).fill(number);
  await page.getByLabel('Total marks').fill('2.5');
  await page.getByLabel('Full question text').fill('Explain the method.\nInclude your reasoning.');
  await page.getByLabel('What are you assessing?').fill('Method and reasoning');
  await page.getByLabel('What earns credit?', { exact: true }).fill('Accept a correct method with relevant reasoning.');
}

test('empty assessment opens a roomy form and saves to the real API contract', async ({ page }, testInfo) => {
  const posted = await setup(page);
  await expect(page.getByRole('heading', { name: 'Add a question', exact: true })).toBeVisible();
  await fill(page);
  const textBox = await page.locator('#question-text').boundingBox();
  expect(textBox.height).toBeGreaterThanOrEqual(240);
  if (!testInfo.project.name.includes('mobile')) expect(textBox.width).toBeGreaterThan(500);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('question-composer.png'), fullPage: true });
  await page.getByRole('button', { name: 'Save & review rubric' }).click();
  await expect(page.locator('#question-composer')).toBeHidden();
  await expect(page.locator('#rubric-workspace')).toContainText('Question 2a');
  expect(posted).toHaveLength(1);
  expect(posted[0]).toMatchObject({ question_number: '2a', max_score: 2.5, criteria: [{ points: 2.5, title: 'Method and reasoning' }] });
});

test('save and add another clears the saved fields and blocks duplicate numbers', async ({ page }) => {
  const posted = await setup(page);
  await fill(page);
  await page.getByRole('button', { name: 'Save & add another' }).click();
  await expect(page.locator('#question-form-status')).toContainText('Question 2a saved');
  await expect(page.locator('#question-text')).toHaveValue('');
  await fill(page);
  await page.getByRole('button', { name: 'Save & review rubric' }).click();
  await expect(page.locator('#question-form-error')).toContainText('already exists');
  expect(posted).toHaveLength(1);
});

test('failed saves preserve writing and re-enable actions', async ({ page }) => {
  await setup(page, { failSave: true });
  await fill(page);
  await page.getByRole('button', { name: 'Save & review rubric' }).click();
  await expect(page.locator('#question-form-error')).toContainText('Your entries are still here');
  await expect(page.locator('#question-text')).toHaveValue('Explain the method.\nInclude your reasoning.');
  await expect(page.getByRole('button', { name: 'Save & review rubric' })).toBeEnabled();
});

test('navigation preserves a question and template replacement requires consent', async ({ page }) => {
  await setup(page, { existing: true });
  await page.getByRole('button', { name: 'Add question', exact: true }).click();
  await fill(page);
  await page.getByRole('button', { name: 'Back to rubric' }).click();
  await page.getByRole('button', { name: 'Add question', exact: true }).click();
  await expect(page.locator('#question-text')).toHaveValue('Explain the method.\nInclude your reasoning.');
  await page.locator('#question-template').selectOption('programming');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: 'Apply template' }).click();
  await expect(page.locator('#criterion-title')).toHaveValue('Method and reasoning');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.locator('#rubric-exam').selectOption('exam2');
  await expect(page.locator('#rubric-exam')).toHaveValue('exam1');
});

test('dark mode and narrow tablet remain readable without horizontal overflow', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('misra-theme', 'dark'));
  await setup(page);
  await page.setViewportSize({ width: 1000, height: 900 });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('question-composer-dark.png'), fullPage: true });
});
