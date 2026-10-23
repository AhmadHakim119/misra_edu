# Local evaluation

The offline CLI consolidates the existing reliability, transfer, error-profile,
confidence and per-question QWK calculations. It adds criterion error analysis and
review risk/coverage curves. It imports saved decisions; it never calls a model,
loads the live database, approves guides or changes grades. No new dependencies.

Run commands from the repository root in PowerShell. Use a **new output path** for
each attempt. Reports and frozen manifests are restricted to ignored `private/`
or `evaluation-artifacts/` directories. The source and tests here contain only
synthetic examples.

## Run the working synthetic demonstration

```powershell
.\misra_ocr_env\Scripts\python.exe misra_backend/evaluation_cli.py demo --output private/evaluation/demo-v1
```

Open `private/evaluation/demo-v1/report/scorecard.md`; the complete machine-readable
report is beside it. The command creates input packets, a protocol specification,
cohort, frozen manifest, local reference labels and manufactured predictions.
The manufactured decisions deliberately include a negation error, a denied
follow-through mark, opposing criterion errors with the same total, a hard gate,
a failed run and a missing run. This tests real report generation and accounting;
**the percentages are not model accuracy or an improvement claim**.

The 13 examples in `synthetic/marking-bank-v1.json` cover full/partial/no credit,
alternative methods, follow-through and fresh errors, notation, paraphrases,
signs, negation and correct numbers with incorrect reasoning. All marks, policies
and rationales are **proposals requiring instructor approval**. Nothing imports
this bank into production prompts. The bank is reusable development/regression
material, never a fresh evaluation sample. Approved demonstrations would need a
separate, versioned approval record tied to the exact bank hash.

## Read the scorecard

- **Headline:** exact total-grade agreement over every prescheduled answer in the
  selected split. Failed/missing/abstained runs cannot count as successes, but do
  not become zero grades. Exact agreement among scored answers is separate.
- **Criteria:** counts/points above and below the declared criterion references,
  labelled/comparable coverage, each differing decision, and matching totals that
  hide opposing criterion errors. An unknown criterion label is `null`, not zero.
  With historical marks these are differences, not proof of false/denied credit.
- **Review:** observed review workload/precision/recall remain in `reliability`.
  The separate curve simulates retaining scored proposals with `review_risk <=
  threshold`. Larger risk means more review. Ties enter together; hard gates,
  unavailable runs and missing risk always require review. Coverage is reported
  over scheduled and scored answers. Risk is disagreement rate among retained
  proposals, with their normalized error size. Zero retained answers means
  undefined risk. Retained does not authorize automatic finalization.
- **Transfer/error size:** existing question/subject macro exact agreement,
  within-one-score-step agreement, normalized MAE/bias/RMSE, direction and worst
  errors, and separate student/question cluster bootstrap intervals. QWK is per
  question/score scale and undefined for degenerate marginals. It is not a percent
  accuracy. Confidence diagnostics remain explicitly uncalibrated.
- **Unmeasured:** instructor acceptance/correction time, OCR fidelity and semantic
  evidence support require their own observations. No values are invented for them.

The CLI fits no confidence mapping or threshold. Declare the review risk signal
and operating threshold before testing. The existing `benchmark_cli.py fit` remains
the separate calibration-only workflow; do not fit on a test set. For repeated
runs, use `summarize_replicates` in `services/evaluation_reliability.py`; keep the
same cohort and report every repeat. Repeats do not multiply independent answers.

## Freeze a real evaluation before importing labels/results

Use the demo's generated JSON as runnable format examples. Keep real data local.

```powershell
.\misra_ocr_env\Scripts\python.exe misra_backend/evaluation_cli.py freeze --spec private/evaluation/study-v1/spec.json --cohort private/evaluation/study-v1/cohort.json --output private/evaluation/study-v1/frozen.json
.\misra_ocr_env\Scripts\python.exe misra_backend/evaluation_cli.py report --manifest private/evaluation/study-v1/frozen.json --references private/evaluation/study-v1/references.json --predictions private/evaluation/study-v1/predictions.json --output private/evaluation/study-v1/report-v1
```

Paths in the spec/cohort are workspace-relative. CLI input/output arguments are
relative to the shell's working directory. Inputs outside the workspace should
first be copied into a private study folder. No original file is overwritten.

The specification requires:

- `protocol_id`; `purpose` (`development`, `held_out_validation`, `subject_transfer`);
  `evaluation_split`; `data_kind` (`synthetic`, `local_private`);
  `prediction_origin` (`synthetic_fixture`, `saved_model_run`); `input_mode`
  (`checked_text`, `raw_ocr`, `reviewed_ocr`); `reference_kind` (historical_teacher,
  instructor_adjudicated, project_user_adjudicated, agent_development_audit).
- `configuration`: `model_id`, `prompt_version`, `verification_version`,
  `calculator_version`, `review_risk_signal`, `inference_settings` object,
  and `retrieval` object with `strategy` and the actual retrieval settings. Keep
  RAG enabled using the approved source scope; record the actual existing model
  and settings. This declaration does not switch the live grader.
- `metric_policy`: `target` (default 0.8), `review_risk_threshold` (default 0.25),
  `bootstrap_samples` (100–10000; default 2000), `seed` (default 171). Exact
  agreement always stays the headline regardless of this target.
- `artifacts`: distinct files with `role` (`guide`, `source`, `policy`, `prompt`,
  `implementation`, optional `examples`), `path` and `approval`. Include the exact
  key/rubric, checked course passages, policies, actual prompt text and grading/
  verification/calculator code snapshots. Multiple files per role are supported.
  Each approval has `status` (`pending`, `not_required`, `approved`). An approved
  record also needs `artifact_sha256`, `approved_by`, `approved_at`; approved
  sources separately require `checked: true`. These are local audit records, not
  an authentication or electronic-signature system.

For `held_out_validation`, use `evaluation_split: test`, `data_kind: local_private`,
`prediction_origin: saved_model_run`, `reference_kind: instructor_adjudicated`,
approved guide/checked sources/any active examples, `prior_registry_path`, and
`registry_complete: true`. The local registry is an array of prior-use records
with `answer_id`, `group_id`, `subject_id`, `question_id` (an explicitly checked
empty registry is allowed only when nothing was previously used). Include **all**
prior development, calibration and test exposure; erasing markings does not make
an answer fresh. Historical-only and agent-labelled studies remain development.

Each cohort record contains exactly:

```json
{
  "answer_id": "new-a1", "subject_id": "new-subject", "question_id": "exam-v1-q1",
  "group_id": "local-pseudonymous-group-1", "split": "test", "input_mode": "checked_text",
  "input_path": "private/evaluation/study-v1/inputs/new-a1.json",
  "input_sha256": "<sha256 of the actual redacted input packet bytes>",
  "max_score": 4, "score_step": 1, "group_checked": true,
  "answer_previously_used": false, "question_previously_used": false,
  "student_previously_used": false
}
```

The input packet is the unchanged redacted student evidence, separate from local
reference labels. Check masks and preservation of active student work first. Use
version-qualified question IDs and stable pseudonymous student groups across
files/subjects. Groups cannot cross development/calibration/test. Held-out
validation rejects previously used answers/students and contradicted newness
claims in the registry; it permits known questions when explicitly labelled so.
Raw OCR and checked-text cohorts cannot be pooled in one protocol. Development
imports may omit `input_path` for old hash-only snapshots; validation cannot.

The freeze includes cohort/configuration, artifact/answer-file hashes, prior-use
registry hash and metric-implementation hashes. Reporting rechecks them. Changed
files/settings require a new version. Fingerprints detect drift; they do not prove
that a provider really used those settings or that human exposure metadata is true.

## Import labels and predictions separately

References are local arrays. Every answer in the selected split needs a checked
total label. Missing total labels **block reporting**, rather than silently
shrinking the denominator. Missing criterion labels do not block total agreement:

```json
[
  {"answer_id": "new-a1", "reference_kind": "instructor_adjudicated", "label_checked": true,
   "reference_score": 3,
   "reference_criteria": [
     {"criterion_id": "method", "max_score": 2, "score_step": 1, "reference_score": 2},
     {"criterion_id": "result", "max_score": 2, "score_step": 1, "reference_score": 1}
   ]}
]
```

Criterion references may be omitted if only totals are labelled. If predicted
criterion decisions are supplied, include all rubric scales in `reference_criteria`
and use `reference_score: null` for each unknown criterion label. Fully labelled
criteria must sum to the total; fully assessed predictions must also sum. Unknown
IDs, duplicates, nonfinite/off-grid scores, invalid totals and mixed reference
provenance are rejected. Preserve original historical labels as separate files;
new adjudication is a new local reference revision, hashed in the report.

Predictions are an array of saved outputs for **one frozen configuration and one
prescheduled repetition**:

```json
[
  {"answer_id": "new-a1", "run_id": "saved-run-1", "status": "scored", "score": 3,
   "criteria": [{"criterion_id": "method", "score": 2}, {"criterion_id": "result", "score": 1}],
   "needs_review": true, "hard_review_required": true, "review_risk": 0.4,
   "confidence": null, "protocol_sha256": "<frozen manifest protocol_sha256>",
   "input_sha256": "<same immutable answer packet sha256>"}
]
```

Use `status: failed|missing|abstained`, `score: null`, no numeric criteria when a
run is unavailable. An absent prediction becomes a missing run. `confidence` is
optional raw 0–100; `review_risk` is a predeclared 0–1 ranking signal (or null).
For example, `1 - confidence/100` can be a **raw uncalibrated** risk signal; record
that exact definition in the configuration. Never fill missing confidence/risk
from reference errors. A hard gate requires `needs_review: true`. Soft recorded
review flags are reported separately from simulated risk thresholds. Export
actual saved decisions into this contract locally; do not recalculate grades or
invent missing criterion decisions. Reference scores, names and student text are
rejected from prediction imports. Duplicate attempts are not best-of selected.

For the synthetic contrast bank, add `--robustness-bank
evaluation/synthetic/marking-bank-v1.json` to `report` only when that exact bank is
included as a frozen `examples` artifact and predictions correspond to its cases.
The detector checks proposed criterion vectors, including semantic changes; it
does not grade prose. Genuine model robustness needs actual saved model outputs
on both sides of each pair. The demo supplies fixtures instead and says so.

## New subject and remaining data boundaries

For `subject_transfer`, additionally supply `baseline_protocol_path` pointing to
the earlier validation manifest. The new subject/questions and student groups
must be absent from prior-use records, other splits and the baseline. Core model,
settings, metric policy, prompts and grading implementation must match that
baseline. The new subject still needs its own approved guide, checked sources,
redacted inputs and independently adjudicated labels. Comparing separate frozen
subject reports is possible now; no evidence yet establishes reliability for
arbitrary subjects.

Actual blockers for a fresh empirical result are new unused labelled answers,
criterion labels where criterion-error claims are needed, approved examples if
they will enter prompts, and any new subject's guide/source approvals. Those
cannot be manufactured by this CLI. No paid calls or external data transfers are
needed to prepare, freeze, validate or score saved results.

## Tests

From `misra_backend/` with the existing environment:

```powershell
$env:DB_URL='sqlite:///:memory:'
..\misra_ocr_env\Scripts\python.exe -m unittest tests.test_evaluation_scorecard tests.test_evaluation_protocol tests.test_evaluation_robustness tests.test_evaluation_transfer tests.test_evaluation_reliability tests.test_evaluation_error_profile tests.test_benchmark_metrics
```

These test exact denominators, criterion error direction/offsetting totals,
missing/null/zero, hard gates/ties/coverage, provenance, approval and drift guards,
split/exposure leakage, new-subject constraints, actual calculator notation/sign
invariants, deliberately bad contrast decisions, and private immutable CLI output.
They do not invoke a semantic grading model.
