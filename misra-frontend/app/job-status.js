/* Display saved job states consistently without changing retry or grading semantics. */
(function () {
  'use strict';
  const active = new Set(['queued', 'processing', 'retrying', 'stopping']);
  const gradingStages = {preparing:'Preparing the approved marking guide and evidence…',
    assessing:'The AI is grading the answer…',verifying:'The AI is checking the proposed marks…',
    saving:'Saving the proposed marks…'};
  const isActive = job => active.has(job?.status);
  const progress = job => `<progress class="job-progress" dir="ltr" max="100" value="${Math.min(100,Math.max(0,Number(job.progress_percent)||0))}" aria-label="Job progress"></progress>`;
  const needsVision = job => job.job_type === 'grade_submission' &&
    (job.error_message || '').startsWith('Local Qwen grades text only. Required images cannot be omitted.');
  const task = job => ({locate_answers:'Answer location',read_answer_area:'Answer area extraction',regrade_corrected_answer:'Corrected answer grading'})[job.operation] || ({grade_submission:'AI grading',ocr_submission:'Handwriting extraction',ocr_batch:'Handwriting extraction',exam_setup:'Exam setup',material_ingestion:'Course material',source_question_drafts:'Question drafting'})[job.job_type] || 'Background work';
  function title(job) {
    if (job.status === 'stopping') return 'Stopping…';
    if (job.status === 'stopped') return 'Stopped';
    if (job.status === 'queued') return 'Queued';
    if (job.status === 'retrying') return 'Waiting to retry';
    if (active.has(job.status)) return 'Processing…';
    if (job.status === 'completed') return job.incomplete_comparison_count ? 'Grading finished with incomplete comparisons' : 'Completed';
    if (job.status === 'failed') return job.operation==='locate_answers'?'Answer location couldn’t finish':job.job_type === 'grade_submission' ? 'Grading couldn’t finish' : job.job_type?.startsWith('ocr') ? 'Extraction couldn’t finish' : 'Processing couldn’t finish';
    return 'Status unavailable';
  }
  function message(job) {
    if (job.status === 'stopping') return 'Stop requested. Any saved grades are kept.';
    if (job.status === 'stopped') return 'Grading stopped. Completed answers stay saved.';
    if (job.status === 'retrying') return 'Processing is continuing automatically. Your paper is saved.';
    if (job.status === 'queued') return 'Your work is saved and queued for processing.';
    if (job.status === 'processing') return gradingStages[job.grading_stage] || (/failed|retry limit reached/i.test(job.progress_message || '') ? 'Processing is continuing. Your paper is saved.' : job.progress_message || 'Processing is continuing. Your paper is saved.');
    if (job.status === 'failed') {
      if(job.operation==='locate_answers')return 'Answer location could not finish. Your extracted text and grades are unchanged. Retry when the extraction service is available.';
      const error = job.error_message || '';
      if (needsVision(job)) return 'This job used text-only Qwen. Save Fully local Qwen in AI services, then open the paper to grade it.';
      if (/AI grading response failed validation:|invalid evidence citations/i.test(error)) return 'The AI response failed validation. No grade was saved for this answer. Review the error details, then retry grading.';
      if (/shared free-model limit/i.test(error)) return 'OpenRouter reached its shared free limit. Use Fully local Qwen or retry after the limit resets.';
      if (/No eligible OpenRouter model|OpenRouter catalog is unavailable/i.test(error)) return 'OpenRouter models are unavailable. Your work is saved. Retry later or use Fully local Qwen.';
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
  window.MisraJobStatus = {task, title, message, details, needsVision, isActive, progress};
})();
