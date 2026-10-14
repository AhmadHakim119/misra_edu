# Source-led assessment marking guide

In the new workspace, choose an assessment → **Sources & rubric**.

1. **Sources:** add/check course material and select its approved pages once for
   the assessment. Questions inherit these choices; source exceptions are optional.
2. **Marking guide:** see all questions together. Open **Edit details** only to
   change criteria, partial credit, scoring rules, solutions or source exceptions.
   Moving between questions or into review saves edits as drafts. Invalid or failed
   saves retain the edits and stop progression; they never approve anything.
3. **Review & approve:** inspect the saved questions, credit, solutions and source
   pages. Confirm review and click **Approve assessment guide** once.

This publishes the selected saved rubric, answer-key and source-choice drafts in
one database transaction. If any part is invalid, unavailable or changed since
review, no partial approval is committed. Refresh after an uncertain response
before trying again. New grading uses the published versions; existing grades
and immutable run snapshots are not rewritten or automatically regraded.

Course material pages still require checking against their originals. Whole-guide
approval cannot make unread or corrupt source pages trustworthy. Existing
assessments without course sources remain usable; missing sources are explained,
not replaced by invented references. The rubric determines credit; source
material supplies subject context, never hidden marking requirements.

AI rubric proposals can retrieve from the guide's saved source choices, including
draft choices that point to already checked material pages. This is draft-only
authoring context. Ordinary student grading never retrieves from unapproved
assessment/source-choice drafts. Instructor-selected scoring policy is retained.

The original frontend and per-version APIs remain compatible. This replacement
is in `/app/next/index.html`; it does not restyle other pages. Restart the API to
load the new review/approval endpoints, then hard-refresh the browser. No new
database migration is needed beyond the previously required foundation/source
upgrades. Tests use synthetic records and mocked AI, not real marking evaluation.

## API boundary

- `GET /api/exams/{exam_id}/marking-guide`: exact saved review, checks and a
  content-bound `review_token`.
- `POST /api/exams/{exam_id}/marking-guide/approve`: token plus
  `confirm_reviewed: true`; one institution-authorized atomic publication.

The token covers content rather than just version IDs, so editing an existing
draft invalidates a prior review. It is a concurrency check, not authentication.
