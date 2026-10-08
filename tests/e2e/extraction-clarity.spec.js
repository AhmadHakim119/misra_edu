const { test, expect } = require('@playwright/test');

test('verified extraction stays concise and locates the source on the paper', async ({ page }, testInfo) => {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/pages/0')) {
      await route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6YAAAAABJRU5ErkJggg==', 'base64'
      ) });
      return;
    }
    let body = {};
    if (path.endsWith('/auth/me')) body = { id: 'teacher', full_name: 'Test Instructor', role: 'teacher' };
    else if (path.endsWith('/health')) body = { status: 'ok', model: 'test' };
    else if (path.endsWith('/exams')) body = [{ id: 'exam', course_code: 'TEST', title: 'Test exam', question_count: 1, approved_question_count: 1 }];
    else if (path.endsWith('/exams/exam/setup-readiness')) body = { ready: true, question_count: 1, pending_questions: [], questions: [] };
    else if (path.endsWith('/jobs')) body = { items: [], active_count: 0 };
    else if (path.endsWith('/submissions/paper/jobs')) body = [];
    else if (path.endsWith('/submissions/paper/extraction-review')) body = {
      submission: { id: 'paper', exam_id: 'exam', page_count: 1, status: 'extracted', extracted_student_name: 'Example Student', extracted_student_number: 'S123', uploaded_at: '2026-09-25T00:00:00' },
      readiness: { expected_question_count: 1, mapped_answer_count: 1, missing_question_numbers: [], suspicious_mapping_count: 0, unmatched_segment_count: 0, bulk_grading_allowed: true, blocking_reasons: [] },
      unmatched_segments: [], excluded_segments: [{ text: '9/10', page_index: 0, unmatched_index: 0, excluded_reason: 'marking' }],
      questions: [{ question: { id: 'q1', question_number: '1', question_text: 'Explain the answer', max_score: 2 }, answer: { id: 'a1', raw_ocr_text: 'Student explanation', ocr_legibility: 'clear' }, mapping_flags: [], sources: [{ id: 's1', page_index: 0, page_number: 1, segment_index: 0, question_number: '1', extracted_text: 'Student explanation', ocr_segment: { bounding_box: { x: .1, y: .2, width: .5, height: .3 } } }] }],
    };
    await route.fulfill({ json: body });
  });
  await page.goto('/pages/submission.html?id=paper');
  await expect(page.getByText('Ready to grade')).toBeVisible();
  await expect(page.getByText('9/10')).toBeHidden();
  await expect(page.locator('#grade-mode')).toBeHidden();
  await expect(page.locator('#next-extraction-issue')).toBeHidden();
  await page.getByLabel('Go to a question', { exact: true }).selectOption('q1');
  await expect(page.locator('.extraction-row')).toHaveAttribute('open', '');
  await page.locator('.extraction-row > summary').click();
  await page.locator('.extraction-row > summary').click();
  await page.getByRole('button', { name: 'Show on page 1 · highlighted' }).click();
  await expect(page.locator('#page-highlight')).toBeVisible();
  await expect(page.locator('#page-highlight')).toHaveCSS('left', /\d/);
  await page.screenshot({ path: testInfo.outputPath('extraction-clarity.png'), fullPage: true, animations: 'disabled' });
  await page.locator('.segment-organizer > summary').click();
  await page.locator('[data-source-id="s1"][type="checkbox"]').check();
  await expect(page.getByRole('button', { name: 'Exclude selected' })).toBeEnabled();
});

test('ungraded mapping issue offers a single background reprocess', async ({ page }) => {
  let requested = 0;
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body = {};
    if (path.endsWith('/auth/me')) body = { id: 'teacher', full_name: 'Test Instructor', role: 'teacher' };
    else if (path.endsWith('/health')) body = { status: 'ok', model: 'test' };
    else if (path.endsWith('/exams')) body = [{ id: 'exam', course_code: 'TEST', title: 'Test exam', question_count: 1, approved_question_count: 1 }];
    else if (path.endsWith('/exams/exam/setup-readiness')) body = { ready: true, question_count: 1, pending_questions: [], questions: [] };
    else if (path.endsWith('/jobs')) body = { items: [], active_count: 0 };
    else if (path.endsWith('/submissions/paper/jobs')) body = [];
    else if (path.endsWith('/submissions/paper/extraction-review')) body = {
      submission: { id: 'paper', exam_id: 'exam', page_count: 2, status: 'extracted', extracted_student_name: 'Example Student', extracted_student_number: 'S123', uploaded_at: '2026-09-25T00:00:00' },
      readiness: { expected_question_count: 1, mapped_answer_count: 0, missing_question_numbers: ['1'], suspicious_mapping_count: 0, unmatched_segment_count: 1, bulk_grading_allowed: false, can_reprocess: true, blocking_reasons: ['One answer is missing.'] },
      unmatched_segments: [{ text: 'student work', page_index: 1, segment_index: 0, unmatched_index: 0 }], excluded_segments: [],
      mapping_issues: [{ unmatched_index: 0, page_index: 1, page_number: 2, segment_index: 0, text: 'student work', reason: 'Visual check unavailable; inspect highlighted region.', candidate_questions: ['1'], bounding_box: { x: .2, y: .3, width: .4, height: .2 } }],
      questions: [{ question: { id: 'q1', question_number: '1', question_text: 'Explain', max_score: 2 }, answer: null, mapping_flags: [], sources: [] }],
    };
    else if (path.endsWith('/submissions/paper/reprocess-extraction')) {
      requested += 1;
      body = { created: true, job: { id: 'job-1', status: 'queued', progress_current: 0, progress_total: 2 } };
    } else if (path.endsWith('/jobs/job-1')) body = { id: 'job-1', status: 'queued', progress_current: 0, progress_total: 2 };
    await route.fulfill({ json: body });
  });
  page.on('dialog', (dialog) => dialog.accept());
  await page.goto('/pages/submission.html?id=paper');
  await expect(page.getByRole('heading', { name: 'See unplaced OCR text' })).toBeVisible();
  await page.getByRole('button', { name: /Page 2 · student work/ }).click();
  await expect(page.locator('#page-label')).toHaveText('Page 2 of 2');
  await expect(page.locator('#page-highlight')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Re-run automatic extraction' })).toBeVisible();
  await page.getByRole('button', { name: 'Re-run automatic extraction' }).click();
  await expect.poll(() => requested).toBe(1);
  await expect(page.getByText('Waiting for an OCR worker…')).toBeVisible();
});
