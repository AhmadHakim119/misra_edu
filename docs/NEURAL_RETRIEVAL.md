# Local embeddings and reranking

MISRA supports local BGE-M3 cosine retrieval, optional BM25 rank fusion and
BGE-reranker-v2-m3. DeepSeek/Gemini/provider
selection remains separate. This adds retrieval capabilities without a vector
database, schema migration or frontend change.

## Strategies

| Setting | Retrieval |
| --- | --- |
| `bm25_v1` | Established BM25 baseline |
| `hybrid_rrf_v1` | Earlier lexical BM25 + character TF-IDF experiment |
| `bm25_rerank_v1` | BM25 candidates, then local cross-encoder reranking |
| `neural_hybrid_v1` | BM25 + dense embeddings, rank fusion, then reranking |
| `dense_v1` | BGE-M3 vectors ranked directly by cosine similarity; no BM25 or reranker |
| `dense_rerank_v1` | Cosine candidates, then BGE reranking; no BM25 |

`MISRA_RETRIEVAL_STRATEGY` selects grading and source-preview retrieval. The source
consultation preserves an explicitly selected neural strategy. Authoring proposals
retain their existing BM25 path. Selecting a neural strategy does not approve a
guide, enable an otherwise disabled source scope or change an historical run.

## Setup

The optional dependencies are pinned in `misra_backend/requirements-neural.txt`.
Use a project environment and an appropriate CPU/CUDA PyTorch build. Do not upgrade
the running OCR environment in place. Downloading the public model weights is an
explicit setup action:

```powershell
.\misra_ocr_env\Scripts\python.exe misra_backend/scripts/setup_neural_retrieval.py --download
.\misra_ocr_env\Scripts\python.exe misra_backend/scripts/setup_neural_retrieval.py
```

The second command verifies local assets without downloading anything. Both model
revisions and individual asset hashes are recorded. BGE-M3's pinned upstream
revision supplies a PyTorch checkpoint; provisioning converts it to safetensors
using a plain tensor state dictionary. This conversion requires **PyTorch 2.10.0
or newer** because older weights-only loaders have
[CVE-2026-24747](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p).
Already provisioned safetensors snapshots require no further checkpoint conversion.
Runtime inference uses `local_files_only=True`, `trust_remote_code=False` and
`use_safetensors=True`; it never loads the original checkpoint or downloads weights.

Configure future API/worker processes with:

```dotenv
MISRA_RETRIEVAL_STRATEGY=dense_rerank_v1
MISRA_RETRIEVAL_DEVICE=cuda
```

Use `cpu` on machines without CUDA. Device changes require restarting the process;
there is no automatic model/provider/device fallback. Restart the API and RQ worker
after configuration changes. Existing academic records are not regraded. Each
worker maintains its own models; use one GPU worker on a small GPU or explicitly
select CPU. First use includes model verification/loading; warm calls are faster.

## Bounds and provenance

Ownership, checked-page approval, exact passage bindings and integrity validation
run **before** neural inference. Retrieval queries use the question and criterion,
never student OCR, teacher marks or student-supplied instructions. Both retrievers
search the same eligible passages. Each retrieves at most 20 candidates; rank
fusion supplies at most 24 candidates to the reranker, including exact links.
The two dense strategies never call BM25 or fuse lexical ranks. They select the
top 20 cosine candidates plus exact links within the same 24-candidate limit.
`dense_v1` returns reciprocal cosine ranks to the selection layer and records raw
cosines separately, so negative cosine values do not get discarded as missing
results. `dense_rerank_v1` applies the cross-encoder only to that dense shortlist.
Neither strategy changes source approval, query construction or context limits.

Original whole passages and offsets remain intact. Existing limits of 6,000
candidates, eight selected passages and 12,000 context characters remain. Neural
selection covers criteria before adding extra passages. Inputs exceeding the
2,048-token neural ranking budget fail explicitly; the code does not silently
truncate equations. Scores and raw reranker logits express ranking, **not** grading
confidence or calibrated relevance probabilities. Required course citations still
must apply to the criterion; citation IDs do not establish academic support.

Derived vectors live in ignored `.local/neural-embeddings/`, keyed by scope,
institution, model revision and content hash. Cache files contain vectors and
checksums, not original source text; no pickle cache is used. Corrupt derived
entries are recomputed locally. Model weights live in ignored `.local/neural-models/`.
Missing or changed assets, invalid vectors, invalid logits and selected-neural
failures stop retrieval before grading; they do not silently return a lexical run.

Grading snapshots retain the strategy, pinned model revisions, candidate ranking
details, criterion links and source provenance. Explicit research strategy arguments
leave the historical BM25 default unchanged. Use a new experiment directory for
every comparison; never replay a sealed study with changed code.


## Evidence and limits

Synthetic regressions exercise approved-source boundaries, cosine ranking,
reranking, cache integrity and missing-model failure behavior. They do not
demonstrate grading accuracy. Actual paper-level attempts, scores, source audits,
costs and findings remain in ignored versioned evaluation directories.

Evaluate retrieval relevance, grading agreement, failure coverage and latency
separately. Two rankers can select the same final passages, and different passages
can produce the same grade. Audit the actual provider payloads before interpreting
a tied comparison. Reused examples provide regression evidence rather than an
untouched evaluation sample. Embeddings and reranking do not repair handwriting.

## Optional definition-bound concept queries

`services/retrieval_query_service.py` binds each proposed concept query to a hash
of the exact approved question and criterion, including its mark allocation.
The opt-in record must cover every criterion exactly once. Changed definitions,
missing/unknown records, invalid provenance or extra student/reference-score fields
fail validation. No model is called by this helper and it cannot approve a guide
or expand the eligible source corpus.

The existing query bytes and BM25 default remain unchanged when no concept records
are supplied. Both the research runner and the internal retrieval service accept
explicit records after their normal approval/ownership checks. Provider grading
packages omit query-generation metadata and retain the actual approved passages.


Short concept queries can retrieve explanatory passages when symbolic criterion
wording matches the wrong topic. Evaluate them against the same approved corpus,
preserve original contexts, and use a new version for each comparison. Retrieval
support, grade agreement and instructor acceptance remain separate measurements.
