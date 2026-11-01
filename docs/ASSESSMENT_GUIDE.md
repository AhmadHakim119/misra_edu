# Source-led assessment marking guide

In the new workspace, choose an assessment → **Sources & rubric**.

1. **Sources:** tick course chapters or select source pages for the assessment.
   Continue to the marking guide; the selection is saved as a draft. Questions
   inherit these choices; source exceptions are optional.
2. **Marking guide:** see the questions, criteria and mark allocations together.
   **Edit criteria** opens one question in place of the assessment outline.
   Each criterion shows its title and marks; expand it to edit what earns credit.
   **Detailed credit & common mistakes** contains scoring, required evidence,
   credit levels, mistakes and alternative methods. **Question settings** contains
   scoring policy, retained reference fields, grading input and rubric history.
   AI suggestions, answer keys and source exceptions remain available below.
   **Back to whole guide**, switching questions, and moving into review save edits
   as drafts. Invalid or failed saves retain the edits and stop progression;
   they never approve anything.
3. **Review & approve:** inspect the saved questions, credit, solutions and source
   pages. If source drafts are selected, the review lists their exact titles and
   PDF pages; confirm and click **Approve guide and selected sources** once.
   Already-approved sources use **Approve assessment guide**.

This publishes the selected saved rubric, answer-key and source-choice drafts in
one database transaction. If any part is invalid, unavailable or changed since
review, no partial approval is committed. Refresh after an uncertain response
before trying again. New grading uses the published versions; existing grades
and immutable run snapshots are not rewritten or automatically regraded.

Source pages can be previewed against their originals. Their approval may be
included explicitly in the same guide approval; separate library approval remains
available. Ticking chapters alone never publishes them. Source fingerprints,
readable selected text, complete ingestion and file integrity are checked before
approval; corrupt, blank or unfinished sources still block the transaction. Existing
assessments without course sources remain usable; missing sources are explained,
not replaced by invented references. The rubric determines credit; source
material supplies subject context, never hidden marking requirements.

AI rubric proposals can retrieve from the guide's saved source choices, including
draft choices that point to already checked material pages. This is draft-only
authoring context. Ordinary student grading never retrieves from unapproved
assessment/source-choice drafts. Instructor-selected scoring policy is retained.

The original frontend and per-version APIs remain compatible. This replacement
is in `/app/index.html`; it does not restyle other pages. Restart the API to
load the new review/approval endpoints, then hard-refresh the browser. No new
database migration is needed beyond the previously required foundation/source
upgrades. Tests use synthetic records and mocked AI, not real marking evaluation.

## API boundary

- `GET /api/exams/{exam_id}/marking-guide`: exact saved review, checks and a
  content-bound `review_token`.
- `POST /api/exams/{exam_id}/marking-guide/approve`: token plus
  `confirm_reviewed: true`; pending source pages additionally require
  `approve_selected_sources: true`. This flag defaults to false, so older clients
  never approve source content implicitly. The content-bound review includes
  `source_approvals` with exact version/page selections and content hashes.

The token covers content rather than just version IDs, so editing an existing
draft invalidates a prior review. It is a concurrency check, not authentication.

## Removing an accidental question

In `/app/setup.html`, open **Marking guide**, select the question, then use
**Delete question** beside **Save draft**. An unsaved addition uses **Discard question**.
Cancellation and rejected deletion preserve current edits. Successful deletion updates
the guide's question count and total; review confirmation is cleared.

The DELETE API removes only unused draft questions and their draft rubric, answer-key
and source-exception rows. It rejects approved/legacy definitions, existing student
papers, saved AI suggestion/grading history and active assessment processing. Original
source material and job output are retained. No schema upgrade is needed.

## Correct an imported question number or wording

From Extraction, use **Edit question details** beside that question. In the
marking-guide editor, choose **Create editable draft** if required, correct
**Question number** and **Question students are asked**, then **Save draft**.
Question identifiers remain separate from stable database IDs and answer links.

Review and approve the whole guide to apply these corrections. Until then,
current question details and grading authority remain unchanged. Correct all
affected numbers before approval: duplicate proposed numbers are blocked, while
a consistent renumbering can be approved together. Maximum marks still have to
match criterion totals. A stale previous definition or changed review token
requires reloading and reviewing again.

The correction version keeps the previous number, wording and language; the
editor exposes **Previously used question details** and retained version history.
Historical grading packages, marks and instructor overrides are not rewritten.
Existing marked answers are flagged to compare their prior guide before another
finalization. Changing question details never remaps sources or regrades papers.

Load the updated API code before saving question-detail corrections, then refresh
the app after protecting current unsaved edits. An older API that omits the
correction now produces an explicit error and retains the edits in the browser.
No schema migration or provider call is required for manual corrections.

Future setup imports remove only exact duplicated whole stems. Similar readings
from different pages are kept as reviewable wording alternatives rather than
concatenated into a false repeated question. This does not establish extraction
accuracy or automatically repair previously imported assessments.

## Remove an extraction entry or an exam question from Extraction

Both actions are available directly in `/app/extraction.html`:

- **Remove extracted entry**, beside each mapped source, affects only that paper.
  It retains the exam question and the excluded text; any resulting missing answer
  stays unresolved, never zero. Expand **Removed extracted entries** to inspect the
  retained text. Use the original page and existing answer-area/page-recovery tools
  if evidence needs to be recovered; this is not a one-click undo operation.
- **Remove question from exam**, beside the question heading, affects all papers.
  Its confirmation shows the question, affected paper count, revised exam total
  and remaining question list. It removes the question from current expected-answer
  counts, grading and export totals, retaining its definition, sources, runs and
  instructor decisions. **Removed exam questions** offers **Restore question to
  exam** and, where available, **View saved grading history** on the same screen.

These actions do not renumber questions. Save or cancel genuine extraction edits
first. Changed previews, active processing and conflicting restore numbers are
rejected. A failed or uncertain write is not automatically replayed.

Individual entries with saved grading/review history keep their existing removal
lock. The disabled control explains that their area must be corrected and explicitly
regraded; saved grading evidence cannot be deleted. Exam-wide removal remains
available and preserves that history. Current decisions and new grading requests
for removed questions are blocked; historical evaluation labels remain separate.

Removing or restoring a question flags existing marked answers for review of the
changed exam total. It does not recalculate marks, finalize decisions or approve
pending guide/source drafts. Restoration retains prior approved rules; an originally
unapproved question remains a draft. Historical runs stay readable in History, with
new grading disabled until restoration.

Load the updated API and worker code, then refresh Extraction after protecting
unsaved edits. No schema migration, provider call or automatic academic-record
change is required to make these controls available.
