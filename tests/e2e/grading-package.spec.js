const { test, expect } = require('@playwright/test');

test('saved grading evidence and historical rules remain inspectable after a failed history request', async ({ page }) => {
  const submission = { id: 's', exam_id: 'e', extracted_student_name: 'Synthetic Learner', extracted_student_number: 'TEST1', page_count: 1 };
  const question = { id: 'q', question_number: '1', question_text: 'Explain your reasoning.', max_score: 2 };
  const pack = { question: { text: 'Original question at grading' }, rubric_version_id: 'r1',
    answer_key: { version: 1, mode: 'reference', reference_text: 'Original approved solution', alternatives: [], document_refs: [] },
    policy: { handwritten_syntax_policy: 'accept_unambiguous' }, routing: { selected_mode: 'text_only', policy_mode: 'pilot' },
    student_evidence: [{ id: 'source:1', page_index: 0, segment_index: 0 }], snapshot_sha256: 'a'.repeat(64) };
  const criteria = [{ criterion_id: 'reason', max_points: 2, points_earned: 2, feedback: 'Reasoning supported.',
    evidence_refs: ['source:1'], reference_refs: ['key:1'], policy_applied: ['handwritten_syntax_policy'], uncertainties: [] }];
  const answer = { id: 'a', question_id: 'q', score: 2, max_score: 2, criteria_scores: criteria,
    grading_raw_response: { mode: 'text_only', grading_package: pack }, review_status: 'none', final_confidence: 70 };
  let historyRequests = 0;
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    if (path.endsWith('/grading-runs')) {
      if (++historyRequests === 1) return route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } });
      return route.fulfill({ json: [{ id: 'run', created_at: '2026-09-01T12:00:00', score: 2, max_score: 2,
        mode: 'text_only', criteria_scores: criteria, response_json: { grading_package: pack }, prompt_version: 'v3-evidence-package' }] });
    }
    const body = path === '/auth/me' ? { id: 't', full_name: 'Synthetic Instructor', role: 'teacher' } :
      path === '/health' ? { status: 'ok' } : path === '/exams' ? [{ id: 'e', title: 'Synthetic assessment' }] :
      path === '/results/s' ? { submission, answers: [answer] } :
      path.endsWith('/extraction-review') ? { submission, questions: [{ question, sources: [] }] } :
      path === '/evaluation' ? { overall: { label_count: 0 } } : {};
    return route.fulfill({ json: body });
  });
  await page.goto('/pages/grade-results.html?id=s');
  await expect(page.getByText('Page 1 · segment 1', { exact: false })).toBeVisible();
  await page.getByText('Rules & references used', { exact: true }).click();
  await expect(page.getByText('Original approved solution', { exact: true })).toBeVisible();
  await page.getByText('Grading history', { exact: true }).click();
  await page.getByRole('button', { name: 'Load saved runs' }).click();
  await page.getByRole('button', { name: 'Retry loading runs' }).click();
  await page.locator('[data-run-history] summary').first().click();
  await expect(page.locator('[data-run-history]')).toContainText('Original question at grading');
  await expect(page.locator('[data-run-history]')).toContainText('Original approved solution');
  expect(historyRequests).toBe(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
