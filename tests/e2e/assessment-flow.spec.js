const { test, expect } = require('@playwright/test');

async function mockAssessmentFlow(page) {
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname.replace('/api', '');
    let body = {};
    if (pathname === '/auth/me') body = { id: 'flow-teacher', full_name: 'Test Instructor', role: 'teacher' };
    else if (pathname === '/health') body = { status: 'ok', model: 'test' };
    else if (pathname === '/exams') body = [
      { id: 'draft-exam', course_code: 'TEST101', title: 'Draft exam', question_count: 2, approved_question_count: 1, submission_count: 0, review_count: 0 },
      { id: 'ready-exam', course_code: 'TEST102', title: 'Ready exam', question_count: 2, approved_question_count: 2, submission_count: 0, review_count: 0 },
    ];
    else if (pathname === '/exams/draft-exam/setup-readiness') body = {
      ready: false, question_count: 2, pending_questions: ['2'], questions: [
        { question_id: 'q1', question_number: '1', errors: [] },
        { question_id: 'q2', question_number: '2', errors: ['Review and approve a rubric for this question.'] },
      ],
    };
    else if (pathname === '/exams/ready-exam/setup-readiness') body = { ready: true, question_count: 2, pending_questions: [], questions: [] };
    else if (pathname === '/submissions') body = [];
    else if (pathname === '/jobs') body = { items: [], active_count: 0 };
    else if (pathname === '/questions') body = [];
    await route.fulfill({ json: body });
  });
}

test('unfinished rubric setup replaces the upload picker with direct fixes', async ({ page }, testInfo) => {
  await mockAssessmentFlow(page);
  await page.goto('/pages/upload.html?exam_id=draft-exam');
  await expect(page.getByRole('heading', { name: 'Finish assessment setup first' })).toBeVisible();
  await expect(page.locator('#upload-ready-fields')).toBeHidden();
  await expect(page.locator('#paper-files')).toBeDisabled();
  await expect(page.getByRole('link', { name: 'Fix question' })).toHaveAttribute('href', 'rubric-studio.html?exam_id=draft-exam&question_id=q2');
  await expect(page.locator('[data-assessment-next]')).toHaveAttribute('href', 'rubric-studio.html?exam_id=draft-exam');
  await page.screenshot({ path: testInfo.outputPath('blocked-upload.png'), fullPage: true, animations: 'disabled' });
});

test('current assessment persists across page reloads and ready setup opens upload', async ({ page }) => {
  await mockAssessmentFlow(page);
  await page.goto('/pages/upload.html?exam_id=ready-exam');
  await expect(page.locator('#upload-ready-fields')).toBeVisible();
  await expect(page.locator('#paper-files')).toBeEnabled();
  await expect(page.locator('[data-assessment-select]')).toHaveValue('ready-exam');
  await expect(page.locator('.workspace-nav-link[href="submissions.html?exam_id=ready-exam"]')).toBeVisible();
  await page.goto('/pages/upload.html');
  await expect(page.locator('#upload-exam')).toHaveValue('ready-exam');
  await expect(page.locator('#upload-ready-fields')).toBeVisible();
  await page.locator('[data-assessment-select]').selectOption('draft-exam');
  await expect(page).toHaveURL(/upload\.html\?exam_id=draft-exam/);
  await expect(page.locator('#upload-ready-fields')).toBeHidden();
});
