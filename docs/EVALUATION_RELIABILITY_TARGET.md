# Measuring the 80% evaluation target

The provisional primary event is **exact agreement with the historical instructor
score**, over every prescheduled eligible answer. This is a measurable proxy for
satisfactory grading, not proof of correctness or an instructor satisfaction rating.
Keep rubric-adherence adjudication separate when an historical score conflicts with
the approved guide. Do not change reference scores or widen tolerances to reach 80%.

`services/evaluation_reliability.py` produces an offline report from one observation
per scheduled answer. It reports exact yield, descriptive Wilson intervals, MAE,
bias, review workload, disagreement recall and disagreements among unflagged scores.
Failed, missing and abstained runs stay in the yield denominator and require
attention; they never become zero grades or caught grading disagreements. A flagged
wrong grade remains wrong for agreement. Undefined rates remain null.

Use one cohort and one frozen model/prompt/retrieval configuration per report.
Separate checked-transcription grading from OCR-fed grading, and report OCR fidelity
against visually checked student work. Parseable JSON, plausible physics, valid
citation IDs and matching final scores do not establish faithful transcription.
Preserve uncertain signs, decimal points, intermediate work and cancellations.

An observed 80% rate in a small reused cohort is development evidence. Report its
sample count and interval; it cannot validate a selected model or confidence mapping.
The Wilson interval assumes independent answers and is descriptive for a single
question. For multiple answers per student, retain the existing grouped benchmark
analysis. Model comparisons must include failed contracts and all scheduled cells;
do not choose the highest grade or the model closest to each known label.

RAG remains required for the main condition. Save the approved source scope, selected
passages, criterion links and hashes. Check whether passages actually support the
physics rather than relying on lexical rank or citation presence. Retrieval cannot
resolve handwriting or authorize a marking-policy change. Frozen earlier comparisons
remain unchanged; reused examples become regression evidence.

Audit tied retrieval comparisons using the actual provider requests, selected
passage/criterion mappings and independent response IDs. A different ranker can
produce the same final context; a different context can still produce the same
marks. Identical percentages neither prove a broken pipeline nor establish equivalent
retrieval quality. Pure-vector ablations must bypass BM25 completely rather than
only renaming a hybrid arm; MISRA exposes `dense_v1` and `dense_rerank_v1` for this.

No confidence mapping or threshold was fitted from the skateboard examples. The
operational raw-confidence threshold remains an uncalibrated review heuristic.
`grading_decision_service.py` now also routes disagreements about visible-work
completeness and error classification to review, even if both agents say supported.
It preserves the proposed marks and original model verdicts. Restart the API and
workers to load changed service code; no restart or live regrading is performed here.

`services/extraction_reliability.py` reports locally checked grade-sensitive OCR
issues separately from grade agreement: silent errors, uncertainty-flag recall
and precision, review coverage and error-free yield over scheduled answers.
Unavailable extractions and cases awaiting source adjudication cannot be labeled
error-free. Empty denominators stay null. These are qualitative fidelity labels,
not character accuracy or calibrated confidence. Presence of an uncertainty flag
does not prove it identifies the actual bad glyph.


## Transfer, reference provenance and source audits

`services/evaluation_transfer.py` adds subject/question macro agreement, score-grid
checks, explicit answer/question/student exposure, separate input stages and
student/question clustered descriptive intervals. One large easy question cannot
hide another question's poor result in the macro report. Reusing an answer also
exposes its question and student; inconsistent exposure declarations fail.
Cross-version student grouping must be checked before using student-cluster claims.
When grouping is unknown, report answer-unit counts without inventing independence.

Historical teacher labels and adjudicated labels are different references. Keep
their event names and reports separate, bind a new adjudication to the applicable
approved guide, and retain the original historical label. Project-user review in
the local demonstration is not independent instructor validation. A post-run
adjudication provides calibration/regression evidence; it does not turn those
answers into an untouched test cohort. Do not redefine an old study's target.

When a later source audit discovers a teacher addition or unreadable symbol,
append an erratum and publish a new clean-yield report. Keep the answer in the
original scheduled denominator as unavailable/abstained, with no manufactured zero.
Also report the resolved clean subset explicitly. Preserve the original requests,
outputs and earlier reports. A corrected-input rerun is a separate regression.

Decision-check v7 adds an approved-policy-gated cross-part follow-through review:
a complete result with a valid local method, denied alongside another conceptual
deduction, may be a repeated input penalty. It flags the issue without inferring
the dependency or changing marks. The rule itself requires explicit guide approval.

Decision-check v8 adds `unexplained_criterion_deduction`: a complete result/mixed
criterion described as error-free with clear policy and a valid/unassessed method
cannot silently lose marks. The guard requests a check of the failed requirement
or numeric mark; it never supplies credit. This also applies when the verifier's
check contradicts the assessor's numeric deduction.

A useful evaluation reports review workload and precision alongside error capture.
Capturing every historical disagreement while flagging nearly every answer does
not establish a low-workload grading workflow. No raw confidence threshold is
fitted or relabeled as a calibrated correctness probability in these diagnostics.

`services/evaluation_error_profile.py` reports the counts above, below and exactly
at a supplied reference separately. Opposing errors can cancel in mean bias while
both remain important. Normalized RMSE, worst normalized error, unflagged error
severity and the complete empirical error distribution describe that difference
across mark scales without fitting a favorable acceptance band. Reference
provenance is explicit: being above a historical teacher mark does not by itself
establish overgrading under a different approved guide. Failed and abstained
attempts remain coverage gaps, never zero scores or numeric errors. Add these as
new diagnostic reports; never retrofit them into sealed historical results.
