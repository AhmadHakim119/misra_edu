# Teaching material to class feedback

The new instructor workspace supports a connected teaching cycle at
`/app/next/index.html`:

1. Create/select a course assessment. In **Sources & rubric → Sources**, add
   lecture slides, notes or textbook chapters to the course library. The multi-file
   control accepts up to 25 PDFs / 100 MB per selection, sending each file through
   the existing validated material-upload endpoint. Each becomes a separate draft
   with its own background reading job. These are not student submissions.
2. Check the extracted content against the original, especially equations. Approve
   only checked pages in the existing course-library reviewer. Scans without text
   still need transcription; this change does not create a new OCR provider.
3. Choose the checked material taught for this assessment. **Use all currently
   approved course materials** copies the latest current approved version/page
   selections into an editable assessment-source draft, up to 64 materials. New
   uploads/approvals are never silently added to a published assessment. Detailed
   page adjustments remain optional; students never choose the retrieval scope.
4. Optionally open **Ask AI to draft a quiz from your teaching material**. Select
   lecture(s), topic, language, difficulty and marks. Request 1–5 proposals at a
   time. Existing free-model generation jobs, source checks and persisted setup
   records are reused. Review/edit questions, proposed solutions, marks and exact
   source quotations; add selected questions as drafts. This is not approval.
   Alternatively, **Use an existing quiz or exam instead** imports its questions
   and optional key without generating replacement questions. Neither route creates
   student submissions. Saved requests survive leaving/reloading the page.
5. Review and approve the whole marking guide once. Existing per-question source
   exceptions are retained. Student upload remains gated by approved definitions.
6. Upload papers, inspect extraction and grade through the existing worker flow.
   Required-source retrieval searches only approved selected pages, using question
   and criterion text—not student text—to select bounded BM25 passages. Exact
   passage links remain supported. No whole book is stuffed into a provider prompt.
7. For every criterion in a **required-source** run, a valid applicable course
   citation is mandatory alongside student-evidence citations. A key citation
   alone does not establish lecture grounding. Missing applicable context stops
   before inference; missing/invalid citations get one bounded correction, then
   fail without saving that answer's grade. Prompt v7 preserves approved policy
   and marks during citation correction. Existing grades are not rewritten.
8. In each criterion row, open **Lecture evidence & student references** to read
   the saved passage, material version and document page, follow its original
   source link, and identify the inspected student page/segment. Historical runs
   without citations are labeled rather than retroactively called grounded.
9. **Class feedback** summarizes recorded question percentages and full/partial/
   zero-credit observations per criterion and saved rubric version, including cited
   teaching pages and pending review counts. Ungraded work is not counted as zero;
   external practical work is excluded. Total-only overrides are excluded from
   criterion observations instead of inventing instructor criterion allocations.

## Boundaries and uncertainty

RAG retrieves academic evidence before inference; a prompt still specifies how
the model must use approved evidence and output the validated contract. Correct
citation IDs are not proof that a passage supports a deduction. Instructor review
remains necessary for semantic support, ambiguous handwriting and key/source
conflicts. Source material cannot invent marking requirements or silently override
the approved rubric/policy/key.

The retrieval baseline is bounded lexical BM25, not a newly installed embedding
or reranking model. Confidence remains an **uncalibrated estimate**; citation
counts and lexical relevance are not probabilities of grade correctness. True
calibration/accuracy improvement needs independent instructor-labelled answers.
Class feedback describes the recorded grades, not proven student misconceptions.

No new schema migration or dependency is introduced by this connected-flow change.
Previously required foundations/source upgrades must be installed. Restart the API
and worker, then hard-refresh the new workspace. Synthetic tests validate software
behavior, not accuracy on actual physics papers. No private paper uploads or live
model calls are part of those tests.

## API additions / compatibility

- `GET /api/exams/{exam_id}/learning-insights`: authenticated, institution-owned
  descriptive feedback from existing answers and immutable package snapshots.
- Assessment and question source scopes accept up to 64 explicit bindings.
- Source-question generation accepts up to 64 materials; generation count and
  retrieval budgets remain bounded. Draft/approval boundaries are unchanged.
- Existing endpoints and original frontend are retained. No automatic assessment
  publication, regrading or claims of error-free autonomous marking are added.
