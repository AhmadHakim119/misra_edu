(function () {
  'use strict';
  const examSelect = document.getElementById('evaluation-exam');
  const content = document.getElementById('evaluation-content');
  const pct = (value) => value == null ? '—' : `${Math.round(Number(value) * 100)}%`;
  const num = (value, digits = 2) => value == null ? '—' : Number(value).toFixed(digits);

  async function loadEvaluation() {
    if (!examSelect.value) return;
    content.innerHTML = '<div class="workspace-card card-pad"><div class="skel" style="height:180px"></div></div>';
    try {
      const report = await MisraAPI.evaluation(examSelect.value);
      const overall = report.overall || {};
      const questions = Object.entries(report.per_question || {});
      content.innerHTML = `
        <section class="metric-grid">
          <article class="workspace-card metric"><span>Instructor labels</span><strong>${overall.label_count ?? 0}</strong></article>
          <article class="workspace-card metric"><span>Mean absolute error</span><strong>${num(overall.mae)}</strong></article>
          <article class="workspace-card metric"><span>Exact agreement</span><strong>${pct(overall.exact_agreement)}</strong></article>
          <article class="workspace-card metric"><span>Within ±1 point</span><strong>${pct(overall.plus_minus_one_agreement)}</strong></article>
          <article class="workspace-card metric"><span>Review warranted</span><strong>${pct(report.review_warranted_rate)}</strong></article>
          <article class="workspace-card metric"><span>High-confidence errors</span><strong>${report.high_confidence_error_count ?? 0}</strong></article>
        </section>
        <section class="workspace-card card-pad">
          <div class="section-head"><div><h2 class="section-title">Per-question agreement</h2><p class="section-copy">Descriptive until the labelled sample is representative.</p></div></div>
          ${questions.length ? `<div class="data-list">${questions.map(([question, metric]) => `<div class="data-row"><div><div class="data-row-title">Question ${MisraUI.escapeHTML(question)}</div><div class="data-row-meta">${metric.label_count} label${metric.label_count === 1 ? '' : 's'} · MAE ${num(metric.mae)}</div></div><div style="min-width:150px"><div class="data-row-meta" style="margin:0 0 6px">Exact ${pct(metric.exact_agreement)}</div><div class="bar-track"><div class="bar-fill" style="width:${Math.max(0, Math.min(100, Number(metric.exact_agreement || 0) * 100))}%"></div></div></div></div>`).join('')}</div>` : MisraUI.emptyState('No labelled answers yet', 'Resolve graded answers in the review queue to begin measuring agreement.', MisraUI.icons.evaluation)}
        </section>
        ${report.high_confidence_errors?.length ? `<section class="workspace-card card-pad"><div class="section-head"><div><h2 class="section-title">High-confidence errors</h2><p class="section-copy">These are the most important calibration failures to investigate.</p></div></div><div class="data-list">${report.high_confidence_errors.map((item) => `<div class="data-row"><div><div class="data-row-title">Question ${MisraUI.escapeHTML(item.question_number)}</div><div class="data-row-meta">AI ${item.ai_score} · Human ${item.human_score} · ${item.final_confidence}% confidence</div></div>${MisraUI.badge(`${item.absolute_error} pt error`, 'danger')}</div>`).join('')}</div></section>` : ''}
        <section class="workspace-card card-pad"><h2 class="section-title">Interpretation note</h2><p class="section-copy">${MisraUI.escapeHTML((report.notes || [])[0] || 'Metrics become meaningful as instructor labels accumulate across subjects and answer types.')}</p></section>`;
    } catch (error) { content.innerHTML = `<div class="workspace-card card-pad">${MisraUI.errorState(error.message)}</div>`; }
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
