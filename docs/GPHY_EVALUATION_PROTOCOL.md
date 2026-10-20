# Offline grading evaluation protocol

MISRA is a local instructor-facing prototype. Instructors own final grades.
This protocol separates grading quality, retrieval support, extraction fidelity
and review workload. Results for a small course/question sample do not establish
performance for every subject.

## Inputs and privacy

- Preserve original papers and historical teacher marks locally. Never send names,
  IDs, marked scans, teacher corrections or reference scores to a model provider.
- Create separate reviewed copies. Preserve student work, including errors and
  cancellations. Obscured or uncertain handwriting remains uncertain.
- Exclude covers, duplicate scans and answers without usable independent labels
  from the relevant agreement cohort. Exclusions are not zero grades.
- Keep questions, keys, criteria, policies, approved course evidence, student
  evidence and reference labels separate. A student-derived reference solution
  retains that provenance and is excluded from the test students.
- Keep papers, reports, request/response logs, labels and cost ledgers under
  ignored `private/` or `evaluation-artifacts/`. Public fixtures are synthetic.

## Freeze before inference

Record question/subpart maxima, permitted score increments, the exact guide and
source hashes, checking/approval provenance, course scope, model settings, prompt
versions, retrieval strategy, budget and prescheduled attempts. Approval belongs
to the exact guide version; source-page checking remains a separate boundary.

Partition by student before development or calibration. Record prior answer,
question and student exposure explicitly. A cleaned or newly rendered copy is
still the same answer. Later corrections and reused cases become regression
evidence rather than a fresh test. Do not choose a best model or repeat per answer.

Use checked transcriptions to isolate grading from OCR, and a separate image-fed
study to measure extraction-to-grade behavior. Compare actual OCR with checked
visible work. Valid JSON, plausible calculations and matching totals do not prove
faithful extraction. Unresolved glyphs need review before release.

## RAG and comparisons

The main grading condition uses approved course evidence. Retrieval uses only
approved question/criterion information, never student answers or teacher marks.
Save selected whole passages, hashes, criterion bindings and actual provider
payloads. Required-source grading fails without applicable evidence/citations.

Hold approved inputs, models and settings fixed when comparing retrievers.
Report relevance/coverage separately from final-grade agreement. Dense-only
ablations must really bypass BM25. Revision notes that closely match exam
questions are legitimate declared course material, but their overlap must be
recorded. They cannot establish transfer to unseen question types.

## Reporting

Report each frozen pipeline, repeat and input mode separately. Include every
prescheduled eligible attempt in exact-yield denominators; failures, missing runs
and abstentions have no manufactured numeric grade. Also report scored-only
agreement, MAE, normalized errors, signed bias, review precision/recall/workload,
coverage, repeated stability, latency and known/unknown spending.

Use question and subject macro reports so a large easy section cannot hide weak
conceptual grading. Keep historical teacher and adjudicated references distinct.
No criterion-level reference may be invented from a total teacher score.
Model confidence is uncalibrated; an 80% target cannot be reached by changing
labels, widening tolerances after seeing results, or choosing higher marks.

The offline implementations are `benchmark_metrics.py`,
`evaluation_reliability.py`, `evaluation_transfer.py`,
`evaluation_error_profile.py`, and `extraction_reliability.py` under backend
services. `benchmark_runner.py` validates frozen research inputs and creates
proposals without changing live academic records. See
[Measuring the evaluation target](EVALUATION_RELIABILITY_TARGET.md) for metric
interpretations and [OCR reliability phases](OCR_RELIABILITY_PHASES.md) for the
extraction review gate.

Preserve original attempts and sealed reports. A source erratum, corrected
transcription, new rubric or new metric report is a new version. No automatic
live regrading, model fallback or silent guide approval is part of this protocol.
