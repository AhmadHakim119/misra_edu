const { test, expect } = require('@playwright/test');

const exam = { id: 'exam-1', title: 'Database Systems Midterm', course_code: 'CS2071', question_count: 3, approved_question_count: 3, submission_count: 5, review_count: 0 };
const readiness = { expected_question_count: 3, mapped_answer_count: 3, bulk_grading_allowed: true, missing_question_numbers: [], blocking_reasons: [] };
const paper = (id, changes = {}) => ({ id, exam_id: exam.id, status: 'extracted', page_count: 4, uploaded_at: '2026-09-28T10:00:00', extracted_student_name: 'Example ' + id, extracted_student_number: 'TEST-' + id, readiness, ...changes });
function sample() {
  return [
    paper('queued', { status: 'uploaded', extracted_student_name: null, extracted_student_number: null, latest_ocr_job: { id: 'job-queued', status: 'queued', progress_percent: 0, progress_total: 4 }, readiness: { ...readiness, mapped_answer_count: 0, bulk_grading_allowed: false } }),
    paper('failed', { status: 'uploaded', latest_ocr_job: { id: 'job-failed', status: 'failed', error_message: 'Provider quota exhausted. Retry after quota is available.' } }),
    paper('ready'),
    paper('graded', { status: 'graded' }),
    paper('identity', { status: 'reviewed', extracted_student_number: null }),
  ];
}
async function mock(page, initial = sample()) {
  const state = { items: initial, fail: false, requests: 0, retries: 0, delay: 0 };
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    let body = {};
    if (path === '/auth/me') body = { id: 'test-teacher', full_name: 'Test Instructor', role: 'teacher' };
    else if (path === '/health') body = { status: 'ok', model: 'test-model' };
    else if (path === '/jobs') body = { items: [], active_count: 0 };
    else if (path === '/exams') body = [exam];
    else if (path.endsWith('/setup-readiness')) body = { ready: true, questions: [], pending_questions: [] };
    else if (path === '/submissions') {
      state.requests += 1;
      if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay));
      if (state.fail) { await route.fulfill({ status: 503, json: { detail: 'Service unavailable' } }); return; }
      body = state.items;
    } else if (path === '/jobs/job-failed/retry') {
      state.retries += 1;
      state.items = state.items.map((item) => item.id === 'failed' ? { ...item, latest_ocr_job: { ...item.latest_ocr_job, status: 'queued', progress_total: 4 } } : item);
      body = { id: 'job-failed', status: 'queued' };
    } else if (path.startsWith('/submissions/') && route.request().method() === 'DELETE') {
      state.items = state.items.filter((item) => item.id !== path.split('/').pop());
      body = { file_removed: true };
    }
    await route.fulfill({ json: body });
  });
  return state;
}

test('paper inbox distinguishes unfinished OCR from missing evidence', async ({ page }) => {
  await mock(page);
  await page.goto('/pages/submissions.html');
  const queued = page.locator('[data-paper-id="queued"]');
  await expect(queued).toContainText('Waiting for worker');
  await expect(queued).not.toContainText('missing');
  await expect(queued).not.toContainText('0/3');
  await expect(queued.getByRole('button', { name: /Delete/ })).toBeDisabled();
  await expect(page.locator('[data-paper-id="failed"]')).toContainText('Extraction stopped');
  await expect(page.locator('[data-paper-id="graded"]').getByRole('link', { name: 'View grades' })).toHaveAttribute('href', 'grade-results.html?id=graded');
  await expect(page.locator('#paper-identity-note')).toContainText('1 paper needs');
  await expect(page.locator('.workspace-nav-link[data-admin-only]')).toHaveCount(2);
  await expect(page.locator('.workspace-nav-link[data-admin-only]').first()).toBeHidden();
  await page.getByRole('button', { name: 'Ready to grade 1', exact: true }).click();
  await expect(page.locator('.paper-item')).toHaveCount(1);
  await expect(page.locator('.paper-item')).toHaveAttribute('data-paper-id', 'ready');
});

test('search, assessment and stage persist on reload with honest empty states', async ({ page }) => {
  await mock(page);
  await page.goto('/pages/submissions.html?exam_id=exam-1');
  await expect(page.locator('#submission-exam')).toHaveValue('exam-1');
  await page.getByRole('button', { name: 'Grades recorded 2', exact: true }).click();
  await page.getByRole('searchbox', { name: 'Find a paper' }).fill('TEST-graded');
  await expect(page.locator('.paper-item')).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole('searchbox', { name: 'Find a paper' })).toHaveValue('TEST-graded');
  await expect(page.locator('#submission-readiness')).toHaveValue('graded');
  await page.getByRole('searchbox', { name: 'Find a paper' }).fill('no such student');
  await expect(page.getByRole('heading', { name: 'No papers match these filters' })).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await expect(page.locator('.paper-item')).toHaveCount(5);
});

test('batch links isolate their papers and can return to the assessment', async ({ page }) => {
  await mock(page, [paper('batch-paper', { batch_id: 'batch1' }), paper('other-paper', { batch_id: 'batch2' })]);
  await page.goto('/pages/submissions.html?exam_id=exam-1&batch_id=batch1');
  await expect(page.locator('.paper-item')).toHaveCount(1);
  await expect(page.locator('.paper-item')).toHaveAttribute('data-paper-id', 'batch-paper');
  await expect(page.locator('#paper-batch-scope')).toBeVisible();
  await page.reload();
  await expect(page.locator('.paper-item')).toHaveCount(1);
  await page.getByRole('button', { name: 'Show all assessment papers' }).click();
  await expect(page.locator('.paper-item')).toHaveCount(2);
  await expect(page).not.toHaveURL(/batch_id/);
  await expect(page).toHaveURL(/exam_id=exam-1/);
});

test('refresh preserves records on failure and recovers without losing filters', async ({ page }) => {
  const state = await mock(page);
  await page.goto('/pages/submissions.html');
  await expect(page.locator('.paper-item')).toHaveCount(5);
  await page.locator('.paper-filter-panel > summary').click();
  await page.locator('#submission-readiness').selectOption('ready');
  state.fail = true;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Showing the last loaded records');
  await expect(page.locator('.paper-item')).toHaveCount(1);
  state.fail = false;
  state.items = [...state.items, paper('new')];
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.locator('.paper-item')).toHaveCount(2);
  await expect(page.locator('#paper-connection')).toBeHidden();
  await expect(page.locator('#submission-readiness')).toHaveValue('ready');
});

test('polling refreshes completed OCR without a page reload', async ({ page }) => {
  const state = await mock(page, [sample()[0]]);
  await page.clock.install();
  await page.goto('/pages/submissions.html');
  await expect(page.locator('[data-paper-id="queued"]')).toContainText('Waiting for worker');
  state.items = [paper('queued', { latest_ocr_job: { status: 'completed' } })];
  await page.clock.fastForward(12500);
  await expect(page.locator('[data-paper-id="queued"]')).toContainText('Ready to grade');
  await expect(page.locator('#paper-stages [data-stage="processing"] strong')).toHaveText('0');
});

test('retry uses the persisted job and asks before consuming quota', async ({ page }) => {
  const state = await mock(page);
  await page.goto('/pages/submissions.html');
  page.once('dialog', async (dialog) => { expect(dialog.message()).toContain('consume quota'); await dialog.dismiss(); });
  await page.getByRole('button', { name: 'Retry extraction', exact: true }).click();
  expect(state.retries).toBe(0);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Retry extraction', exact: true }).click();
  await expect(page.locator('[data-paper-id="failed"]')).toContainText('Waiting for worker');
  expect(state.retries).toBe(1);
});

test('pagination keeps long lists manageable and search covers all loaded papers', async ({ page }) => {
  await mock(page, Array.from({ length: 25 }, (_, i) => paper(String(i))));
  await page.goto('/pages/submissions.html');
  await expect(page.locator('.paper-item')).toHaveCount(20);
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.locator('.paper-item')).toHaveCount(5);
  await page.getByRole('searchbox', { name: 'Find a paper' }).fill('TEST-0');
  await expect(page.locator('.paper-item')).toHaveCount(1);
  await expect(page.locator('#paper-pagination')).toBeHidden();
});

test('dashboard directs extracted work to grading, not already recorded grades', async ({ page }) => {
  await mock(page, [paper('ready')]);
  await page.goto('/pages/dashboard.html');
  await expect(page.locator('#dashboard-primary-action')).toHaveText('Start grading');
  await expect(page.locator('#dashboard-primary-action')).toHaveAttribute('href', 'submissions.html?exam_id=exam-1');
  await expect(page.locator('#dashboard-stats')).toContainText('Grades recorded0');
  await page.getByRole('searchbox', { name: 'Find an assessment' }).fill('unknown');
  await expect(page.getByRole('heading', { name: 'No matching assessments' })).toBeVisible();
});

test('completed extraction is never counted as recorded grades and reviews remain explicit', async ({ page }) => {
  await mock(page, [paper('complete', { status: 'completed' }), paper('review', { status: 'needs_review' }), paper('working', { status: 'grading' })]);
  await page.goto('/pages/submissions.html');
  await expect(page.locator('[data-paper-id="complete"]')).toContainText('Ready to grade');
  await expect(page.locator('[data-paper-id="review"]')).toContainText('Grade review needed');
  await expect(page.locator('[data-paper-id="working"]')).toContainText('Grading in progress');
  await expect(page.locator('#paper-stages [data-stage="graded"] strong')).toHaveText('1');
});

test('queued grading and interrupted grading cannot appear ready to grade', async ({ page }) => {
  await mock(page, [paper('grading-queued', { latest_grading_job: { status: 'queued', progress_total: 3, progress_percent: 0 } }), paper('grading-failed', { status: 'grading', latest_grading_job: { status: 'failed', error_message: 'Grading provider unavailable.' } })]);
  await page.goto('/pages/submissions.html');
  await expect(page.locator('[data-paper-id="grading-queued"]')).toContainText('Grading queued');
  await expect(page.locator('[data-paper-id="grading-queued"]').getByRole('link', { name: 'View progress' })).toHaveAttribute('href', 'grade-results.html?id=grading-queued');
  await expect(page.locator('[data-paper-id="grading-failed"]')).toContainText('Grading stopped');
  await expect(page.locator('#paper-stages [data-stage="ready"] strong')).toHaveText('0');
});

test('long and untrusted names remain text, with keyboard-accessible filters', async ({ page }) => {
  await mock(page, [paper('unsafe', { extracted_student_name: '<img src=x onerror="window.injected=true">', extracted_student_number: 'S' + '123'.repeat(40) }), paper('arabic', { extracted_student_name: 'اسم تجريبي طويل للطالب لاختبار اتجاه الكتابة وعرض البيانات' })]);
  await page.goto('/pages/submissions.html');
  await expect(page.locator('.paper-person img')).toHaveCount(0);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  const summary = page.locator('.paper-filter-panel > summary');
  await summary.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#submission-identity')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('deleting requires confirmation and removes only the chosen paper', async ({ page }) => {
  const state = await mock(page);
  await page.goto('/pages/submissions.html');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.locator('[data-delete-submission="ready"]').click();
  await expect(page.locator('.paper-item')).toHaveCount(5);
  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('[data-delete-submission="ready"]').click();
  await expect(page.locator('.paper-item')).toHaveCount(4);
  expect(state.items.some((item) => item.id === 'ready')).toBe(false);
});

for (const theme of ['light', 'dark']) {
  test('paper workspace visual coverage in ' + theme, async ({ page }, testInfo) => {
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await mock(page);
    await page.addInitScript((theme) => localStorage.setItem('misra-theme', theme), theme);
    await page.goto('/pages/submissions.html');
    await expect(page.locator('.paper-item')).toHaveCount(5);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('papers-' + theme + '.png'), fullPage: true, animations: 'disabled' });
    await page.goto('/pages/dashboard.html');
    await expect(page.locator('.dashboard-assessment')).toHaveCount(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('overview-' + theme + '.png'), fullPage: true, animations: 'disabled' });
    expect(errors).toEqual([]);
  });
}
