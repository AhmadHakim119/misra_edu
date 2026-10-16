/* Display saved job states consistently without changing retry or grading semantics. */
(function () {
  'use strict';
  const active = new Set(['queued', 'processing', 'retrying']);
  const task = job => ({grade_submission:'AI grading',ocr_submission:'Handwriting extraction',ocr_batch:'Handwriting extraction',exam_setup:'Exam setup',material_ingestion:'Course material',source_question_drafts:'Question drafting'})[job.job_type] || 'Background work';
  function title(job) {
    if (active.has(job.status)) return 'Processing…';
    if (job.status === 'completed') return 'Completed';
    if (job.status === 'failed') return job.job_type === 'grade_submission' ? 'Grading couldn’t finish' : job.job_type?.startsWith('ocr') ? 'Extraction couldn’t finish' : 'Processing couldn’t finish';
    return 'Status unavailable';
  }
  function message(job) {
    if (job.status === 'retrying') return 'Processing is continuing automatically. Your paper is saved.';
    if (job.status === 'queued') return 'Your work is saved and queued for processing.';
    if (job.status === 'processing') return /failed|retry limit reached/i.test(job.progress_message || '') ? 'Processing is continuing. Your paper is saved.' : job.progress_message || 'Processing is continuing. Your paper is saved.';
    if (job.status === 'failed') {
      const error = job.error_message || '';
      if (/AI grading response failed validation:|invalid evidence citations/i.test(error)) return 'The AI response failed validation. No grade was saved for this answer. Review the error details, then retry grading.';
      if (/Selected free model is not in the current catalog|Free model catalog is unavailable|selected (?:free )?model (?:is unavailable|does not accept images)/i.test(error)) return 'The grading model is unavailable. Your paper is saved. Retry after the model settings are fixed.';
      if (/429|quota|rate.limit|resource.exhausted/i.test(error)) return 'The AI service is busy. Your paper is saved. Try again later.';
      if (/queue unavailable|could not reach.*queue/i.test(error)) return 'Processing is unavailable. Your paper is saved. Retry when the service is back.';
      return 'Your paper and saved results are retained. Check the error details before retrying.';
    }
    return job.progress_message || 'Open the paper to review the saved results.';
  }
  function details(job, escape) {
    return job.status === 'failed' && job.error_message ? '<details class="job-error-details"><summary>Error details</summary><p dir="auto">' + escape(job.error_message) + '</p></details>' : '';
  }
  window.MisraJobStatus = {task, title, message, details};
})();
