# Native instructor workflow

Open `/app/index.html` on the MISRA API. It opens the native dashboard.
An existing `index.html?exam_id=…` link still opens the shared marking workspace.
The main instructor app lives in `misra-frontend/app/` and is served at `/app/`.
The server root opens the public landing page, with links into this app.
The old interface is isolated at `/legacy/pages/`;
old `/app/next/` bookmarks redirect to the main app while preserving the query.
Shared controllers and original assets are retained. No data migration is needed.

## Public introduction and review conveniences — 16 October 2026

- `/` serves `app/landing.html`: the existing logo, a synthetic grading example,
  instructor workflow, three AI roles and a secondary thesis section. App and sign-in
  links open the canonical interface. English/Arabic and light/dark preferences persist
  on the device; content and native links remain usable without JavaScript.
- Navbar account controls align at the opposite end from navigation in both directions.
- Paper review offers **Adjust highlight** for misplaced extraction boxes. Draw or
  move/resize the box and save it on this device. This changes the displayed overlay;
  it does not improve automatic localization, edit OCR, alter grades or rerun extraction.
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

All instructor navigation in `/next` stays in `/next`. Essential existing controllers
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
