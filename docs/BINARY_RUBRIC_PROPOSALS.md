# Experimental binary rubric proposals

`services/binary_rubric_proposal.py` is an opt-in offline adapter. It accepts
explicit `met`, `unmet` or `uncertain` decisions for an already approved binary
rubric and produces the existing `GradingResult` shape. It performs no provider
call, database write, guide approval or live workflow change.

Provider numeric marks, maxima and totals are forbidden in this contract. A new
proposal gets each criterion's approved weight for `met` and zero for `unmet`.
An `uncertain` verdict abstains for the entire answer; it does not become a zero
grade. Duplicate/missing/unknown criterion IDs, implicit or partial-credit rubrics,
nonfinite values and inconsistent approved maxima fail validation.

The caller must first validate the approved guide and source scope, build the
standard privacy-filtered provider package, preserve the raw classification,
restore/validate evidence citations and run the existing independent verification
and review checks. The adapter preserves verdicts and standard citation fields.
It does not infer correctness from a reason string or repair an earlier score.
Model confidence remains uncalibrated.

This experiment addresses responses that describe a criterion as satisfied while
returning zero marks. Deriving new proposal marks from one explicit classification
removes a redundant numeric decision. It cannot ensure the classification itself
is right. Compare it against the numeric contract with identical approved inputs,
RAG, model settings and prescheduled repeats; include abstentions and contract
failures in the scheduled denominator. Do not select the higher grade per answer.

The physics pilot is a reused-answer regression. The live grading contract,
routers, database and frontend continue to use their existing path. Promoting
this alternative requires evidence beyond passing structural tests.
