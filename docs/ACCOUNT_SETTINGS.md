# Marking defaults and account controls

The instructor app uses `/app/account.html`. Marking preferences appear first;
appearance, security, connected AI roles and account removal have separate sections.

## Marking defaults

- `GET /api/auth/settings` reports the current instructor's saved setting, approved
  profile availability, and completion of the twelve-answer approved survey.
- `PUT /api/auth/settings` accepts only the strict boolean `use_marking_preferences`.
  It defaults to true when no row exists. The setting belongs to the authenticated
  instructor and institution; clients cannot choose another user.
- New native question drafts initialize their policy from the approved profile.
  Explicitly creating an editable rubric draft requests the same defaults from the
  backend. Imported exam and source-question drafts also use them.
- Settings opt-out prevents future automatic copies. Explicit instructor edits win
  when a draft is saved. Existing drafts, approved definitions and grading snapshots
  are never changed by loading a profile, approving a survey, or toggling this setting.
- A whole-guide review/approval remains required before these rules can affect grading.
- No survey means ordinary default rules. A dismissible inline reminder is optional.
  Taking the survey saves valid edits first; a failed save leaves the editor intact.
- An approved twelve-answer survey shows a green completion check. An existing opt-out
  remains off when the survey is updated. Partial drafts do not show completed.

## Account deletion

`DELETE /api/auth/account` requires the authenticated instructor's current password,
CSRF token and exact `DELETE` confirmation. The UI explains retention before submission.
Deletion removes the current user's name, email, password access and active sessions.
The user row remains as an anonymized inactive identity to preserve institutional
papers, grades, source/guide snapshots, survey history, decisions and audit references.
This is account removal, not a purge of historical institutional records. Historical
snapshots are not rewritten. Administrators cannot re-enable or reset a deleted account.
The last active institution administrator and users with active tasks cannot delete
their accounts until another administrator exists / those tasks finish.

## Upgrade and checks

The additive `scripts/upgrade_account_settings.py` creates only
`instructor_account_settings`. It is idempotent, has no backfill and changes no existing
academic rows. Back up the local database and obtain authorization before running it:

```powershell
# From misra_backend, using the project's Python environment
python scripts/upgrade_account_settings.py
```

Missing schema returns an actionable 503; login and existing grading remain available.
Restart the API if it does not reload Python files, then refresh the app. No provider
configuration, worker grading pipeline, dependency or paid call is introduced here.
Tests use synthetic records, isolated SQLite and mocked browser APIs.
