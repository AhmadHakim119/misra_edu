const { test, expect } = require('@playwright/test');

function commonBody(path) {
  if (path === '/auth/me') return { id: 'teacher', full_name: 'Synthetic Instructor', role: 'teacher' };
  if (path === '/health') return { status: 'ok' };
  return null;
}

test('grade override requires a reason and sends structured reason evidence', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const submission = { id: 'submission', exam_id: 'exam', extracted_student_name: 'Synthetic Learner', page_count: 1 };
  const question = { id: 'question', question_number: '1', question_text: 'Synthetic question', max_score: 3 };
  const answer = { id: 'answer', question_id: question.id, score: 2, max_score: 3, criteria_scores: [],
    review_status: 'pending', needs_review: true, final_confidence: 60, raw_ocr_text: 'Synthetic response' };
  let resolution = null;

  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api', '');
    if (path === '/answers/answer/resolve-review') {
      resolution = request.postDataJSON();
      answer.teacher_override_score = resolution.human_score;
      answer.review_status = 'overridden';
      answer.needs_review = false;
      return route.fulfill({ json: { answer, review_label: { answer_id: answer.id, ...resolution } } });
    }
    const shared = commonBody(path);
    if (shared) return route.fulfill({ json: shared });
    if (path === '/exams') return route.fulfill({ json: [{ id: 'exam', title: 'Synthetic assessment' }] });
    if (path === '/results/submission') return route.fulfill({ json: { submission, answers: [answer], latest_review_labels: [] } });
    if (path.endsWith('/extraction-review')) return route.fulfill({ json: { submission, questions: [{ question, sources: [] }] } });
    if (path === '/evaluation') return route.fulfill({ json: { overall: { label_count: 0 } } });
    return route.fulfill({ json: {} });
  });

  await page.goto('/pages/grade-results.html?id=submission');
  const form = page.locator('[data-instructor-grade-form]');
  await form.locator('[name="human_score"]').fill('2.5');
  expect(await form.evaluate((element) => [...element.elements].filter((field) => field.willValidate && !field.checkValidity()).map((field) => field.name))).toEqual([]);
  await form.getByRole('button', { name: 'Save instructor grade' }).click();
  expect(pageErrors).toEqual([]);
  await expect(form.getByText('Select at least one reason')).toBeVisible();
  expect(resolution).toBeNull();

  await form.getByText('Minor notation', { exact: true }).click();
  await form.locator('[name="review_reason_note"]').fill('Meaning is unambiguous.');
  await form.getByRole('button', { name: 'Save instructor grade' }).click();
  await expect.poll(() => resolution).not.toBeNull();
  expect(resolution.action).toBe('override');
  expect(resolution.review_reason_codes).toEqual(['minor_notation']);
  expect(resolution.review_reason_note).toBe('Meaning is unambiguous.');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test('review queue exposes source evidence before decisions and keeps approval reasons optional', async ({ page }) => {
  const answer = { id: 'answer', submission_id: 'submission', question_id: 'question', score: 2, max_score: 2,
    feedback: 'Synthetic feedback', raw_ocr_text: 'Synthetic response', final_confidence: 40, review_reasons: null };
  let resolution = null;
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api', '');
    if (path === '/answers/answer/resolve-review') {
      resolution = request.postDataJSON();
      return route.fulfill({ json: { answer, review_label: { answer_id: answer.id, ...resolution } } });
    }
    const shared = commonBody(path);
    if (shared) return route.fulfill({ json: shared });
    if (path === '/exams') return route.fulfill({ json: [{ id: 'exam', title: 'Synthetic assessment' }] });
    if (path === '/review-queue') return route.fulfill({ json: resolution ? [] : [answer] });
    if (path === '/exams/exam/questions') return route.fulfill({ json: [{ id: 'question', question_number: '1', max_score: 2 }] });
    return route.fulfill({ json: {} });
  });

  await page.goto('/pages/reviews.html?exam_id=exam');
  const evidenceLink = page.getByRole('link', { name: 'Open grade results & source evidence' });
  await expect(evidenceLink).toHaveAttribute('href', 'grade-results.html?id=submission');
  await expect(page.getByText('Model confidence estimate: 40%')).toBeVisible();
  await expect(page.getByText(/uncalibrated model estimate/i)).toBeVisible();
  expect(await page.locator('#review-detail').evaluate((element) => {
    const link = element.querySelector('.review-evidence-cta');
    const form = element.querySelector('#review-form');
    return Boolean(link && form && (link.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING));
  })).toBeTruthy();
  await page.getByRole('button', { name: 'Approve AI score' }).click();
  await expect.poll(() => resolution).not.toBeNull();
  expect(resolution.action).toBe('approve');
  expect(resolution.review_reason_codes).toEqual([]);
  expect(resolution.review_reason_note).toBeNull();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
