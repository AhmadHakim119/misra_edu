const { test, expect } = require('@playwright/test');

async function coverageFixture(page, status = 'needs_attention', { questionCount = 1, hasBox = true } = {}) {
  const box = { x: .1, y: .6, width: .8, height: .2 };
  const issue = { code: 'unaccounted_answer_region', page_index: 1, page_number: 2, region_index: 1, bounding_box: box, message: 'Visible student work has no complete mapped transcription.' };
  if (!hasBox) issue.bounding_box = null;
  const coverage = { status, answer_region_count: 2, accounted_region_count: status === 'needs_attention' ? 1 : 2,
    issues: status === 'needs_attention' ? [issue] : [], warnings: status === 'unverified' ? [{ code: 'page_coverage_unverified' }] : [],
    pages: [{ page_index: 0, page_number: 1, page_role: 'cover', coverage_reported_complete: true, regions: [] },
      { page_index: 1, page_number: 2, page_role: 'answers', coverage_reported_complete: status !== 'unverified', regions: [{ accounted: true }, { accounted: status !== 'needs_attention' }] }] };
  const requests = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (/\/pages\/\d+$/.test(path)) {
      await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="white"/><text x="60" y="60" fill="black">Synthetic test page — not student data</text><text x="60" y="180" fill="black">W = Fd</text><text x="60" y="540" fill="black">F = 12 N (unaccounted region)</text></svg>' });
      return;
    }
    let body = {};
    if (path.endsWith('/auth/me')) body = { id: 'teacher', full_name: 'Test Instructor', role: 'teacher' };
    else if (path.endsWith('/health')) body = { status: 'ok', model: 'test' };
    else if (path.endsWith('/exams')) body = [{ id: 'exam', course_code: 'TEST', title: 'Synthetic exam', question_count: 1, approved_question_count: 1 }];
    else if (path.endsWith('/setup-readiness')) body = { ready: true, questions: [], pending_questions: [] };
    else if (path.endsWith('/jobs')) body = path.includes('/submissions/') ? [] : { items: [], active_count: 0 };
    else if (path.endsWith('/extraction-review')) body = {
      submission: { id: 'paper', exam_id: 'exam', page_count: 2, status: 'extracted', extracted_student_name: 'Synthetic Student', extracted_student_number: 'TEST-1', uploaded_at: '2026-10-12T00:00:00' },
      readiness: { expected_question_count: 1, mapped_answer_count: 1, missing_question_numbers: [], suspicious_mapping_count: 0, unmatched_segment_count: 0, bulk_grading_allowed: status !== 'needs_attention', can_reprocess: true, blocking_reasons: [] },
      coverage, unmatched_segments: [], excluded_segments: [], questions: Array.from({ length: questionCount }, (_, index) => ({ question: { id: `q${index}`, question_number: String(index + 1), question_text: 'Calculate work', max_score: 2 }, answer: { id: `a${index}`, raw_ocr_text: 'W = Fd' }, mapping_flags: [], sources: [{ id: `source${index}`, page_index: 1, page_number: 2, segment_index: 0, extracted_text: 'W = Fd' }] })),
    };
    else if (path.endsWith('/reextract')) {
      requests.push(JSON.parse(route.request().postData()));
      body = { page_index: 1, question_numbers: ['1'], segments: [], notes: 'No tight region found' };
    }
    await route.fulfill({ json: body });
  });
  return requests;
}

test('coverage gap locates original area and offers recovery even when all questions are mapped', async ({ page }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const requests = await coverageFixture(page);
  await page.goto('/pages/submission.html?id=paper');
  await expect(page.locator('#grade-all')).toBeDisabled();
  const area = page.getByRole('button', { name: /Page 2 · Show unresolved answer area/ });
  await area.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#page-label')).toHaveText('Page 2 of 2');
  await expect(page.locator('#page-highlight')).toBeVisible();
  await expect(page.locator('#page-highlight')).toHaveCSS('top', /\d/);
  await expect(page.locator('#paper-region-caption')).toContainText('no complete mapped transcription');
  await expect(page.locator('#source-viewer')).toBeFocused();
  await expect(page.locator('#reextract-page')).toBeEnabled();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo({top:0,behavior:'instant'}); });
  await page.screenshot({ path: testInfo.outputPath('coverage-gap.png'), fullPage: true, animations: 'disabled' });
  await page.locator('#reextract-page').click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].question_numbers).toEqual(['1']);
  expect(errors).toEqual([]);
});

test('uncertain coverage is not presented as independent verification', async ({ page }) => {
  await coverageFixture(page, 'unverified');
  await page.goto('/pages/submission.html?id=paper');
  await page.locator('#coverage-panel summary').click();
  await expect(page.locator('#coverage-panel')).toContainText('Full-page coverage is not confirmed');
  await expect(page.locator('#coverage-panel')).toContainText('does not independently prove');
  await expect(page.locator('#coverage-panel')).toContainText('routed to review');
});

test('coverage controls remain readable and keyboard usable in dark mode', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('misra-theme', 'dark'));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await coverageFixture(page);
  await page.goto('/pages/submission.html?id=paper');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  const area = page.getByRole('button', { name: /Show unresolved answer area/ });
  await area.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#source-viewer')).toBeFocused();
  await expect(page.locator('#page-highlight')).toBeVisible();
  await expect(page.locator('#grade-all')).toBeDisabled();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo({top:0,behavior:'instant'}); });
  await page.screenshot({ path: testInfo.outputPath('coverage-dark.png'), fullPage: true, animations: 'disabled' });
});

test('coverage instructions match unavailable page recovery and missing highlight', async ({ page }, testInfo) => {
  await coverageFixture(page, 'needs_attention', { questionCount: 31, hasBox: false });
  await page.goto('/pages/submission.html?id=paper');
  await page.getByRole('button', { name: /Show unresolved answer area/ }).click();
  await expect(page.locator('#page-highlight')).toBeHidden();
  await expect(page.locator('#reextract-page')).toBeHidden();
  await expect(page.locator('#paper-region-caption')).toContainText('affected page');
  await expect(page.locator('#paper-region-caption')).toContainText('Use Re-run automatic extraction');
  await expect(page.locator('#paper-region-caption')).not.toContainText('highlighted');
  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo({top:0,behavior:'instant'}); });
  await page.screenshot({ path: testInfo.outputPath('coverage-edge.png'), fullPage: true, animations: 'disabled' });
});
