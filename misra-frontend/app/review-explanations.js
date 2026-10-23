/* Saved concerns and measured review performance; never a confidence guarantee. */
(function(){
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const rate=value=>value==null?'Not measured':`${(value*100).toFixed(1)}%`;
  function render(answer){
    const report=answer?.review_explanation;
    const rows=report?.items||[];
    const heading=report?.status==='instructor_reviewed'?'Recorded concerns · instructor reviewed':answer?.needs_review?'Why this needs review':'Review checks';
    return `<section class="review-explanation" aria-label="Review explanation"><h3>${heading}</h3>${rows.length?rows.map(row=>`<div class="review-explanation-row"><h4>${esc(row.title)}${row.criterion_id?` · ${esc(row.criterion_id)}`:''}</h4><p dir="auto">${esc(row.reason)}</p><p><strong>Check:</strong> ${esc(row.action)}</p>${row.source==='uncalibrated_heuristic'?'<p class="muted">Confidence heuristic; not a verified error.</p>':''}${[...(row.evidence_refs||[]),...(row.reference_refs||[])].length?`<p class="muted">Recorded references: ${[...(row.evidence_refs||[]),...(row.reference_refs||[])].map(esc).join(', ')}</p>`:''}</div>`).join(''):`<p>${answer?.needs_review?'This older result requests review without a detailed structured explanation. Inspect its rationale and original work.':'No recorded issue. The saved checks do not establish that the grade is correct.'}</p>`}</section>`;
  }
  function metrics(report){
    const m=report?.review_safety_metrics,w=report?.review_flag_metrics;
    return `<section class="native-panel" aria-label="Review routing measurements"><h2>Do review flags catch problems?</h2>${m?.known_review_snapshots?`<p>${esc(m.known_review_snapshots)} labelled answers with saved review flags; ${esc(m.missing_review_snapshots)} missing flag snapshots.</p><dl class="summary-strip"><div><dt>Disagreements caught</dt><dd>${esc(m.disagreements_caught)}</dd></div><div><dt>Disagreements missed</dt><dd>${esc(m.disagreements_missed)}</dd></div><div><dt>Error capture</dt><dd>${rate(m.disagreement_recall)}</dd></div><div><dt>Review workload</dt><dd>${rate(m.review_rate)}</dd></div></dl><p>${esc(m.flagged_matching_grades)} matching grades were also flagged. A matching total can still hide uncertain evidence or incorrect reasoning.</p><p>Disagreement among unflagged answers: ${rate(m.unflagged_disagreement_rate)}. Flag precision for disagreement: ${rate(m.disagreement_precision)}.</p>`:'<p>No measured error-capture result yet. Saved instructor labels and the original review flags are required; unavailable data is not shown as zero errors.</p>'}${w?`<h3>Did instructors say review was warranted?</h3><p>Review-need recall ${rate(w.recall)} · precision ${rate(w.precision)} · ${esc(w.snapshot_label_count)} labelled review snapshots. This is separate from total-grade disagreement.</p>`:'<p>Instructor-labelled review usefulness has not been measured.</p>'}<p class="muted">These measurements evaluate routing. They are not a live probability that a particular grade is correct.</p></section>`;
  }
  window.MisraReview={render,metrics};
})();
