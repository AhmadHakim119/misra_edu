# Senior-project demonstration and evaluation direction

Confirmed scope: 14 October 2026. This document records the project direction.
For the completed 17 October private pilot's methodology and limitations, see
[GPHY evaluation protocol](GPHY_EVALUATION_PROTOCOL.md). That experiment measures
agreement on checked text; it does not establish general grading or OCR accuracy.

## Product target

A local senior-project demonstration of instructor-controlled assessment:
approved questions, answer keys, marking rules and course references → student
papers → extraction → proposed grades → instructor review → export.

The canonical frontend is the static HTML/CSS/JavaScript workspace at
`/app/index.html`. Improve it through bounded screen changes, starting with
marking-guide editing. Retain the compatibility frontend until its remaining
capabilities are ported and parity is verified. Keep the existing backend stack,
approval boundaries, original runs, instructor overrides and audit history.

## Two primary research questions

1. How closely do MISRA's proposed marks agree with independent instructor marks
   on the evaluated handwritten answers?
2. Does retrieval from approved course material using bounded BM25 change that
   agreement or the frequency of unsupported marking decisions?

The result may show benefit, no clear difference, or harm. Report the result
actually observed. A local demonstration does not establish production readiness
or reliability across subjects, languages or institutions.

## Main experiment

Use paired runs on the same answer set:

| Fixed between conditions | Changed between conditions |
| --- | --- |
| Model and endpoint, prompt version except source-use instructions, inference settings, extracted answer/images, question, answer key, rubric and policy, maximum mark | No retrieved course passages vs bounded BM25 passages from approved, selected course material |

The no-retrieval condition still receives the question, approved answer key,
rubric and policy. It is not a different marking scheme. Record prompts and
retrieval settings. Keep experimental no-retrieval variants separate from the
production required-source rule; never disable that rule on a real assessment.

Freeze extraction for the main comparison to isolate the effect of retrieval.
Report extraction limitations. A later comparison using checked human
transcriptions can help identify errors caused by OCR. Model or modality
comparisons are secondary experiments and must not change at the same time as
retrieval in the primary experiment.

## Data and labels

Each subject needs its own verified papers, source material, approved guide
and independently recorded reference labels. The preparation checklist below
applies before selecting an evaluation sample.

- Inventory papers, questions, answer counts, languages, score scales, available
  course sources and marking schemes before selecting a sample.
- Obtain instructor marks assigned independently of AI output. Later corrections
  made while viewing AI grades are useful workflow evidence but must be identified
  separately from independent reference labels.
- Keep original papers private. Benchmark inputs must exclude identities and
  instructor marks/comments; record any redaction or excluded evidence.
- Keep human scores outside model inputs, retrieval indexes and prompts.
- Separate development and held-out evaluation by paper/student before tuning.
  A separate exam/year may provide an additional generalization comparison, if
  there are sufficient examples with compatible marking guides and source material.
- Freeze rubric/key/policy/source versions and document hashes in a manifest.
- Report the number of PDFs, papers, students, questions and answer examples
  separately. A PDF count is not an evaluation sample size.

Any expanded dataset still needs independent-label, input and source checks. The
pilot's approvals and reviewed inputs do not certify every paper or source page.
No live experiment is authorized merely by storing a paper in the workspace.

## Metrics and reporting

| Measure | Interpretation and boundary |
| --- | --- |
| Exact agreement | Fraction of scored answers matching the instructor's score; state permitted score increments and numeric tolerance. |
| MAE and RMSE | Average absolute and squared-error-sensitive differences in marks. Report by question/scale as well as pooled counts. |
| Normalized MAE/RMSE | Divide each error by that question's maximum mark before aggregation. |
| Signed normalized bias | Shows whether the model tends to overmark or undermark. |
| Tolerance agreement | Use a tolerance specified before evaluating; a universal ±1 mark is unsuitable across different maximum marks. |
| Criterion agreement | Requires instructor criterion allocations; do not invent them from a total score. |
| Review/abstention/failure rates | Include all attempted answers and reasons; report coverage alongside error on successfully scored answers. |
| Paired retrieval effect | Report per-answer differences and uncertainty clustered by paper/student when sample size supports it. |
| Latency and usage | Record actual stage times, token usage, attempts and reported cost; unknown values stay unknown. |

Quadratic weighted kappa is optional when the compared answers share defensible
ordinal score categories. Do not pool incompatible mark scales into one kappa.
Report sample sizes and distributions, excluded/failed runs and intervals where
appropriate. A small dataset supports a limited pilot claim.

If instructors can label relevant passages, report retrieval Recall@k and
nDCG@k separately. If they audit criterion decisions, report unsupported awards,
unsupported deductions and semantic citation correctness/completeness with clear
denominators. Valid citation identifiers alone do not establish support.

LLM confidence remains uncalibrated. Calibration requires a defined event,
independent labels and separate fitting/evaluation data. ROUGE, BERTScore and
correlation do not substitute for agreement on marks.

## Free inference and Gemini replacement

The user wants a free alternative to Gemini. Current code already offers
`GRADING_PROVIDER=openrouter_free`; `services/free_model_gateway.py` requires
an explicit free model, checks current catalog pricing and image support, and
disables paid/model fallback. This inspection is not a live inference result.
OCR and some setup services still use Gemini, so changing the grading provider
alone does not remove that dependency.

Select a pinned non-Gemini model only after checking current availability,
image support, quotas and the existing output contract. Validate the adapter
with synthetic data first. A local-model option requires measured hardware
capacity and latency. Preserve historical provider metadata and existing runs.

Hermes is an optional orchestration layer with separately configured inference
providers. Its use does not itself provide a free model or establish better
grading. The current persisted worker flow is sufficient for the first controlled
comparison; an additional agent framework should have a specific demonstrated job.

Provider documentation consulted on 14 October 2026:
[Hermes providers](https://hermes-agent.nousresearch.com/docs/integrations/providers),
[OpenRouter limits](https://openrouter.ai/docs/api_reference/limits).

## Demonstration and judge questions

Demonstrate a complete saved workflow, then show the experimental configuration,
sample counts, paired results and a few inspected disagreements. Separate software
checks from empirical results.

- **What does RAG add?** Approved course context retrieved using question and
  criterion text. The paired experiment measures its effect.
- **Who decides the mark?** The instructor approves marking definitions and owns
  final grades; AI results remain proposals with preserved history.
- **How is accuracy measured?** Against independent instructor marks on a frozen
  evaluation set, using agreement, errors, coverage and uncertainty.
- **Why BM25?** It is the existing bounded lexical baseline. Better retrieval or
  grading than another method has not been established without comparison.
- **What happens when AI is wrong?** Retain the evidence and original run, expose
  failure/review states, and record instructor corrections without rewriting history.
- **What remains limited?** The evaluated sample, extraction errors, source
  coverage, rubric ambiguity, model availability and any untested languages/tasks.
