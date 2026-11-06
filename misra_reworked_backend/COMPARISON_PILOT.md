# Comparison-first grading experiment

`comparison_pilot.py` evaluates a deliberately simple research baseline alongside
a fresh Qwen-only run. It calls the loopback Ollama service, not the application
database. It neither publishes marking guides nor finalizes grades.

1. Embed the model answer and active student text with a local Qwen embedding model.
2. Compare vectors using cosine similarity. Never interpret this as a probability.
3. Above the frozen threshold, propose full credit; otherwise call local Qwen.
4. Validate outputs and keep all proposed results pending instructor review.

This initial comparator proposes full credit only. Low similarity cannot assign
zero or partial credit. Per-criterion semantic classifiers and richer level
exemplars are future experiments, not capabilities demonstrated by this baseline.
Matching a whole paragraph cannot itself establish every rubric criterion.

## Calibration and testing

Use `--fit-calibration` only with calibration references. The fitter maximizes
coverage subject to zero observed candidate errors on those examples; this is
not a guarantee of future correctness. It may disable bypass entirely if no
threshold can separate incorrect and correct full-credit candidates.

For later testing, pass a previously frozen `--policy` instead. Policy bindings
include the rubric, embedding digest and comparator version. Calibration paper
hashes/IDs cannot be reused under a test label. Test labels never fit thresholds,
and the test report evaluates only the frozen threshold, not a threshold sweep.
For larger data, split by student and duplicate-answer groups before calibration;
use held-out questions separately when evaluating transfer to new questions.

Reference labels are stored separately from model requests. A/B comparisons of
the two original papers are development diagnostics once used to tune a policy.
Constructed paraphrase/negation examples are stress tests with declared developer
expectations. They are not independently marked evaluation data.

## Measured outputs

- Comparison coverage and errors among comparison-resolved proposals.
- Referral recall, precision and F1 for **full-credit candidate errors**.
- Criterion and total reference agreement, MAE, scored/unscored counts.
- Actual embedding/grading call counts and elapsed stage times.
- Unsafe full-credit candidates and unnecessary fallbacks on stress cases.

OCR, instructor review effort, energy and monetary savings are left unmeasured.
Serial arms are affected by loading and prompt caches; their timing is a
diagnostic observation, not a controlled speedup estimate. Local inference has
no per-request grading API charge; hardware and human costs remain separate.

## Runtime and invocation

Uses the existing Python environment and Pydantic. No additional Python ML stack
is required. Ollama must already have the named local grading and embedding
models. The small embedding model runs on CPU to limit competition for GPU VRAM.
Missing models, malformed vectors or truncated inputs fail rather than silently
switching providers or manufacturing grades.

```powershell
& .\misra_reworked_backend\.venv\Scripts\python.exe .\misra_reworked_backend\comparison_pilot.py --guide <private-guide.json> --answers <private-answers.json> --references <private-references.json> --stress-cases <private-stress-cases.json> --output .\private\<new-run> --fit-calibration --diagnostic-draft
```

All output directories must be new and under ignored `private/`. Save full source
pages separately and retain crossed-out content in evidence snapshots; only
active text reaches the comparison and grading models.

Tests use synthetic fixtures and mocked local model transport:

```powershell
Set-Location misra_reworked_backend
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```
