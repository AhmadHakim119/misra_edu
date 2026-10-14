"""Offline OCR/text overlap metrics. These scores must never become grade accuracy."""
from collections import Counter
import re
import unicodedata

MAX_DP_CELLS = 4_000_000


def normalized_text(text, *, normalize_whitespace=False):
    if not isinstance(text,str): raise ValueError("Metric inputs must be text.")
    text = unicodedata.normalize("NFC",text)
    return " ".join(text.split()) if normalize_whitespace else text


def _distance(reference, candidate, *, lcs=False):
    if len(reference) * len(candidate) > MAX_DP_CELLS:
        raise ValueError("Text comparison is too large; evaluate smaller aligned answer/page segments.")
    if len(candidate) > len(reference): reference,candidate = candidate,reference
    previous = [0] * (len(candidate) + 1) if lcs else list(range(len(candidate) + 1))
    for index,left in enumerate(reference,1):
        current = [0 if lcs else index]
        for position,right in enumerate(candidate,1):
            if lcs:
                current.append(previous[position-1] + 1 if left == right else max(previous[position],current[-1]))
            else:
                current.append(min(previous[position]+1,current[-1]+1,previous[position-1]+(left != right)))
        previous = current
    return previous[-1]


def _prf(overlap, reference_count, candidate_count):
    precision = overlap / candidate_count if candidate_count else None
    recall = overlap / reference_count if reference_count else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if reference_count else None)
    return {"precision":precision,"recall":recall,"f1":f1}


def text_metrics(reference, candidate, *, normalize_whitespace=False):
    reference = normalized_text(reference,normalize_whitespace=normalize_whitespace)
    candidate = normalized_text(candidate,normalize_whitespace=normalize_whitespace)
    reference_words, candidate_words = reference.split(),candidate.split()
    # Case and punctuation are preserved for transcription errors; overlap metrics
    # use separate lexical tokenization and cannot certify semantic equivalence.
    reference_tokens = re.findall(r"\w+",reference.casefold(),re.UNICODE)
    candidate_tokens = re.findall(r"\w+",candidate.casefold(),re.UNICODE)
    result = {"reference_char_count":len(reference),"reference_word_count":len(reference_words),
        "character_error_rate":_distance(reference,candidate)/len(reference) if reference else None,
        "word_error_rate":_distance(reference_words,candidate_words)/len(reference_words) if reference_words else None,
        "normalization":"NFC+whitespace" if normalize_whitespace else "NFC",
        "interpretation":"CER/WER measure transcription errors; ROUGE measures lexical overlap, not grading correctness or reasoning quality."}
    for size in (1,2):
        ref = Counter(tuple(reference_tokens[i:i+size]) for i in range(len(reference_tokens)-size+1))
        pred = Counter(tuple(candidate_tokens[i:i+size]) for i in range(len(candidate_tokens)-size+1))
        result[f"rouge_{size}"] = _prf(sum((ref & pred).values()),sum(ref.values()),sum(pred.values()))
    result["rouge_l"] = _prf(_distance(reference_tokens,candidate_tokens,lcs=True),len(reference_tokens),len(candidate_tokens))
    return result
