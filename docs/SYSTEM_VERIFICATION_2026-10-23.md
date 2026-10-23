# Local prototype verification — 23 October 2026

Verdict: **CONDITIONAL** for instructor-supervised local thesis-prototype use.
This is a bounded engineering assessment of the current uncommitted working tree.
It is not formal certification, an exhaustive security audit, or evidence of
grading accuracy. Existing assessments and historical records were not modified.

## Changes and verification

- Verified the applied-review-label and stale-review-token fixes already present.
  Evaluation-only labels cannot replace displayed applied criterion marks;
  missing/stale decision tokens are rejected without changing the saved decision.
- Fixed `/app/reviews.html`: only the latest request may render rows, errors or
  loading completion. Old rows clear immediately on loading/failure, so the exam
  selector cannot describe another exam's queue. Refresh remains keyboard usable.
- Added delayed-success, delayed-error and failed-load/retry browser regressions.
- Refreshed local Impeccable metadata while preserving DESIGN.md. Removed cached
  color ramps rather than retaining unverified derived colors. Repointed the old
  ledger brief to `/app/` and labeled its original migration plan as historical.
  These files and synthetic screenshots remain Git-ignored.

## Audit coverage and limits

| Boundary | Evidence examined | Limit |
| --- | --- | --- |
| Authentication | Session tampering/revocation and CSRF guards; authentication tests | No public deployment or penetration test |
| Institution isolation/private files | Scoped resource queries, document handlers, upload validation and cross-tenant denial tests | Sampled paths; no exhaustive endpoint proof |
| Sources/grading | Approved definitions, tenant-linked package construction, required applicable citations, validation/retry gates | Citation validity does not establish academic support |
| Instructor authority/history | Applied label selection, stale saves/reopening, immutable labels/runs, export readiness | Database concurrency tested using synthetic fixtures, not live MariaDB |
| Upload/OCR/jobs | File signatures/size/pages, cleanup, mapping authorization, persisted retry and orphan recovery | Redis/RQ/provider behavior mocked; no process-crash or live recovery drill |
| Frontend | Canonical workflow browser suite; focused queue checks, keyboard retry, light/dark desktop/mobile captures | Chromium only; no exhaustive WCAG, screen-reader or device certification |

## Checks

- Full backend: **723 tests passed**, using isolated databases and mocked providers.
- Focused review queue: **10 desktop/mobile checks passed**.
- Full browser suite: **337 passed, 1 skipped** (3.1 minutes). The skipped
  mobile case intentionally targets the desktop-only approved hero dimensions.
- JavaScript syntax: **17 changed/new files passed**.
- `git diff --check`: passed.
- Impeccable doctor: no findings; rule registry available.

Sandbox runs initially stalled during Windows socket initialization; the suites
were run outside the sandbox with the same synthetic fixtures. Backend execution
reported an existing requests dependency compatibility warning. No packages were
installed or changed.

## Conditions and handoff

Restart the API to load the earlier review-contract changes and refresh open
grading pages. No migration is introduced by these fixes. No live service was
restarted and nothing was committed, pushed or deployed.

Before relying on this installation with actual student records, separately
verify the installed schema, private storage permissions, database/Redis/worker
configuration, backup restoration and job recovery in an authorized environment.
Real-paper grading accuracy and confidence calibration require independent
instructor-labelled evaluation. Instructors retain final grading responsibility.

Private visual evidence: `.impeccable/review/review-before-*.png` and
`review-after-{light,dark}-{desktop,mobile}-chromium.png`. The scoped screen brief
and full browser log are in that same ignored directory.
