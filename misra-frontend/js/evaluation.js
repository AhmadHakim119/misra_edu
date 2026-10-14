(function () {
  'use strict';
  const examSelect = document.getElementById('evaluation-exam');
  const content = document.getElementById('evaluation-content');
  const pct = (value) => value == null ? '—' : `${Math.round(Number(value) * 100)}%`;
  const num = (value, digits = 2) => value == null ? '—' : Number(value).toFixed(digits);
  let requestId = 0;

  async function loadEvaluation() {
    if (!examSelect.value) return;
    const currentRequest = ++requestId;
    content.innerHTML = '<div class="workspace-card card-pad"><div class="skel" style="height:180px"></div></div>';
    try {
      const report = await MisraAPI.evaluation(examSelect.value);
      if (currentRequest !== requestId) return;
      const overall = report.overall || {};
      const questions = Object.entries(report.per_question || {});
      content.innerHTML = `
        <section class="workspace-card card-pad"><h2 class="section-title">Paper grading agreement</h2><p class="section-copy">Metrics use instructor-labelled answers, not the student’s exam percentage. ${report.unique_answer_count ?? overall.label_count ?? 0} distinct answers; ${overall.label_count ?? 0} grading-run observations. Regrading the same paper does not create an independent test sample.</p>${report.latest_per_answer ? `<p>Latest instructor-labelled observation per answer: MAE ${num(report.latest_per_answer.mae)} · exact agreement ${pct(report.latest_per_answer.exact_agreement)}.</p>` : ''}${report.excluded_external_labels?.length ? `<details><summary>${report.excluded_external_labels.length} historical labels excluded: assessed outside MISRA</summary><p>These are excluded under the current approved assessment scope, not deleted or counted as improved AI predictions.</p><ul>${report.excluded_external_labels.map(row => `<li>Question ${MisraUI.escapeHTML(row.question_number)} · historical label ${MisraUI.escapeHTML(row.review_label_id)}</li>`).join('')}</ul></details>` : ''}</section>
        <section class="metric-grid">
          <article class="workspace-card metric"><span>Instructor labels</span><strong>${overall.label_count ?? 0}</strong></article>
          <article class="workspace-card metric"><span>Mean absolute error</span><strong>${num(overall.mae)}</strong></article>
          <article class="workspace-card metric"><span>Exact agreement</span><strong>${pct(overall.exact_agreement)}</strong></article>
          <article class="workspace-card metric"><span>Within ±1 point</span><strong>${pct(overall.plus_minus_one_agreement)}</strong></article>
          <article class="workspace-card metric"><span>Review warranted</span><strong>${pct(report.review_warranted_rate)}</strong></article>
          <article class="workspace-card metric"><span>High-confidence errors</span><strong>${report.high_confidence_error_count ?? 0}</strong></article>
        </section>
        <section class="workspace-card card-pad"><h2 class="section-title">Score scale &amp; marking bias</h2><p class="section-copy">Normalized error makes different question totals comparable. Negative bias means the AI awards fewer marks than the instructor.</p><dl class="evaluation-diagnostics"><dt>Normalized mean absolute error</dt><dd>${pct(overall.normalized_mae)} of available marks · ${overall.normalized_label_count ?? 0} observations with historical maxima</dd><dt>Root mean squared error</dt><dd>${num(overall.rmse)} points</dd><dt>Mean signed error (AI − instructor)</dt><dd>${num(overall.mean_signed_error)} points</dd><dt>Review precision / recall</dt><dd>${pct(report.review_flag_metrics?.precision)} / ${pct(report.review_flag_metrics?.recall)} · ${report.review_flag_metrics?.snapshot_label_count ?? 0} review snapshots</dd></dl></section>
        <section class="workspace-card card-pad"><h2 class="section-title">Evidence quality</h2><p class="section-copy">Valid source IDs do not prove that a deduction is justified. Instructor annotations measure that separately; an unannotated result is not a verified result.</p><dl class="evaluation-diagnostics"><dt>Student citation coverage</dt><dd>${pct(report.saved_run_diagnostics?.student_citation_coverage)} · ${report.saved_run_diagnostics?.criterion_count ?? 0} saved criteria</dd><dt>Invalid saved citation / rule references</dt><dd>${report.saved_run_diagnostics?.invalid_reference_count ?? 0}</dd><dt>Instructor-reported unsupported deductions</dt><dd>${report.instructor_error_annotations?.unsupported_deduction_count ?? 0}</dd><dt>Instructor-reported citation errors</dt><dd>${report.instructor_error_annotations?.evidence_citation_error_count ?? 0}</dd></dl><p class="field-hint">${report.instructor_error_annotations?.annotation_count ?? 0} of ${report.instructor_error_annotations?.label_count ?? 0} labels have reason annotations. Counts are not a held-out error rate.</p></section>
        <section class="workspace-card card-pad"><h2 class="section-title">Observed model performance</h2><p class="section-copy">Timing and reported cost from saved runs, not a controlled comparison. Missing usage data is unknown, not zero cost.</p>${report.saved_run_diagnostics?.performance?.length ? `<div class="data-list">${report.saved_run_diagnostics.performance.map(item => `<div class="data-row"><div><strong>${MisraUI.escapeHTML(item.model)}</strong><p class="data-row-meta">${MisraUI.escapeHTML(item.prompt_version)} · ${MisraUI.escapeHTML(item.mode)} · ${item.run_count} runs</p><p>Median ${num(item.median_latency_ms == null ? null : item.median_latency_ms / 1000)} seconds · reported cost ${item.reported_cost_usd == null ? 'unavailable' : `$${num(item.reported_cost_usd, 6)}`} (${item.cost_observation_count} observations)</p></div></div>`).join('')}</div>` : '<p>No saved grading runs in this assessment.</p>'}</section>
        <section class="workspace-card card-pad">
          <div class="section-head"><div><h2 class="section-title">Per-question agreement</h2><p class="section-copy">Descriptive until the labelled sample is representative.</p></div></div>
          ${questions.length ? `<div class="data-list">${questions.map(([question, metric]) => `<div class="data-row"><div><div class="data-row-title">Question ${MisraUI.escapeHTML(question)}</div><div class="data-row-meta">${metric.label_count} label${metric.label_count === 1 ? '' : 's'} · MAE ${num(metric.mae)}</div></div><div style="min-width:150px"><div class="data-row-meta" style="margin:0 0 6px">Exact ${pct(metric.exact_agreement)}</div><div class="bar-track"><div class="bar-fill" style="width:${Math.max(0, Math.min(100, Number(metric.exact_agreement || 0) * 100))}%"></div></div></div></div>`).join('')}</div>` : MisraUI.emptyState('No labelled answers yet', 'Resolve graded answers in the review queue to begin measuring agreement.', MisraUI.icons.evaluation)}
        </section>
        ${report.high_confidence_errors?.length ? `<section class="workspace-card card-pad"><div class="section-head"><div><h2 class="section-title">High-confidence errors</h2><p class="section-copy">These are the most important calibration failures to investigate.</p></div></div><div class="data-list">${report.high_confidence_errors.map((item) => `<div class="data-row"><div><div class="data-row-title">Question ${MisraUI.escapeHTML(item.question_number)}</div><div class="data-row-meta">AI ${item.ai_score} · Human ${item.human_score} · ${item.final_confidence}% confidence</div></div>${MisraUI.badge(`${item.absolute_error} pt error`, 'danger')}</div>`).join('')}</div></section>` : ''}
        <section class="workspace-card card-pad"><h2 class="section-title">Interpretation note</h2><p class="section-copy">${MisraUI.escapeHTML((report.notes || [])[0] || 'Metrics become meaningful as instructor labels accumulate across subjects and answer types.')}</p></section>`;
    } catch (error) { if (currentRequest === requestId) content.innerHTML = `<div class="workspace-card card-pad">${MisraUI.errorState(error.message)}</div>`; }
  }

  async function init() {
    try {
      const exams = await MisraAPI.exams();
      examSelect.innerHTML = exams.length ? exams.map((exam) => `<option value="${exam.id}">${MisraUI.escapeHTML(exam.course_code ? `${exam.course_code} · ${exam.title}` : exam.title)}</option>`).join('') : '<option value="">No assessments found</option>';
      const requested = MisraUI.getParam('exam_id'); if (exams.some((exam) => exam.id === requested)) examSelect.value = requested;
      examSelect.addEventListener('change', loadEvaluation); await loadEvaluation();
    } catch (error) { content.innerHTML = `<div class="workspace-card card-pad">${MisraUI.errorState(error.message)}</div>`; }
  }
  init();
})();
