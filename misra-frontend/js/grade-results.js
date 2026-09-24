(function () {
  'use strict';

  const submissionId = MisraUI.getParam('id');
  const title = document.getElementById('result-title');
  const meta = document.getElementById('result-meta');
  const actions = document.getElementById('result-actions');
  const errorRegion = document.getElementById('result-error');
  const jobRegion = document.getElementById('grading-job');
  const summary = document.getElementById('grade-summary');
  const questionsHost = document.getElementById('grade-questions');
  const questionsCopy = document.getElementById('question-results-copy');
  const toggleResults = document.getElementById('toggle-results');

  let report = null;
  let activeJobId = MisraUI.getParam('job_id');

  function wait(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  function renderJob(job) {
    const current = Number(job.progress_current || 0);
    const total = Number(job.progress_total || 0);
    const percent = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
    if (job.status === 'failed') {
      jobRegion.innerHTML = `<div class="workspace-card card-pad job-status-card is-error" role="alert"><div><strong>Grading stopped after ${job.attempt_count} attempt${job.attempt_count === 1 ? '' : 's'}</strong><p>${MisraUI.escapeHTML(job.error_message || 'The worker could not finish this grading job.')}</p></div><button class="btn btn-primary" type="button" data-retry-grading="${job.id}">Retry safely</button></div>`;
      return;
    }
    const label = job.status === 'retrying' ? 'Grading retry scheduled' : job.status === 'processing' ? 'Grading answers' : 'Waiting for a grading worker';
    jobRegion.innerHTML = `<div class="workspace-card card-pad job-status-card" role="status"><div class="job-status-head"><div><span class="upload-status-pulse" aria-hidden="true"></span><strong>${label}</strong></div><span>${total ? `${current} of ${total}` : 'Queued'}</span></div><div class="job-progress-track" role="progressbar" aria-label="Grading progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span style="width:${percent}%"></span></div><p>${MisraUI.escapeHTML(job.progress_message || 'This page updates automatically. You may safely leave and return later.')}</p></div>`;
  }

  async function watchJob(jobId) {
    activeJobId = jobId;
    for (;;) {
      const job = await MisraAPI.job(jobId);
      if (job.status === 'completed') {
        jobRegion.innerHTML = '';
        await load();
        window.showToast('Grading complete.', 'success');
        return;
      }
      renderJob(job);
      if (job.status === 'failed') {
        await load();
        return;
      }
      await wait(1800);
    }
  }

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
    const identity = MisraUI.identityState(submission);
    const totalScore = rows.reduce((total, row) => total + Number(effectiveScore(answers.get(row.question.id)) || 0), 0);
    const totalMax = rows.reduce((total, row) => total + Number(row.question.max_score || 0), 0);
    const gradedCount = rows.filter((row) => effectiveScore(answers.get(row.question.id)) !== null).length;
    const percentage = totalMax ? (totalScore / totalMax) * 100 : 0;
    const reviewCount = [...answers.values()].filter((answer) => answer.needs_review || answer.review_status === 'pending').length;
    const complete = gradedCount === rows.length && rows.length > 0;

    title.textContent = identity.displayName;
    meta.textContent = `${identity.displayNumber} · ${exam?.course_code ? `${exam.course_code} · ` : ''}${exam?.title || 'Assessment'} · graded ${gradedCount} of ${rows.length}`;
    actions.innerHTML = `<a class="btn btn-secondary" href="submission.html?id=${encodeURIComponent(submission.id)}">${identity.needsAttention ? 'Complete identity' : 'View extraction'}</a>${reviewCount ? `<a class="btn btn-primary" href="reviews.html?exam_id=${encodeURIComponent(submission.exam_id)}">Review ${reviewCount} flagged</a>` : ''}`;

    const calibrationReady = calibration.labelCount >= calibration.minimumLabels;
    const note = reviewCount
      ? 'Some answers require instructor review before the result should be finalized.'
      : calibrationReady
        ? `No answer was flagged. Confidence is supported by ${calibration.labelCount} instructor labels for this assessment.`
        : `No answer was flagged, but confidence is not calibrated for this assessment (${calibration.labelCount} of ${calibration.minimumLabels} instructor labels). Treat it as a model estimate, not a probability that the grade is correct.`;
    summary.innerHTML = `${identity.needsAttention ? `<div class="identity-guidance-state needs-action grade-identity-warning"><span class="readiness-mark">!</span><div><strong>${MisraUI.escapeHTML(identity.label)}</strong><p>${MisraUI.escapeHTML(identity.message)} Blackboard export may be blocked until this is corrected.</p></div><a class="btn btn-secondary" href="submission.html?id=${encodeURIComponent(submission.id)}">Check identity</a></div>` : ''}<div class="grade-summary ${reviewCount || !calibrationReady ? 'needs-review' : ''}">
      <div class="grade-total"><span>${complete ? 'Final recorded score' : 'Current recorded score'}</span><div><strong>${number(totalScore)}</strong><small>/ ${number(totalMax)}</small></div><p>${number(percentage)}%</p></div>
      <div class="grade-summary-detail"><div><span>Status</span><strong>${complete ? 'Grading complete' : 'Incomplete grading'}</strong></div><div><span>Questions graded</span><strong>${gradedCount} of ${rows.length}</strong></div><div><span>Instructor review</span><strong>${reviewCount ? `${reviewCount} waiting` : 'Not flagged'}</strong></div></div>
      <div class="grade-summary-note"><span class="readiness-mark">${reviewCount || !calibrationReady ? '!' : '✓'}</span><p>${note}</p></div>
    </div>`;
  }

  function renderCriteria(criteria, gradingPackage) {
    if (!Array.isArray(criteria) || !criteria.length) return '<p class="grade-empty-copy">No criterion-level scores were recorded.</p>';
    const evidence = new Map((gradingPackage?.student_evidence || []).map(item => [item.id, item]));
    const label = id => {
      const item = evidence.get(id);
      if (!item) return id;
      return item.page_index === undefined ? 'Combined extracted answer' : `Page ${item.page_index + 1}${item.segment_index === undefined ? ' image' : ` · segment ${item.segment_index + 1}`}`;
    };
    return `<div class="criteria-results">${criteria.map((criterion) => `<div class="criterion-result"><div class="criterion-result-head"><strong>${MisraUI.escapeHTML(criterionName(criterion.criterion_id))}</strong><span>${number(criterion.points_earned)} / ${number(criterion.max_points)}</span></div><p>${MisraUI.escapeHTML(criterion.feedback || 'No criterion feedback was recorded.')}</p>
      ${gradingPackage ? `<p><strong>Evidence:</strong> ${MisraUI.escapeHTML((criterion.evidence_refs || []).map(label).join('; ') || 'No evidence cited — review required.')}</p>` : ''}
      ${criterion.reference_refs?.length ? `<p><strong>Reference:</strong> ${MisraUI.escapeHTML(gradingPackage?.answer_key?.version ? `Answer key v${gradingPackage.answer_key.version}` : 'Legacy rubric reference')}</p>` : ''}
      ${criterion.policy_applied?.length ? `<p><strong>Rules applied:</strong> ${MisraUI.escapeHTML(criterion.policy_applied.map(criterionName).join(', '))}</p>` : ''}
      ${criterion.uncertainties?.length ? `<p class="mapping-warning"><strong>Needs judgment:</strong> ${MisraUI.escapeHTML(criterion.uncertainties.join('; '))}</p>` : ''}
      </div>`).join('')}</div>`;
  }

  function renderGradingPackage(pack) {
    if (!pack?.question || !pack?.answer_key) return '<p>This older run has no complete grading-package snapshot. Existing rubric/run records are retained.</p>';
    const key = pack.answer_key;
    const policies = Object.entries(pack.policy || {});
    return `<p>Saved at grading time. Later edits do not change this record. Citations identify sources; they do not prove that the AI interpreted them correctly.</p>
      <h4>Question at grading</h4><p>${MisraUI.escapeHTML(pack.question.text || '')}</p>
      <p><strong>Rubric / policy version:</strong> ${MisraUI.escapeHTML(pack.rubric_version_id || 'Legacy definition')}</p>
      <p><strong>Answer key:</strong> ${key.is_legacy_fallback ? 'Legacy rubric reference' : `Version ${number(key.version)}`}${key.mode === 'no_fixed_answer' ? ' · No fixed answer' : ''}</p>
      ${key.reference_text ? `<pre>${MisraUI.escapeHTML(key.reference_text)}</pre>` : ''}
      ${key.alternatives?.length ? `<p><strong>Accepted alternatives:</strong></p><ul>${key.alternatives.map(text => `<li>${MisraUI.escapeHTML(text)}</li>`).join('')}</ul>` : ''}
      ${key.document_refs?.length ? `<p><strong>Reference pages:</strong> ${MisraUI.escapeHTML(key.document_refs.map(ref => `Pages ${ref.page_indices.map(p => p + 1).join(', ')} (document ${ref.job_id})`).join('; '))}</p>` : ''}
      <h4>Marking policy</h4>${policies.length ? `<dl>${policies.map(([name,value]) => `<dt>${MisraUI.escapeHTML(criterionName(name))}</dt><dd>${MisraUI.escapeHTML(String(value ?? 'Not specified').replaceAll('_', ' '))}</dd>`).join('')}</dl>` : '<p>Legacy criteria and notes apply; no explicit policy was stored.</p>'}
      <p><strong>Route:</strong> ${MisraUI.escapeHTML(modeLabel(pack.routing?.selected_mode))} · ${MisraUI.escapeHTML(pack.routing?.policy_mode || 'Not recorded')}</p>
      <details><summary>Snapshot identifiers</summary><p class="grade-empty-copy">Definition fingerprint: ${MisraUI.escapeHTML(pack.snapshot_sha256 || 'Not recorded')}</p><p class="grade-empty-copy">Student document fingerprint: ${MisraUI.escapeHTML(pack.student_document_sha256 || 'Not available')}</p></details>`;
  }

  function validEvidenceBox(source) {
    const box = source?.ocr_segment?.bounding_box;
    if (!box) return null;
    const values = [box.x, box.y, box.width, box.height].map(Number);
    if (values.some((value) => !Number.isFinite(value))) return null;
    const [x, y, width, height] = values;
    if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > 1.01 || y + height > 1.01) return null;
    return { x, y, width, height };
  }

  function renderPaperEvidence(row) {
    const pages = [...new Set(row.sources.map((source) => source.page_number))].sort((left, right) => left - right);
    if (!pages.length) {
      return `<aside class="paper-evidence is-unavailable"><h3>Answer on paper</h3><p>No source page is tracked for this question.</p><a href="submission.html?id=${encodeURIComponent(report.submission.id)}">Check extraction mapping</a></aside>`;
    }

    const figures = pages.map((page, index) => {
      const sources = row.sources.filter((source) => source.page_number === page);
      const boxes = sources.map(validEvidenceBox).filter(Boolean);
      const overlays = boxes.length
        ? boxes.map((box) => `<span class="evidence-highlight" style="--evidence-x:${box.x * 100}%;--evidence-y:${box.y * 100}%;--evidence-width:${box.width * 100}%;--evidence-height:${box.height * 100}%" aria-hidden="true"></span>`).join('')
        : '<span class="evidence-highlight is-page-level" aria-hidden="true"></span>';
      const caption = boxes.length
        ? `${boxes.length} answer region${boxes.length === 1 ? '' : 's'} highlighted from OCR evidence.`
        : 'This older OCR record has page-level evidence only; the exact answer coordinates were not stored.';
      return `<figure class="evidence-page" data-evidence-page="${page}" ${index ? 'hidden' : ''}>
        <div class="evidence-page-canvas"><img src="${MisraAPI.submissionPageUrl(report.submission.id, page - 1)}" alt="Original submitted paper, page ${page}" loading="lazy">${overlays}</div>
        <figcaption>${MisraUI.escapeHTML(caption)}</figcaption>
      </figure>`;
    }).join('');
    const tabs = pages.length > 1 ? `<div class="evidence-page-tabs" aria-label="Source pages">${pages.map((page, index) => `<button type="button" data-evidence-page-target="${page}" aria-pressed="${index === 0 ? 'true' : 'false'}">Page ${page}</button>`).join('')}</div>` : `<span class="paper-evidence-page">Page ${pages[0]}</span>`;

    return `<aside class="paper-evidence" aria-label="Original paper evidence for question ${MisraUI.escapeHTML(row.question.question_number)}">
      <div class="paper-evidence-head"><div><h3>Answer on paper</h3><p>Compare the recorded grade with the student’s actual work.</p></div>${tabs}</div>
      ${figures}
      <a class="paper-evidence-link" href="submission.html?id=${encodeURIComponent(report.submission.id)}&page=${pages[0] - 1}">Open full extraction view →</a>
    </aside>`;
  }

  function renderInstructorEditor(row, answer, latestLabel) {
    if (!answer) {
      return `<section class="instructor-grade-editor is-unavailable"><div><h3>Instructor grade</h3><p>This question has no mapped answer. Correct its OCR mapping before assigning a grade.</p></div><a class="btn btn-secondary" href="submission.html?id=${encodeURIComponent(report.submission.id)}">Fix extraction</a></section>`;
    }
    if (answer.score === null || answer.max_score === null) {
      return `<section class="instructor-grade-editor is-unavailable"><div><h3>Instructor grade</h3><p>The answer is mapped but has not been graded yet.</p></div><button class="btn btn-primary" type="button" data-grade-answer="${answer.id}">Grade this question</button></section>`;
    }

    const currentScore = effectiveScore(answer);
    const maxScore = Number(row.question.max_score || answer.max_score || 0);
    const criteria = Array.isArray(answer.criteria_scores) ? answer.criteria_scores : [];
    const humanCriteria = answer.review_status === 'overridden' && Array.isArray(latestLabel?.human_criteria_scores)
      ? new Map(latestLabel.human_criteria_scores.map((item) => [item.criterion_id, item]))
      : new Map();
    const statusLabel = answer.review_status === 'overridden'
      ? 'Instructor override active'
      : answer.review_status === 'approved'
        ? 'Instructor approved'
        : 'AI grade recorded';
    const statusTone = answer.review_status === 'overridden' ? 'warning' : answer.review_status === 'approved' ? 'success' : 'draft';
    const selectedReasons = new Set(latestLabel?.review_reason_codes || []);
    const reasonOptions = [
      ['valid_alternative', 'Valid alternative', 'The answer is correct using another accepted approach.'],
      ['minor_notation', 'Minor notation', 'Meaning is clear despite a small notation or handwritten syntax issue.'],
      ['method_credit', 'Method credit', 'The method earns credit even though the final answer is incomplete or incorrect.'],
      ['carried_forward_error', 'Carried-forward error', 'A later step is consistent with an earlier mistake.'],
      ['language_tolerance', 'Language tolerance', 'Language quality is not being assessed by this criterion.'],
      ['rubric_issue', 'Rubric issue', 'The approved rubric does not represent the intended marking decision.'],
      ['ocr_or_mapping_error', 'OCR or mapping error', 'The extracted evidence is wrong. This is never treated as a marking preference.'],
      ['other', 'Other', 'Record a different reason in the detail field.'],
    ];
    const reasonEditor = `<fieldset class="review-reason-fieldset">
      <legend>Reason for this decision <span>Required when changing the grade</span></legend>
      <p>Select every reason that influenced the decision. Extraction errors are kept separate from marking preferences.</p>
      <div class="review-reason-options">${reasonOptions.map(([value, label, description]) => `<label><input type="checkbox" name="review_reason_codes" value="${value}"${selectedReasons.has(value) ? ' checked' : ''}><span><strong>${label}</strong><small>${description}</small></span></label>`).join('')}</div>
      <label class="field review-reason-note"><span>Reason detail <small>Optional</small></span><textarea class="input" name="review_reason_note" rows="2" maxlength="1000" placeholder="Add context that will help interpret this decision later.">${MisraUI.escapeHTML(latestLabel?.review_reason_note || '')}</textarea></label>
      <p class="field-error" data-review-reason-error role="alert" hidden>Select at least one reason before saving a changed grade.</p>
    </fieldset>`;
    const criterionEditor = criteria.length ? `<details class="grade-criterion-editor">
      <summary>Adjust criterion scores <span>Optional</span></summary>
      <div class="grade-criterion-inputs">${criteria.map((criterion) => {
        const saved = humanCriteria.get(criterion.criterion_id);
        const points = saved?.points_earned ?? criterion.points_earned ?? 0;
        return `<label><span><strong>${MisraUI.escapeHTML(criterionName(criterion.criterion_id))}</strong><small>Maximum ${number(criterion.max_points)}</small></span><span class="criterion-score-control"><input class="input" type="number" inputmode="decimal" min="0" max="${Number(criterion.max_points)}" step="0.01" value="${Number(points)}" data-criterion-score data-criterion-id="${MisraUI.escapeHTML(criterion.criterion_id)}" data-criterion-max="${Number(criterion.max_points)}" aria-label="${MisraUI.escapeHTML(criterionName(criterion.criterion_id))} points"><small>/ ${number(criterion.max_points)}</small></span></label>`;
      }).join('')}</div>
      <p>Changing a criterion automatically updates the instructor score.</p>
    </details>` : '';

    return `<section class="instructor-grade-editor">
      <div class="instructor-grade-head"><div><h3>Instructor grade</h3><p>This is the score used in totals and exports. You can override the AI without regrading the paper.</p></div>${MisraUI.badge(statusLabel, statusTone)}</div>
      <form data-instructor-grade-form data-answer-id="${answer.id}" data-ai-score="${Number(answer.score)}">
        <div class="instructor-score-row">
          <label for="instructor-score-${answer.id}">Recorded score</label>
          <div><input class="input instructor-score-input" id="instructor-score-${answer.id}" name="human_score" type="number" inputmode="decimal" min="0" max="${maxScore}" step="0.01" value="${Number(currentScore)}" required><span>/ ${number(maxScore)}</span></div>
          <small>AI suggested ${number(answer.score)} / ${number(answer.max_score)}</small>
        </div>
        ${criterionEditor}
        ${reasonEditor}
        <label class="field instructor-note"><span>Instructor note <small>Optional</small></span><textarea class="input" name="reviewer_notes" rows="2" placeholder="Explain the adjustment for your records.">${MisraUI.escapeHTML(answer.teacher_notes || latestLabel?.reviewer_notes || '')}</textarea></label>
        <div class="instructor-grade-actions"><button class="btn btn-primary" type="submit">Save instructor grade</button>${answer.teacher_override_score !== null && answer.teacher_override_score !== undefined ? `<button class="btn btn-ghost" type="button" data-restore-ai="${answer.id}">Restore AI score</button>` : ''}<span data-grade-form-status role="status"></span></div>
      </form>
    </section>`;
  }

  function renderQuestion(row, answer, latestLabel, index, totalRows, calibration) {
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
    return `<details class="grade-question" ${totalRows <= 5 || index === 0 || reviewNeeded ? 'open' : ''}>
      <summary><span class="mapping-number">${MisraUI.escapeHTML(row.question.question_number)}</span><span class="grade-question-title"><strong>${MisraUI.escapeHTML(row.question.question_text || `Question ${row.question.question_number}`)}</strong><small>${sourceLinks}</small></span><span class="grade-question-score"><strong>${score === null ? 'Not graded' : number(score)}</strong>${score === null ? '' : `<small>/ ${number(row.question.max_score)}</small>`}</span><span class="grade-question-action">Review &amp; edit</span><span class="disclosure" aria-hidden="true">⌄</span></summary>
      <div class="grade-question-body">
        ${reviewNeeded ? '<div class="mapping-warning"><strong>Instructor review required</strong><span>This answer was flagged by the grading policy or confidence checks.</span></div>' : ''}
        <div class="grade-answer-meta">${MisraUI.badge(modeLabel(mode), 'draft')}${MisraUI.badge(confidenceLabel, calibrationReady && Number(confidence) >= 80 ? 'success' : 'warning')}${answer?.teacher_override_score !== null && answer?.teacher_override_score !== undefined ? MisraUI.badge('Instructor override', 'warning') : ''}</div>
        <div class="question-evidence-layout">
          ${renderPaperEvidence(row)}
          <div class="question-grade-column">
            ${renderInstructorEditor(row, answer, latestLabel)}
            <section class="grade-feedback"><h3>Feedback</h3><p>${MisraUI.escapeHTML(answer?.feedback || 'No feedback was recorded for this answer.')}</p></section>
            <section class="grade-criteria"><h3>Criterion breakdown</h3>${renderCriteria(answer?.criteria_scores, answer?.grading_raw_response?.grading_package)}</section>
            <div class="grade-disclosures">
              <details><summary>Rules &amp; references used</summary>${renderGradingPackage(answer?.grading_raw_response?.grading_package)}</details>
              ${answer ? `<details><summary>Grading history</summary><button class="btn btn-secondary" type="button" data-load-history="${answer.id}">Load saved runs</button><div data-run-history role="status"></div></details>` : ''}
              <details><summary>AI reasoning</summary><p>${MisraUI.escapeHTML(answer?.reasoning || 'No reasoning was recorded.')}</p></details>
              <details><summary>Extracted answer</summary><pre>${MisraUI.escapeHTML(answer?.raw_ocr_text || 'No OCR text was recorded.')}</pre></details>
            </div>
          </div>
        </div>
      </div>
    </details>`;
  }

  function renderQuestions(rows, answers, reviewLabels, calibration) {
    questionsCopy.textContent = `${rows.length} question${rows.length === 1 ? '' : 's'} · every question can be reviewed and edited here`;
    toggleResults.hidden = rows.length < 2;
    if (!rows.length) {
      questionsHost.innerHTML = MisraUI.emptyState('No configured questions', 'Return to the assessment and add questions before grading.');
      return;
    }
    questionsHost.innerHTML = rows.map((row, index) => {
      const answer = answers.get(row.question.id);
      return renderQuestion(row, answer, answer ? reviewLabels.get(answer.id) : null, index, rows.length, calibration);
    }).join('');
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
      const reviewLabels = new Map((results.latest_review_labels || []).map((label) => [label.answer_id, label]));
      renderSummary(results.submission, exam, answers, extraction.questions, calibration);
      renderQuestions(extraction.questions, answers, reviewLabels, calibration);
      MisraUI.reveal(questionsHost.querySelectorAll('.grade-question'));
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

  questionsHost.addEventListener('click', async event => {
    const button = event.target.closest('[data-load-history]');
    if (!button || button.disabled) return;
    const host = button.parentElement.querySelector('[data-run-history]');
    button.disabled = true;
    host.textContent = 'Loading saved runs…';
    try {
      const runs = await MisraAPI.gradingRuns(button.dataset.loadHistory);
      if (!host.isConnected) return;
      host.innerHTML = runs.length ? runs.map(run => `<details><summary>${MisraUI.escapeHTML(new Date(run.created_at).toLocaleString())} · ${number(run.score)} / ${number(run.max_score)} · ${MisraUI.escapeHTML(modeLabel(run.mode))}</summary><p>${MisraUI.escapeHTML(run.prompt_version || '')}</p>${renderGradingPackage(run.response_json?.grading_package)}${renderCriteria(run.criteria_scores, run.response_json?.grading_package)}</details>`).join('') : '<p>No saved grading runs.</p>';
      button.hidden = true;
    } catch (error) {
      host.textContent = error.message || 'Unable to load runs. Try again.';
      button.textContent = 'Retry loading runs';
    } finally { button.disabled = false; }
  });

  jobRegion.addEventListener('click', async (event) => {
    const retry = event.target.closest('[data-retry-grading]');
    if (!retry) return;
    retry.disabled = true;
    retry.textContent = 'Queueing retry…';
    try {
      const job = await MisraAPI.retryJob(retry.dataset.retryGrading);
      await watchJob(job.id);
    } catch (error) {
      renderJob({ id: activeJobId, status: 'failed', attempt_count: 0, error_message: error.message });
    }
  });

  questionsHost.addEventListener('input', (event) => {
    if (!event.target.matches('[data-criterion-score]')) return;
    const form = event.target.closest('[data-instructor-grade-form]');
    if (!form) return;
    form.dataset.criteriaDirty = 'true';
    const inputs = [...form.querySelectorAll('[data-criterion-score]')];
    const score = inputs.reduce((total, input) => total + (Number(input.value) || 0), 0);
    form.querySelector('[name="human_score"]').value = String(Math.round(score * 100) / 100);
  });

  questionsHost.addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-instructor-grade-form]');
    if (!form) return;
    event.preventDefault();
    if (!form.reportValidity()) return;

    const submit = form.querySelector('[type="submit"]');
    const status = form.querySelector('[data-grade-form-status]');
    const humanScore = Number(form.elements.human_score.value);
    const aiScore = Number(form.dataset.aiScore);
    const criteriaDirty = form.dataset.criteriaDirty === 'true';
    const criteriaInputs = [...form.querySelectorAll('[data-criterion-score]')];
    const humanCriteriaScores = criteriaDirty
      ? criteriaInputs.map((input) => ({
        criterion_id: input.dataset.criterionId,
        points_earned: Number(input.value),
        max_points: Number(input.dataset.criterionMax),
      }))
      : null;
    const notes = form.elements.reviewer_notes.value.trim();
    const reasonCodes = [...form.querySelectorAll('[name="review_reason_codes"]:checked')].map((input) => input.value);
    const reasonNote = form.elements.review_reason_note.value.trim();
    const isOverride = criteriaDirty || Math.abs(humanScore - aiScore) > 0.001;
    const reasonError = form.querySelector('[data-review-reason-error]');
    if (isOverride && !reasonCodes.length) {
      reasonError.hidden = false;
      form.querySelector('[name="review_reason_codes"]').focus();
      return;
    }
    reasonError.hidden = true;

    submit.disabled = true;
    submit.textContent = 'Saving grade…';
    status.textContent = '';
    try {
      await MisraAPI.resolveReview(form.dataset.answerId, {
        action: isOverride ? 'override' : 'approve',
        apply_as_current: true,
        human_score: isOverride ? humanScore : null,
        human_criteria_scores: isOverride ? humanCriteriaScores : null,
        was_review_warranted: isOverride,
        review_reason_codes: reasonCodes,
        review_reason_note: reasonNote || null,
        reviewer_notes: notes || null,
      });
      await load();
      window.showToast('Instructor grade saved. Totals and exports are updated.', 'success');
    } catch (error) {
      status.textContent = error.message;
      status.dataset.tone = 'error';
      submit.disabled = false;
      submit.textContent = 'Save instructor grade';
    }
  });

  questionsHost.addEventListener('click', async (event) => {
    const evidencePageButton = event.target.closest('[data-evidence-page-target]');
    if (evidencePageButton) {
      const evidence = evidencePageButton.closest('.paper-evidence');
      const targetPage = evidencePageButton.dataset.evidencePageTarget;
      evidence.querySelectorAll('[data-evidence-page-target]').forEach((button) => {
        button.setAttribute('aria-pressed', String(button === evidencePageButton));
      });
      evidence.querySelectorAll('[data-evidence-page]').forEach((page) => {
        page.hidden = page.dataset.evidencePage !== targetPage;
      });
      return;
    }

    const restore = event.target.closest('[data-restore-ai]');
    const grade = event.target.closest('[data-grade-answer]');
    if (!restore && !grade) return;
    const button = restore || grade;
    button.disabled = true;
    const previousText = button.textContent;
    button.textContent = restore ? 'Restoring…' : 'Grading…';
    try {
      if (restore) {
        await MisraAPI.resolveReview(restore.dataset.restoreAi, {
          action: 'approve',
          apply_as_current: true,
          was_review_warranted: true,
          reviewer_notes: 'Instructor restored the current AI grade from the grade editor.',
        });
        window.showToast('AI score restored.', 'success');
      } else {
        await MisraAPI.gradeAnswer(grade.dataset.gradeAnswer, 'auto');
        window.showToast('Question graded.', 'success');
      }
      await load();
    } catch (error) {
      window.showToast(error.message, 'error');
      button.disabled = false;
      button.textContent = previousText;
    }
  });

  (async function initialize() {
    if (!submissionId) { await load(); return; }
    try {
      if (!activeJobId) {
        const jobs = await MisraAPI.submissionJobs(submissionId, 'grade_submission');
        const latest = jobs[0];
        if (latest && ['queued', 'processing', 'retrying'].includes(latest.status)) activeJobId = latest.id;
      }
      if (activeJobId) await watchJob(activeJobId); else await load();
    } catch (error) {
      errorRegion.innerHTML = MisraUI.errorState(error.message);
    }
  })();
})();
