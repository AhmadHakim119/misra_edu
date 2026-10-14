const { test, expect } = require('@playwright/test');

test('evaluation distinguishes grade errors, citation coverage, annotations and unknown cost',async ({page}) => {
  await page.route('**/api/**',route => {
    const path = new URL(route.request().url()).pathname.replace('/api','');
    const report = {overall:{label_count:2,mae:.75,rmse:.8,normalized_mae:.15,normalized_label_count:2,mean_signed_error:-.75,exact_agreement:0,plus_minus_one_agreement:1},
      unique_answer_count:2,review_flag_metrics:{precision:1,recall:.5,snapshot_label_count:2},
      instructor_error_annotations:{unsupported_deduction_count:1,evidence_citation_error_count:0,annotation_count:1,label_count:2},
      saved_run_diagnostics:{student_citation_coverage:1,criterion_count:4,invalid_reference_count:0,
        performance:[{model:'Synthetic model',prompt_version:'synthetic-v5',mode:'text_only',run_count:2,median_latency_ms:1500,reported_cost_usd:null,cost_observation_count:0}]}};
    return route.fulfill({json:path === '/auth/me' ? {id:'u',full_name:'Synthetic Instructor',role:'teacher'} :
      path === '/exams' ? [{id:'e',title:'Synthetic assessment'}] : path === '/evaluation' ? report : path === '/jobs' ? {items:[],active_count:0} : {status:'ok'}});
  });
  await page.goto('/pages/evaluation.html');
  await expect(page.getByRole('heading',{name:'Score scale & marking bias'})).toBeVisible();
  await expect(page.locator('#evaluation-content')).toContainText('15% of available marks');
  await expect(page.locator('#evaluation-content')).toContainText('-0.75 points');
  await expect(page.locator('#evaluation-content')).toContainText('reported cost unavailable');
  await expect(page.locator('#evaluation-content')).toContainText('1 of 2 labels have reason annotations');
  await expect(page.locator('#evaluation-content')).toContainText('not a controlled comparison');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
