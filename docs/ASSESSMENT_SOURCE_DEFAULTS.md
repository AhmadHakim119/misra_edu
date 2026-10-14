# Assessment source defaults

Select approved course material once for an assessment rather than configuring
each question separately. Reference content supplies subject context; the approved
rubric, answer key and marking policy continue to determine credit.

## Setup

For an existing database, back up MariaDB first, then run from `misra_backend`:

```powershell
python .\scripts\upgrade_assessment_sources.py
```

Restart the API **and** RQ worker. This additive script creates source-default
storage and ensures course-material tables exist. It does not rewrite existing
assessments, question scopes, rubrics or grading history. New installations use
`database/schema.sql`. A missing default table leaves legacy question-only grading
available, but default configuration returns a clear upgrade-required response.

## Instructor workflow

1. Review course materials and approve only checked pages in the course library.
2. In Rubric Studio, open **Assessment source defaults**.
3. Add approved versions and document pages. Page positions start at 1 in the UI.
4. Save a draft, or explicitly **Save & approve assessment sources**.
5. Check the question exceptions list. Existing approved question scopes are not
   silently replaced by the new default.
6. For a question that should return to the default, open its **Course sources**,
   choose **Use assessment default**, then approve that choice.
7. Preview retrieval on representative questions before grading. Required
   retrieval stops when relevant context cannot be found; approval is not proof
   of retrieval quality or marking accuracy.

## Precedence and history

An approved question exception wins, including an explicit disabled scope.
An approved `inherit` question version instead uses the active assessment default.
Without an approved question exception, the active approved assessment default
applies. Drafts never shadow active approvals. If neither exists, the legacy
question/key/rubric workflow remains available.

Each future grading package records scope origin, scope version and integrity
hash, any question inheritance decision, and the exact retrieved passages. New
approvals supersede earlier active versions but never rewrite saved runs. Source
integrity failures stop grading rather than silently falling back.

Defaults apply to all criteria. Criterion-specific passage links remain question
exceptions. Material versions must belong to the assessment's course and tenant;
only previously approved pages can be selected. Student text is not used to
construct retrieval queries.

## API

- `GET /api/exams/{id}/material-scopes`: versions and question inheritance status.
- `POST /api/exams/{id}/material-scopes`: save a draft default.
- `POST /api/exams/{id}/material-scopes/{scope_id}/approve`: explicit approval.
- `GET /api/questions/{id}/effective-material-scope`: resolved scope and origin.
- Existing question scope and retrieval preview routes support approved inheritance.

The original frontend remains available. The parallel replacement interface is
being developed separately; these controls do not imply replacement feature parity.
