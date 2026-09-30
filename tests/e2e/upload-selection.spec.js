const { test, expect } = require('@playwright/test');
const path = require('path');
const file = name => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('Synthetic upload fixture') });

async function setup(page, { hold = false, fail = false, jobs = [], theme = 'dark', batchCompleted = 2 } = {}) {
  await page.addInitScript(theme => localStorage.setItem('misra-theme', theme), theme);
  const traffic = [], persisted = new Set();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url()).pathname.replace('/api', '');
    traffic.push({ url, method: request.method(), body: request.postData() });
    let body;
    if (url === '/auth/me') body = { id: 'teacher', full_name: 'Test Instructor', role: 'teacher' };
    else if (url === '/health') body = { status: 'ok', model: 'test' };
    else if (url === '/exams') body = [{ id: 'exam1', title: 'Synthetic assessment', course_code: 'TEST101' }];
    else if (url === '/jobs') body = { items: jobs, active_count: 0 };
    else if (url.endsWith('/setup-readiness')) body = { ready: true, message: 'Rubrics approved. Ready for student answers.' };
    else if (url === '/upload-exam' || url === '/upload-batch') {
      if (hold) await gate;
      if (fail) return route.fulfill({ status: 422, json: { detail: 'Synthetic validation failure. Choose another file.' } });
      persisted.add('student1');
      body = { submission: { id: 'student1' }, job: url === '/upload-batch' ? { id: 'batch-job', batch_id: 'batch1', status: 'queued' } : { id: 'job1', status: 'queued' } };
    } else if (url === '/jobs/job1') body = { id: 'job1', job_type: 'ocr_submission', submission_id: 'student1', status: 'completed', progress_total: 2 };
    else if (url === '/jobs/batch-job') body = { id: 'batch-job', job_type: 'ocr_batch', batch_id: 'batch1', status: 'completed', progress_total: 2 };
    else if (url === '/batches/batch1') body = { batch: { total_count: 2, completed_count: batchCompleted, failed_count: 0 } };
    else if (url.endsWith('/extraction-review')) body = { submission: { id: 'student1' }, readiness: { mapped_answer_count: 1, expected_question_count: 1, mapping_complete: true } };
    else return route.fulfill({ status: 404, json: { detail: 'Not mocked' } });
    await route.fulfill({ json: body });
  });
  await page.goto('/pages/upload.html');
  await expect(page.locator('#upload-button')).toBeEnabled();
  return { traffic, persisted, release, uploads: () => traffic.filter(r => ['/upload-exam', '/upload-batch'].includes(r.url)) };
}

async function drop(page, names) {
  await page.locator('#dropzone').evaluate((element, names) => {
    const dataTransfer = new DataTransfer();
    names.forEach(name => dataTransfer.items.add(new File(['synthetic'], name, { type: 'application/pdf' })));
    element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer }));
  }, names);
}

test('selection locks picker and drop replacement until Remove; keyboard and dark mobile remain usable', async ({ page }, info) => {
  await setup(page);
  const input = page.locator('#paper-files');
  await input.focus();
  await expect(page.locator('#dropzone')).toHaveCSS('outline-style', 'solid');
  if (!info.project.use.isMobile) {
    await page.locator('#dropzone').hover();
    await expect(page.locator('#dropzone')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, -3)');
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(page.locator('#dropzone')).toHaveCSS('transform', 'none');
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await input.setInputFiles(file('first.pdf'));
  await expect(input).toBeDisabled();
  await expect(page.locator('#dropzone')).toHaveAttribute('aria-disabled', 'true');
  await drop(page, ['replacement.pdf']);
  await expect(page.locator('#file-summary')).toContainText('first.pdf');
  await expect(page.locator('#file-summary')).not.toContainText('replacement.pdf');
  await expect(page.locator('[data-mode="batch"]')).toBeDisabled();
  await expect(page.locator('#pages-field')).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.evaluate(() => { document.activeElement.blur(); window.scrollTo({ top: 0, behavior: 'instant' }); });
  await page.screenshot({ path: path.resolve('.impeccable/review', `phase1-upload-${info.project.use.isMobile ? 'mobile' : 'desktop'}.png`), fullPage: true });
  await page.locator('#clear-files').click();
  await expect(input).toBeEnabled();
  await expect(input).toBeFocused();
  await drop(page, ['replacement.pdf']);
  await expect(page.locator('#file-summary')).toContainText('replacement.pdf');
});

test('pending and accepted uploads cannot repeat; new selection never deletes accepted paper', async ({ page }) => {
  const state = await setup(page, { hold: true });
  await page.locator('#paper-files').setInputFiles(file('original.pdf'));
  await page.locator('#upload-button').click();
  await expect.poll(() => state.uploads().length).toBe(1);
  await expect(page.locator('#clear-files')).toBeDisabled();
  await page.locator('#upload-form').dispatchEvent('submit');
  await drop(page, ['duplicate.pdf']);
  expect(state.uploads()).toHaveLength(1);
  state.release();
  await expect(page.locator('#upload-form')).toBeHidden();
  await expect(page.locator('#upload-result')).toContainText('Extraction complete');
  await page.locator('#upload-form').dispatchEvent('submit');
  expect(state.uploads()).toHaveLength(1);
  await page.locator('#upload-another').click();
  await expect(page.locator('#paper-files')).toBeEnabled();
  await expect(page.locator('#file-summary')).toHaveText('No files selected');
  await expect(page).not.toHaveURL(/job_id=/);
  await page.locator('#paper-files').setInputFiles(file('next.pdf'));
  await page.locator('#clear-files').click();
  expect(state.persisted.has('student1')).toBeTruthy();
  expect(state.traffic.filter(r => ['DELETE', 'PATCH', 'PUT'].includes(r.method))).toEqual([]);
  expect(state.uploads()).toHaveLength(1);
});

test('batch submits every selected file and Clear restores mode selection', async ({ page }) => {
  const state = await setup(page);
  await page.locator('[data-mode="batch"]').click();
  await drop(page, ['a.pdf', 'b.pdf']);
  await expect(page.locator('#file-summary')).toContainText('2 files');
  await expect(page.locator('#clear-files')).toHaveText('Clear files');
  await page.locator('#clear-files').click();
  await expect(page.locator('[data-mode="single"]')).toBeEnabled();
  await page.locator('#paper-files').setInputFiles([file('c.pdf'), file('d.pdf')]);
  await page.locator('#upload-button').click();
  await expect(page.locator('#upload-form')).toBeHidden();
  expect(state.uploads()).toHaveLength(1);
  expect(state.uploads()[0].url).toBe('/upload-batch');
  expect(state.uploads()[0].body).toContain('filename="c.pdf"');
  expect(state.uploads()[0].body).toContain('filename="d.pdf"');
});

test('rejected upload retains selection and allows explicit removal', async ({ page }) => {
  await setup(page, { fail: true });
  await page.locator('#paper-files').setInputFiles(file('invalid.pdf'));
  await page.locator('#upload-button').click();
  await expect(page.locator('#upload-result')).toContainText('Synthetic validation failure');
  await expect(page.locator('#paper-files')).toBeDisabled();
  await expect(page.locator('#clear-files')).toBeEnabled();
  await page.locator('#clear-files').click();
  await expect(page.locator('#paper-files')).toBeEnabled();
  await expect(page.locator('#file-summary')).toHaveText('No files selected');
});

test('individual removal updates the batch payload and keeps focus predictable', async ({ page }) => {
  const state = await setup(page);
  await page.locator('[data-mode="batch"]').click();
  await page.locator('#paper-files').setInputFiles([file('keep.pdf'), file('remove.pdf'), file('also-keep.pdf')]);
  await expect(page.getByRole('list', { name: 'Selected papers' }).getByRole('listitem')).toHaveCount(3);
  await expect(page.locator('#pages-field')).toBeHidden();
  await page.getByRole('button', { name: 'Remove remove.pdf', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Remove also-keep.pdf', exact: true })).toBeFocused();
  await page.locator('#upload-button').click();
  await expect(page.locator('#upload-result')).toContainText('2 of 2 papers recorded as extracted');
  expect(state.uploads()[0].body).not.toContain('filename="remove.pdf"');
  expect(state.uploads()[0].body).toContain('filename="keep.pdf"');
  await expect(page.locator('#upload-result a')).toHaveAttribute('href', 'submissions.html?exam_id=exam1&batch_id=batch1');
});

test('combined PDF requires positive whole page counts before upload', async ({ page }) => {
  const state = await setup(page);
  await page.locator('[data-mode="batch"]').click();
  await page.locator('#paper-files').setInputFiles(file('combined.pdf'));
  await page.locator('#pages-per-student').fill('1.5');
  await page.locator('#upload-button').click();
  await expect(page.locator('#upload-result')).toContainText('whole number');
  expect(state.uploads()).toHaveLength(0);
  await page.locator('#clear-files').click();
  await expect(page.locator('#pages-per-student')).toHaveValue('');
  await page.locator('#paper-files').setInputFiles(file('combined.pdf'));
  await page.locator('#pages-per-student').fill('4');
  await page.locator('#upload-button').click();
  await expect.poll(() => state.uploads().length).toBe(1);
  expect(state.uploads()[0].body).toContain('name="pages_per_student"');
});

test('returning to Upload offers the current assessment job without re-uploading', async ({ page }) => {
  const state = await setup(page, { jobs: [
    { id: 'unrelated', exam_id: 'other', job_type: 'ocr_submission', status: 'queued' },
    { id: 'job1', exam_id: 'exam1', job_type: 'ocr_submission', status: 'completed' },
  ] });
  await expect(page.locator('#recent-upload')).toContainText('Finished — review results');
  await page.locator('#recent-upload a').click();
  await expect(page.locator('#upload-form')).toBeHidden();
  await expect(page.locator('#upload-result')).toContainText('Extraction complete');
  await page.reload();
  await expect(page.locator('#upload-result')).toContainText('Extraction complete');
  expect(state.uploads()).toHaveLength(0);
});

test('zero extracted papers never appears as a successful full batch', async ({ page }) => {
  await setup(page, { batchCompleted: 0 });
  await page.locator('[data-mode="batch"]').click();
  await page.locator('#paper-files').setInputFiles([file('one.pdf'), file('two.pdf')]);
  await page.locator('#upload-button').click();
  await expect(page.locator('#upload-result')).toContainText('Batch needs a status check');
  await expect(page.locator('#upload-result')).toContainText('0 of 2');
});

for (const theme of ['light', 'dark']) {
  test('upload batch layout in ' + theme, async ({ page }, info) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await setup(page, { theme });
    await page.locator('[data-mode="batch"]').click();
    await page.locator('#paper-files').setInputFiles([file('Database Systems — Section 1 — Student paper.pdf'), file('Another-paper-with-a-very-long-filename-for-responsive-testing.pdf'), file('ورقة اختبار.pdf')]);
    await expect(page.locator('#selected-file-list li')).toHaveCount(3);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath('upload-' + theme + '.png'), fullPage: true, animations: 'disabled' });
    expect(errors).toEqual([]);
  });
}
