# Native instructor workflow

Open `/app/index.html` on the MISRA API. It opens the native dashboard.
An existing `index.html?exam_id=…` link still opens the shared marking workspace.
The main instructor app lives in `misra-frontend/app/` and is served at `/app/`.
The server root opens the public landing page, with links into this app.
The retired HTML interface is no longer distributed. Known `/legacy/pages/` and
`/app/pages/` bookmarks redirect to their current equivalents; old paper `id`
parameters become `submission_id`. Old `/app/next/` bookmarks also redirect to the
main app. Shared controllers and original assets are retained. No data migration
is needed. Browser regression tests target the current app; retired page-specific
tests are kept only in the ignored local archive.

## Public introduction and review conveniences — 16 October 2026

- `/` serves `app/landing.html`: the existing logo, a synthetic grading example,
  instructor workflow, three AI roles and a secondary thesis section. App and sign-in
  links open the canonical interface. English/Arabic and light/dark preferences persist
  on the device; content and native links remain usable without JavaScript.
- Navbar account controls align at the opposite end from navigation in both directions.
- Answer-area localization runs automatically after extraction for new individual and
  batch uploads. Complete native PDF text matches need no extra model call; scans use
  the configured extraction provider and a numbered coordinate grid. Page results are
  checkpointed in the current extraction job, separately from OCR evidence and grades.
- Existing papers automatically request any missing page location when opened. Matching
  pending, completed, unlocated and failed attempts are reused, so refreshing cannot
  repeatedly launch new inference. Other active paper work finishes first. GET requests
  remain read-only; the browser uses an authenticated CSRF-protected POST to ensure work.
- **Extraction → Select answer area** lets the instructor draw or adjust a rectangle,
  read the selected area, review/edit its transcription, and confirm that it contains
  the complete answer for that mapped part. Saving creates an immutable correction
  revision in the existing processing-job store; original OCR and previous runs stay
  intact. Pending previews can be reopened after refresh without reading again.
- **View & grade** displays answer regions and links back to Extraction for editing.
  After a saved correction, **Regrade corrected answer** explicitly requests one new
  answer proposal. It uses reviewed text, the selected crop, full original mapped
  pages, approved rubric/key/policy and bounded course evidence. Assessment and
  verification receive the same images. Existing instructor grades are retained;
  the new proposal needs a fresh instructor decision before export. Regrading is
  answer-specific, request-idempotent and checkpointed to preserve earlier runs.
- AI completion cannot overwrite an active manual draft or a confirmed server revision.
  Unsaved changes block navigation/grading; failed saves keep the edited transcription.
  A highlight is an evidence location, not proof of a correct extraction or grade.
- Localization failure leaves extraction saved and offers manual selection. Per-page
  fingerprints reject stale results. Retry checkpoints are committed with extracted
  sources, preventing another OCR pass after a worker interruption during localization.
  No database or enum upgrade is needed. Vision areas remain estimates for review.
- **Discard changes** restores the loaded instructor decision without an API write.
  Saved instructor notes are shown when the decision is reopened.

Verification: full backend discovery **337 passed**; full browser suite **507 passed,
3 viewport-specific skips**. After final landing copy/accessibility fixes, its targeted
suite passed **8 tests**. JavaScript syntax and `git diff --check` passed. Browser
fixtures were synthetic and providers mocked; no grading-accuracy claim follows.
Private captures cover desktop/mobile, English/Arabic and both themes. The live root
returned HTTP 200 with the original logo and canonical app link. No database migration,
worker restart, live inference, commit or push was performed for these UI changes.

## Pages

| Route under `/app/` | Purpose |
| --- | --- |
| `dashboard.html` | Real exams, paper/review counts, active-job count and recent activity |
| `assessments.html` | Create courses/exams and duplicate existing exams |
| `setup.html?exam_id=…` | Questions, answer keys, criterion rubrics, optional checked sources, imports, explicit guide approval |
| `upload.html?exam_id=…` | Single or batch uploads and persisted extraction progress |
| `extraction.html?exam_id=…&submission_id=…` | Original pages, transcription corrections, mapping, unmatched fragments, student identity and signed page recovery |
| `grading.html?exam_id=…&submission_id=…` | Handwritten evidence, criterion marks, explanations, verifier findings and instructor decisions |
| `reviews.html?exam_id=…` | Flagged-answer queue with direct links to the corresponding question |
| `history.html?exam_id=…&submission_id=…` | Saved AI run comparison and every retained instructor decision; explicit new-run action |
| `feedback.html?exam_id=…` | Recorded class feedback and criterion observations |
| `results.html?exam_id=…` | Recorded grades, review/identity exclusions and CSV/Excel exports |
| `identities.html?exam_id=…` | Resolve missing names and numbers without discarding other pending entries |
| `activity.html` | The latest 20 eligible persisted jobs, refresh and permitted retries |
| `evaluation.html?exam_id=…` | Recorded review-label agreement, sample limitations and JSON download |
| `account.html` | Saved marking defaults, appearance, security, AI status and account deletion |
| `admin.html` | Institution instructor accounts, service health, recovery and audit records |
| `course-library.html?course_id=…` | Course-wide books/chapters, page checks and reviewed chapter ranges; optional `exam_id` includes that assessment’s extra files |
| `marking-survey.html` | Saved instructor grading scenarios and explicit profile approval |

Course books are uploaded once. Assessments select chapters with checkboxes and
may add their own PDF/PPTX files. See [Course library and marking survey](COURSE_LIBRARY.md)
for the workflow, tested additive upgrade and scan-reading boundaries.

All instructor navigation stays in `/app/`. Essential existing controllers
and backend APIs are reused. The focused setup/upload/grading/feedback/results entry
points mount one shared `workspace-template.html`; `workspace-navigation.js` handles
page transitions with the existing unsaved-state guards. `app-shell.js` shares
navigation, guarded mutations and session state across the other native pages.

English/Arabic controls share `locale.js`; selecting Arabic sets `lang=ar` and RTL.
Saved question wording, original images, student evidence and instructor text remain
verbatim. Provider/server diagnostic messages and some specialist explanatory text
remain English. Light/near-black themes use the existing Figtree/teal ledger tokens.

## Three bounded AI roles

1. **Extraction** reads complete paper pages, identifies student information, maps
   answer fragments and exposes uncertainties for instructor correction.
2. **Assessment** receives a versioned grading package: question, approved rubric,
   answer key, scoring policies, student evidence, and applicable approved passages
   retrieved by bounded BM25. Image-based grading also receives original pages.
3. **Verification** makes a separate inference call over the same projected package,
   proposed criterion marks and relevant images. It checks every criterion and can
   require instructor review. It cannot change marks, fetch new evidence, approve
   drafts or finalize grades. Invalid/missing verifier output prevents saving a new
   proposal; historical grades remain intact.

Verification results and provider metadata are stored in existing JSON snapshots;
there is no migration for these additions. This second AI check is not independent
human ground truth. Two calls to the same model can share the same error.

Instructor acceptance/adjustment remains the final decision. A later AI run retains
earlier runs and instructor overrides. No exam-wide auto-approval was introduced.
Required-source grading still fails without applicable course evidence/citations.

## Configured mixed-provider profile

The local, ignored `misra_backend/.env` now selects this profile, as requested:

```dotenv
MISRA_AI_PROVIDER=openrouter_free
OCR_PROVIDER=gemini
SETUP_PROVIDER=openrouter_free
GRADING_PROVIDER=openrouter_free
VERIFICATION_PROVIDER=openrouter_free
SETUP_MODEL=qwen/qwen3.8-27b:free
GRADING_MODEL=qwen/qwen3.8-27b:free
VERIFICATION_MODEL=qwen/qwen3.8-27b:free
VERIFICATION_ENABLED=true
```

Existing credentials were preserved. No credentials are stored in this document or
the frontend. Gemini uses the existing `gemini-2.5-flash` extraction default.
OpenRouter lists the explicit [Qwen free vision endpoint](https://openrouter.ai/qwen/qwen3.8-27b:free)
as free and image-capable when checked on 14 October 2026. Its capacity/rate limits
are external constraints. The gateway verifies current zero pricing and image
support before sending inference, rejects paid/router models, and has no automatic
paid or cross-provider fallback. Gemini account quota/billing is separate.

Restart **both API and RQ worker** to load these settings and code changes. No
restart or model inference was performed as part of this implementation. Settings
reports configured providers, not proof that a model is reachable or accurate.

## Optional local inference

The adapter accepts an installed vision model through a loopback OpenAI-compatible
endpoint, such as `http://127.0.0.1:11434/v1`. Set the desired task providers to
`local`, replace their task-specific `*_MODEL` overrides with the installed model
name (or remove those overrides and set `LOCAL_AI_MODEL`), and set
`LOCAL_AI_VISION=true` only for a vision-capable model. Images are retained, never
silently replaced by text. Unsupported inputs, remote URLs, truncated responses
and model mismatches fail closed. No model download or hardware benchmark was run.

## Integrity and validation

- Transcription corrections use optimistic `expected_text` checks, retain the
  original extracted text, reject already graded evidence and active jobs, and
  leave other unsaved forms intact.
- Page recovery previews are tied to the selected original page. Changing the
  page clears the preview; applying recovery requires a fresh valid preview.
- Results/review/history responses have explicit public schemas and omit internal
  storage paths. Review history is institution-scoped. Grading-policy reads/writes
  also check the question's institution.
- Identity-only edits preserve the course's instructor name when that field was
  omitted. Export response headers are exposed for supported cross-origin clients.
- Browser tests use synthetic papers/API records. The HTTP contract test uses real
  FastAPI routes, isolated SQLite and mocked inference. Backend tests cover the
  enabled verifier separately from legacy tests with verification disabled.

These tests establish software behaviour. They do not measure handwritten OCR
accuracy, human–AI grading agreement, BM25 benefit or production readiness. Private
GPHY171 papers and their teacher marks were not submitted to any model. Screenshots
and test logs stay in the ignored `.impeccable/review/` directory.

### Verification record — 14 October 2026

- Full backend discovery: **289 passed**, isolated SQLite and dummy credentials.
  Grading fixtures explicitly select the mocked provider and disable verification
  unless that test exercises it; the local mixed-provider configuration remains
  present. Targeted provider/extraction/material tests: **69 passed**.
- Full browser suite: **367 passed, 3 viewport-specific skips**. After the final
  focused-page layout changes, the native workflow suite: **22 passed**, including
  two added responsive/theme/RTL checks. These runs overlap; do not add their counts.
- Native/shared JavaScript syntax and `git diff --check`: passed.
- Synthetic after-images inspected for desktop/mobile, light/dark and Arabic RTL.
- No live inference, production database changes, migrations, service restarts,
  commits or pushes. Some specialist/server text remains English.

### Answer-location verification — 16 October 2026

Full backend discovery: **350 passed**. Full browser suite: **515 passed, 3 skips**.
Final page-specific localization/native-location tests: **23 passed**. JavaScript
syntax and diff whitespace checks passed. Synthetic captures cover desktop/mobile,
light/dark and Arabic controls. The local API exposes the action and the idle worker
was restarted with empty queues. No migration or live localization inference was run.
These mocked checks do not establish the new method's localization accuracy; the
instructor must inspect its proposed region on the original page.

### Automatic-area verification — 16 October 2026

Full backend: **358 passed**. Focused paper review: **39 passed, 1 viewport skip**.
Full browser: **516 passed, 3 skips, 1 failure** at workspace module loading before
an editor fixture initialized. That exact editor case then passed **6 isolated
repeats** (three desktop, three mobile); the full run is not claimed clean.
Automatic extraction checkpoints and individual/batch localization use synthetic
fixtures and mocked providers. Manual save/cancel/storage failure, Arabic, both
viewports/themes and concurrent AI/manual work are covered. The worker was safely
restarted idle, and the local automatic API parameter was confirmed. No database
upgrade or live localization inference was initiated by tools.

### Confirmed extraction corrections — 17 October 2026

Answer-region editing now belongs to Extraction. Reading a region produces a
durable preview; instructor confirmation saves a separate revision. The original
OCR, original full pages, earlier AI runs and prior instructor decisions remain
available. A saved correction does not automatically request regrading.

Explicit corrected-answer regrading creates one new proposal with the confirmed
text, selected crop, full mapped original pages and existing approved grading
inputs. Required course evidence and citation validation remain enforced. Existing
instructor grades are retained while the new proposal awaits review. Saving a
current instructor decision is blocked during its pending corrected-answer job;
historical evaluation labels remain independent. Unsaved instructor edits must be
saved or discarded before requesting regrading.

Final backend discovery: **381 passed**, including an actual FastAPI HTTP sequence
through preview, confirmation, extraction review, regrading, results and preserved
run/decision history. Focused browser workflow/editor checks: **143 passed, 1
viewport skip**. Eight synthetic network-failure tests verify one bounded workspace
download retry, visible persistent failure and no duplicate module execution.
The final full browser run passed **539 tests, with 3 viewport-specific skips**
using four workers, after fixing the intermittent workspace-download failures found
in the earlier runs. SQL compilation checks verify current reads for MySQL write
paths; the regression database remains isolated SQLite.
JavaScript syntax and diff whitespace checks passed. Private synthetic captures
cover Extraction in both themes, both viewports, Arabic RTL and zoom alignment.

No schema migration or provider changes were needed. The worker was restarted only
after confirming it was idle with empty queues. The API exposes the new routes.
Tools made no live inference calls; these checks do not measure OCR, localization
or grading accuracy.
