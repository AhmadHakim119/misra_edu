"""Local CPU neural scorers. Model files must be predownloaded and pinned."""
import gc
import math
from pathlib import Path
import re
from time import perf_counter

from comparison_methods import tokens


def bertscore_scores(model_path, reference, texts):
    from bert_score import BERTScorer
    setup = perf_counter()
    scorer = BERTScorer(model_type=str(model_path), num_layers=5, device="cpu",
                       batch_size=8, idf=False, rescale_with_baseline=False, use_fast_tokenizer=True)
    setup_ms = (perf_counter() - setup) * 1000
    started = perf_counter()
    precision, recall, f1 = scorer.score(texts, [reference] * len(texts), verbose=False)
    elapsed_ms = (perf_counter() - started) * 1000
    result = {"bertscore_precision": precision.tolist(), "bertscore_recall": recall.tolist(), "bertscore_f1": f1.tolist()}
    del scorer
    gc.collect()
    return result, {"setup_ms": setup_ms, "batch_inference_ms": elapsed_ms,
                    "model_path": str(model_path), "layers": 5, "idf": False,
                    "rescale_with_baseline": False, "device": "cpu"}


def nli_scores(model_path, reference, texts, claims):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    setup = perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path, local_files_only=True, use_safetensors=True, trust_remote_code=False).eval().to("cpu")
    setup_ms = (perf_counter() - setup) * 1000
    # Model author's documented order: contradiction, entailment, neutral.
    mapping = ["contradiction", "entailment", "neutral"]
    if model.config.num_labels != 3:
        raise ValueError("NLI model must have its documented three labels.")
    pairs, layout = [], []
    for text in texts:
        start = len(pairs)
        pairs.extend([(text, reference), (reference, text)])
        claim_start = len(pairs)
        pairs.extend((text, claim) for claim in claims)
        sentence_start = len(pairs)
        sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
        pairs.extend((sentence, reference) for sentence in sentences)
        pairs.extend((sentence, claim) for sentence in sentences for claim in claims)
        layout.append((start, claim_start, sentence_start, len(pairs)))
    probabilities = []
    started = perf_counter()
    with torch.inference_mode():
        for i in range(0, len(pairs), 16):
            batch = pairs[i:i + 16]
            encoded = tokenizer([p[0] for p in batch], [p[1] for p in batch],
                                padding=True, truncation=False, return_tensors="pt")
            if encoded["input_ids"].shape[1] > 512:
                raise ValueError("NLI input too long; no silent truncation is allowed.")
            probabilities.extend(torch.softmax(model(**encoded).logits, dim=-1).tolist())
    elapsed_ms = (perf_counter() - started) * 1000
    result = {"nli_entailment": [], "nli_bidirectional": [], "nli_sentence_guard": [], "nli_criterion_support": []}
    details = []
    for start, claim_start, sentence_start, end in layout:
        forward, reverse = probabilities[start], probabilities[start + 1]
        criterion_entailment = [p[1] for p in probabilities[claim_start:sentence_start]]
        max_contradiction = max((p[0] for p in probabilities[sentence_start:end]), default=forward[0])
        result["nli_entailment"].append(forward[1])
        result["nli_bidirectional"].append(min(forward[1], reverse[1]))
        result["nli_sentence_guard"].append(forward[1] * (1 - max_contradiction))
        result["nli_criterion_support"].append(min(criterion_entailment) * (1 - max_contradiction))
        details.append({"forward": dict(zip(mapping, forward)), "reverse": dict(zip(mapping, reverse)),
                        "criterion_entailment": criterion_entailment, "max_sentence_contradiction": max_contradiction})
    del model, tokenizer
    gc.collect()
    return result, {"setup_ms": setup_ms, "batch_inference_ms": elapsed_ms,
                    "pair_count": len(pairs), "label_order": mapping,
                    "model_path": str(model_path), "claims": claims,
                    "details": details, "note": "NLI softmax scores are uncalibrated; no guaranteed math reasoning."}


def ner_scores(model_path, reference, texts):
    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer
    setup = perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
    model = AutoModelForTokenClassification.from_pretrained(
        model_path, local_files_only=True, use_safetensors=True, trust_remote_code=False).eval().to("cpu")
    setup_ms = (perf_counter() - setup) * 1000
    def entities(text):
        encoded = tokenizer(text, return_offsets_mapping=True, return_tensors="pt", truncation=False)
        offsets = encoded.pop("offset_mapping")[0].tolist()
        if encoded["input_ids"].shape[1] > 512:
            raise ValueError("NER input too long; no silent truncation.")
        with torch.inference_mode():
            labels = model(**encoded).logits.argmax(-1)[0].tolist()
        spans, active = [], None
        for label, (first, last) in zip(labels, offsets):
            tag = model.config.id2label[label]
            if not last or tag == "O":
                if active:
                    spans.append(active)
                    active = None
                continue
            kind = tag.split("-", 1)[-1]
            if tag.startswith("I-") and active and active[0] == kind:
                active = (kind, active[1], last)
            else:
                if active:
                    spans.append(active)
                active = (kind, first, last)
        if active:
            spans.append(active)
        return sorted({(kind, " ".join(tokens(text[first:last]))) for kind, first, last in spans})
    started = perf_counter()
    expected = set(entities(reference))
    extracted = [entities(text) for text in texts]
    values = [len(expected & set(found)) / len(expected) if expected else None for found in extracted]
    elapsed_ms = (perf_counter() - started) * 1000
    del model, tokenizer
    gc.collect()
    return {"named_entity_coverage": values}, {"setup_ms": setup_ms, "batch_inference_ms": elapsed_ms,
             "reference_entities": sorted(expected), "student_entities": extracted,
             "note": "No reference entities means this method is not applicable, not a perfect match."}
