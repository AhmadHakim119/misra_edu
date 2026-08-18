# MISRA-EDU Evaluation Log

Running record of real test findings from the OCR and grading pipeline. Each entry documents a specific, reproducible observation — not general impressions — so this can feed the evaluation chapter directly.

---

## Test Case 1: Physics — Effat University, Class Assignment #1 (Spring 2026)

**Content:** Printed English question text, handwritten mixed-language work (English + minor Arabic logo text), STEM notation (work/energy equations), no student name/ID present on page.

**OCR findings:**

- Correctly transcribed all handwritten numeric values and equations across 3 multi-part questions (Q3, Q4, Q5), including boxed final answers (37.6 J, 1507.9 Kg, 15.87 m/s, -7232.4 J, 28 m, 258.3 N) — all verified correct against the source image.
- Correctly produced valid LaTeX notation for every equation.
- Correctly distinguished printed question prompts from handwritten student work after prompt tuning (see below).
- Correctly reported `identity_legibility: "not_found"` — no name/ID was present on this page, and the system did not hallucinate one.
- One ambiguous decorative mark near a logo was inconsistently read across runs — once as a partial Arabic string ("لُج"), once as a possible name ("فطيمة"), once as unrelated text ("ف و"). This is likely non-text decorative content; the model's inconsistent interpretation of it is a reasonable/expected behavior given genuine ambiguity, not a grading-relevant error.

**Prompt iteration required:**

- Initial prompt produced `question_number` values with inconsistent formatting (`"Q3a"` vs `"3a"`) — fixed by adding an explicit formatting rule.
- Initial prompt included the printed question prompt text as its own segment, cluttering output — fixed by explicitly instructing the model to extract only handwritten student work.

**Grading findings:**

- Correct rubric-based grading on Q3a (work formula question): full credit (1.0/1.0), correctly ignored a stray "• 1" multiplication artifact in the OCR'd text without penalizing it.
- `llm_confidence`: 98-100 across repeated runs on this clean, unambiguous answer.

---

## Test Case 2: Linear Algebra — MATH307, Quiz 2 (Fall 2025)

**Content:** Handwritten-only page (no printed question text visible in the crop tested), dense matrix/cofactor notation, visible scratched-out/reworked calculation, handwritten student name and ID number.

### Finding A — Identity extraction errors (real, non-zero error rate)

| Field      | OCR extracted                                                                                                                        | Actual (verified)     | Error type                                 |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------ | --------------------- | ------------------------------------------ |
| Name       | "Forah Kareem Abousayya" (varied slightly across runs: "Ferah Kareem Abasagga", "Fourah Kareem Abansayya", "Farah Kareem Aboudiyya") | Farah Kareem Aburayya | Cursive letter confusion (F/Fo, r/ou, s/r) |
| Student ID | "821107290"                                                                                                                          | S21107290             | Leading letter "S" misread as digit "8"    |

Name extraction varied across every independent run — no two runs produced an identical spelling, though all were phonetically/visually close to the real name. ID number was consistently misread the same way (8 vs S) across multiple runs, suggesting a systematic visual ambiguity rather than random noise.

**System behavior:** Correctly reported `identity_status: "unmatched_extracted"` in all cases — the system did not falsely claim a confirmed match, correctly deferring identity resolution to a human reviewer. This validates the design decision to never auto-trust OCR'd identity fields.

### Finding B — Run-to-run segment labeling inconsistency

The same source image, run independently 4 times, produced different segment counts and occasional different `question_number` labeling for the same handwritten content (e.g., the cofactor-matrix section was correctly labeled `"1b"` in most runs, but labeled `"2"` in one run). Root cause investigation showed this is likely driven by genuine ambiguity in the source material (a visibly scratched-out, reworked calculation for matrix C) rather than pure model non-determinism — different runs appear to pick up different versions of the student's crossed-out vs. final work.

**Implication for system design:** Motivated adding a safety net (`unmatched_segments` field on `Submission`) so that any segment failing to match a known question is preserved and visible rather than silently discarded — closing a real data-loss gap the initial implementation had.

### Finding C — Consistent subscript misreading (C32 vs C23)

Across all 4 independent OCR runs that successfully captured the cofactor section, the model consistently read the cofactor entries as `C22`, `C23`, `C33` — never `C32`. This was consistent enough across independent runs to be treated as the model's stable reading of the source material, not noise.

### Finding D — JSON validity bug surfaced by LaTeX-heavy content

Dense matrix notation (`\begin{bmatrix}...\end{bmatrix}`) caused the model to occasionally place unescaped LaTeX backslashes directly in the `"text"` field (as opposed to the dedicated `"math_notation"` field), producing invalid JSON and a hard crash. This had not occurred on any prior test image, since none contained matrix/LaTeX-heavy notation.

**Fix applied:** (1) explicit prompt rule separating plain-text `"text"` from LaTeX-only `"math_notation"`, requiring double-escaped backslashes; (2) a one-time automatic retry with a corrective re-prompt if JSON parsing fails, before raising an error.

### Finding E — Grading correctly distinguished shown work from final submitted values

On the cofactor sub-question (1b, 3 points), grading correctly identified that the student's shown calculation steps for C22 were mathematically correct (yielding 1), but the value written into their final submitted cofactor matrix was inconsistent (0) — and graded strictly on the final submitted value per rubric instructions, awarding 0 points for C22 despite correct work shown. C33, where calculation and final value agreed and were correct, received full credit. Final score: 1/3.

This is a materially more sophisticated grading judgment than simple answer-matching — it reflects genuine engagement with the rubric's `notes` field instruction ("grade based on final values as presented in the matrix").

**Confidence scoring on this ambiguous case:** `llm_confidence: 95`, `final_confidence: 97.5`. High confidence despite partial credit — reflects that the _values themselves_ were legible and the _judgment_ was clear, even though the underlying source material had genuine ambiguity (crossed-out work). This is a meaningful distinction: confidence tracked certainty-of-judgment, not correctness-of-answer, matching the system's intended design.

**Open question:** No test case so far has triggered `needs_review = True` (threshold currently `final_confidence < 70`, unvalidated placeholder). All tested cases — including genuinely partial-credit and visually messy ones — have scored confidence above threshold. This suggests either (a) the threshold is set too low to catch real ambiguous cases, or (b) Gemini's confidence calibration tends to stay high even on genuinely uncertain content. Requires a larger, deliberately-varied test sample and hand-grading comparison to calibrate properly — planned for the dedicated evaluation phase.

---

## Test Case 3: AI Rubric Suggestion — Arabic Linear Algebra Question

**Setup:** Tested the rubric-suggestion endpoint (`POST /api/exams/{exam_id}/suggest-rubric`) with a bare Arabic question and no other guidance beyond subject and max score, to evaluate whether the AI-generated rubric is a genuine, usable pedagogical artifact rather than a superficial translation exercise.

**Input:**

- `question_text`: "احسب القيم الذاتية للمصفوفة" (Find the eigenvalues of the matrix)
- `subject`: Linear Algebra (from exam context)
- `max_score`: 2.0
- `language`: "ar"

**Output — full criteria breakdown:**

| Criterion                              | Description (Arabic)                                                                | Points | Partial credit |
| -------------------------------------- | ----------------------------------------------------------------------------------- | ------ | -------------- |
| `characteristic_equation_setup`        | صياغة المعادلة المميزة (det(A - λI) = 0) بشكل صحيح، وتحديد المحددة المناسبة.        | 0.5    | No             |
| `characteristic_polynomial_derivation` | اشتقاق كثير الحدود المميز بشكل صحيح من المحددة، وتبسيطه إلى صورته القياسية.         | 0.7    | Yes            |
| `eigenvalue_calculation`               | تحديد وحساب القيم الذاتية (جذور كثير الحدود المميز) بشكل صحيح، مع إظهار طريقة الحل. | 0.8    | Yes            |

**Notes field generated:** Independently introduced an "Error Carried Forward" grading policy in Arabic — instructing that if an early computational error occurs, later steps should be evaluated on correctness of method rather than double-penalizing the same mistake, unless the error trivializes the problem. Also specified that eigenvalues are acceptable in any order.

**Findings:**

- Points across the three criteria summed exactly to `max_score` (0.5 + 0.7 + 0.8 = 2.0) — schema validation passed without adjustment needed.
- Criterion decomposition reflects a genuine, pedagogically sound breakdown of the solution process (setup → derivation → final computation) that a linear algebra instructor would recognize, not a generic template.
- Terminology used ("المعادلة المميزة", "كثير الحدود المميز", "القيم الذاتية") is standard, technically correct Arabic mathematical vocabulary — not machine-translation-style phrasing.
- The unprompted introduction of an "Error Carried Forward" policy is notable: this is a real, standard grading pedagogy concept the prompt never explicitly requested, suggesting the model is drawing on genuine pedagogical patterns rather than following a rigid template.
- Partial-credit judgments (binary for setup, partial for derivation/calculation) are defensible and consistent with how the physics and linear-algebra rubrics were manually designed earlier in testing (Test Cases 1–2), suggesting the model's judgment on this dimension generalizes reasonably across subjects.

**Implication:** This is a concrete example supporting the claim that rubric suggestion in Arabic produces substantively usable pedagogical content, not superficial translation — relevant to the project's core differentiator (bilingual STEM assessment support where no existing published tooling has demonstrated this capability).

---

## Test Case 4: Confidence Function Sensitivity Analysis (Isolated Unit Test)

**Motivation:** No real test case across Test Cases 1–3 had triggered `needs_review = True`, despite including a genuinely partial-credit, partially-ambiguous answer (Test Case 2's `1b`, scratched-out cofactor work). Needed to determine whether this was because the confidence mechanism itself doesn't work, or because real test inputs hadn't been extreme enough to cross the threshold.

**Method:** Tested `_compute_final_confidence()` directly with controlled synthetic inputs, isolating each of the three weighted signals (OCR legibility: 0.3, LLM self-reported confidence: 0.5, score boundary risk: 0.2) one at a time, holding the other two at their best possible value.

**Results:**

| Case                    | OCR legibility | LLM confidence | Score ratio    | final_confidence | needs_review (threshold 70) |
| ----------------------- | -------------- | -------------- | -------------- | ---------------- | --------------------------- |
| Clean answer (all good) | clear          | 98             | 1.0            | 99.0             | False                       |
| Worst case (all bad)    | illegible      | 30             | 0.5 (boundary) | 18.0             | True                        |
| Partial OCR only        | partial        | 95             | 1.0            | 85.5             | False                       |
| Boundary risk only      | clear          | 95             | 0.5 (boundary) | 77.5             | False                       |

**Findings:**

- The mechanism itself is confirmed correct: when all three signals are genuinely poor simultaneously, `final_confidence` drops sharply (18.0) and `needs_review` correctly triggers. The earlier absence of any real triggered case in Test Cases 1–3 was not a bug — it reflects that real test content never produced simultaneously poor signals across all three dimensions.
- **A single weak signal alone is currently insufficient to trigger review** under the present weighting. Partial (not illegible) OCR legibility alone only drops confidence to 85.5; a boundary-risk score alone (a real, meaningful grading ambiguity) only drops it to 77.5. Both remain comfortably above the 70 threshold.
- Given `llm_confidence` carries the largest weight (0.5) and has empirically stayed in the 95–100 range across every real grading test so far — including a genuinely partial-credit case with visible scratched-out student work (Test Case 2, finding E) — this signal is currently acting as a de facto floor that keeps `final_confidence` high even when other signals indicate real uncertainty. This suggests `llm_confidence` may be a weaker discriminator of actual answer ambiguity than initially assumed, at least for this model and prompt design.

**Implication:** The current threshold (70) and signal weights (0.3 / 0.5 / 0.2) were placeholders, never validated against real data, exactly as flagged at design time. This test confirms they likely under-trigger review in practice — a genuinely ambiguous real answer (Test Case 2's `1b`) did not get flagged despite visible cross-outs and a documented case where shown work and final submitted values diverged. Proper calibration requires a larger hand-graded comparison sample (planned evaluation phase) to determine whether the fix should be a lower threshold, rebalanced weights (reducing reliance on `llm_confidence`), or both.

---

## Test Case 5: Real Batch Processing at Scale — Quiz 5 (40-page PDF, 10 students)

**Setup:** A real, unedited 40-page PDF containing 10 students' quizzes (4 pages each), submitted by an instructor via a common scanning workflow. Used to test the batch upload endpoint end-to-end: fixed-size PDF chunking (`pages_per_student=4`), background sequential processing, per-submission identity extraction, and the `unmatched_segments` safety net (since only 3 of the quiz's 11 actual sub-questions had been seeded with rubrics at test time).

**Preliminary finding — inconsistent internal page ordering within student packets:** Manual inspection confirmed that at least one student's 4-page packet had its 3rd and 4th sheets swapped in physical scan order (verified against each page's own "Page X of 4" printed label), while a second student's packet was in correct order. This rules out a uniform, predictable scanning artifact — page order is not reliable per-student. Verified via an isolated unit test (`_split_pdf` alone, no AI involved) that this reordering originates in the source scan itself, not in the application's PDF-splitting logic — `pdf2image`-based extraction faithfully preserves whatever order exists in the source file. Because the system's OCR-to-question matching is content-based (each page's text is independently read and matched by detected question number) rather than position-based, this disorder did not affect correctness — the sub-question sitting on the "wrong" physical page was still correctly extracted and matched. This is a meaningful architectural validation: order-independent matching, motivated originally by a different concern (multi-segment merging), also happens to make the system robust to a real, unpredictable scanning artifact.

**Batch mechanics — results:**

- 10 submissions correctly created from one 40-page file via fixed chunking; each carries the correct 4-page group.
- Background/sequential processing confirmed working: submissions completed one at a time, `Batch.completed_count` incrementing correctly, without blocking the original upload request (which returned in well under a second).
- `unmatched_segments` correctly preserved substantial, genuine student content across every successfully processed submission — one student alone produced 33 unmatched segments (full workings for questions 2b, 2c, 3, 3a, 3b, 4, 4a, 5a, 5b, 5c), none lost, all ready to be matched once the remaining questions are seeded. This is strong, real-scale confirmation that the safety net built after the earlier duplicate-segment bug generalizes correctly beyond the case that originally motivated it.
- OCR quality held up on more complex real content than any prior single-page test — e.g., one student's full multi-step composed transformation matrix derivation (reflection → rotation → dilation, three matrices multiplied in sequence) was transcribed with correct, clean LaTeX throughout.

**Failure — Gemini API free-tier rate limit:**
5 of 10 submissions failed with `429 RESOURCE_EXHAUSTED` (`generativelanguage.googleapis.com/generate_content_free_tier_requests`, daily limit of 20 requests on `gemini-2.5-flash`). Given ~4–5 real API calls per submission (one per page, occasionally more with retries) plus substantial same-day testing across earlier sessions, the daily quota was exhausted partway through this single 40-page batch.

This is confirmed as an **infrastructure/billing constraint, not an application defect**:

- The existing retry-on-transient-error logic (`gemini_client.py`) correctly identified `429` as retryable and attempted backoff retries as designed.
- Each failed submission's `error_message` was captured accurately and completely (exact quota error, retry-delay guidance), correctly persisted per-submission rather than crashing the batch or silently failing.
- `Batch.status` correctly resolved to `"completed_with_errors"` with an accurate `failed_count: 5` — the system's own status reporting is trustworthy and did not mask the failure.
- No data corruption, no silent loss, no incorrect grading occurred as a result — failed submissions are cleanly distinguishable from successful ones and can be safely retried once quota is available.

**Decision:** This will not be worked around by degrading request volume, batching multiple pages into fewer calls, or other quality-compromising changes to the OCR/grading pipeline. The correct fix is upgrading to a paid Gemini API tier before further large-scale batch testing or deployment. This is documented here as a known, explicit operational constraint of the free-tier development environment, not a system design flaw — a real institutional deployment would require a paid tier budgeted accordingly, which is a reasonable and expected cost of operating an AI-assisted grading system at scale.

**Implication for the report:** This is a legitimate, citable finding about the operational/cost profile of an LLM-dependent grading system — worth stating explicitly rather than omitting, as it reflects a real deployment consideration (API cost/throughput planning) distinct from the model-quality findings in Test Cases 1–4.

---

## Test Case 6: Multimodal Grading Disagreement — Diagram-Based Physics Question

**Setup:** A de-identified, single-page handwritten physics submission was evaluated against a 2.5-point friction-work question. The student calculated the normal force and kinetic-friction force, then used path lengths from a printed top-view diagram to calculate friction work for three paths. The same OCR text and rubric were graded once in `text_only` mode and once in `image_text` mode. Both runs were preserved independently in the `grading_runs` table.

**Ground-truth verification:** Manual inspection of the diagram confirmed the student's path lengths were correct:

- Path 1: 4 + 4 + 1 + 1 + 1 = 11 m
- Path 2: 5 m
- Path 3: 7 m

Therefore the student's three friction-work values and full score of 2.5/2.5 were correct.

| Mode         | Score     | LLM confidence | Final confidence | Latency  | Outcome   |
| ------------ | --------- | -------------- | ---------------- | -------- | --------- |
| Text only    | 2.5 / 2.5 | 100            | 100              | 7.375 s  | Correct   |
| Image + text | 1.0 / 2.5 | 98             | 79               | 13.245 s | Incorrect |

**Failure mode:** The image-enabled run correctly read the student's written calculations, but incorrectly inferred that the diagram's path lengths were 14 m, 8 m, and 10 m. It consequently removed all 1.5 points allocated to the three path-work criteria. The text-only run correctly accepted the student's values.

**Findings:**

- Multimodal input is not inherently safer: visual access introduced a diagram-reasoning error that the text-only run did not make.
- The model was highly confident in the incorrect image-based interpretation (`llm_confidence: 98`), reinforcing the Test Case 4 finding that model self-reported confidence is not a sufficient review signal.
- The existing confidence formula produced 79, above the current review threshold of 70, so the incorrect 1.5-point downgrade was not flagged. This is a concrete real-world false negative for the current `needs_review` policy.
- Persisting each attempt in `grading_runs` was essential: the two modes differed by 1.5/2.5 points (60% of the question score), a disagreement that would have been lost under the former overwrite-only design.
- Image + text took approximately 1.8x longer than text-only in this case (13.245 s vs 7.375 s).

**Implication:** A future routing policy must treat material disagreement between text-only and image-enabled grades as a hard human-review trigger, regardless of either individual run's self-reported confidence. The system must not automatically select the higher score merely because it is more lenient; instead, it should present both criterion-level results to the instructor and withhold automatic finalization until the discrepancy is resolved.

**Data-use note:** This case contains real student identity information in the source upload. It is documented here only as an internal technical finding. It must be redacted or used with appropriate permission before appearing in any thesis dataset, report, or public demonstration.

---

## Test Case 7: Controlled Rubric V1 vs V2 Regrade — Partial Order and Hasse Diagram

**Setup:** The same MATH203 Question 2g answer, source image, grading mode (`image_text`), and human reference score were evaluated using the original coarse schema-1 rubric and the approved granular schema-2 rubric. The V2 rubric separated reflexivity, antisymmetry, transitivity, and the Hasse diagram into independently scored criteria.

| Rubric/prompt                 | Mode         | AI score   | Human score | Absolute error | Final confidence |
| ----------------------------- | ------------ | ---------- | ----------- | -------------- | ---------------- |
| Schema 1 / `v1`               | Image + text | 0.75 / 3.0 | 3.0 / 3.0   | 2.25           | 97.5             |
| Schema 2 / `v2-rubric-policy` | Image + text | 3.0 / 3.0  | 3.0 / 3.0   | 0.0            | 100.0            |

**Findings:**

- The coarse single criterion (`q_2g_complete`) allowed one disputed interpretation to suppress nearly the entire score. The granular V2 criteria localized the required evidence and produced exact agreement with the instructor.
- All four V2 criteria achieved exact criterion-level agreement in this controlled case.
- The V1 result was a high-confidence error: it was wrong by 2.25 points while reporting `final_confidence: 97.5`. Rubric structure improved the decision, but the comparison again shows that model confidence alone is not a reliable correctness estimate.
- Because this is one answer regraded under two rubric versions, it is paired evidence of a corrected failure mode, not proof that V2 will improve every subject or question.

---

## Test Case 8: Controlled Multimodal Counterfactual — Graph Isomorphism Matrices

**Setup:** The same MATH203 Question 5d answer and approved V2 rubric were graded in both `text_only` and `image_text` modes. OCR retained only the conclusion, "graphs are isomorphic," while the source page visibly contained matching handwritten adjacency matrices that justified the conclusion. The instructor reference score was 2.0/2.0.

| Rubric/prompt                 | Mode         | AI score  | Human score | Absolute error | Final confidence |
| ----------------------------- | ------------ | --------- | ----------- | -------------- | ---------------- |
| Schema 2 / `v2-rubric-policy` | Text only    | 0.5 / 2.0 | 2.0 / 2.0   | 1.5            | 40.0             |
| Schema 2 / `v2-rubric-policy` | Image + text | 2.0 / 2.0 | 2.0 / 2.0   | 0.0            | 100.0            |

**Findings:**

- This is direct evidence that multimodal grading can recover valid student evidence omitted by OCR. The image-enabled run explicitly recognized the matching adjacency matrices and awarded the representation and justification criteria correctly.
- Text-only grading correctly evaluated the evidence it received, but that evidence was incomplete. It therefore cannot safely grade diagram-, graph-, or handwritten-matrix-dependent criteria without either visual input or human review.
- The 1.5-point mode disagreement was correctly treated as material. The review mechanism lowered the retained result's confidence to 40 and required review while preserving the instructor's existing override.
- This complements Test Case 6 rather than contradicting it: images can either recover missing evidence or introduce visual-reasoning errors. Adaptive routing and disagreement review are therefore safer than always trusting either mode.

### Evaluation snapshot after Test Cases 7–8

The evaluation endpoint contained five versioned run-level labels across two answers:

| Cohort           | Labels | MAE   | Exact agreement | Within +/-1 point |
| ---------------- | ------ | ----- | --------------- | ----------------- |
| Schema 1 + image | 2      | 1.625 | 0.0%            | 50.0%             |
| Schema 2 + image | 2      | 0.000 | 100.0%          | 100.0%            |
| Schema 2 + text  | 1      | 1.500 | 0.0%            | 0.0%              |

Across all five run-level labels, MAE was 0.95, exact agreement was 40%, and within-1-point agreement was 60%. Review-flag precision was 100% (1 true positive, 0 false positives), but recall was only 33.33% (2 historical false negatives). These figures are descriptive only: the sample contains just two unique student answers and deliberately includes multiple counterfactual runs per answer, so it is not representative of deployment performance.

**Data-use note:** These tests use real student work. Any thesis publication, presentation, or public demonstration must use permission or properly de-identified reproductions.

---

## Test Case 9: AI-Generated Rubric Lifecycle — Graph Isomorphism

**Setup:** The existing MATH203 Question 5d was used to test the complete instructor-controlled AI-rubric workflow. The system generated a new Rubric V2 draft using the saved question, current active rubric, instructor answer key, expected method, grading approach, and instructor notes. The instructor reviewed and edited the draft before approving it as version 3. The same answer was then regraded in `image_text` mode and compared with the known human score.

**Lifecycle verified:**

1. `POST /api/questions/{question_id}/suggest-rubric-version` created rubric version 3 with `source: ai` and `status: draft`.
2. The previously approved rubric remained active while the AI version was a draft.
3. The instructor edited wording and common-error guidance through the draft-update endpoint.
4. Explicit approval activated version 3; earlier grading runs retained their original rubric snapshots.
5. The new grading run stored the exact approved rubric-version identifier and full rubric snapshot.
6. An evaluation-only instructor label was attached to the new run without replacing the answer's existing human override.

| Field               | Result                                                       |
| ------------------- | ------------------------------------------------------------ |
| Rubric version      | `ac9c50d1-531e-470b-ad3f-cf22b350a2bc` (schema 2, version 3) |
| Grading run         | `a9f665cd-1cf6-4ee4-b3f2-ae0ec3c16885`                       |
| Mode                | Image + text                                                 |
| AI score            | 2.0 / 2.0                                                    |
| Human score         | 2.0 / 2.0                                                    |
| Absolute error      | 0.0                                                          |
| Criterion agreement | Exact on all three criteria                                  |
| Latency             | 12.985 s                                                     |

**Findings:**

- The AI-generated rubric correctly separated the isomorphism conclusion (0.5), graph representation (0.75), and isomorphism justification (0.75). It explicitly treated accurate matching adjacency matrices as mathematical justification without requiring redundant prose.
- Multimodal grading used source page 6 and awarded exact full credit on all three criteria, matching the instructor's score and interpretation.
- Version lineage worked end to end: the run references the approved AI rubric version, while prior schema-1 and schema-2 runs remain reproducible from their own snapshots.
- The run retained `final_confidence: 40` and `needs_review: true` because it materially disagreed with the earlier text-only result (0.5 versus 2.0). The instructor confirmed that this disagreement warranted review, making the flag a true positive even though the image-enabled score itself was correct.
- The answer's prior `review_status: overridden` and teacher score remained intact because the new label was created with `apply_as_current: false`. This confirms that evaluation experiments do not silently erase instructor decisions.

### Evaluation snapshot after Test Case 9

The endpoint contained six versioned run-level labels across the same two unique answers:

| Cohort           | Labels | MAE   | Exact agreement | Within +/-1 point |
| ---------------- | ------ | ----- | --------------- | ----------------- |
| Schema 1         | 2      | 1.625 | 0.0%            | 50.0%             |
| Schema 2         | 4      | 0.375 | 75.0%           | 75.0%             |
| Schema 2 + image | 3      | 0.000 | 100.0%          | 100.0%            |
| Schema 2 + text  | 1      | 1.500 | 0.0%            | 0.0%              |

Across all six run-level labels, MAE was 0.7917, exact agreement was 50%, and within-1-point agreement was 66.67%. Review-flag precision remained 100%; recall increased from 33.33% to 50% after the new material-disagreement flag was human-verified as warranted (2 true positives, 0 false positives, and 2 historical false negatives).

**Limitation:** These figures contain repeated counterfactual and rubric-version runs on only two unique student answers. They validate mechanics and document specific corrected failure modes, but they must not be reported as population-level grading accuracy.

---

## Test Case 10: Instructor Leniency Calibration — Fall 2024 Graph Isomorphism

**Setup:** A fresh upload of the instructor-verified MATH203 Fall 2024 assignment completed extraction for 17 atomic answers with page provenance and zero unmatched segments. Question 5d asked whether two printed graphs were isomorphic. The instructor awarded the handwritten response 2.0/2.0 under a deliberately lenient grading policy.

The answer correctly concluded that the graphs were not isomorphic, reported six vertices and eight edges for each graph, listed neighborhoods for selected vertices, and stated that the adjacency structures differed. The instructor accepted this concise, visually supported reasoning without requiring a formal statement about invariants or adjacency-preserving bijections.

### Rubric calibration

An AI-generated balanced V2 rubric was reviewed before approval. Its original draft reserved points for preliminary vertex/edge/degree checks, which would unfairly cap an elegant direct proof below full credit. The instructor-edited version instead separated the conclusion, decisive structural evidence, and logical connection.

The balanced image run awarded 1.25/2.0 with `final_confidence: 97.5` and did not request review. The instructor overrode it to 2.0/2.0. This is a high-confidence false negative showing that technically defensible rubric strictness can still disagree with the instructor's intended pedagogy.

A lenient V3 rubric was then generated and explicitly calibrated to accept the student's concise neighborhood comparison as full-credit reasoning when supported by the visible graph.

| Rubric      | Mode         | AI score   | Human score | Absolute error | Final confidence        | Review flag |
| ----------- | ------------ | ---------- | ----------- | -------------- | ----------------------- | ----------- |
| Balanced V2 | Image + text | 1.25 / 2.0 | 2.0 / 2.0   | 0.75           | 97.5                    | False       |
| Lenient V3  | Image + text | 1.0 / 2.0  | 2.0 / 2.0   | 1.0            | 67.5                    | True        |
| Lenient V3  | Text only    | 2.0 / 2.0  | 2.0 / 2.0   | 0.0            | 40.0 after disagreement | True        |

### Multimodal failure

The lenient image-enabled run introduced a factual graph-reading error. It claimed Graph H had six edges and omitted the visible horizontal edge between `v6` and `v2`; it also rejected the student's neighborhood lists. Visual inspection confirmed that both graphs have eight edges and that the student's listed neighborhoods match the printed graph. The paired text-only run, using the same lenient rubric, awarded the instructor-verified 2.0/2.0.

**Findings:**

- Instructor strictness is not merely a UI preference. It must change observable performance-level descriptions and evidence requirements; changing only a policy label does not reliably change grading behavior.
- A lenient policy should accept concise or implicit reasoning only when the intended mathematical connection is unambiguous. It should not make factually incorrect work correct.
- Image access again proved non-monotonic: it caused a graph-reading hallucination even though OCR had preserved the student's correct written counts and neighborhoods.
- The material mode-disagreement gate worked as intended for the lenient pair: the 1.0-point difference triggered review and reduced final confidence to 40 while preserving the instructor's override.
- The balanced high-confidence error was not caught, reinforcing that self-reported confidence and a fixed confidence threshold remain insufficient without calibrated instructor labels.

### Fall 2024 evaluation snapshot

This exam currently has three run-level labels for one unique answer. Overall MAE is 0.5833, exact agreement is 33.33%, and within-1-point agreement is 100%. Review precision is 100% and recall is 66.67% (2 true positives, 0 false positives, and 1 false negative). These values describe this controlled case only and are not population-level accuracy measurements.

**OCR coverage note:** The fresh nine-page upload extracted 17 of the 20 seeded atomic answers. Questions 1a-1c were not mapped, likely because their responses use highlighting/selection formatting rather than ordinary handwritten answer segments. This should be investigated separately as an answer-format coverage gap.

---

## Test Case 12: CS2071 Visual-Evidence Routing Failure

**Setup:** A six-page handwritten Database Systems midterm was extracted into three configured questions. Question 1 required an EER diagram, Question 2 required a relational schema drawn from a supplied ER diagram, and Question 3 contained six handwritten SQL tasks.

The first automatic run used OCR text only for every question because no question policy existed. Question 1 was incorrectly penalized for not drawing a diagram even though the source page visibly contained one. Question 2 was incorrectly penalized for not marking primary and foreign keys because OCR flattened the student's underlines and reference arrows. Question 3 was correctly graded from text after its handwritten-SQL policy was made lenient.

Image + text regrading changed Question 1 from 2.0/6.0 to 5.0/6.0 and Question 2 from 2.0/4.0 to 3.5/4.0. Both material disagreements were capped at 40 confidence and routed to instructor review. The instructor awarded 6.0/6.0 and 4.0/4.0 respectively. The resulting two image-run labels have MAE 0.75, 0% exact agreement, 100% within-one-point agreement, and review precision/recall of 100% for this controlled case.

**Implemented correction:**

- Added simple per-question grading input modes: `adaptive`, `image_text_required`, and `text_only`.
- `auto` now uses the original page for questions whose text, rubric, or OCR provenance indicates diagrams, schemas, graphical notation, or mathematical work.
- A text-only run that lacks required visual evidence is capped at 40 confidence, marked for review, and records `visual_evidence_not_seen`.
- Rubric Studio exposes the setting as Adaptive, Image + text required, or Text only. The two visual CS2071 questions are now configured as image + text required.

**Limitation:** This case validates routing and review mechanics for two visual answers. It does not establish population-level accuracy or prove that image access always improves grading; earlier graph tests show that image-enabled grading can also introduce visual hallucinations.

---

## Open items for future evaluation work

1. Expand the hand-graded sample and calibrate `needs_review`; the current five run-level labels yield 100% precision but only 33.33% recall, with two historical false negatives.
2. Quantify OCR run-to-run consistency systematically (run N images × M repetitions each, measure segment-count and label variance).
3. Build a small labeled test set specifically containing scratched-out/reworked handwritten work to study how consistently OCR handles it.
4. Investigate whether the C32/C23 subscript misread is specific to this handwriting sample or a broader pattern — test against additional cofactor/subscript-heavy math content.
5. Measure identity-extraction accuracy across a larger sample of handwritten names/IDs to get a real error rate, not just anecdotal examples.
6. Determine appropriate paid-tier Gemini API request quota/budget needed to support realistic batch sizes (e.g., a 40-page, 10-student batch consumed the entire free-tier daily allowance on its own) before any larger-scale evaluation or demo involving multiple batches in one day.

## Test Case 11: Local VLM Fallback — Qwen2-VL-2B (4-bit Quantized)

**Motivation:** All prior test cases ran exclusively on Gemini 2.5 Flash via API. Given hardware constraints (RTX 3050, 4GB VRAM) and the free-tier quota ceiling documented in Test Case 5, tested whether a local, quantized VLM could serve as a fallback for OCR extraction — avoiding API cost/quota entirely for at least a subset of pages.

**Setup:** Qwen2-VL-2B-Instruct, 4-bit GGUF quantization, run locally on consumer hardware (RTX 3050, 4GB VRAM). Same `OCR_PROMPT` and `OCRPageResult` schema as the Gemini pipeline, applied to a high-school-level Arabic math exam page (mixed Arabic prose and handwritten mathematical notation). Ran 5 independent passes over the same page to check consistency as well as raw accuracy.

**Findings:**

- Mathematical notation extraction failed completely across all 5 runs — equations were either omitted entirely, replaced with unrelated symbols, or emitted as malformed LaTeX that did not parse. Not a single equation was transcribed correctly or consistently across runs.
- Arabic text output was garbled and incoherent in all 5 runs — output strings did not form valid or meaningful Arabic words in the majority of segments, unlike Gemini's clean, grammatically coherent Arabic transcription seen in Test Cases 1–3.
- `question_number` and segment labeling was unreliable — segments were frequently mislabeled, merged incorrectly, or dropped, with no consistent pattern across the 5 runs (unlike the systematic, explainable inconsistencies documented for Gemini in Test Case 2, Finding B).
- Estimated accuracy loss relative to Gemini 2.5 Flash on this content type is approximately 90% — i.e., the model was correct on roughly one-tenth as much content as Gemini on the same page, based on informal comparison against the known-correct answer key.
- The failure mode did not resemble a prompt-calibration issue (as seen and fixed via prompt iteration in Test Case 1) — it reflected a fundamental capability gap for this model size and quantization level on Arabic-script, math-heavy handwritten content. No further tuning was attempted, as the gap was too large to plausibly close through prompt engineering alone.

**Implication:** A 4-bit quantized 2B-parameter VLM on 4GB consumer VRAM is not viable for this project's OCR accuracy requirements, particularly for Arabic and STEM notation — the two content types most central to MISRA-EDU's differentiator. This is a legitimate, citable finding on the cost/infrastructure tradeoff for institutional deployment: achieving the accuracy this system requires means either (a) a paid LLM API budget (Gemini or equivalent hosted model), or (b) GPU infrastructure capable of running a substantially larger local model at full or near-full precision, well beyond what a 4GB consumer GPU with aggressive quantization can support.
