const { test, expect } = require('@playwright/test');

async function setup(page, { imported = false, ready = false, dark = false, failConfirm = false } = {}) {
  if (dark) await page.addInitScript(() => localStorage.setItem('misra-theme', 'dark'));
  const traffic = [], questions = [], imports = [];
  const data = { job: { id: 'job1', job_type: 'exam_setup', status: 'completed', progress_total: 1, progress_current: 1 },
    questions: [{ question_number: '1', question_text: 'Explain why the method works.', max_score: 3, marking_guide: 'Award credit for valid reasoning.', answer_key: '', source_pages: ['0:0'] }], documents: [{ role: 'blank_exam', page_count: 1 }], warnings: [] };
  if (imported) imports.push(data);
  let polls = 0;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    const method = route.request().method();
    traffic.push({ path, method });
    let body;
    if (path === '/auth/me') body = { id: 'teacher', full_name: 'Test Instructor', role: 'teacher' };
    else if (path === '/health') body = { status: 'ok', model: 'test-model' };
    else if (path === '/exams') body = [{ id: 'exam1', title: 'Test assessment', course_code: 'TEST101' }];
    else if (path.endsWith('/setup-readiness')) body = { ready, message: ready ? 'Rubrics approved. Ready for student answers.' : 'Review and approve the rubrics before uploading student answers.' };
    else if (path.endsWith('/questions')) body = questions;
    else if (path.endsWith('/setup-imports') && method === 'POST') { imports.push(data); body = { ...data, questions: [], job: { ...data.job, status: 'queued', progress_current: 0 } }; }
    else if (path.endsWith('/setup-imports')) body = imports;
    else if (path.endsWith('/setup-imports/job1')) body = data;
    else if (path.endsWith('/confirm')) {
      if (failConfirm) return route.fulfill({ status: 409, json: { detail: 'Question 1 already exists. Existing questions were not changed.' } });
      const value = route.request().postDataJSON().questions[0];
      questions.push({ ...value, id: 'q1' }); data.imported_question_ids = ['q1']; body = { question_ids: ['q1'] };
    } else if (path.endsWith('/rubric-versions')) body = [{ id: 'v1', version_number: 1, status: 'draft', rubric_json: { max_score: 3, criteria: [{ id: 'c1', title: 'Reasoning', description: 'Valid reasoning', points: 3 }] } }];
    else if (path.endsWith('/rubric')) return route.fulfill({ status: 409, json: { detail: 'Approve the draft first.' } });
    else if (path.endsWith('/grading-policy')) body = { mode: 'adaptive' };
    else if (path === '/upload-exam') body = { job: { id: 'student-job', job_type: 'ocr_submission', status: 'queued' }, submission: { id: 'student1' } };
    else if (path === '/jobs/student-job') body = { id: 'student-job', job_type: 'ocr_submission', submission_id: 'student1', status: polls++ > 0 ? 'completed' : 'processing', progress_current: 0, progress_total: 1 };
    else if (path.endsWith('/extraction-review')) body = { submission: { id: 'student1' }, readiness: { mapped_answer_count: 1, expected_question_count: 1, mapping_complete: true } };
    else return route.fulfill({ status: 404, json: { detail: 'Not mocked' } });
    return route.fulfill({ json: body });
  });
  return traffic;
}
const file = { name: 'blank-exam.pdf', mimeType: 'application/pdf', buffer: Buffer.from('synthetic mocked upload') };

test('setup upload never calls the submission endpoint and leads to draft review', async ({ page }, testInfo) => {
  const traffic = await setup(page);
  await page.goto('/pages/rubric-studio.html');
  await expect(page.locator('#setup-upload-button')).toBeEnabled();
  await page.locator('#setup-exam-file').setInputFiles(file);
  await page.locator('#setup-upload-button').click();
  await expect(page.locator('#setup-upload-form')).toBeHidden();
  await expect(page.locator('#setup-status')).toContainText('ready to review', { timeout: 8000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('setup-review.png'), fullPage: true });
  await page.locator('#setup-confirm-button').click();
  await expect(page.locator('#setup-status')).toContainText('Questions added');
  await expect(page.locator('#rubric-workspace')).toContainText('Approve');
  await expect(page.locator('#upload-link')).toHaveAttribute('aria-disabled', 'true');
  expect(traffic.some(r => r.path === '/upload-exam' || r.path === '/upload-batch')).toBeFalsy();
});

test('completed setup resumes on reload and failed confirmation preserves edits', async ({ page }) => {
  await setup(page, { imported: true, failConfirm: true });
  await page.goto('/pages/rubric-studio.html');
  await expect(page.locator('#setup-review')).toBeVisible();
  await page.locator('#import-text-0').fill('Instructor corrected question.');
  await page.locator('#setup-confirm-button').click();
  await expect(page.locator('#setup-confirm-error')).toContainText('Your edits are still here');
  await expect(page.locator('#import-text-0')).toHaveValue('Instructor corrected question.');
});

test('setup in dark mode preserves the workspace and remains readable', async ({ page }, testInfo) => {
  await setup(page, { dark: true });
  await page.goto('/pages/rubric-studio.html');
  await expect(page.locator('#setup-upload-button')).toBeEnabled();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('#setup-new-upload')).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('setup-dark.png'), fullPage: true });
});

test('student upload requires approved rubrics', async ({ page }) => {
  await setup(page);
  await page.goto('/pages/upload.html');
  await expect(page.locator('#upload-readiness')).toContainText('approve');
  await expect(page.locator('#upload-button')).toBeDisabled();
  await expect(page.locator('#upload-ready-fields')).toBeHidden();
  await expect(page.getByRole('heading', { name: 'Finish assessment setup first' })).toBeVisible();
  await expect(page.locator('#setup-link')).toHaveAttribute('href', 'rubric-studio.html?exam_id=exam1');
});

test('ready rubrics hand off to student upload without treating setup documents as submissions', async ({ page }) => {
  await setup(page, { ready: true });
  await page.goto('/pages/rubric-studio.html');
  await expect(page.locator('#rubric-next-step')).toContainText('Assessment ready for student papers');
  await expect(page.getByRole('link', { name: 'Continue to student uploads' })).toHaveAttribute('href', 'upload.html?exam_id=exam1');
});

test('switching assessments cannot leave the manual workspace hidden', async ({ page }) => {
  await setup(page, { imported: true });
  await page.route('**/api/exams', route => route.fulfill({ json: [{ id: 'exam1', title: 'First exam' }, { id: 'exam2', title: 'Second exam' }] }));
  await page.route('**/api/exams/exam2/setup-imports', route => route.fulfill({ json: [] }));
  await page.goto('/pages/rubric-studio.html');
  await expect(page.locator('#setup-review')).toBeVisible();
  await page.locator('#import-text-0').fill('Unsaved edit.');
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('#rubric-exam').selectOption('exam2');
  await expect(page.locator('#rubric-exam')).toHaveValue('exam1');
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#rubric-exam').selectOption('exam2');
  await expect(page.locator('#setup-review')).toBeHidden();
  await expect(page.locator('.rubric-layout')).toBeVisible();
  await expect(page.locator('#question-composer')).toBeVisible();
});

test('student upload becomes a progress view, then a review action', async ({ page }, testInfo) => {
  await setup(page, { ready: true });
  await page.goto('/pages/upload.html');
  await expect(page.locator('#upload-button')).toBeEnabled();
  await page.locator('#paper-files').setInputFiles(file);
  await page.locator('#upload-button').click();
  await expect(page.locator('#upload-form')).toBeHidden();
  const nextStep = page.getByRole('link', { name: 'Continue to grading', exact: true });
  await expect(nextStep).toBeVisible({ timeout: 8000 });
  await expect(nextStep).toHaveAttribute('href', 'submission.html?id=student1');
  await page.screenshot({ path: testInfo.outputPath('upload-complete.png'), fullPage: true });
  await page.locator('#upload-another').click();
  await expect(page.locator('#upload-form')).toBeVisible();
  await expect(page.locator('#file-summary')).toContainText('No files selected');
});
