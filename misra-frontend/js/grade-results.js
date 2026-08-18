(function () {
  'use strict';

  const submissionId = MisraUI.getParam('id');
  const title = document.getElementById('result-title');
  const meta = document.getElementById('result-meta');
  const actions = document.getElementById('result-actions');
  const errorRegion = document.getElementById('result-error');
  const summary = document.getElementById('grade-summary');
  const questionsHost = document.getElementById('grade-questions');
  const questionsCopy = document.getElementById('question-results-copy');
  const toggleResults = document.getElementById('toggle-results');

  let report = null;

  function number(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return '—';
    return parsed.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function criterionName(value) {
    return String(value || 'Criterion').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function modeLabel(mode) {
    if (mode === 'image_text') return 'Image + text';
    if (mode === 'text_only') return 'Text only';
    return mode ? mode.replaceAll('_', ' ') : 'Not recorded';
  }

  function effectiveScore(answer) {
    return answer?.teacher_override_score ?? answer?.score ?? null;
  }

  function renderSummary(submission, exam, answers, rows, calibration) {
    const totalScore = rows.reduce((total, row) => total + Number(effectiveScore(answers.get(row.question.id)) || 0), 0);
    const totalMax = rows.reduce((total, row) => total + Number(row.question.max_score || 0), 0);
    const gradedCount = rows.filter((row) => effectiveScore(answers.get(row.question.id)) !== null).length;
    const percentage = totalMax ? (totalScore / totalMax) * 100 : 0;
    const reviewCount = [...answers.values()].filter((answer) => answer.needs_review || answer.review_status === 'pending').length;
    const complete = gradedCount === rows.length && rows.length > 0;

    title.textContent = submission.extracted_student_name || submission.extracted_student_number || 'Unidentified student';
    meta.textContent = `${exam?.course_code ? `${exam.course_code} · ` : ''}${exam?.title || 'Assessment'} · graded ${gradedCount} of ${rows.length}`;
    actions.innerHTML = `<a class="btn btn-secondary" href="submission.html?id=${encodeURIComponent(submission.id)}">View extraction</a>${reviewCount ? `<a class="btn btn-primary" href="reviews.html?exam_id=${encodeURIComponent(submission.exam_id)}">Review ${reviewCount} flagged</a>` : ''}`;

    const calibrationReady = calibration.labelCount >= calibration.minimumLabels;
    const note = reviewCount
      ? 'Some answers require instructor review before the result should be finalized.'
      : calibrationReady
        ? `No answer was flagged. Confidence is supported by ${calibration.labelCount} instructor labels for this assessment.`
        : `No answer was flagged, but confidence is not calibrated for this assessment (${calibration.labelCount} of ${calibration.minimumLabels} instructor labels). Treat it as a model estimate, not a probability that the grade is correct.`;
    summary.innerHTML = `<div class="grade-summary ${reviewCount || !calibrationReady ? 'needs-review' : ''}">
      <div class="grade-total"><span>${complete ? 'Final recorded score' : 'Current recorded score'}</span><div><strong>${number(totalScore)}</strong><small>/ ${number(totalMax)}</small></div><p>${number(percentage)}%</p></div>
      <div class="grade-summary-detail"><div><span>Status</span><strong>${complete ? 'Grading complete' : 'Incomplete grading'}</strong></div><div><span>Questions graded</span><strong>${gradedCount} of ${rows.length}</strong></div><div><span>Instructor review</span><strong>${reviewCount ? `${reviewCount} waiting` : 'Not flagged'}</strong></div></div>
      <div class="grade-summary-note"><span class="readiness-mark">${reviewCount || !calibrationReady ? '!' : '✓'}</span><p>${note}</p></div>
    </div>`;
  }

  function renderCriteria(criteria) {
    if (!Array.isArray(criteria) || !criteria.length) return '<p class="grade-empty-copy">No criterion-level scores were recorded.</p>';
    return `<div class="criteria-results">${criteria.map((criterion) => `<div class="criterion-result"><div class="criterion-result-head"><strong>${MisraUI.escapeHTML(criterionName(criterion.criterion_id))}</strong><span>${number(criterion.points_earned)} / ${number(criterion.max_points)}</span></div><p>${MisraUI.escapeHTML(criterion.feedback || 'No criterion feedback was recorded.')}</p></div>`).join('')}</div>`;
  }

  function renderQuestion(row, answer, index, calibration) {
    const pages = [...new Set(row.sources.map((source) => source.page_number))];
    const confidence = answer?.final_confidence ?? answer?.llm_confidence;
    const mode = answer?.grading_raw_response?.mode;
    const score = effectiveScore(answer);
    const reviewNeeded = Boolean(answer?.needs_review || answer?.review_status === 'pending');
    const sourceLinks = pages.length ? pages.map((page) => `<a href="submission.html?id=${encodeURIComponent(report.submission.id)}&page=${page - 1}">Page ${page}</a>`).join('') : '<span>No tracked page</span>';

    const calibrationReady = calibration.labelCount >= calibration.minimumLabels;
    const confidenceLabel = calibrationReady
      ? `${number(confidence)}% calibrated confidence`
      : `Model estimate ${number(confidence)}% · uncalibrated`;
    return `<details class="grade-question" ${index === 0 || reviewNeeded ? 'open' : ''}>
      <summary><span class="mapping-number">${MisraUI.escapeHTML(row.question.question_number)}</span><span class="grade-question-title"><strong>${MisraUI.escapeHTML(row.question.question_text || `Question ${row.question.question_number}`)}</strong><small>${sourceLinks}</small></span><span class="grade-question-score"><strong>${number(score)}</strong><small>/ ${number(row.question.max_score)}</small></span><span class="disclosure" aria-hidden="true">⌄</span></summary>
      <div class="grade-question-body">
        ${reviewNeeded ? '<div class="mapping-warning"><strong>Instructor review required</strong><span>This answer was flagged by the grading policy or confidence checks.</span></div>' : ''}
        <div class="grade-answer-meta">${MisraUI.badge(modeLabel(mode), 'draft')}${MisraUI.badge(confidenceLabel, calibrationReady && Number(confidence) >= 80 ? 'success' : 'warning')}${answer?.teacher_override_score !== null && answer?.teacher_override_score !== undefined ? MisraUI.badge('Instructor override', 'warning') : ''}</div>
        <section class="grade-feedback"><h3>Feedback</h3><p>${MisraUI.escapeHTML(answer?.feedback || 'No feedback was recorded for this answer.')}</p></section>
        <section class="grade-criteria"><h3>Criterion breakdown</h3>${renderCriteria(answer?.criteria_scores)}</section>
        <div class="grade-disclosures">
          <details><summary>AI reasoning</summary><p>${MisraUI.escapeHTML(answer?.reasoning || 'No reasoning was recorded.')}</p></details>
          <details><summary>Extracted answer</summary><pre>${MisraUI.escapeHTML(answer?.raw_ocr_text || 'No OCR text was recorded.')}</pre></details>
        </div>
      </div>
    </details>`;
  }

  function renderQuestions(rows, answers, calibration) {
    questionsCopy.textContent = `${rows.length} question${rows.length === 1 ? '' : 's'} · expand a row for feedback and criterion scores`;
    toggleResults.hidden = rows.length < 2;
    if (!rows.length) {
      questionsHost.innerHTML = MisraUI.emptyState('No configured questions', 'Return to the assessment and add questions before grading.');
      return;
    }
    questionsHost.innerHTML = rows.map((row, index) => renderQuestion(row, answers.get(row.question.id), index, calibration)).join('');
  }

  async function load() {
    if (!submissionId) {
      errorRegion.innerHTML = MisraUI.errorState('No submission ID was provided. Open a graded paper from Extraction results.');
      summary.innerHTML = '';
      questionsHost.innerHTML = '';
      return;
    }
    try {
      const [results, extraction, exams] = await Promise.all([
        MisraAPI.results(submissionId),
        MisraAPI.extractionReview(submissionId),
        MisraAPI.exams(),
      ]);
      report = extraction;
      const exam = exams.find((item) => item.id === results.submission.exam_id);
      let evaluation = null;
      try { evaluation = await MisraAPI.evaluation(results.submission.exam_id); } catch (_) { evaluation = null; }
      const calibration = { labelCount: Number(evaluation?.overall?.label_count || 0), minimumLabels: 10 };
      const answers = new Map(results.answers.map((answer) => [answer.question_id, answer]));
      renderSummary(results.submission, exam, answers, extraction.questions, calibration);
      renderQuestions(extraction.questions, answers, calibration);
    } catch (error) {
      errorRegion.innerHTML = MisraUI.errorState(error.message);
      summary.innerHTML = '';
      questionsHost.innerHTML = '';
    }
  }

  toggleResults.addEventListener('click', () => {
    const rows = [...questionsHost.querySelectorAll('.grade-question')];
    const expand = rows.some((row) => !row.open);
    rows.forEach((row) => { row.open = expand; });
    toggleResults.textContent = expand ? 'Collapse all' : 'Expand all';
  });

  load();
})();
