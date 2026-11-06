"""Compare score families on frozen A/B calibration and declared stress cases."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
from time import perf_counter

import rubric_pilot as grading
from comparison_methods import VERSION, keyword_scores, lexical_scores, normalize_scores, summarize_method, vector_scores
from neural_comparison_methods import bertscore_scores, ner_scores, nli_scores
from semantic_comparison import active_text, validate_vectors


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run(source, feature_path, manifest_path, output, *, run_llm=False):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    protocol = read(source / "protocol.json")
    guide = grading.Guide.model_validate(protocol["guide"])
    answers = [grading.Answer.model_validate(a) for a in protocol["answers"]]
    stress = read(source / "stress-cases.json")
    references = read(source / "reference-labels.json")
    if references["split"] != "calibration":
        raise ValueError("This development runner cannot fit policies from test labels.")
    features = read(feature_path)
    if features["guide_sha256"] != grading.digest(guide.model_dump()):
        raise ValueError("Feature descriptions must match the frozen guide.")
    ids = [a.answer_id for a in answers] + [s["id"] for s in stress]
    texts = [active_text(a) for a in answers] + [s["text"] for s in stress]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate cases.")
    cached_request = read(source / "embedding-request.json")
    if cached_request["input"] != [guide.model_answer, *texts]:
        raise ValueError("Cached embeddings must bind to these exact texts in order.")
    vectors = validate_vectors(read(source / "embedding-response.json"), cached_request["model"], len(texts) + 1)
    models = read(manifest_path)
    for model in models.values():
        for filename, expected in model["files_sha256"].items():
            if hashlib.sha256((Path(model["path"]) / filename).read_bytes()).hexdigest() != expected:
                raise ValueError("Pinned model file changed.")
    output.mkdir(parents=True, exist_ok=False)
    grading.save_new(output / "protocol.json", {
        "version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "source_run": str(source.resolve()), "source_protocol_sha256": hashlib.sha256((source / "protocol.json").read_bytes()).hexdigest(),
        "guide": guide.model_dump(), "features": features, "models": models,
        "case_ids": ids, "case_texts": texts, "references": references, "stress_cases": stress,
        "packages": {name: importlib.metadata.version(name) for name in
                     ["torch", "transformers", "bert-score", "rouge-score", "nltk", "rake-nltk", "numpy", "scikit-learn"]},
        "source_hashes": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ["run_comparison_methods.py", "comparison_methods.py", "neural_comparison_methods.py", "rubric_pilot.py"]},
        "execution": "CPU scorers sequentially, followed by optional local Ollama judge",
        "labels_in_model_requests": False, "automatic_retries": 0,
    })
    all_scores, timings, failures = {}, {}, {}
    def store_family(name, function):
        started = perf_counter()
        try:
            values, details = function()
            values = {name: normalize_scores(scores) for name, scores in values.items()}
            if any(len(scores) != len(ids) for scores in values.values()):
                raise ValueError("A scorer omitted scheduled cases.")
            for method, scores in values.items():
                all_scores[method] = dict(zip(ids, scores))
            timings[name] = {"total_elapsed_ms": round((perf_counter() - started) * 1000, 3), **details}
            grading.save_new(output / (name + ".json"), {"scores": values, "details": timings[name]})
            print("Completed " + name, flush=True)
        except Exception as error:
            failures[name] = {"type": type(error).__name__, "message": str(error)[:1500]}
            grading.save_new(output / (name + "-failure.json"), failures[name])
            print("Failed " + name + ": " + type(error).__name__, flush=True)
    def geometry():
        rows = [vector_scores(vectors[0], vector) for vector in vectors[1:]]
        norms = [math.sqrt(math.fsum(v * v for v in vector)) for vector in vectors]
        return {name: [r[name] for r in rows] for name in rows[0]}, {
            "vector_norm_min": min(norms), "vector_norm_max": max(norms),
            "embedding_backbone": cached_request["model"], "vectors": "exact frozen vectors from source experiment",
            "shared_encoder_time_ms_in_source": read(source / "report.json")["comparison_first"]["embedding_stage_ms"],
            "note": "Angular similarity is monotonic in cosine. Unit-normalized dot and L2 preserve its ranking."}
    store_family("geometry", geometry)
    def lexical():
        rows, details = [], []
        for text in texts:
            scores, info = lexical_scores(guide.model_answer, text, features["concepts"])
            rows.append(scores)
            details.append(info)
        return {name: [row[name] for row in rows] for name in rows[0]}, {"cases": details, "bleu_smoothing": "NLTK method1; uniform BLEU-4 weights"}
    store_family("lexical", lexical)
    setup_texts = [guide.question, guide.model_answer, *[level.description for c in guide.criteria for level in c.levels]]
    store_family("keywords", lambda: keyword_scores(guide.model_answer, texts, setup_texts))
    import torch
    torch.set_num_threads(4)
    store_family("bertscore", lambda: bertscore_scores(models["bertscore"]["path"], guide.model_answer, texts))
    store_family("nli", lambda: nli_scores(models["nli"]["path"], guide.model_answer, texts,
                                           [features["nli_claims"][c.id] for c in guide.criteria]))
    store_family("ner", lambda: ner_scores(models["ner"]["path"], guide.model_answer, texts))
    if run_llm:
        started = perf_counter()
        llm_results, llm_scores = [], []
        all_answers = [*answers, *[grading.Answer.model_validate({
            "answer_id": item["id"], "source_sha256": hashlib.sha256(item["text"].encode()).hexdigest(),
            "transcription_method": "synthetic_text", "transcription_status": "constructed_fixture",
            "segments": [{"id": "synthetic_segment", "text": item["text"], "crossed_out": False}],
        }) for item in stress]]
        for answer in all_answers:
            result = grading.run_pilot(guide, [answer], output / "llm" / answer.answer_id,
                                        "qwen3:4b-instruct", diagnostic_draft=True)["results"][0]
            llm_results.append(result)
            llm_scores.append(result["score"] / guide.max_points
                              if result.get("score") is not None and result["status"] == "proposed" else None)
            print("Qwen judge " + answer.answer_id + ": " + result["status"], flush=True)
        all_scores["qwen_rubric_judge"] = dict(zip(ids, llm_scores))
        timings["qwen_rubric_judge"] = {"total_elapsed_ms": round((perf_counter() - started) * 1000, 3),
                                        "scheduled": len(all_answers), "failed": sum(r["status"] == "failed" for r in llm_results),
                                        "note": "Actual rubric scores normalized by maximum; full credit only can bypass."}
        grading.save_new(output / "qwen-judge.json", {"results": llm_results, "scores": llm_scores, "timing": timings["qwen_rubric_judge"]})
    full = {c.id: next(level.id for level in c.levels if level.points == c.max_points) for c in guide.criteria}
    calibration = {r["answer_id"]: r["criterion_levels"] == full for r in references["references"]}
    stress_labels = {s["id"]: s["expected_safe_full_credit"] for s in stress}
    methods = {name: {"scores": scores, **summarize_method(scores, calibration, stress_labels)}
               for name, scores in all_scores.items()}
    report = {"version": VERSION, "methods": methods, "timings": timings, "failures": failures,
              "case_ids": ids, "calibration_labels": calibration, "stress_expectations": stress_labels,
              "independent_test_metrics": None, "instructor_review_time_ms": None,
              "limitations": ["Two calibration examples, ten constructed stress cases, one English question.",
                              "A cutoff fit on these two labels is not evidence of general grading accuracy.",
                              "Scores are not interchangeable probabilities; different preprocessing is recorded.",
                              "BERTScore uses the declared small DistilBERT configuration, not its largest recommended encoder.",
                              "General English NLI/NER models are not validated mathematical graders.",
                              "Local scoring is not OCR, and all grades remain proposals."]}
    grading.save_new(output / "report.json", report)
    print(json.dumps({"output": str(output.resolve()), "methods": len(methods), "failed_families": list(failures)}), flush=True)
    return report


def summarize_saved_run(output):
    """First-write recovery/aggregation of recorded scores; no model calls."""
    protocol = read(output / "protocol.json")
    ids = protocol["case_ids"]
    scores, timings, failures = {}, {}, {}
    for family in ("geometry", "lexical", "keywords", "bertscore", "nli", "ner"):
        file = output / (family + ".json")
        failure = output / (family + "-failure.json")
        if file.is_file():
            recorded = read(file)
            for method, values in recorded["scores"].items():
                if len(values) != len(ids):
                    raise ValueError("Saved scores omitted cases.")
                scores[method] = dict(zip(ids, normalize_scores(values)))
            timings[family] = recorded["details"]
        elif failure.is_file():
            failures[family] = read(failure)
        else:
            raise ValueError("A scheduled family has neither scores nor a recorded failure.")
    if (output / "qwen-judge.json").is_file():
        judge = read(output / "qwen-judge.json")
        scores["qwen_rubric_judge"] = dict(zip(ids, normalize_scores(judge["scores"])))
        timings["qwen_rubric_judge"] = judge["timing"]
    elif (output / "llm").exists():
        raise ValueError("The judge batch is incomplete; do not silently omit it.")
    guide = grading.Guide.model_validate(protocol["guide"])
    full = {c.id: next(level.id for level in c.levels if level.points == c.max_points) for c in guide.criteria}
    calibration = {r["answer_id"]: r["criterion_levels"] == full for r in protocol["references"]["references"]}
    stress = {s["id"]: s["expected_safe_full_credit"] for s in protocol["stress_cases"]}
    report = {
        "version": VERSION, "case_ids": ids,
        "methods": {name: {"scores": values, **summarize_method(values, calibration, stress)} for name, values in scores.items()},
        "timings": timings, "failures": failures, "calibration_labels": calibration,
        "stress_expectations": stress, "independent_test_metrics": None, "instructor_review_time_ms": None,
        "summary_built_from_saved_outputs": True,
        "postprocessor_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "score_adapter_source_sha256": hashlib.sha256(Path(__file__).with_name("comparison_methods.py").read_bytes()).hexdigest(),
        "recovery_note": "NumPy scalars are normalized at the adapter boundary. Original scorer outputs and judge calls are unchanged; no inference was repeated.",
        "limitations": ["Two calibration examples and ten constructed stress cases for one English question.",
                        "Cutoffs are fitted on A/B, never the stress expectations.",
                        "Small DistilBERT BERTScore and general-English NLI/NER are specific tested configurations.",
                        "Raw scores are not probabilities; zero coverage must not be mistaken for a reliable grader.",
                        "No independent grading accuracy, OCR time or instructor time saving has been established."],
    }
    grading.save_new(output / "report.json", report)
    print(json.dumps({"methods": len(report["methods"]), "failed_families": list(failures), "inference_repeated": False}))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "features", "models", "output"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--summarize-existing", type=Path)
    parser.add_argument("--run-llm", action="store_true")
    args = parser.parse_args()
    if args.summarize_existing:
        if not args.summarize_existing.resolve().is_relative_to((Path(__file__).resolve().parents[1] / "private").resolve()):
            parser.error("Saved outputs must stay in ignored private/.")
        summarize_saved_run(args.summarize_existing)
        return
    if any(getattr(args, name) is None for name in ("source", "features", "models", "output")):
        parser.error("Source, features, models and output are required for a new run.")
    if not args.output.resolve().is_relative_to((Path(__file__).resolve().parents[1] / "private").resolve()):
        parser.error("Outputs must stay in ignored private/.")
    run(args.source, args.features, args.models, args.output, run_llm=args.run_llm)


if __name__ == "__main__":
    main()
