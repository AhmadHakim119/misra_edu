const { test, expect } = require('@playwright/test');

const API = 'http://127.0.0.1:8000/api';

async function mockWorkspaceApi(page, overrides = {}) {
  const responses = {
    '/auth/me': {
      id: 'instructor-1',
      email: 'instructor@example.edu',
      full_name: 'Test Instructor',
      role: 'admin',
      must_change_password: false,
    },
    '/health': { status: 'ok', model: 'test-model', queue: 'available' },
    '/jobs': { items: [], active_count: 0 },
    '/exams': [{
      id: 'exam-1',
      title: 'Database Systems Midterm',
      course_code: 'CS2071',
      question_count: 3,
      approved_question_count: 2,
      submission_count: 1,
      review_count: 1,
    }],
    '/submissions': [{
      id: 'submission-1',
      extracted_student_name: 'Example Student',
      extracted_student_number: 'TEST-1001',
      identity_status: 'matched',
      status: 'graded',
    }],
    ...overrides,
  };

  await page.route(`${API}/**`, async (route) => {
    const url = new URL(route.request().url());
    const payload = responses[url.pathname.replace('/api', '')];
    if (payload === undefined) {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Not mocked' }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
  });
}

test('dashboard is usable with keyboard and exposes live records', async ({ page }) => {
  await mockWorkspaceApi(page);
  await page.goto('/pages/dashboard.html');

  await expect(page.getByRole('heading', { name: 'Keep every assessment moving.' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Database Systems Midterm' })).toBeVisible();
  await expect(page.getByText('Finish rubrics')).toBeVisible();
  await expect(page.getByText('What needs you now')).toBeVisible();
  await expect(page.getByText('Test Instructor')).toBeVisible();

  const skipLink = page.getByRole('link', { name: 'Skip to main content' });
  await skipLink.focus();
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(page.locator('#workspace-content')).toBeFocused();
});

test('mobile navigation opens, receives focus, and closes with Escape', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes('mobile'), 'Mobile interaction is covered in the mobile project.');
  await mockWorkspaceApi(page);
  await page.goto('/pages/dashboard.html');

  const menu = page.getByRole('button', { name: 'Open navigation' });
  await menu.click();
  await expect(menu).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('link', { name: 'Overview' })).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(menu).toHaveAttribute('aria-expanded', 'false');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
  expect(overflow).toBeTruthy();
});

test('theme selection is controlled from Settings and persists after reload', async ({ page }) => {
  await mockWorkspaceApi(page);
  await page.addInitScript(() => {
    if (!localStorage.getItem('misra-theme')) localStorage.setItem('misra-theme', 'light');
  });
  await page.goto('/pages/account.html');

  await page.getByRole('radio', { name: /Dark/ }).check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.getByText('Dark theme selected')).toBeVisible();

  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.getByRole('radio', { name: /Dark/ })).toBeChecked();

  await page.goto('/pages/dashboard.html');
  const colors = await page.evaluate(() => ({
    body: getComputedStyle(document.body).backgroundColor,
    card: getComputedStyle(document.querySelector('.dashboard-command')).backgroundColor,
  }));
  expect(colors.body).toBe('rgb(8, 11, 9)');
  expect(colors.card).toBe('rgb(18, 23, 19)');
});

test('failed dashboard requests produce an actionable retry state', async ({ page }) => {
  await mockWorkspaceApi(page, { '/exams': undefined });
  await page.goto('/pages/dashboard.html');

  await expect(page.getByRole('alert').first()).toContainText('Start the backend on port 8000');
  await expect(page.getByRole('button', { name: 'Reload and try again' }).first()).toBeVisible();
});

test('background OCR progress remains visible after navigation', async ({ page }) => {
  const activeJob = {
    id: 'job-1',
    job_type: 'ocr_batch',
    status: 'processing',
    batch_id: 'batch-1',
    submission_id: null,
    exam_id: 'exam-1',
    exam_title: 'Database Systems Midterm',
    course_code: 'CS2071',
    progress_current: 4,
    progress_total: 11,
    progress_percent: 36.4,
    progress_message: 'Extracting submission 4 of 11',
  };
  await mockWorkspaceApi(page, { '/jobs': { items: [activeJob], active_count: 1 } });

  await page.goto('/pages/dashboard.html');
  await expect(page.getByText('1 background task in progress')).toBeVisible();
  await expect(page.getByText('Extracting submission 4 of 11')).toBeVisible();
  await expect(page.getByRole('progressbar', { name: 'Extracting uploaded batch progress' })).toHaveAttribute('aria-valuenow', '36.4');

  await page.goto('/pages/account.html');
  await expect(page.getByText('1 background task in progress')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open' })).toHaveAttribute('href', 'submissions.html?exam_id=exam-1&batch_id=batch-1');
});

test('completed background work stays visible until dismissed', async ({ page }) => {
  const completedJob = {
    id: 'job-complete',
    job_type: 'ocr_batch',
    status: 'completed',
    batch_id: 'batch-1',
    submission_id: null,
    exam_id: 'exam-1',
    exam_title: 'Database Systems Midterm',
    course_code: 'CS2071',
    progress_current: 11,
    progress_total: 11,
    progress_percent: 100,
    progress_message: 'Batch extraction complete',
  };
  await mockWorkspaceApi(page, { '/jobs': { items: [completedJob], active_count: 0 } });

  await page.goto('/pages/dashboard.html');
  await expect(page.getByText('Background activity finished')).toBeVisible();
  await page.getByRole('button', { name: 'Dismiss Extracting uploaded batch' }).click();
  await expect(page.locator('[data-job-center]')).toBeHidden();

  await page.reload();
  await expect(page.locator('[data-job-center]')).toBeHidden();
});

test('paper-level batch failures are not presented as successful extraction', async ({ page }) => {
  const completedWithErrors = {
    id: 'job-with-errors',
    job_type: 'ocr_batch',
    status: 'completed',
    batch_id: 'batch-1',
    exam_id: 'exam-1',
    exam_title: 'Database Systems Midterm',
    course_code: 'CS2071',
    progress_current: 11,
    progress_total: 11,
    progress_percent: 100,
    progress_message: 'Completed',
    batch_status: 'completed_with_errors',
    batch_total_count: 11,
    batch_completed_count: 0,
    batch_failed_count: 11,
  };
  await mockWorkspaceApi(page, { '/jobs': { items: [completedWithErrors], active_count: 0 } });

  await page.goto('/pages/dashboard.html');
  await expect(page.getByText('Completed with errors')).toBeVisible();
  await expect(page.getByText('0 extracted successfully; 11 failed.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry failed papers' })).toBeVisible();
});
