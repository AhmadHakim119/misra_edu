# Whole-paper extraction coverage

MISRA preserves the original paper. A displayed highlight locates evidence on the
full page; it does not replace that original with a cropped answer image.

## Mapping and coverage are different

Finding an answer for every expected question does not establish that all visible
work was transcribed. The OCR contract now asks separately for:

- The printed question heading, where visible, rather than only a student label.
- An inventory of detected student-answer regions, including numbers, selections,
  equations, diagrams, margin work and crossed-out work.
- Links from each region to the returned transcription segments, or empty links
  when work is visible but was not transcribed.
- Whether the provider reports that it inspected the entire page.

Whole-paper reconciliation prefers an unambiguous printed heading, but refuses a
strong heading/content conflict instead of silently assigning it. Dotted and
Arabic-digit labels are retained. An explicit answer page containing numeric
responses and student identity is not automatically treated as a score-only cover.
Bare parent labels are not assigned to the first of several configured subparts.

## Persisted provenance

`extraction_inventories` stores an immutable-by-workflow version for each completed
extraction: original document hash, physical page count, detected regions, segment
metadata and a canonical manifest hash. Active sources retain their inventory,
physical page and segment identifiers. Reprocessing creates a new version instead
of editing an earlier inventory. Explicit instructor exclusions retain provenance.

The hash detects changed saved inventory content; it is not a cryptographic access
control or an independent check of model output. A correctly sealed model omission
is still an omission. In-place external edits to original files are not independently
detected by this coverage report; production storage should enforce immutability.

## Grading boundary

| State | Meaning | Behavior |
| --- | --- | --- |
| `not_recorded` | Legacy extraction or upgrade not installed | Existing workflow remains available; no retroactive coverage claim |
| `provider_accounted` | All inventoried regions are mapped or explicitly excluded, and provider reports full-page inventory | Normal grading checks still apply; not independent verification |
| `unverified` | Missing full-page report or incomplete region inventory | Grading routes to review and caps confidence at 40 |
| `needs_attention` | Known visible region is not accounted for | Grading blocked before a provider call |
| `invalid` | Saved manifest or physical page count does not match | Grading blocked; reprocess an eligible ungraded paper or inspect history |

Both the API readiness check and grading-package builder enforce known gaps.
Saved grading packages preserve the coverage snapshot used; paired-run comparison
requires equivalent coverage evidence. A covered region says where evidence came
from, not that the transcription or awarded marks are correct.

## Recovery flow

Open **Extraction results → a paper → Paper coverage**. An unresolved-area button
opens its physical page and highlights the reported region. Page recovery can run
even when every expected question already has an answer. Review the proposed text
before approving it; nothing is merged on preview alone.

A signed, instructor-confirmed recovery can account for an inventoried area only
when its box covers at least 95% of that area and has at least 80% intersection-over-
union. A whole-page rectangle cannot clear small missing regions. Preview excludes
already-accounted text when recovering known regions for already-mapped questions.
If a tight match is unavailable, the issue stays open; use the full-paper re-scan.
Existing graded answers cannot be rewritten by page recovery.

For assessments above the recovery endpoint's 30-question request limit, use the
full-paper automatic re-scan for coverage gaps. No automatic repeated provider
requests are scheduled merely to improve the mapped count.

## Installation and testing

Back up an existing database, then from `misra_backend` run:

```powershell
python .\scripts\upgrade_extraction_coverage.py
```

Restart the API and worker. The upgrade is additive and idempotent; application
startup does not run it automatically. The fresh-install SQL schema includes it.

Regression tests use synthetic pages and mocked providers. They demonstrate
software boundaries and compatibility, not empirical handwriting recognition
accuracy or grading accuracy. An independent OCR benchmark and instructor-labelled
held-out papers remain necessary.

## Display locations on the original paper

The extraction and grading-results viewers can locate a source segment from the
original PDF's selectable text. An authenticated, institution-scoped, read-only
`GET /api/submissions/{id}/source-locations?page_index=0` request uses Poppler
`pdftotext -bbox-layout` locally for one page. Page positions are zero-based in
the API and start at one in the interface.

Only a unique complete normalized token match receives a native text-layer
rectangle. Numbers, arithmetic signs and grouping are preserved; repeated text
is ambiguous rather than resolved by guessing. This is a display aid, not a
new grading signal or proof of visual/OCR correctness. The full page remains
visible. Original OCR coordinates, answer text, grades and historical runs are
not rewritten, including for already-graded submissions.

Scans, missing Poppler, timeouts and text that cannot be uniquely located retain
explicitly labelled approximate OCR coordinates (dashed outline), or page-only
display if no usable coordinates exist. Install `pdftotext` alongside Poppler
and make it available on the backend's PATH to enable native lookup. No model
request, package addition or database migration is required for this lookup.
