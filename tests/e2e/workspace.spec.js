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
    '/exams': [{
      id: 'exam-1',
      title: 'Database Systems Midterm',
      course_code: 'CS2071',
      question_count: 3,
      submission_count: 1,
      review_count: 1,
    }],
    '/submissions': [{
      id: 'submission-1',
      extracted_student_name: 'Leen Sharab',
      extracted_student_number: 'S23108524',
      identity_status: 'matched',
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

  await expect(page.getByRole('heading', { name: 'Instructor overview' })).toBeVisible();
  await expect(page.getByText('Database Systems Midterm')).toBeVisible();
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
});

test('failed dashboard requests produce an actionable retry state', async ({ page }) => {
  await mockWorkspaceApi(page, { '/exams': undefined });
  await page.goto('/pages/dashboard.html');

  await expect(page.getByRole('alert').first()).toContainText('Start the backend on port 8000');
  await expect(page.getByRole('button', { name: 'Reload and try again' }).first()).toBeVisible();
});
