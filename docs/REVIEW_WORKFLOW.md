# Review routing, correction and instructor context

## Instructor workflow

- **Course library → Open original PDF** opens a saved source independently of
  text review. The embedded reviewer permits same-origin framing only for a
  successful source-PDF response; account and institution checks still apply.
  Other pages, non-PDF responses and errors retain framing protection. Switching
  courses remounts the reader and ignores delayed chapter-index responses. Failed
  loads can be retried without showing another course's files; unsaved edits can
  cancel switching. Approved content remains immutable.
- **Dashboard → Review concerns** previews the stated reason and the next check.
  **Review** opens the complete queue. **AI grading** shows the saved rationale,
  affected criterion, evidence references, original page and instructor controls.
- A deduction on reported uncertain work is a review gate even at 100 model
  confidence. Existing gates cover extraction, missing verification, criterion
  conflicts, numerical checks, policy conflicts and corrected extraction.
  These checks request review; they never award extra marks.
- A flagged answer requires an explicit evidence-check acknowledgement in the
  browser before saving an instructor decision. This is an interaction guard,
  not proof of human attention or a new model-accuracy measurement.
- **Reopen saved decision for review** retains the old mark, notes and immutable
  labels, records an audit event and returns the answer to pending review. It
  rejects a stale displayed run/label/decision and active paper processing.
  Reopening reasons appear in History's saved review actions. Operational audit
  events follow the existing audit-retention setting; immutable grade labels and
  grading snapshots retain their separate history.
- **Sources & rubric → Review & approve → Reopen guide for corrections**
  preserves the approved snapshots and prefills correction drafts. It retains
  any already saved draft. New grading requires approval again. Existing affected
  grades return to review without recalculation; overrides and original runs stay
  intact. Active assessment processing and stale guide tokens block reopening.
- **Exams → Saved pilot studies → Physics pilot** exposes the 68 saved booklets,
  2,105 answer slots and 748 complete-page images. Individual rubric links open
  the ordinary versioned editor. The archive shows original proposals, local
  adjustments, unresolved ranges, source evidence and saved review concerns.
  It is a read-only study archive, not imported instructor-final grades. Original
  marked pages are private instructor evidence; no new inference uses them.
  Multiple-choice caps remain reflected in saved totals.
- Saved-pilot exam rows show their own archived-paper/review counts and open
  **Review saved papers** for that exam. The Review queue lists saved paper
  concerns separately from live answer decisions. Failed discovery is shown as
  unavailable, never as a measured zero; source records are not imported as
  artificial finalized grades.

## Answer-location display

Native PDF text matches and versioned instructor-confirmed areas take priority.
Coarse vision-grid boxes receive a bounded local vertical ink-extent check when
displayed. The check can expand a clipped intersecting ink band; it suppresses
blank, invalid or search-edge-clipped estimates rather than moving a box to a
different nearby answer. Ruled lines alone do not establish an answer region.
Unversioned device-only rectangle overrides are no longer used.

The check preserves the provider's original coordinates and every extraction,
grading run and instructor correction. It makes no provider call. It does not
verify the answer's semantic identity or horizontal placement and cannot promise
correct boxes for all handwriting; inspect the complete page and correct the area
in Extraction when required. Multiline/aspect-ratio/zoom and paper/question-change
regressions check software behavior, not OCR or grading accuracy.

## Metrics

**Exact grade agreement remains the headline.** Evaluation also shows errors
caught, errors missed, disagreement recall, review workload, disagreement among
unflagged answers, and matching grades that were flagged. The comparison uses
frozen review-flag snapshots and the latest labelled observation per answer;
missing flags are unknown, not successful unflagged grades.

Instructor-labelled review usefulness is separate: its precision/recall uses
the instructor's `was_review_warranted` decision. A matching total can still
need review for faulty evidence or reasoning. Criterion comparisons require
both human and AI criterion labels and remain separated by question and rubric
version. The local JSON download retains the underlying labelled observations.

These changes add observable routing safeguards, not empirical accuracy results.
No fresh model runs were made. Confidence estimates and operational thresholds
remain uncalibrated; a confidently wrong response with no detectable conflict can
still escape the checks. The original small DeepSeek/MiniMax comparisons remain
unchanged. Offline scorecards, criterion error analysis and risk/coverage curves
are documented in [the evaluation workflow](../evaluation/README.md).

## Persistent instructor profile

**Settings → Marking preferences / survey** now includes subjects, course level,
usual marking style, question types and notes about questions, partial credit and
rubric style. The existing twelve scenarios still specify concrete marking rules.
Drafts, explicit approval and version history reuse the existing profile store.
Question types are labelled checkboxes mapped to the validated API identifiers.
Save errors identify rejected fields while retaining all scenario answers and
teaching notes. The form checks subject limits before sending a save request.
Other question types can have an optional description. A separate saved exam
language preference supports English, Arabic and mixed-language exams; explicit
exam settings take precedence. Arabic interface mode translates profile controls,
options and help without translating instructor-written notes or changing the
saved exam-language preference. Switching interface languages retains unsaved
scenario answers and profile edits. Approved profiles remain read-only; use
**Create new draft** to update them without answering the twelve scenarios again.

Approved context is reused for question/rubric suggestions when automatic
preferences are enabled. New manual guide drafts retain the existing approved
marking-default application. Question-generation requests freeze the exact profile
version/content hash alongside their source package, so a later profile edit does
not change a retry. Rubric suggestions record the profile version/hash in their
draft history. Explicit request settings, approved sources and assessment rules
take precedence. Broad leniency is not a score uplift. Existing approved guides
and historical grades never inherit a newly edited profile automatically.

Profiles are owned by one account and institution. Only approved, opted-in,
bounded teaching preferences enter design prompts; account identifiers remain
local. Student papers, OCR errors and raw grades are not automatically memorized.
Do not put student records into the profile's free-text teaching notes.

## Local operation and checks

Setup imports checkpoint each successfully validated exam/key page. Retrying an
existing failed import skips those pages; an invalid or failed page is not saved
as completed. Temporary OpenRouter 500/502/503/504 errors get at most three
attempts for the identical free-model request, waiting 2 and then 4 seconds.
Authentication, credit and quota errors are not immediately retried by this
transport handler. The existing queued-job retry limit still applies afterward;
these bounds do not guarantee provider availability or sufficient daily quota.

The setup reader supplies its JSON schema and permits one same-page format
repair if the response fails validation. Missing question text is never silently
dropped or filled from a student's solution, and unknown marks remain unknown.
Unusable responses do not approve or import questions. Error messages and repair
prompts contain validation field names/types, not the invalid response content.
Restart the RQ worker to load these changes, then use **Activity → Retry safely**
on the existing failed setup request instead of uploading the documents again.

No new dependencies or database migration are required. Restart the API after
updating backend code; restart workers before using the revised grading checks.
Chapter selection now uses one approval flow: tick chapters, continue to the
marking guide, then confirm **Approve guide and selected sources**. Continuing
saves the selection draft. The final review lists exact source titles/pages and
fingerprints their content; that single explicit action approves their readable
source drafts, reference scopes, keys and criteria atomically. Merely ticking a
chapter publishes nothing. Unfinished ingestion, blank selected text, changed
files, stale reviews and cross-course references block publication. A late
failure rolls back every source and guide approval. Existing separate library
approval remains available, and old API clients must opt in with
`approve_selected_sources: true` to include pending source pages.
For completed exam/key imports, **Add selected questions to the marking guide**
now identifies missing fields, opens a collapsed invalid field and focuses it.
Select **Multiple choice** for an MCQ: a separate written guide may stay empty
when its reference answer is recorded. An empty mark value starts at an editable
1 mark on selection; existing values are retained. The saved draft then uses a
binary correct-option criterion. Written answers still require a marking guide,
and every question still needs positive marks. Failed saves preserve edits and
excluded rows; pending confirmation is locked against duplicate submission.
These are draft-authoring changes, not approval or regrading of existing work.
Restart the API and refresh the page to use them; recover the completed request
through **Check saved quiz requests** rather than running extraction again.
An imported question's **Total marks** can also be corrected in its editable
rubric draft without deleting the question. Criteria must add up to that draft
total. Whole-guide review displays the proposed total and warns when it differs
from the current question total; the additive `current_max_score` field retains
the latter for comparison. Saving/reviewing the draft does not change the current
total. Explicit whole-guide approval applies it through the existing version
approval service, preserves prior runs and marks, and flags existing proposals
for renewed review. Approved/current definitions still require matching totals
in grading preflight; this is not a relaxation of grading validation.
Opening the profile, review queue and saved-pilot archive starts no inference.
Live extraction/grading viewers retain their existing automatic answer-location
jobs, which can use the configured OCR provider when no location is available;
the local geometry check itself starts no jobs and never regrades an answer.

```powershell
# From misra_backend, using the project's Python environment:
$env:DB_URL = 'sqlite:///:memory:'
..\misra_ocr_env\Scripts\python.exe -m unittest tests.test_review_workflow tests.test_assessment_guide tests.test_source_question_drafts
..\misra_ocr_env\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
# From the repository root:
npm run test:e2e
```

Tests use synthetic fixtures, isolated databases and mocked providers. On Windows,
the test process needs local socket-pair permission. Real archives remain under
ignored `misra_backend/storage/pilot_archives/`; original study files remain in
ignored `private/`. Archive routes require instructor authentication and matching
institution/exam ownership, verify file hashes and reject traversal. Recovery
writes use the existing session/CSRF boundary and audit trail. This is a scoped
security review, not a production security certification.
