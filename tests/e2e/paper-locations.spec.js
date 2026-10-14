const { test, expect } = require('@playwright/test');

async function fixture(page, { native = true, unavailable = false, hold = false } = {}) {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const sources = [{ id: 's1', page_index: 0, page_number: 1, segment_index: 0,
    extracted_text: 'First case: W = 1.00 × 400 = 400 J.',
    ocr_segment: { bounding_box: { x: .1, y: .6, width: .7, height: .01 } } }];
  await page.route('**/api/**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    let body = {};
    if (pathname.endsWith('/auth/me')) body = { id: 'teacher', full_name: 'Synthetic Instructor', role: 'teacher' };
    else if (pathname.endsWith('/health')) body = { status: 'ok', model: 'test' };
    else if (pathname.endsWith('/exams')) body = [{ id: 'exam', course_code: 'TEST', title: 'Synthetic physics' }];
    else if (pathname.endsWith('/setup-readiness')) body = { ready: true, questions: [] };
    else if (pathname.endsWith('/jobs')) body = pathname.includes('/submissions/') ? [] : { items: [], active_count: 0 };
    else if (pathname.endsWith('/extraction-review')) body = {
      submission: { id: 'paper', exam_id: 'exam', page_count: 1, status: 'graded', extracted_student_name: 'Synthetic Test', extracted_student_number: 'TEST001' },
      readiness: { expected_question_count: 1, mapped_answer_count: 1, missing_question_numbers: [], suspicious_mapping_count: 0, unmatched_segment_count: 0, bulk_grading_allowed: true, can_reprocess: false },
      questions: [{ question: { id: 'q1', question_number: '1', question_text: 'Calculate work', max_score: 2 }, answer: { id: 'a1', raw_ocr_text: sources[0].extracted_text }, mapping_flags: [], sources }], unmatched_segments: [],
    };
    else if (pathname.endsWith('/source-locations')) {
      if (hold) await gate;
      if (unavailable) return route.fulfill({ status: 503, json: { detail: 'Unavailable' } });
      body = { page_index: 0, display_only: true, sources: { s1: native
        ? { status: 'located', method: 'native_pdf_text', bounding_box: { x: .1, y: .25, width: .7, height: .025 } }
        : { status: 'unverified', method: 'ocr_estimate', reason: 'ambiguous_text' } } };
    }
    else if (/\/pages\/0$/.test(pathname)) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="white"/><text x="60" y="212" font-size="14">First case: W = 1.00 × 400 = 400 J.</text></svg>' });
    else if (pathname.endsWith('/results/paper')) body = { submission: { id: 'paper', exam_id: 'exam' }, answers: [{ id: 'a1', question_id: 'q1', score: 2, max_score: 2, needs_review: false, review_status: 'approved', criteria_scores: [] }], latest_review_labels: [] };
    else if (pathname.endsWith('/evaluation')) body = { overall: { label_count: 0 } };
    await route.fulfill({ json: body });
  });
  return release;
}

test('extraction highlight encloses native text rather than inaccurate OCR rectangle', async ({ page }, info) => {
  await fixture(page);
  await page.goto('/pages/submission.html?id=paper');
  await page.locator('#extraction-question-jump').selectOption('q1');
  await page.getByRole('button', { name: 'Find answer on page 1' }).click();
  await expect(page.locator('#paper-region-caption')).toContainText('Text matched on the original PDF');
  await expect(page.locator('#page-highlight')).not.toHaveClass(/is-approximate/);
  expect(await page.locator('#page-highlight').evaluate(element => element.style.top)).toBe('25%');
  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo({ top: 0, behavior: 'instant' }); });
  await page.screenshot({ path: info.outputPath('native-text-highlight.png'), fullPage: true, animations: 'disabled' });
});

for (const unavailable of [false, true]) test(`uncertain or unavailable location is explicitly approximate (${unavailable})`, async ({ page }) => {
  await fixture(page, { native: false, unavailable });
  await page.goto('/pages/submission.html?id=paper');
  await page.locator('#extraction-question-jump').selectOption('q1');
  await page.getByRole('button', { name: 'Find answer on page 1' }).click();
  await expect(page.locator('#paper-region-caption')).toContainText('Approximate OCR location');
  await expect(page.locator('#page-highlight')).toHaveClass(/is-approximate/);
  expect(await page.locator('#page-highlight').evaluate(element => element.style.top)).toBe('60%');
});

test('late location response cannot replace another selected page view', async ({ page }) => {
  const release = await fixture(page, { hold: true });
  await page.goto('/pages/submission.html?id=paper');
  await page.locator('#extraction-question-jump').selectOption('q1');
  await page.getByRole('button', { name: 'Find answer on page 1' }).click();
  await expect(page.locator('#paper-region-caption')).toContainText('Finding this answer');
  // A question jump resets the viewer, including same-page navigation.
  await page.locator('#extraction-question-jump').selectOption('q1');
  release();
  await expect(page.locator('#page-highlight')).toBeHidden();
  await expect(page.locator('#paper-region-caption')).toBeHidden();
});

test('grade result evidence uses the same native positions without changing score', async ({ page }) => {
  await fixture(page);
  await page.goto('/pages/grade-results.html?id=paper');
  await expect(page.locator('.evidence-page figcaption')).toContainText('1 text-matched region');
  const box = page.locator('.evidence-highlight');
  await expect(box).not.toHaveClass(/is-approximate/);
  expect(await box.evaluate(element => element.style.getPropertyValue('--evidence-y'))).toBe('25%');
  await expect(page.locator('.grade-question-score')).toContainText('2');
});
