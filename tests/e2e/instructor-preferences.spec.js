const { test, expect } = require('@playwright/test');

const approvedProfile = {
  id: 'profile-1', version_number: 1, status: 'approved', applies_automatically: false,
  scenario_answers: [
    ['valid_alternative_method', 'full_credit'], ['minor_handwritten_syntax', 'full_credit'],
    ['equivalent_notation', 'full_credit'], ['carried_forward_error', 'single_penalty'],
    ['language_quality_outside_criterion', 'ignore'],
  ].map(([scenario_id, selected_option]) => ({ scenario_id, selected_option })),
  derived_proposal: { method_credit: 'full_if_valid', alternative_methods_allowed: true,
    handwritten_syntax_policy: 'accept_unambiguous', notation_policy: 'equivalent_allowed',
    error_carried_forward: 'single_penalty', language_quality_policy: 'ignore_unless_assessed' },
};

test('settings creates and explicitly approves an optional marking profile', async ({ page }, testInfo) => {
  const writes = []; let versions = [];
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    const method = route.request().method();
    if (path === '/auth/me') return route.fulfill({ json: { id: 't', email: 'teacher@example.test', full_name: 'Synthetic Instructor', role: 'teacher' } });
    if (path === '/health') return route.fulfill({ json: { status: 'ok' } });
    if (path === '/instructor-preference-versions' && method === 'GET') return route.fulfill({ json: versions });
    if (path === '/instructor-preference-versions' && method === 'POST') {
      writes.push(route.request().postDataJSON());
      versions = [{ ...approvedProfile, ...writes.at(-1), status: 'draft' }];
      return route.fulfill({ status: 201, json: versions[0] });
    }
    if (path.endsWith('/approve')) { versions[0] = { ...versions[0], status: 'approved' }; return route.fulfill({ json: versions[0] }); }
    return route.fulfill({ json: {} });
  });
  await page.goto('/pages/account.html');
  const validMethodGroup = page.getByRole('group', { name: /valid method/ });
  await validMethodGroup.getByRole('radio', { name: 'Full credit' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(validMethodGroup.getByRole('radio', { name: 'Partial credit' })).toBeFocused();
  await page.getByRole('group', { name: /valid method/ }).getByRole('radio', { name: 'Full credit' }).check();
  await page.getByRole('group', { name: /handwritten syntax/ }).getByRole('radio', { name: 'Do not deduct' }).check();
  await page.getByRole('group', { name: /equivalent notation/ }).getByRole('radio', { name: 'Accept as equivalent' }).check();
  await page.getByRole('group', { name: /early mistake/ }).getByRole('radio', { name: 'Penalize once' }).check();
  await page.getByRole('group', { name: /grammar or spelling/ }).getByRole('radio', { name: 'Do not deduct' }).check();
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  expect(writes[0].scenario_answers).toHaveLength(5);
  expect(writes[0].explicit_preferences).toEqual({});
  await expect(page.getByText('Proposed rubric defaults')).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Save & approve profile' }).click();
  await expect(page.getByText('Approved profiles never change existing rubrics.')).toBeVisible();
  await expect(page.getByRole('radio', { name: 'Full credit', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({
    path: `.impeccable/review/phase2-preferences-${testInfo.project.name}.png`,
    fullPage: true,
  });
});

test('a failed preference save keeps every instructor decision in place', async ({ page }) => {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 't', email: 'teacher@example.test', full_name: 'Synthetic Instructor', role: 'teacher' } });
    if (path === '/health') return route.fulfill({ json: { status: 'ok' } });
    if (path === '/instructor-preference-versions' && route.request().method() === 'GET') return route.fulfill({ json: [] });
    if (path === '/instructor-preference-versions' && route.request().method() === 'POST') {
      return route.fulfill({ status: 503, json: { detail: 'Preference service unavailable' } });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto('/pages/account.html');
  const choices = [
    [/valid method/, 'Full credit'],
    [/handwritten syntax/, 'Do not deduct'],
    [/equivalent notation/, 'Accept as equivalent'],
    [/early mistake/, 'Penalize once'],
    [/grammar or spelling/, 'Do not deduct'],
  ];
  for (const [groupName, optionName] of choices) {
    await page.getByRole('group', { name: groupName }).getByRole('radio', { name: optionName }).check();
  }

  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByText('Preference service unavailable')).toBeVisible();
  for (const [groupName, optionName] of choices) {
    await expect(page.getByRole('group', { name: groupName }).getByRole('radio', { name: optionName })).toBeChecked();
  }
});

test('repeated review patterns become an explicit draft proposal, never an automatic rule', async ({ page }) => {
  const writes = [];
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    const method = route.request().method();
    if (path === '/auth/me') return route.fulfill({ json: { id: 't', email: 'teacher@example.test', full_name: 'Synthetic Instructor', role: 'teacher' } });
    if (path === '/health') return route.fulfill({ json: { status: 'ok' } });
    if (path === '/instructor-preference-versions' && method === 'GET') return route.fulfill({ json: [] });
    if (path === '/instructor-preference-suggestions') return route.fulfill({ json: {
      minimum_distinct_labels: 3,
      applies_automatically: false,
      excluded_reason_codes: ['rubric_issue', 'ocr_or_mapping_error', 'other'],
      suggestions: [{ review_reason_code: 'minor_notation', distinct_label_count: 3, source_label_ids: ['l1', 'l2', 'l3'], proposed_policy: { notation_policy: 'equivalent_allowed' }, applies_automatically: false }],
    } });
    if (path === '/instructor-preference-versions' && method === 'POST') {
      writes.push(route.request().postDataJSON());
      return route.fulfill({ status: 201, json: { id: 'draft', version_number: 1, status: 'draft', ...writes[0], derived_proposal: { notation_policy: 'equivalent_allowed' } } });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto('/pages/account.html');
  await expect(page.getByText('Patterns ready for your judgment')).toBeVisible();
  await expect(page.getByText('Supported by 3 distinct reviews')).toBeVisible();
  await page.getByRole('button', { name: 'Use in draft' }).click();
  await expect(page.getByText('equivalent allowed')).toBeVisible();
  expect(writes).toHaveLength(0);
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  expect(writes[0].explicit_preferences).toEqual({ notation_policy: 'equivalent_allowed' });
  expect(writes[0].scenario_answers).toEqual([]);
});

test('Rubric Studio applies an approved profile only to an editable draft after confirmation', async ({ page }) => {
  const writes = [];
  const rubric = { schema_version: 2, max_score: 2, criteria: [{ id: 'c', title: 'Reasoning', description: 'Valid reasoning', points: 2, scoring_type: 'scaled', partial_credit_allowed: true, performance_levels: [], required_evidence: [], common_errors: [], alternative_methods: [] }], policy: { grading_approach: 'balanced', method_credit: 'partial', handwritten_syntax_policy: 'criterion_specific', language_quality_policy: 'criterion_specific', error_carried_forward: 'criterion_specific', notation_policy: 'standard_required', alternative_methods_allowed: false, arithmetic_error_policy: 'single_penalty', units_policy: 'required_when_applicable', evidence_requirement: 'key_steps', illegible_response_policy: 'manual_review' } };
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    if (path === '/auth/me') return route.fulfill({ json: { id: 't', full_name: 'Synthetic Instructor', role: 'teacher' } });
    if (path === '/health') return route.fulfill({ json: { status: 'ok' } });
    if (path === '/instructor-preference-versions') return route.fulfill({ json: [approvedProfile] });
    if (path === '/exams') return route.fulfill({ json: [{ id: 'e', title: 'Synthetic assessment' }] });
    if (path.endsWith('/questions')) return route.fulfill({ json: [{ id: 'q', question_number: '1', question_text: 'Explain.', max_score: 2 }] });
    if (path.endsWith('/setup-imports')) return route.fulfill({ json: [] });
    if (path.endsWith('/rubric')) return route.fulfill({ json: { rubric, rubric_version_id: 'r' } });
    if (path.endsWith('/rubric-versions') && route.request().method() === 'GET') return route.fulfill({ json: [{ id: 'r', version_number: 1, status: 'draft', rubric_json: rubric }] });
    if (path.includes('/answer-key-versions')) return route.fulfill({ json: [] });
    if (path.endsWith('/grading-policy')) return route.fulfill({ json: { mode: 'adaptive' } });
    if (path === '/rubric-versions/r' && route.request().method() === 'PUT') { writes.push(route.request().postDataJSON()); return route.fulfill({ json: { id: 'r', version_number: 1, status: 'draft', rubric_json: writes.at(-1).rubric } }); }
    return route.fulfill({ json: {} });
  });
  await page.goto('/pages/rubric-studio.html?exam_id=e&question_id=q');
  await page.getByText('Ask AI for a granular draft', { exact: true }).click();
  await page.locator('[data-rubric-panel="policy"] > summary').click();
  await expect(page.getByLabel('Additional context for this draft')).toBeVisible();
  await expect(page.locator('#suggestion-context-help')).toContainText('not an approved answer key');
  for (const id of ['criterion-0-title', 'criterion-0-points', 'criterion-0-description', 'criterion-0-scoring', 'criterion-0-evidence', 'suggestion-grading-approach', 'policy-grading-approach']) {
    await expect(page.locator(`label[for="${id}"]`)).toBeVisible();
    await expect(page.locator(`#${id}`)).toBeVisible();
  }
  const apply = page.getByRole('button', { name: 'Use my profile v1' });
  await expect(apply).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await apply.click();
  await expect(page.locator('[data-policy="method_credit"]')).toHaveValue('full_if_valid');
  await expect(page.locator('#policy-handwritten_syntax_policy')).toHaveValue('accept_unambiguous');
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  expect(writes[0].rubric.policy).toMatchObject(approvedProfile.derived_proposal);
});
