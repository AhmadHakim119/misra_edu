# Approved-source grading

This describes implemented behaviour, not a claim that the model grades correctly.
MISRA remains an instructor-reviewed prototype.

## Application flow

```text
Instructor uploads course PDF or enters teaching notes
    → private file + draft material version + MariaDB job record
    → RQ worker reads native PDF text locally
    → full page inventory and character-positioned passages
    → instructor checks/corrects text and approves selected pages
    → question/criterion source scope is drafted and approved

Approved question + rubric criteria
    → bounded BM25/exact-passage retrieval within approved course pages
    → grading package: question, key, rubric, policy, passages, student evidence
    → explicit grading provider
    → deterministic score/criterion/citation validation
    → saved AI proposal + immutable package snapshot
    → instructor review/override
    → eligible grade export
```

Redis delivers work; MariaDB owns document versions, approvals, progress,
passages, source scope, runs and review labels. Course-material ingestion does
not create a student submission. Native PDF and PPTX text reading is local.
Explicit scanned-PDF reading can invoke the configured extraction provider; its
output still requires instructor source-page approval. See [Course library](COURSE_LIBRARY.md).

## Boundaries

| Input | Responsibility |
|---|---|
| Question | Defines the task the student was asked |
| Approved answer key | Reference solution and accepted alternatives |
| Approved rubric | Defines assessable criteria and points |
| Approved policy | Explicit academic tolerances and evidence requirements |
| Approved course sources | Selected contextual passages, not extra scoring rules |
| Student OCR and images | Untrusted student evidence, never instructions |
| Model output | Proposed criterion scores, explanations and citations |
| Backend validation | Enforces permitted IDs, bounds, totals and citation scope |
| Instructor decision | Reviews ambiguity and authorizes corrections |

Course materials are institution/course-owned. A source scope cannot refer to
another course's document, an unapproved version, an unapproved page, an
unknown rubric criterion, or an unrelated passage. Approved versions are
immutable. New document/scope versions supersede prior approvals; pinned older
approved source versions remain available until a new scope is explicitly
approved. File and content hashes detect missing/changed references.

## Retrieval contract

The query is constructed from the approved question and criterion wording, not
from student answers. This prevents answers from choosing their own marking
authority. BM25 is lexical retrieval: it is not an embedding model, semantic
proof, or a replacement for instructor review of equations. Exact passage links
are available for text that lexical search misses.

Retrieval selects up to two passages per criterion and eight passages/12,000
characters in total. It never cuts a passage to meet the budget. A required
scope fails before inference when relevant configured context is missing.
Optional incomplete context is recorded and routed to review. Citation IDs are
checked against each criterion's allowed sources. Missing required-source
citations trigger review and confidence limiting; a citation alone does not
establish that the model interpreted the source correctly.

PDF page positions and printed labels are distinct. The API uses zero-based
page indices; the interface shows document pages starting at 1. Draft native
text is explicitly unverified. Scans without a text layer require a verified
transcription before approval. Native extraction can damage formulas, so this
milestone does not claim automatic mathematical OCR or equation recovery.

## Historical evidence

Every new grading run stores passage text, title, version, page/character span,
content/file hashes, retrieval query and scope. The provider receives academic
context and local citation aliases, not tenant IDs or storage paths. Returned
aliases are resolved before validation. Later material/rubric edits cannot
change the saved package. Mode-audit comparisons reject changed source context
rather than attribute a definition change to text-versus-image performance.

## Provider contract

`GRADING_PROVIDER=gemini` preserves existing grading. `openrouter_free` enables
one explicitly configured `:free` model, with current zero-priced catalog
verification and no paid/model/text-only fallback. Unsupported vision, provider
failure, truncated/invalid output or changed model routing does not save a grade.
Neither routing option guarantees model capacity or accuracy. Existing OCR,
setup import and rubric suggestion functions still use Gemini. Without a Gemini
key these operations fail explicitly; importing the application/material tools
does not need to fail solely because that key is absent.

## Grading response correction

Prompt version `v6-traceable-citations` explicitly requires a tracked student
segment/page citation for every criterion when that evidence exists, including
partial/zero credit and explanations of a missing step. A citation identifies
the inspected evidence; it does not assert that an absent step is present.

Only citation/policy-reference contract failures receive one correction request,
using the identical grading package, provider and original images. The original
proposal's total and criterion marks are frozen. Invented/out-of-scope references,
score changes and a second invalid response remain rejected. Invalid JSON/schema
or rubric scores do not trigger citation correction. No automatic citation
attachment, OCR rerun, reference retrieval or provider fallback occurs.

A successfully corrected run records both calls' metadata and an initial-response
hash, retains the ordinary full validation, and requires instructor review with
confidence capped at 40. Structural citation validity is not semantic support.
Available cost/token usage is summed across calls; missing usage stays unknown.
These are accepted-run observations, not complete provider billing records.

An exhausted contract correction fails the persisted grading job immediately;
stale automatic queue deliveries cannot make further model calls. Explicit manual
retry remains available and retains the job's already-completed answer list.
Invalid responses create no grade/run for the rejected answer, and failure messages
contain safe reasons rather than raw model/student content. Provider connectivity
failures retain the existing job retry policy. No database upgrade is required.

## Evaluation interpretation

Grade agreement is measured against immutable instructor labels: MAE, RMSE,
signed error, normalized MAE, exact/within-one agreement, review precision/recall
and high-confidence errors. Normalization uses historical run/criterion maxima,
not the latest mutable question. Criterion-by-definition grouping separates
unrelated questions and rubric versions. Old pooled views remain for API
compatibility.

Saved-run diagnostics count structural citations and observed timing/usage by
model, prompt version and mode. Missing cost is unknown. Review reasons can
explicitly identify unsupported deductions and incorrect source citations;
these are instructor annotations, not automated semantic judgments, and they
are excluded from marking-preference learning. Unannotated predictions are not
known-correct predictions.

CER and WER measure OCR transcription against aligned manual text. ROUGE-1/2/L
measure lexical overlap and must not be presented as grading accuracy. Their
offline implementation preserves Arabic and mathematical symbols; whitespace
normalization is opt-in. Large comparisons are bounded to protect CPU-only
hosts.

## Still required before comparative accuracy claims

- Separate development/calibration and held-out labelled papers.
- Instructor-approved answer keys and criterion marks, including choice rules.
- Verified student/page coverage and robust automatic answer mapping.
- Provider capacity and private-data handling approval for real benchmarks.
- Paired old/new runs with matched evidence and definitions.
- Human assessment of deduction support and semantic citation correctness.

Source-derived question generation is documented separately in
[Source question drafts](SOURCE_QUESTION_DRAFTS.md). Embedding reranking, a replacement
frontend, local multimodal OCR and Moodle integration remain separate milestones.
