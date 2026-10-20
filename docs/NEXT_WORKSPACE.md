# Native instructor workspace

The current route map, three-role AI pipeline, mixed-provider configuration and
validation boundaries are documented in [Native instructor workflow](NATIVE_WORKSPACE.md).
The focused native pages supersede the porting backlog below.

Open `/app/index.html` on the running MISRA API. The retired HTML interface is no
longer distributed; its known bookmarks redirect to current pages. Shared
controllers remain in use by the current app.

The new workspace is an **assessment-first marking ledger**, developed in phases.
It is a functional preview, not yet a replacement with full feature parity or a
completed visual-fidelity review.

## Available in the preview

- Connected [teaching-material → quiz → marking → feedback flow](TEACHING_CYCLE.md):
  multi-PDF material upload, all-checked-material selection, native optional quiz
  proposals, existing-exam/key import, saved request recovery, per-criterion lecture
  excerpts/original links and descriptive class credit observations. Confidence is
  still uncalibrated; citation identity is not proof of correctness.

- Assessment selection and paper search, with one next action per paper.
- Saved extraction, question navigation and criterion titles from run snapshots.
- Original full-page evidence, page navigation, zoom and an accessible expanded view.
- Text-matched/approximate highlights, with the full page retained at every zoom level.
- Visible saved course-reference provenance, marking guidance, policy and AI rationale.
- Recorded marks, instructor overrides, optional criterion edits and structured reasons.
- Run-pinned review decisions; failed-save retention and unsaved-navigation guards.
- Safe queue retry, initial whole-paper grading and persistent job progress.
- Review-only paper filter and shared Settings light/dark/system preference.
- Native single/batch student-paper upload, with locked selection and setup checks.
- Accepted OCR-job recovery after reload, with progress polling and safe connection-loss states.
- Assessment-wide source defaults, explicit draft/approval and question exceptions.
- Source/rubric readiness summaries and assessment-scoped authoring links.
- Native rubric authoring: criteria, credit levels, common mistakes, scoring policy,
  explicit draft/approval, version history and optional AI rubric suggestions.
- Independently versioned answer-key text, alternatives and reference documents.
- Native course-library upload/notes, revisions, transcription correction, checked
  page approval and question-specific retrieval scopes.
- A focused assessment next-action: finish setup, view progress, review a paper,
  upload, or check export. Papers are not opened automatically on a normal visit.
- Collapsible assessment index and paper picker; paper and editable grade appear
  together after selecting a submission.
- Student-name/number correction beside the original paper, without losing an
  unsaved grade. Completed single uploads open their extracted paper directly.
- Separate Activity view for persisted OCR/grading jobs rather than a permanent
  extra panel beside every marking decision.
- Native export checks, per-student inclusion/exclusion explanations, Blackboard
  and generic CSV downloads and Excel reports.
- Native assessment/course creation, sign-in, password recovery and Settings
  (appearance, marking preferences and password change), using existing APIs.

Extraction readiness and grading progress are separate states. Model estimates
and review flags sit beside the editable score; optional controls stay below.
Expanding a paper does not discard a grade draft or crop the stored evidence.

Paper totals use instructor overrides and exclude externally assessed practical
work. Missing grades are not replaced with zero. Model confidence remains
explicitly uncalibrated; highlights locate evidence but do not verify grades.
The preview does not silently start another full-paper grading job when the paper
already has recorded marks. Use the existing job retry/history tools for those cases.

## Native workflow destinations

The requested setup, upload, extraction correction, grading history, review queue,
identity, feedback, results, evaluation and administration workflows now have
native `/app/` destinations. Links inside this workspace no longer send instructors
to `/pages`. Local retired copies are ignored reference material and are not a
supported fallback. This does not certify every historical feature.

Assessment-wide references require the additive source-default upgrade described
in [Assessment source defaults](ASSESSMENT_SOURCE_DEFAULTS.md). Back up first and
restart both the API and worker after applying it yourself.

## Test boundary

Browser tests use synthetic API records and synthetic original pages. Software
tests establish workflow behaviour, not improved marking accuracy on real papers.
Private drafts and selected files remain in memory; theme and interface-language preferences
are stored locally. The URL may retain assessment/view/job identifiers to recover
accepted work, never file bytes or student names. Reloading discards an unsent
file selection but does not repeat an accepted upload. An ambiguous upload
response requires checking papers/activity before choosing a new selection.

## Marking guide and library

Choose an assessment → **Sources & rubric**. The source-led replacement uses **Sources → Marking
guide → Review & approve**, with one assessment-wide approval. See
[Assessment marking guide](ASSESSMENT_GUIDE.md) for its save, source and publication
boundaries. Existing approved rubric versions are read-only; create
an editable draft, then save or explicitly approve it. Credit levels and mistake
guidance use ordinary labeled fields, not JSON. The action bar remains visible
while the longer sections collapse. Approval never rewrites saved grading runs.

New questions in this preview send `approve_initial_rubric: false`, so their
first rubric is genuinely a draft and cannot be used for grading until approved.
The original manual-question endpoint keeps its prior default for old clients.
Restart the API to load this backward-compatible request option; no database
migration is needed for the option itself.

The new guide publishes rubric, answer-key and source-choice drafts together.
Source-page verification remains a separate library boundary. Original tools
retain their independent per-version approval APIs. Course-library PDFs are setup
references, never student submissions.
After approving library pages, select them as assessment defaults or question
exceptions. Existing question wording is displayed read-only; this port does
not add a question-rewording/versioning workflow.

Interrupted question creation or rubric approval is not automatically replayed.
Reload definitions to inspect persisted state before another write. Unsent drafts
are in memory, not a durable offline editor. AI rubric suggestions use the
configured existing provider; software tests mock that provider and do not
establish its accuracy, availability or cost.

## Focused marking and export

Open an assessment and follow its next-action prompt. Select a paper from the
list to bring up its question, full original page and editable instructor grade.
The paper picker and assessment index can collapse to make more room for the
work. Optional rationale, criterion edits and student details use disclosures.

Correct a name or student number in **Student details** beside the paper. Saving
identity does not discard a grade draft; changed marks still need their own save.
The next action is guidance, not a claim that an unflagged AI grade is correct.
Confidence uses the recorded final value when available and remains uncalibrated.

Choose **Export** to check each student before downloading. Blackboard CSV
withholds blocking rows; generic CSV can include incomplete/flagged records with
their report fields. Excel remains available to inspect results if preflight is
temporarily unavailable. Zero is a recorded mark, not a missing result.
Unsaved marking/foundation edits must be resolved before export.

Native sign-in returns to the new workspace. Existing password-reset emails may
still link to the original reset page, which remains functional during migration.
This phase introduces no new authentication backend or public self-registration.
