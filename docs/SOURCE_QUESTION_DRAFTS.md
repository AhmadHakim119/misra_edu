# Questions from approved course material

This extends assessment setup, not student submissions. An instructor can ask for
questions, proposed solutions and marking criteria from already-approved textbook
pages or teaching notes. Generation uses the explicit free-only OpenRouter gateway;
it does not use a paid endpoint or fall back to Gemini.

## Instructor workflow

1. Open Rubric Studio and select an assessment.
2. Open **Create questions from course material → Manage course library**.
   An empty assessment can use the library without creating a dummy question.
3. Add a PDF or typed notes. Review/correct their text and approve selected pages,
   including equations and symbols. Scanned PDFs still need transcription.
4. Choose an approved version, document page positions, topic/learning objective,
   language, difficulty, 1–5 questions and marks per question.
5. Request generation. Selected approved passages are sent to the configured free
   provider. A saved setup job allows navigation, reload, retries and later review.
6. Review proposals, quoted source evidence, suggested solutions and marking guides.
   Edit, renumber or exclude proposals before adding them.
7. Adding proposals creates **draft** questions/rubrics, separate draft answer keys
   and draft required-source scopes. Review and approve each grading foundation in
   Rubric Studio before uploading/grading student work.

Generating and importing do not approve source scopes, rubrics or answer keys.
Generated text never replaces existing questions with colliding numbers. Repeated
confirmation is idempotent. Current unsaved grading-foundation edits are protected.

## Retrieval and validation

The source package pins approved material versions and pages in the assessment's
course and institution. Relevant whole passages are ranked with BM25 from the
instructor's topic—not student answers. Exact passage selections are supported by
the API. The budget is at most eight passages and 12,000 characters, with at most
6,000 candidates; passages/equations are not truncated to fit. Narrow a selection
if it exceeds the budget or has no relevant matches.

The provider must return the requested question count, self-contained question
text, a suggested solution or explicit no-fixed-answer mode, marking criteria
whose totals match the requested marks, and source citations for both questions
and criteria. The backend rejects unknown IDs, invented quotations, duplicate
questions, non-finite scores and invalid totals. Quotes must occur verbatim in the
selected passage. Marks per question use at most two decimal places.

**A matching quotation does not prove academic correctness.** It validates that
the cited excerpt exists; it cannot establish that a proposed calculation, teaching
objective, solution, difficulty or interpretation is correct. Instructor review
remains mandatory. Question wording and marks must fit the actual assessment.

## Persistence and boundaries

The existing `exam_setup` job type is reused with purpose `course_source_questions`.
No new database table or job enum is required specifically for this feature.
Course-material and grading-foundation upgrades must already be installed.

Jobs retain request parameters, retrieved source content/hashes, parser/material
version provenance, generation metadata, original proposal snapshots and a mapping
from each imported draft ID to its question and instructor-reviewed snapshot.
Sources are revalidated during execution and confirmation. Retrying cannot silently
generate from changed approved content. Successfully saved proposals are reused
without another inference call; tampered snapshots are rejected.

If instructors change the marking guide or total before import, their reviewed
guide is used rather than silently restoring model criteria. Unchanged proposals
retain their granular suggested criteria. All results remain drafts.

## Provider setup and limitations

Use the private backend `.env` with `OPENROUTER_API_KEY` and an explicit `:free`
`OPENROUTER_GRADING_MODEL`. Do not commit the real key. Generation always uses the
free-only gateway regardless of the normal grading provider. Current catalog
pricing must verify as zero before inference; unavailable, truncated or invalid
responses fail without paid or model fallback. Free capacity is not guaranteed.

This implementation uses reviewed text, not arbitrary figure retrieval or a local
vision model. Generated questions must not depend on missing diagrams/data.
Arabic/mixed-language accuracy, formula correctness, question quality and empirical
grading agreement require instructor evaluation; deterministic tests do not prove
those outcomes. No live private-source experiment was run during implementation.
