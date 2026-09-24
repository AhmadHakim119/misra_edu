const { test, expect } = require('@playwright/test');
async function fixture(page, { fail = false } = {}) {
  const writes = []; let versions = [];
  const rubric = { schema_version: 2, max_score: 3, criteria: [{ id: 'c', title: 'Reasoning', description: 'Valid reasoning.', points: 3 }], policy: { grading_approach: 'balanced' } };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    const method = route.request().method(); let body = {};
    if (path === '/auth/me') body = { id: 't', full_name: 'Synthetic Instructor', role: 'teacher' };
    else if (path === '/health') body = { status: 'ok' };
    else if (path === '/exams') body = [{ id: 'e', title: 'Synthetic assessment' }, { id: 'e2', title: 'Second assessment' }];
    else if (path.endsWith('/questions')) body = [{ id: 'q1', question_number: '1', question_text: 'Explain a valid method.', max_score: 3 }, { id: 'q2', question_number: '2', question_text: 'Explain another method.', max_score: 3 }];
    else if (path.endsWith('/setup-imports')) body = [];
    else if (path.endsWith('/setup-readiness')) body = { ready: false, questions: [] };
    else if (path.endsWith('/rubric')) body = { rubric, rubric_version_id: 'r1' };
    else if (path.endsWith('/rubric-versions')) body = [{ id: 'r1', version_number: 1, status: 'draft', rubric_json: rubric }];
    else if (path.endsWith('/grading-policy')) body = { mode: 'adaptive' };
    else if (path.endsWith('/answer-key-documents')) body = { job_id: 'doc1', document_index: 0, page_count: 3, media_type: 'application/pdf' };
    else if (path.includes('/answer-key-versions')) {
      if (method === 'GET') body = versions;
      else if (path.endsWith('/approve')) { versions[0].status = 'approved'; body = versions[0]; }
      else {
        writes.push(route.request().postDataJSON());
        if (fail) return route.fulfill({ status: 503, json: { detail: '<private internal failure>' } });
        body = { ...writes.at(-1), id: 'k1', question_id: 'q1', version_number: 1, status: 'draft' }; versions = [body];
      }
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/pages/rubric-studio.html?exam_id=e');
  await expect(page.locator('#key-mode')).toBeVisible();
  return writes;
}
test('answer key saves and approves independently; approved history is read-only', async ({ page }, info) => {
  const writes = await fixture(page);
  await expect(page.locator('#answer-key-panel')).toHaveAttribute('aria-labelledby', 'answer-key-title');
  await expect(page.locator('#answer-key-title')).toHaveText('Answer key');
  await page.locator('#key-reference').fill('Synthetic reference: a valid equivalent method earns credit.');
  await page.locator('#key-alternatives').fill('Method A\nMethod B');
  await page.getByRole('button', { name: 'Save answer-key draft', exact: true }).click();
  await expect(page.locator('#key-reference')).toBeEnabled();
  expect(writes[0]).toMatchObject({ reference_text: 'Synthetic reference: a valid equivalent method earns credit.', acceptable_answers: ['Method A', 'Method B'] });
  page.once('dialog', d => d.accept());
  await page.getByRole('button', { name: 'Save & approve answer key' }).click();
  await expect(page.locator('#key-reference')).toBeDisabled();
  await expect(page.locator('#rubric-reference')).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `.impeccable/review/phase1-key-${info.project.name}.png`, fullPage: true });
  await page.getByRole('button', { name: 'Create answer-key draft' }).click();
  await expect(page.locator('#key-reference')).toBeEnabled();
});
test('failed answer-key saves preserve entries and canceled navigation', async ({ page }) => {
  await fixture(page, { fail: true });
  await page.locator('#key-reference').fill('Unsaved reference');
  await page.getByRole('button', { name: 'Save answer-key draft', exact: true }).click();
  await expect(page.locator('#answer-key-panel [role="alert"]')).toContainText('Your edits are still here');
  await expect(page.locator('#key-reference')).toHaveValue('Unsaved reference');
  page.once('dialog', d => d.dismiss()); await page.locator('[data-question-id="q2"]').click();
  await expect(page.locator('#key-reference')).toHaveValue('Unsaved reference');
  page.once('dialog', d => d.dismiss()); await page.locator('#rubric-exam').selectOption('e2');
  await expect(page.locator('#rubric-exam')).toHaveValue('e');
});
test('documents use one-based page input and no-fixed-answer clears reference payload', async ({ page }) => {
  const writes = await fixture(page);
  await page.locator('#key-file').setInputFiles({ name: 'synthetic.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF synthetic mock') });
  await page.getByRole('button', { name: 'Upload reference document' }).click();
  await expect(page.locator('#key-pages-0')).toBeVisible();
  await page.locator('#key-pages-0').fill('1, 3');
  await page.getByRole('button', { name: 'Save answer-key draft', exact: true }).click();
  await expect(page.locator('#key-mode')).toBeEnabled();
  expect(writes[0].document_refs).toEqual([{ job_id: 'doc1', page_indices: [0, 2] }]);
  await page.locator('#key-mode').selectOption('no_fixed_answer');
  await page.getByRole('button', { name: 'Save answer-key draft', exact: true }).click();
  await expect(page.locator('#key-mode')).toBeEnabled();
  expect(writes.at(-1)).toMatchObject({ mode: 'no_fixed_answer', reference_text: '', acceptable_answers: [], document_refs: [] });
});
