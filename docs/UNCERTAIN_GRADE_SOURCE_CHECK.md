# Checking uncertain grades against original evidence

Implemented 18 October 2026. RAG remains part of grading. This adds a bounded
second check for uncertain new proposals; historical grades are not regraded.

## What happens

1. The assessment agent proposes criterion marks using the approved guide, key,
   student evidence and applicable approved course passages. The server validates
   marks, totals and citations. The verification agent checks that proposal.
2. Low raw confidence, criterion uncertainties, a conflicting total, citation
   repair or a verification concern triggers **one source consultation**.
3. Retrieval uses BM25 plus character TF-IDF rank fusion within the **same pinned,
   approved chapter/page scope**. It can select up to four passages per criterion,
   within the existing eight-passage/12,000-character limit. Coverage is considered
   before extra passages. If the larger selection cannot cover required criteria,
   the original BM25 strategy is revalidated; integrity/approval errors still fail.
4. In text-only grading, the configured extraction agent can re-read the original
   mapped student pages. It returns separately labeled observations, with stable
   segment IDs. Conflicting or ambiguous observations require instructor review.
   They never overwrite saved OCR or instructor-confirmed corrections.
   Image grading already supplies the original pages and selected regions to the
   verifier. Page roles and approved reference images stay separate.
5. The configured verification agent checks the academic support for each mark
   against those passages and student evidence. It must cite an applicable course
   passage and tracked student evidence for every finding. Unknown IDs, omitted
   criteria, unapproved references and replacement score fields are rejected.
6. If the source check identifies a specific academic concern and the original
   evidence is sufficiently clear, the **assessment agent reassesses once** using
   the same approved guide and the additional approved passages. It may increase,
   decrease or retain marks. All criterion/score/citation checks still apply, and
   a fresh verification is required. The result is an **advisory alternative**;
   it never replaces the main proposal automatically. Disputed alternatives are
   labeled as disputed. Invalid revisions leave the valid initial proposal in review.
7. MISRA saves both proposals, both source snapshots, original checks, page
   observations, trigger reasons and inference metadata. Existing verification
   findings explain the reassessment and its proposed score difference. Reassessment requires
   instructor review. The instructor can correct extraction, explicitly regrade,
   accept or adjust. Previously saved runs and instructor decisions are preserved.

## Review behavior

- A successful source check cannot erase an earlier verification flag or bypass
  the raw-confidence threshold. High confidence is not proof of correctness.
- A missing page, unavailable model or unusable supplemental response is recorded
  explicitly and keeps a valid primary proposal in review. A conflicting or missing
  original-page check blocks automatic reassessment in the application. No
  automatic fallback model, approval, inferred work or repeated check/revision loop
  is used. The three configured roles remain extraction, assessment and verification.
- A disabled/unconfigured source scope is not silently broadened to the whole
  course. The instructor is told approved course evidence is unavailable.
- Supplemental source checking uses the configured roles. No provider settings,
  approved rubrics or live academic records are changed by this implementation.


## Verification and evaluation

Source consultation, advisory revisions and review gates have synthetic backend
regression coverage. Passing contracts does not establish academic correctness.
Evaluate new versions with frozen approved inputs and prescheduled cohorts;
keep original provider responses, costs, failed attempts and adjudications private.
Report grading agreement, source support, OCR fidelity and review workload separately.
Old runs remain unchanged. No migration is required by these services.
