const { test, expect } = require('@playwright/test');

async function fixture(page, { approved = false, failSave = false } = {}) {
  let rubric = { schema_version: 2, max_score: 3, reference_context: 'A valid reference solution.', acceptable_answers: ['Equivalent reasoning'],
    criteria: [{ id: 'c1', title: 'Reasoning', description: 'Valid reasoning earns credit.', points: 3 }], policy: { grading_approach: 'balanced' } };
  const writes = [];
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    let body;
    if (path === '/auth/me') body = { id: 't', full_name: 'Test Instructor', role: 'teacher' };
    else if (path === '/health') body = { status: 'ok', model: 'test-model' };
    else if (path === '/exams') body = [{ id: 'e', title: 'Synthetic assessment' }, { id: 'e2', title: 'Second assessment' }];
    else if (path.endsWith('/questions')) body = [{ id: 'q1', question_number: '1', question_text: 'Explain your reasoning.', max_score: 3 }, { id: 'q2', question_number: '2', question_text: 'Explain another method.', max_score: 3 }];
    else if (path.endsWith('/setup-imports')) body = [];
    else if (path.endsWith('/setup-readiness')) body = { ready: approved, message: 'Review the approved marking rules.', questions: [] };
    else if (path.endsWith('/grading-policy')) body = { mode: 'adaptive' };
    else if (path.endsWith('/rubric')) body = { rubric, rubric_version_id: 'v1' };
    else if (path.endsWith('/rubric-versions')) body = [{ id: 'v1', version_number: 1, status: approved ? 'approved' : 'draft', rubric_json: rubric }];
    else if (path === '/rubric-versions/v1' && route.request().method() === 'PUT') {
      writes.push(route.request().postDataJSON());
      if (failSave) return route.fulfill({ status: 503, json: { detail: 'Save temporarily unavailable' } });
      rubric = writes.at(-1).rubric;
      body = { id: 'v1', version_number: 1, status: 'draft', rubric_json: rubric };
    } else return route.fulfill({ status: 404, json: { detail: 'Not mocked' } });
    return route.fulfill({ json: body });
  });
  await page.goto('/pages/rubric-studio.html?exam_id=e');
  await expect(page.locator('#rubric-reference')).toBeVisible();
  return writes;
}

test('reference edits persist with draft and survive reload', async ({ page }, testInfo) => {
  const writes = await fixture(page);
  await page.locator('#rubric-reference').fill('Instructor reference: accept any valid equivalent method.');
  await page.locator('#rubric-alternatives').fill('Method A\nMethod B');
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeEnabled();
  expect(writes[0].rubric).toMatchObject({ reference_context: 'Instructor reference: accept any valid equivalent method.', acceptable_answers: ['Method A', 'Method B'] });
  await page.reload();
  await expect(page.locator('#rubric-reference')).toHaveValue('Instructor reference: accept any valid equivalent method.');
  await page.locator('.rubric-reference').screenshot({ path: testInfo.outputPath('rubric-reference.png'), animations: 'disabled' });
});

test('failed reference saves preserve writing; navigation requires consent', async ({ page }) => {
  await fixture(page, { failSave: true });
  await page.locator('#rubric-reference').fill('Unsaved instructor reference');
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeEnabled();
  await expect(page.locator('#rubric-reference')).toHaveValue('Unsaved instructor reference');
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('[data-question-id="q2"]').click();
  await expect(page.locator('#rubric-reference')).toHaveValue('Unsaved instructor reference');
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('#rubric-exam').selectOption('e2');
  await expect(page.locator('#rubric-exam')).toHaveValue('e');
});

test('approved reference is immutable in the editor', async ({ page }) => {
  await fixture(page, { approved: true });
  await expect(page.locator('#rubric-reference')).toBeDisabled();
  await expect(page.locator('#rubric-alternatives')).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Create editable draft' })).toBeVisible();
});

for (const action of ['Save draft', 'Approve']) {
  test(`${action} locks reference fields and restores them after request failure`, async ({ page }, testInfo) => {
    await fixture(page);
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    const endpoint = action === 'Approve' ? '**/api/rubric-versions/v1/approve' : '**/api/rubric-versions/v1';
    await page.route(endpoint, async route => { await gate; await route.fulfill({ status: 503, json: { detail: 'Synthetic delayed failure' } }); });
    await page.locator('#rubric-reference').fill('Reference waiting to save');
    await page.getByRole('button', { name: action, exact: true }).click();
    await expect(page.locator('#rubric-reference')).toBeDisabled();
    await expect(page.locator('#rubric-alternatives')).toBeDisabled();
    await expect(page.locator('[data-policy="grading_approach"]')).toBeDisabled();
    await page.locator('.rubric-reference').screenshot({ path: testInfo.outputPath('reference-pending.png'), animations: 'disabled' });
    release();
    await expect(page.locator('#rubric-reference')).toBeEnabled();
    await expect(page.locator('#rubric-reference')).toHaveValue('Reference waiting to save');
    page.once('dialog', dialog => dialog.dismiss());
    await page.locator('[data-question-id="q2"]').click();
    await expect(page.locator('#rubric-reference')).toHaveValue('Reference waiting to save');
  });
}

test('confirmed discard restores persisted reference when composer is closed', async ({ page }) => {
  await fixture(page);
  await page.locator('#rubric-reference').fill('To be discarded');
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#open-question-form').click();
  await page.locator('#close-question-form').click();
  await expect(page.locator('#rubric-reference')).toHaveValue('A valid reference solution.');
});

test('a later canceled question-form guard keeps rubric edits protected', async ({ page }) => {
  await fixture(page);
  await page.locator('#open-question-form').click();
  await page.locator('#question-text').fill('Unsaved new question');
  await page.locator('#close-question-form').click();
  await page.locator('#rubric-reference').fill('Unsaved reference');
  let dialogs = 0;
  const handle = dialog => ++dialogs === 1 ? dialog.accept() : dialog.dismiss();
  page.on('dialog', handle);
  await page.locator('#rubric-exam').selectOption('e2');
  await expect(page.locator('#rubric-exam')).toHaveValue('e');
  expect(dialogs).toBe(2);
  page.off('dialog', handle);
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('[data-question-id="q2"]').click();
  await expect(page.locator('#rubric-reference')).toHaveValue('Unsaved reference');
});
