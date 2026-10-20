# Review routing and retrieval metrics

The server sums validated criterion marks while retaining conflicting model
totals and original response attempts for review. It never rounds, repairs or
infers criterion credit. Invalid IDs, maxima, scores, evidence and required course
citations still fail validation. Historical runs stay unchanged.

`review_policy_service.py` records the review-policy version, thresholds, signals
and reason codes for each new run. Raw and blended confidence thresholds are
uncalibrated operational heuristics. Missing verification, unclear extraction,
total discrepancies and evidence concerns independently require review. Matching
text/image grades cannot clear these gates. Review does not approve a grade.

`review_metrics_service.py` reports explicit confusion counts, disagreement recall
and precision, scoring coverage, exact yield over scheduled answers, workload and
disagreements among unflagged proposals. Missing, failed and abstained proposals
need attention but never become zero grades or caught grading errors. Undefined
rates remain null. A review count does not measure time saved.

`hybrid_rrf_v1` combines bounded BM25 and character TF-IDF cosine ranks. It is a
lexical hybrid, not a semantic embedding model. The optional neural strategies
are described in [Local embeddings and reranking](NEURAL_RETRIEVAL.md). All use
the same checked-page, approved-scope, ownership and citation safeguards; student
answers and historical grades never control the query or source scope.

Use synthetic software regressions for implementation checks and separately
frozen paper-level studies for empirical evaluation. Keep paper-specific findings,
reference labels, costs and original provider responses in ignored private
directories. New diagnostics cannot overwrite a sealed comparison.
