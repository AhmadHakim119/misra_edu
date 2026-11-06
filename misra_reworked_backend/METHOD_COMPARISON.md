# Independent comparison methods

`run_comparison_methods.py` evaluates each method separately on the same frozen
question/model answer and cases. It does not combine scores or change an approved
guide. All grade outputs are research proposals pending instructor review.

Covered families:

- Qwen embeddings: cosine, raw dot product, L2, L1 and angular similarity.
- Lexical: BLEU-4 with declared smoothing; ROUGE-1/2/L; word error rate and
  character Levenshtein similarity. An additional ROUGE variant preserves math
  operators instead of discarding them during tokenization.
- Concept/keyword coverage: explicit reference-derived alias groups, TF-IDF,
  RAKE weighting and a pretrained English named-entity recognizer.
- BERTScore precision/recall/F1 using the declared local DistilBERT configuration.
- Local DeBERTa NLI: forward/bidirectional entailment, sentence contradiction
  signals and per-criterion claim support. Raw three-class scores are retained.
- Local Qwen rubric grading on every case, including constructed stress cases.

Higher-is-better score orientation is explicit: distance scores use the negative
distance and WER uses 1-WER. Negative WER similarity is permitted when insertions
exceed reference length; it is not silently clipped. Scores are not calibrated
correctness probabilities.

Thresholds are fitted only on instructor-confirmed A/B calibration labels.
Constructed stress expectations do not select thresholds. A method that cannot
separate A from B can abstain on all cases; zero errors at zero coverage is not
a successful grader. Inapplicable NER has null scores when no reference entities
exist rather than being interpreted as a perfect match.

Angular distance is a monotonic transform of cosine. For normalized vectors,
dot product equals cosine and squared L2 equals 2-2*cosine. Such changes cannot
improve rankings merely by stretching the score scale. Raw magnitude variation
and L1 are recorded separately rather than assumed to solve contradictions.

## Isolated runtime

Use the optional pinned `requirements-methods.txt` in an experiment environment;
these packages are not added to the app's main requirements. The recorded pilot
environment reused existing PyTorch/NumPy and installed compatible local metric
and Transformers versions. Preserve the package manifest for reproduction.

Download trusted public model data separately, pin the repository revision and
file hashes, and use safetensors with local-only model loading. Student text is
processed locally; model downloads do not require sending answer data to an
external inference service. Offline encoders use CPU; the Qwen judge uses the
existing loopback Ollama service.

```powershell
& <experiment-python.exe> .\misra_reworked_backend\run_comparison_methods.py --source <frozen-comparison-run> --features <reference-derived-features.json> --models <pinned-model-manifest.json> --output .\private\<new-run> --run-llm
```

The judge uses `qwen3:4b-instruct`. Constructed text has distinct provenance and
cannot claim to be visually verified OCR. Full source pages and cancelled work
remain preserved; only active work is scored. There are no automatic retries,
provider fallbacks, database writes or automatic final-grade approval.

Each family saves its original scores, settings and timing. Failures remain
explicit. CPU batch timing, setup/loading and shared embedding cost are distinct
from total upload-to-review time. General grading accuracy, instructor workload
and monetary savings require independent labeled data and separate measurement.

## Handwritten paragraph pilot

`paragraph_experiment.py` collects draft OCR answers and compares them with
private rubric references. `ocr_quality_experiment.py` uses the same mapping
configuration to measure transcription error against checked text. Keep scans,
rubrics, annotations, scores and the `paragraph-config.json` file under the
ignored experiment directory passed as `--root`.

The configuration has three fields. `anchors` maps page positions `"1"` and
`"3"` to two boundary entries in the form
`[question_id, printed_text, min_y_fraction, max_y_fraction]`. `prompt_endings`
maps question IDs to the last printed line before the answer. `claims` maps
question IDs to lists of criterion statements for local entailment scoring.
