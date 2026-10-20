# Physics extraction reliability phases

This work changes the offline extraction diagnostic first. Existing studies,
approved marking rules, saved AI runs and instructor decisions remain immutable.
RAG uses the same approved evidence; OCR never receives a key or a reference score.

1. **Source images:** render original PDF pages at 360 DPI, reapply reviewed masks,
   remove identity footers and verify visually. Preserve full pages locally and
   colour extracts alongside derived contrast images. Do not upload full marked pages.
2. **Located lines:** create reviewed equation/answer crops with page coordinates,
   image hashes and reading order. Keep printed context separate. Retain the full
   student answer so omitted work can be detected.
3. **Independent readers:** test Gemini Flash and a specialist formula reader.
   Each reader receives only images and transcription instructions. Record failed
   or unavailable services, exact settings, raw responses and durable costs.
4. **Disagreements:** preserve reader alternatives per region. Compare operators,
   decimals, exponents and digit sequences without solving or repairing an answer.
   Agreement is a screening signal, not calibrated correctness.
5. **Review before grading:** produce a local crop/alternatives review packet.
   A disputed, missing or uncertain reading blocks the experiment's grading gate
   until an instructor records a versioned decision tied to the evidence digest.
   Never infer approval from elapsed time, matching grades or agent review.

Implementation status and empirical results belong in the ignored versioned study
directory. Tests use synthetic evidence. Reused physics examples are regression
evidence; new OCR results do not turn them into an untouched evaluation cohort.

The offline gate does not change the running app or migrate its database. Existing
instructor-confirmed answer-area revisions remain the application's correction path.

## Current implementation

`services/ocr_verification.py` validates located readings, keeps raw alternatives,
normalizes explicit typesetting equivalents only, flags source ambiguities and
screens bounded numeric equalities without changing text. Same-family reruns do
not count as independent readers. Missing readers, stale decisions and modified
comparison snapshots cannot pass the gate.

`services/ocr_review_packet.py` creates a private, script-free image/alternatives
packet with verified crop hashes. It has no provider connection or save action.
`scripts/review_ocr_transcriptions.py` checks trusted local instructor decisions
against the evidence digest and writes a new revision without updating live grades.
The CLI is an offline operator tool, not an authenticated application endpoint.

`services/ocr_review_triage.py` orders critical or uncertain regions first and
attaches prior human component replies to the current evidence digest. A partial
reply cannot clear the full-region grading gate. The private packet displays these
replies so the same symbol need not be requested again. Wider-line versus focus
checks flag changed signs or digits without treating another run of the same model
as an independent vote. A matching sequence can still contain a shared error.

Colour/contrast close-ups can introduce errors as well as clarify writing.
Retain both views and never automatically replace a line with a focus reading.
Keep actual reader attempts and paper-specific outcomes in the private study.

Later human replies can resolve specific components in append-only adjudication
records without approving a whole answer. Preserve the earlier tentative reading,
its image location and the superseding confirmation. Do not repeatedly ask about
a component already confirmed by the instructor. Keep the historical full-region
gate unchanged; distinguish unresolved specific questions from the wider gate's
remaining verification records. Explicitly authorized draft-text grading remains
a conditional research diagnostic, with source release disabled and instructor
finalization required. Record any separately approved marking-policy amendment
in its own version; it cannot change the transcription or earlier results.

A schema-constrained response can fix missing fields or invented region IDs while
still joining separate handwritten lines or adding a digit. Validate the actual
writing after contract validation. Preserve failed contracts in their own attempts;
an improved schema/prompt is a new version, not a replay that overwrites history.
Keep line boundaries explicit, retain same-family wider/crop disagreements, and
do not promote a specialist solely because it produced parseable output.

Teacher additions include seemingly harmless unit symbols as well as ticks,
corrections and scores. A unit inserted into a checked transcription is still a
source-boundary error. Append a source erratum, invalidate the affected clean
claim and create a literal-only revision. Instructor confirmation of one component
does not approve every character or the final grade. An unreadable reply remains
unresolved rather than becoming the mathematically convenient reading.
