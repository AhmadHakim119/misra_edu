const { test, expect } = require('@playwright/test');

const exams = [
  { id: 'e1', course_id: 'c1', course_code: 'CS2071', course_title: 'Database Systems', term: 'Spring 2026', title: 'Midterm examination', question_count: 3, approved_question_count: 3, submission_count: 12, review_count: 2 },
  { id: 'e2', course_id: 'c1', course_code: 'CS2071', course_title: 'Database Systems', term: 'Spring 2026', title: 'Final assignment', question_count: 2, approved_question_count: 0, submission_count: 0, review_count: 0 },
  { id: 'e3', course_id: 'c2', course_code: 'MATH203', course_title: 'Discrete Mathematics', title: 'Logic quiz', question_count: 2, approved_question_count: 2, submission_count: 0, review_count: 0 },
];
const checks = { ready: true, message: 'Setup checks passed. Ready for student answers.', questions: [
  { question_id: 'q1', question_number: '1', max_score: 6, approved: true, rubric_version: 2, reference_recorded: true, grading_approach: 'lenient', evidence_mode: 'image_text_required', errors: [], warnings: [] },
  { question_id: 'q2', question_number: '2', max_score: 4, approved: true, rubric_version: 1, reference_recorded: false, grading_approach: 'balanced', evidence_mode: 'adaptive', errors: [], warnings: ['Confirm that the criteria are sufficient for an open-ended answer.'] },
] };
async function mock(page, { empty = false, fail = false, dark = false } = {}) {
  if (dark) await page.addInitScript(() => localStorage.setItem('misra-theme', 'dark'));
  let failures = fail ? 1 : 0;
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    if (path.endsWith('/setup-readiness') && failures-- > 0) return route.fulfill({ status: 503, json: { detail: 'Connection interrupted' } });
    const body = path === '/auth/me' ? { id: 't', full_name: 'Test Instructor', role: 'teacher' } :
      path === '/health' ? { status: 'ok', model: 'test-model' } :
      path === '/exams' ? (empty ? [] : exams) : path === '/courses' ? [] :
      path.endsWith('/setup-readiness') ? checks : {};
    return route.fulfill({ json: body });
  });
}

test('course groups, typo search and filters keep assessment actions scoped', async ({ page }) => {
  await mock(page);
  await page.goto('/pages/assessments.html');
  await expect(page.locator('.assessment-course-group')).toHaveCount(2);
  await page.getByLabel('Find an assessment').fill('databse');
  await expect(page.locator('.assessment-item')).toHaveCount(2);
  await page.getByLabel('Show', { exact: true }).selectOption('setup');
  await expect(page.locator('.assessment-item')).toHaveCount(1);
  await expect(page.getByRole('link', { name: 'Finish setup' })).toHaveAttribute('href', 'rubric-studio.html?exam_id=e2');
  await page.getByLabel('Find an assessment').fill('zzzzzzzz');
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await expect(page.locator('.assessment-item')).toHaveCount(3);
});

test('inline workspace shows versioned boundaries and scoped grades link', async ({ page }, testInfo) => {
  await mock(page);
  await page.goto('/pages/assessments.html?exam_id=e1');
  await expect(page.getByText('Approved rubric v2')).toBeVisible();
  await expect(page.getByText('Approved rubric v2')).toContainText('Image required');
  await expect(page.getByRole('link', { name: /3. Grades & export/ })).toHaveAttribute('href', 'grades.html?exam_id=e1');
  await expect(page.getByRole('link', { name: 'Edit question 1 rubric' })).toHaveAttribute('href', 'rubric-studio.html?exam_id=e1&question_id=q1');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('assessment-workspace.png'), fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: 'Logic quiz', exact: true }).click();
  await expect(page.locator('#workspace-e1')).toBeHidden();
  await expect(page.getByRole('link', { name: /3. Grades & export/ })).toHaveAttribute('href', 'grades.html?exam_id=e3');
});

test('failed checks offer retry without claiming setup is ready', async ({ page }) => {
  await mock(page, { fail: true });
  await page.goto('/pages/assessments.html?exam_id=e1');
  await expect(page.getByRole('alert')).toContainText('Could not check setup');
  await expect(page.getByText('Setup checked', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Retry checks' }).click();
  await expect(page.getByText('Setup checked', { exact: true })).toBeVisible();
});

test('new assessment opens actual form and empty catalog explains the next action', async ({ page }) => {
  await mock(page, { empty: true });
  await page.goto('/pages/assessments.html');
  await expect(page.getByText('Start with your first assessment')).toBeVisible();
  await page.getByRole('button', { name: 'New assessment', exact: true }).click();
  await expect(page.locator('#assessment-title')).toBeFocused();
  await expect(page.locator('#new-assessment')).toHaveAttribute('open', '');
});

test('dark mode and keyboard disclosure remain usable', async ({ page }, testInfo) => {
  await mock(page, { dark: true });
  await page.goto('/pages/assessments.html');
  const toggle = page.getByRole('button', { name: 'Midterm examination', exact: true });
  await toggle.focus(); await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByText('Approved rubric v2')).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.screenshot({ path: testInfo.outputPath('assessment-dark.png'), fullPage: true, animations: 'disabled' });
});
