# Bounded instructor-app usability fixes — 26 October 2026

This is frontend verification using synthetic records and mocked APIs, not a
grading-accuracy result or a study with instructors. No live records, providers,
academic history, dependencies or backend contracts were changed for this task.
Pre-existing working-tree changes were retained.

## Implemented screens

1. **Marking-guide question overview.** The former 36px/24px identifier column
   crowded long identifiers beside the wording. Identifiers and marking controls
   now occupy a header; complete wording uses the next full-width row. The
   existing editor, marks and approval behavior are preserved.
2. **Extraction original-paper viewer.** Show original page now retains source
   identity, distinguishes the active saved region and reveals it without
   opening the area editor. Pending requests clear old overlays immediately.
   Missing, failed and stale locations have distinct recovery messages. Image
   failures hide the overlay and provide a read-only reload. Unsaved text survives.
3. **Grading original-paper viewer.** The same location-load failure now provides
   an explicit read-only retry, with instructor drafts preserved. Shared controls
   hide/revisit regions; expanded viewing and zoom retain the original evidence.
4. **Untouched Add question.** Opening a new form no longer marks it dirty or
   forces empty content through Save when returning to the guide. Genuine edits
   still validate and remain protected; the initial form says it is not saved.
   Opening the form also invalidates an older pending guide view, so a late
   response cannot hide the new question or its unsaved edits.

Short numeric/letter native-PDF matches (including zero and values with units)
cannot by themselves establish a student's response mark. Valid saved manual
regions take precedence over older location responses and are checked against
their source and page. Invalid geometry is rejected. Existing OCR estimates
remain explicitly approximate; AI regions remain unverified. These changes affect
display, never transcriptions or grades. They do not make localization infallible.

Location-job acceptance is reused in memory for the same paper/page/evidence
version. Existing server checkpoints remain authoritative across reloads. A failed
read of saved locations does not start inference. No inference was performed
during verification.

## Dependency review: retain, do not bulk-delete

The proposed deletion list is not a safe removal list:

- `app/workspace-template.html` and the sequential workspace loader still load
  shared `api.js`, `answer-keys.js`, `assessment-sources.js`, `course-materials.js`
  and `paper-evidence.js`. Their versioning, unsaved guards and evidence behavior
  are used by the canonical instructor app.
- `app.js` supplies theme, preferences, notifications and common UI behavior;
  `auth.js` handles authentication forms. Instructor-preference controls are shared.
- Local compatibility HTML still refers to the proposed legacy controllers and
  legacy styles. `pages/assessments.html` references Fuse's vendored script;
  `js/assessments.js` uses Fuse; `scripts/vendor-frontend.cjs` copies both its script
  and license; `package.json` retains the dependency and vendor command.
- `services/frontend_routes.py` mounts shared JS/CSS/assets. It currently redirects
  `/legacy/pages/` bookmarks to canonical routes, while AGENTS describes a separately
  available compatibility interface. This pre-existing documentation/runtime
  difference needs its own decision; no route or archive was removed here.

References were checked in canonical HTML/loaders, local compatibility HTML,
shared controllers, backend static routes, scripts and tests. Uncertain deletions
are deferred. No files or npm dependencies were deleted.

## Backlog classification and limits

| Finding | Classification / disposition |
| --- | --- |
| Identifier/text crowding | Confirmed; fixed and tested with long/short English and Arabic wording |
| Every paper has broken highlighting | Unsupported generalization; saved regions already render in existing paths |
| Lost answer identity and stale overlays in extraction | Confirmed; fixed |
| Untouched Add question trapped by empty-content validation | Confirmed; fixed beyond the pre-existing survey-only workaround |
| Saved-location failures look like missing locations | Confirmed in extraction and grading; fixed |
| Text matching a printed value proves an MCQ choice | Incorrect; guarded in display, no choice inferred |
| Manual area corrections and explicit corrected-answer regrading | Already implemented; preserved and regression-tested |
| Draft-question deletion / review reopening / unsaved grade discard | Existing capabilities; not replaced with fictional restore behavior |
| All native/legacy branches are dead | Incorrect; shared and compatibility dependencies remain |
| Archive/restore, retention, job cancellation, roster matching | Separate backend/product contracts; deferred |
| Autosave, global shortcuts, shared polling, shell consolidation | Optional changes needing their own bounded evidence and failure checks |
| API update/versioning for approved course/exam/question definitions | Separate backend contract; no historical definition mutation introduced |
| Server-side survey dismissal | Separate backend feature; existing local dismissal retained |
| Workspace loader strips script version queries | Confirmed source behavior; latency/cache consequences unmeasured, deferred |
| 30–150 paper capacity / instructor usability outcomes | Unmeasured; no capacity or participant-study claim |

Reliable automatic selection-mark localization still requires suitable saved
server evidence distinguishing response ink from the printed option block. When
it is absent, the interface shows recovery rather than a fabricated rectangle.
No new model, localization service or provider experiment was added.
The supplied screenshot does not expose its saved location payload. No live paper
was inspected, so the precise missing-data cause for that particular record remains
unverified; the reproducible frontend failures above were checked synthetically.

## Verification evidence

Files touched for this task: `app/guide.css`, `app/guide.js`, `app/editors.js`,
`app/extraction.js`, `app/paper-highlights.js`, `app/ledger.css`, `app/ledger.js`,
`app/locale.js` and shared `js/paper-evidence.js` under `misra-frontend/`;
`tests/e2e/ledger-editors.spec.js`, `tests/e2e/ledger.spec.js` and the new
`tests/e2e/extraction-locations.spec.js`; this report and private screen briefs.
Pre-existing edits in some of these files were preserved.

Private briefs, actual before/after synthetic screenshots and command logs are in
Git-ignored `.impeccable/review/usability-20261026/`. Screens include desktop
1280×720 and Pixel 7; light/dark; English/Arabic and LTR/RTL.

Regression coverage includes zero, repeated printed values, two answers on one
page, multi-page work, missing/invalid/stale locations, late responses, saved
manual revisions, image/load failures, keyboard selection, zoom/expanded viewing,
unsaved text/marks, failed confirmations, required review acknowledgement and
stale-save conflicts. No new backend test was required by a backend change.

The final `npm run test:e2e` run, including the retry-focus and delayed-guide fixes,
passed **399 tests with 1 intentional mobile skip** (the desktop-only composition
check). An earlier focused extraction/grading run passed **77 tests with the same
1 skip**. JavaScript syntax,
`git diff --check` and the guide layout scan passed. One survey-return failure in
an earlier full run did not recur in targeted rechecks or the final full run; its
cause was not established and no survey-behavior fix is claimed.

Exact final command results are recorded in the private verification summary and
the task handoff. Human usability, manual screen-reader use, provider accuracy and
150-paper throughput remain untested. No migration or service restart is needed;
refresh the app after protecting any unsaved edits to load frontend changes.

## Complete extraction workspace and spacing follow-up

Ungraded paper actions now open the existing complete extraction editor. The
grading inspector remains the place for marks and recorded decisions; its
correction links carry the selected question and source into Extraction.
The existing full grading history and compatibility pages remain available.

Extraction now has a question selector, previous/next question controls and a
position count. All question forms remain on the same page, including multi-page
answers and questions without mapped evidence. Moving between questions keeps
text drafts; missing evidence clears the previous highlight.

The extraction layout uses scoped 8/16/24 spacing, a compact readiness/action
group, a wider original-paper pane and a mobile Back to answer control. Explicit
Show original page / Show selected answer area actions reveal the viewer as well
as its selected region. The active outline has a question/part label. Selecting
an answer area remains a separate correction operation; location does not verify
transcription or marks. Missing/invalid locations still require inspection or a
manual answer-area selection.

Shared navigation now uses View & grade consistently. Arabic application labels
were added for the new controls; original question text and answers remain
verbatim. No grading rule, source approval, API contract or saved grade changed.

Current synthetic before/after captures, screen briefs, navigation/visible-region
checks and final browser log are private under
`.impeccable/review/extraction-flow-20261026/`. The original verification totals
above describe the earlier iteration; consult that directory's RESULTS.md for
the follow-up's actual test results. No migration or service restart is needed.
