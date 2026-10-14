/* UI states reflect persisted records; they never grant grading/export permission. */
(function () {
  'use strict';
  const active = new Set(['queued', 'processing', 'retrying']);
  const number = (value) => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
  function state(paper) {
    const status = String(paper.status || '').toLowerCase();
    const job = paper.latest_ocr_job;
    const gradingJob = paper.latest_grading_job;
    const readiness = paper.readiness || {};
    const result = (key, label, tone, detail, action, page = 'submission') => ({
      key, label, tone, detail, action, href: `${page}.html?id=${encodeURIComponent(paper.id)}`,
      active: key === 'processing', graded: ['graded', 'review'].includes(key),
    });
    if (active.has(gradingJob?.status) || (!['failed', 'completed'].includes(gradingJob?.status) && status === 'grading')) return result('processing', gradingJob?.status === 'queued' ? 'Grading queued' : gradingJob?.status === 'retrying' ? 'Retrying grading' : 'Grading in progress', 'draft', gradingJob?.progress_message || 'You can leave this page. Your worker will continue grading.', 'View progress', 'grade-results');
    if (active.has(job?.status) || (!['failed', 'completed'].includes(job?.status) && ['uploaded', 'queued', 'processing', 'extracting', 'retrying'].includes(status))) {
      const label = job?.status === 'retrying' || status === 'retrying' ? 'Retrying extraction'
        : job?.status === 'processing' || ['extracting', 'processing'].includes(status) ? 'Reading paper' : 'Waiting for worker';
      return result('processing', label, 'draft', job?.progress_message || 'Identity and answer mapping appear after extraction finishes.', 'View progress');
    }
    if (gradingJob?.status === 'failed' && !['graded', 'reviewed', 'needs_review'].includes(status)) return result('attention', 'Grading stopped', 'danger', gradingJob.error_message || 'Open the grading results to inspect the failed job and retry.', 'Resolve grading', 'grade-results');
    if (job?.status === 'failed' || ['failed', 'error'].includes(status)) return result('attention', 'Extraction stopped', 'danger', job?.error_message || paper.error_message || 'Open the paper to inspect the failure and retry safely.', 'Resolve failure');
    if (status === 'needs_review') return result('review', 'Grade review needed', 'warning', 'Open the recorded grades and resolve flagged answers.', 'Review grades', 'grade-results');
    if (['graded', 'reviewed'].includes(status)) return result('graded', 'Grades recorded', 'success', 'View scores, feedback and instructor corrections.', 'View grades', 'grade-results');
    if (readiness.bulk_grading_allowed === true) return result('ready', 'Ready to grade', 'success', 'Answer mapping checks passed. Open the paper to begin grading.', 'Open paper');
    const missing = Array.isArray(readiness.missing_question_numbers) ? readiness.missing_question_numbers : [];
    return result('attention', 'Check extraction', 'warning', missing.length ? `Missing answers: ${missing.join(', ')}.` : readiness.blocking_reasons?.[0] || 'Open the paper to inspect the evidence that needs verification.', 'Check paper');
  }
  function counts(papers) {
    const counts = { all: papers.length, processing: 0, attention: 0, ready: 0, graded: 0, review: 0, identity: 0 };
    papers.forEach((paper) => {
      const flow = state(paper);
      counts[flow.key] += 1;
      if (!flow.active && (!String(paper.extracted_student_name || '').trim() || !String(paper.extracted_student_number || '').trim())) counts.identity += 1;
    });
    return counts;
  }
  window.MisraPaperFlow = { state, counts, number };
})();
