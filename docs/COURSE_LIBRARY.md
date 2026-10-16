# Course books and assessment chapter selection

## Separate chapter PDFs

Chapter choices can be saved before source-page review. The selection is a draft:
use **Review source pages** beside a chapter to open its actual document and text.
Unchecked sources cannot be published with the guide or retrieved for grading.
Saving with no changes is disabled; successful saves report the selected chapter
count and whether source review remains. This uses the existing assessment-source
draft records and requires no database upgrade.

Files named `Chapter_7-Walker_Physics.pdf` are already divided: one checkbox
selects all pages in the file, labelled Chapter 7 and sorted by chapter number.
Exercise numbers and review headings inside a chapter PDF cannot rename or split
it. Whole-book PDFs still offer detected boundaries for instructor checking.
Explicitly saved chapter boundaries take precedence; saved source scopes and
historical grades are never rewritten. Source text still needs explicit approval.

Open `/app/course-library.html` or choose **Course library** in the native
navigation. Select the course to see its existing uploaded materials. Do not
upload those chapters again; they are already course-owned.

## Instructor flow

1. Add the whole book, individual chapter PDFs, teaching notes or PowerPoint
   `.pptx` decks to the course library once. The upload selection supports up to
   25 files/100 MB in total, with the existing per-file server limits retained.
   PDFs/decks may contain up to 1,000 pages/slides by default.
2. For PDF scans, **Read scanned pages with the extraction service** uses the
   configured extraction provider only on pages without native text. Reading is
   a durable background job; completed draft-page transcriptions are reused on
   retry. For already uploaded draft PDFs, choose **Read scanned pages** in the
   saved library. Approved versions are never re-read or rewritten.
3. Native/OCR chapter headings propose page ranges. English `Chapter`/`Unit`,
   Arabic `الفصل`/`الوحدة`, split headings and repeated running headers are handled.
   Multiple chapter entries on a contents page are excluded. These are proposals:
   review titles and boundaries against the original and save corrected ranges.
   If headings cannot be identified, the document is shown as one section; use
   **Add chapter** to define its actual ranges. PDF positions start at 1 and may
   differ from printed page labels.
4. Review/correct the extracted source pages and explicitly approve the pages
   you checked. Checking chapter boundaries does **not** approve source text.
   PowerPoint reading preserves slide order and reads slide text locally. Images,
   charts and equations need checking in the original deck and, where necessary,
   instructor transcription or a PDF export. Binary `.ppt` is not accepted.
5. Open an assessment’s **Rubric → Sources**. Tick the chapters it covers: for
   example, Quiz 1 selects Chapters 1 and 2, while Quiz 2 selects Chapter 3.
   All questions inherit that quiz’s approved selection; existing question
   exceptions still take precedence. Every page in a selected chapter must be
   approved before guide publication. Draft chapter selections may include pages
   awaiting review. Partial existing page selections use an indeterminate box.
6. Optionally add extra PDF/PPTX material in **Add extra material for this
   assessment**. These files appear only in this assessment’s library view and
   cannot be selected for grading or question generation in another assessment.
7. Save the chapter-selection draft and review/approve the entire marking guide.
   BM25 searches bounded passages within these selected, approved pages. Student
   answers cannot choose chapters or change the retrieval scope.

## Marking survey

The native dashboard offers **Start marking survey** when the instructor has no
approved profile. **Do this later** defers the invitation for that browser session;
Settings also links to the questionnaire. Twelve scenarios cover alternative methods,
handwritten syntax, equivalent notation, carried-forward errors, language quality,
arithmetic errors, missing units, rounding, required working, illegible handwriting,
incomplete solutions and contradictory answers. Partial drafts may be saved; the
native questionnaire requires all twelve answers before approval. Earlier approved
profiles remain unchanged and can seed a new expanded draft.

Answers are stored in the existing instructor preference-version table, scoped to
the instructor and institution. Saving a draft and approving a profile are explicit
actions. Approved preferences fill new native guide drafts by default, including
imported exams. Settings has a saved opt-out; existing drafts keep their rules.
The instructor still reviews and approves the whole guide before grading.
See [Account settings](ACCOUNT_SETTINGS.md) for completion, opt-out and account removal.
This is a record of academic preferences, not a validated personality assessment.
It never changes approved rubrics, original runs or instructor overrides by itself.

## Additive database step

Two new tables store reviewed chapter-index revisions and assessment attachment
ownership: `material_chapter_indexes` and `assessment_material_attachments`.
The tested upgrade only creates missing tables. It does not modify existing source
text, books, assessments, policies or grades. It requires the existing course-material
tables. Back up the database before running it, from `misra_backend/`:

```powershell
..\misra_ocr_env\Scripts\python.exe scripts\upgrade_material_library.py
```

The instructor explicitly authorized backup and upgrade on 14 October 2026. The
local database was backed up before creating these two tables; the dump completion
marker and SHA-256 were checked. Existing assessment/source/grade row counts were
unchanged, and both tables were verified. The private dump and manifest are in the
Git-ignored `.impeccable/review/database-backups/` directory. No restore test was run.

The API is serving the updated routes. The verified idle worker was gracefully
stopped and replaced with the updated worker, running in the background with
private logs under `.impeccable/review/material-library-worker-20261014T173211.*.log`.
The queue and database had no pending jobs during restart. Hard-refresh the browser
to load the updated interface. For another installation, back up first, apply the
script, then restart its API and worker. Before installation, source files remain
visible but saving chapter indexes/attachments returns an actionable 503.

## Verification boundaries

Synthetic tests cover a 500-page book with ten chapter ranges, per-quiz selections,
stale/overlapping metadata, original approved-content hashes, extra-file isolation,
OCR resume after interruption, real FastAPI upload/creation contracts, PowerPoint
package validation, stored survey choices and rejected-save retention. Browser
captures use synthetic records only, in desktop/mobile light/dark/RTL states.

No real book OCR, provider throughput benchmark, grading accuracy measurement or
BM25 benefit experiment was performed. Chapter detection still requires review;
valid source IDs and software tests do not establish semantic grading accuracy.

Verification on 14 October 2026: full backend **306 passed**; full browser
**397 passed, 3 viewport-specific skips**. Final library integrity checks:
**12 passed**; final native library/survey browser checks: **18 passed**. These
runs overlap and their counts must not be added. JavaScript syntax and
`git diff --check` passed. The authorized local upgrade and worker restart were
completed; the running API, queue and new tables were verified without inference.
