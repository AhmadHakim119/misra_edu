# Security and recovery follow-up — 23 October 2026

Verdict: **CONDITIONAL** for supervised local thesis-prototype use. This follows
SYSTEM_VERIFICATION_2026-10-23.md and records additional checks on the uncommitted
working tree. It does not certify a production installation or grading accuracy.

## Security changes

- Login previously had no attempt budget. Database audit records now enforce
  10 attempts per normalized email and 50 per client address per 15 minutes,
  with HTTP 429 and Retry-After. Identifiers are keyed hashes. UTC timestamps
  avoid dependence on database timezone. Unknown/inactive accounts also perform
  a password-hash check rather than returning before the expensive check.
- Logout previously cleared browser cookies without checking CSRF or revoking a
  copied cookie. Valid-session logout now requires CSRF and increments the user
  session version. **This signs out existing sessions on every device.**
- CSRF comparisons safely handle non-ASCII input rather than raising TypeError.
- Blackboard CSV assessment headers and Excel assessment/course/term metadata
  now use the existing formula-neutralization helper. These fields previously
  bypassed it and could become spreadsheet formulas.
- API/page responses now set nosniff, DENY framing, no-referrer and a minimal CSP
  prohibiting framing, objects and cross-origin base URLs. This is deliberately
  not a comprehensive script CSP; inline application behavior remains supported.

## Actual isolated recovery drills

`scripts/recovery_drill.py` creates its own temporary directories and instances.
It does not accept an existing data directory or application database connection.
All servers bind loopback on temporary ports and are stopped after the drill.

| Drill | Result | Boundary |
| --- | --- | --- |
| MariaDB backup/restore | Passed; all 31 application tables compared | Synthetic institutions, course, exam, rubric, paper, override, immutable run, label and job |
| MariaDB forced process loss/restart | Passed; committed rows unchanged | Newly initialized temporary server |
| Original-paper restoration | Passed; byte hash and both full PDF pages preserved | Synthetic blank two-page original, not a private paper |
| Redis AOF process loss/restart | Passed; queued item recovered and consumed | Isolated WSL Redis with appendfsync=always |
| Real MISRA Redis/RQ worker | Passed; material job completed, zero provider calls | Real isolated Redis/RQ, synthetic PDF, isolated SQLite database |

Reproduce from repository root with existing tools:

```powershell
python scripts/recovery_drill.py mysql --mysql-bin C:/xampp/mysql/bin
wsl -d Ubuntu -- python3 /mnt/c/Users/hakim/OneDrive/Desktop/dood/misra-edu/scripts/recovery_drill.py redis
python scripts/recovery_drill.py rq
```

These are reproducible drills, not a scheduled backup system. They do not prove
that the current installation's backups, configuration or retention are adequate.
No live database, Redis service, worker, provider or private paper was modified.

## Verification

- Full backend suite: **729 passed**.
- Full desktop/mobile Chromium suite: **339 passed, 1 intentional desktop-only
  layout skip**.
- Added automated accessible-name and text-contrast checks for the review screen
  in both themes, plus existing keyboard retry and asynchronous-state checks.
  These checks are not exhaustive WCAG or screen-reader verification.
- Syntax and whitespace checks passed. No dependency or migration was added.

## Remaining conditions

- Restart the API and refresh browser pages to apply the security changes.
- Validate installed configuration, encrypted/private backup handling, retention
  and a representative restore on the deployment host before actual reliance.
- Combined MariaDB+RQ concurrency, forced worker death during grading, distributed
  abuse/load testing, external penetration testing and manual assistive-technology
  review remain unverified. The login budget is not an atomic distributed quota;
  concurrent admission can exceed the window boundary by in-flight requests.
- The Redis drill uses a known persistence configuration, not the installation's
  live Redis configuration. Windows RQ uses an in-process worker.
- The subsequently identified physics dataset was audited locally against its
  saved predictions. The original seven-answer primary cohort matched 5/7
  historical instructor marks in both saved pipelines; one reused control and
  nine non-independent calibration labels were reported separately. Those runs
  predate current code changes, so current-system accuracy remains unestablished.
  The detailed report is private under evaluation-artifacts/. No new inference
  or live academic-record change was performed.
- No commits, deployments, paid calls or live restarts were made. Private test
  logs remain in the Git-ignored `.impeccable/review/` directory.
