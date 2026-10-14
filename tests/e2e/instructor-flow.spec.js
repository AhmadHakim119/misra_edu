const { test, expect } = require('@playwright/test');

const submission = { id: 'paper', exam_id: 'exam', page_count: 1, extracted_student_name: 'Synthetic Learner', extracted_student_number: 'TEST-1' };
const questions = [1, 2].map(n => ({ question: { id: `q${n}`, question_number: String(n), question_text: `Explain synthetic concept ${n}`, max_score: 3 }, sources: [], mapping_flags: [], answer: { id: `a${n}`, raw_ocr_text: 'Synthetic response' } }));
const answers = questions.map((row, i) => ({ id: `a${i + 1}`, question_id: row.question.id, score: 2, max_score: 3, criteria_scores: [], needs_review: false }));
const extraction = { submission, questions, unmatched_segments: [], excluded_segments: [], readiness: { expected_question_count: 2, mapped_answer_count: 2, missing_question_numbers: [], suspicious_mapping_count: 0, unmatched_segment_count: 0, bulk_grading_allowed: true } };

async function mock(page, handler = async () => false) {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    if (await handler(route, path)) return;
    let body = {};
    if (path === '/auth/me') body = { id: 'teacher', role: 'teacher', full_name: 'Synthetic Instructor' };
    else if (path === '/health') body = { status: 'ok' };
    else if (path === '/exams') body = [{ id: 'exam', course_id: 'course', course_code: 'TEST', title: 'Synthetic assessment' }];
    else if (path === '/submissions') body = [];
    else if (path === '/results/paper') body = { submission, answers, latest_review_labels: [] };
    else if (path.endsWith('/extraction-review')) body = extraction;
    else if (path.endsWith('/jobs')) body = path === '/jobs' ? { items: [], active_count: 0 } : [];
    else if (path === '/evaluation') body = { overall: { label_count: 0 } };
    await route.fulfill({ json: body });
  });
}

test('question navigation filters without losing edits and keeps the next action local', async ({ page }, testInfo) => {
  await mock(page, async (route, path) => {
    if (path !== '/results/paper') return false;
    await route.fulfill({ json: { submission, answers: answers.map((answer, index) => ({ ...answer, needs_review: index === 1 })), latest_review_labels: [] } });
    return true;
  });
  await page.goto('/pages/grade-results.html?id=paper');
  await expect(page.locator('[data-grade-question="q2"]')).not.toHaveAttribute('open', '');
  await expect(page.locator('[data-grade-question="q1"]').getByText('Confidence not recorded', { exact: true })).toBeVisible();
  await page.locator('[data-answer-id="a1"] [name="reviewer_notes"]').fill('Keep my unfinished note');
  await page.getByRole('button', { name: 'Review 1 flagged', exact: true }).click();
  await expect(page.locator('[data-grade-question="q1"]')).toBeHidden();
  await expect(page.locator('[data-grade-question="q2"]')).toHaveAttribute('open', '');
  await page.getByLabel('Go to a question', { exact: true }).selectOption('q1');
  await expect(page.locator('[data-answer-id="a1"] [name="reviewer_notes"]')).toHaveValue('Keep my unfinished note');
  await expect(page.getByRole('button', { name: 'All questions', exact: true })).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('guided-grading.png'), fullPage: true });
  await page.evaluate(() => document.documentElement.dataset.theme = 'dark');
  await page.screenshot({ path: testInfo.outputPath('guided-grading-dark.png'), fullPage: true });
});

test('saving one question preserves another draft; failed save preserves edits and leaving warns', async ({ page }, testInfo) => {
  let fail = false;
  await mock(page, async (route, path) => {
    if (!path.endsWith('/resolve-review')) return false;
    await route.fulfill({ status: fail ? 503 : 200, json: fail ? { detail: 'Temporarily offline' } : {} });
    return true;
  });
  await page.goto('/pages/grade-results.html?id=paper');
  const first = page.locator('[data-answer-id="a1"]');
  const second = page.locator('[data-answer-id="a2"]');
  await page.getByRole('button', { name: 'Expand all', exact: true }).click();
  await second.locator('[name="reviewer_notes"]').fill('Keep this unsaved explanation');
  await first.getByRole('button', { name: 'Save instructor grade' }).click();
  await expect(first.locator('[data-grade-form-status]')).toHaveText('Saved');
  await expect(second.locator('[name="reviewer_notes"]')).toHaveValue('Keep this unsaved explanation');
  fail = true;
  await second.getByRole('button', { name: 'Save instructor grade' }).click();
  await expect(second.locator('[data-grade-form-status]')).toContainText('Not saved');
  await expect(second.locator('[name="reviewer_notes"]')).toBeEnabled();
  await expect(second.locator('[name="reviewer_notes"]')).toHaveValue('Keep this unsaved explanation');
  const dialog = page.waitForEvent('dialog');
  const navigation = page.goto('/pages/grades.html').catch(() => {});
  await (await dialog).dismiss();
  await navigation;
  await expect(page).toHaveURL(/grade-results/);
  await page.screenshot({ path: testInfo.outputPath('grade-review.png'), fullPage: true });
  await page.evaluate(() => document.documentElement.dataset.theme = 'dark');
  await page.screenshot({ path: testInfo.outputPath('grade-review-dark.png'), fullPage: true });
});

for (const kind of ['ocr', 'grading']) {
  test(`${kind} reconnect checks the existing job without scheduling duplicates`, async ({ page }) => {
    let jobChecks = 0;
    let writes = 0;
    await mock(page, async (route, path) => {
      if (route.request().method() !== 'GET') writes += 1;
      if (path === '/submissions/paper/jobs') {
        await route.fulfill({ json: jobChecks >= 2 ? [] : [{ id: 'job', status: 'processing' }] });
        return true;
      }
      if (path === '/jobs/job') {
        jobChecks += 1;
        await route.fulfill({ status: jobChecks === 1 ? 503 : 200, json: jobChecks === 1 ? { detail: 'Disconnected' } : { id: 'job', status: 'completed' } });
        return true;
      }
      return false;
    });
    await page.goto(`/pages/${kind === 'ocr' ? 'submission' : 'grade-results'}.html?id=paper`);
    await expect(page.getByText('Progress connection interrupted')).toBeVisible();
    await page.getByRole('button', { name: 'Reconnect', exact: true }).click();
    await expect(page.getByText('Progress connection interrupted')).toHaveCount(0);
    expect(jobChecks).toBeGreaterThanOrEqual(2);
    expect(writes).toBe(0);
  });
}

test('external practical is not an AI zero and label count does not claim calibration', async ({ page }, testInfo) => {
  const scope = { kind: 'paper_only', external_question_ids: ['q2'], external_question_numbers: ['2'], external_max_score: 3, paper_max_score: 3 };
  await mock(page, async (route, path) => {
    let body;
    if (path === '/results/paper') body = { submission, answers: [{ ...answers[0], final_confidence: 90 }], external_answers: [answers[1]], latest_review_labels: [], grading_scope: scope };
    else if (path.endsWith('/extraction-review')) body = { ...extraction, questions: [questions[0]], grading_scope: scope, external_questions: [questions[1].question] };
    else if (path === '/evaluation') body = { overall: { label_count: 100 }, unique_answer_count: 30 };
    else return false;
    await route.fulfill({ json: body });
    return true;
  });
  await page.goto('/pages/grade-results.html?id=paper');
  await expect(page.getByText('Paper-only recorded score', { exact: true })).toBeVisible();
  await expect(page.getByText('Paper component only — not the full exam grade', { exact: true })).toBeVisible();
  await expect(page.locator('[data-instructor-grade-form]')).toHaveCount(1);
  await expect(page.getByText(/Model estimate .*uncalibrated/)).toBeVisible();
  await expect(page.getByText(/30 distinct labelled answers/)).toBeVisible();
  await expect(page.locator('.grade-question > summary').filter({ hasText: 'Assessed outside MISRA' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('paper-only-light.png'), fullPage: true });
  await page.evaluate(() => document.documentElement.dataset.theme = 'dark');
  await page.screenshot({ path: testInfo.outputPath('paper-only-dark.png'), fullPage: true });
});

test('export shows every student, distinguishes profiles, and blocks an empty Blackboard export', async ({ page }, testInfo) => {
  const rows = Array.from({ length: 10 }, (_, i) => ({ submission_id: `p${i}`, student_name: `Synthetic Student ${i}`, username: i ? `TEST-${i}` : null, score: 2, max_score: 3, issues: i ? [] : [{ code: 'missing_identifier', blocking: true, message: 'Student number is missing' }] }));
  await mock(page, async (route, path) => {
    if (!path.includes('preflight')) return false;
    await route.fulfill({ json: { rows, grade_column: 'Synthetic assessment', counts: { ready: rows.filter(row => !row.issues.length).length, missing_identifier: 1 } } });
    return true;
  });
  await page.goto('/pages/grades.html?exam_id=exam');
  await expect(page.locator('.export-preflight-row')).toHaveCount(10);
  await expect(page.getByText('9 included · 1 excluded.', { exact: false })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Fix identity' })).toHaveAttribute('href', 'submission.html?id=p0#metadata-editor');
  await page.selectOption('#export-profile', 'generic');
  await expect(page.getByText('10 included · 0 excluded.', { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.locator('#export-profile')).toHaveValue('generic');
  rows.splice(1);
  await page.selectOption('#export-profile', 'blackboard');
  await expect(page.locator('#export-csv')).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByText('0 included · 1 excluded.', { exact: false })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('export-light.png'), fullPage: true });
  await page.evaluate(() => document.documentElement.dataset.theme = 'dark');
  await page.screenshot({ path: testInfo.outputPath('export-dark.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test('identity save failure keeps input, opens from export link, and page selection persists', async ({ page }, testInfo) => {
  await mock(page, async (route, path) => {
    if (!path.endsWith('/metadata')) return false;
    await route.fulfill({ status: 503, json: { detail: 'Temporarily offline' } });
    return true;
  });
  await page.goto('/pages/submission.html?id=paper#metadata-editor');
  await expect(page.locator('#student-name')).toBeVisible();
  await page.locator('#student-name').fill('Corrected synthetic name');
  await page.getByRole('button', { name: 'Save paper details' }).click();
  await expect(page.locator('#metadata-form [role="status"]')).toContainText('Not saved');
  await expect(page.locator('#student-name')).toHaveValue('Corrected synthetic name');
  await expect(page.locator('#student-name')).toBeEnabled();
  await expect(page).toHaveURL(/page=0/);
  expect(await page.locator('#unmatched-panel').evaluate(element => Boolean(document.querySelector('.extraction-layout').compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING))).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('extraction-light.png'), fullPage: true });
  await page.evaluate(() => document.documentElement.dataset.theme = 'dark');
  await page.screenshot({ path: testInfo.outputPath('extraction-dark.png'), fullPage: true });
});
