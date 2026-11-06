"""Independent score families and calibration-only routing evaluation."""
from collections import Counter
import math
from numbers import Real
import re
import unicodedata

from semantic_comparison import cosine


VERSION = "method-comparison-v1"


def normalize_scores(values):
    """Convert ML-library scalars at the adapter boundary, preserving missingness."""
    normalized = []
    for value in values:
        if value is None:
            normalized.append(None)
        elif isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value):
            normalized.append(float(value))
        else:
            raise ValueError("A metric must return finite numeric scores or explicit nulls.")
    return normalized


def tokens(text):
    text = unicodedata.normalize("NFC", text).lower().replace("×", "*").replace("−", "-")
    return re.findall(r"\d+(?:\.\d+)?|[^\W\d_]+|[=+*/-]", text, re.UNICODE)


def edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, first in enumerate(left, 1):
        current = [i]
        for j, second in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (first != second)))
        previous = current
    return previous[-1]


def vector_scores(reference, candidate):
    similarity = cosine(reference, candidate)
    dot = math.fsum(x * y for x, y in zip(reference, candidate))
    l2 = math.sqrt(math.fsum((x - y) ** 2 for x, y in zip(reference, candidate)))
    l1 = math.fsum(abs(x - y) for x, y in zip(reference, candidate))
    return {"cosine": similarity, "dot_product": dot, "euclidean_similarity": -l2,
            "manhattan_similarity": -l1, "angular_similarity": 1 - math.acos(similarity) / math.pi}


def lexical_scores(reference, candidate, concepts):
    from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu
    from rouge_score.rouge_scorer import RougeScorer

    ref, cand = tokens(reference), tokens(candidate)
    rouge = RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=False).score(reference, candidate)
    class OperatorTokenizer:
        def tokenize(self, text):
            return tokens(text)
    preserved = RougeScorer(["rouge1", "rouge2", "rougeL"], tokenizer=OperatorTokenizer()).score(reference, candidate)
    word_edits = edit_distance(ref, cand)
    char_edits = edit_distance(reference.lower(), candidate.lower())
    present = set(cand)
    matched = [name for name, aliases in concepts.items() if any(
        (len(tokens(alias)) == 1 and tokens(alias)[0] in present)
        or (len(tokens(alias)) > 1 and any(cand[i:i + len(tokens(alias))] == tokens(alias)
                                         for i in range(len(cand)))) for alias in aliases)]
    result = {"bleu4": sentence_bleu([ref], cand, smoothing_function=SmoothingFunction().method1),
              "wer_similarity": 1 - word_edits / len(ref) if ref else None,
              "character_edit_similarity": 1 - char_edits / max(len(reference), len(candidate), 1),
              "concept_coverage": len(matched) / len(concepts) if concepts else None}
    for name in ("rouge1", "rouge2", "rougeL"):
        result[name + "_f1"] = rouge[name].fmeasure
        result[name + "_operators_f1"] = preserved[name].fmeasure
    return result, {"word_edits": word_edits, "character_edits": char_edits,
                    "reference_word_count": len(ref), "matched_concepts": matched,
                    "normalization": "Unicode NFC; lower case; keep negation, numbers and operators for BLEU/WER/custom ROUGE"}


def keyword_scores(reference, texts, setup_texts):
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
    from rake_nltk import Rake
    vectorizer = TfidfVectorizer(tokenizer=tokens, token_pattern=None, lowercase=False)
    vectorizer.fit(setup_texts)
    ref_vector = vectorizer.transform([reference])
    matrix = vectorizer.transform(texts)
    tfidf = (matrix @ ref_vector.T).toarray()[:, 0].tolist()
    weights = {word: value for word, value in zip(vectorizer.get_feature_names_out(), ref_vector.toarray()[0]) if value > 0}
    weighted = [sum(weight for word, weight in weights.items() if word in set(tokens(text))) / sum(weights.values())
                if weights else None for text in texts]
    rake = Rake(stopwords=list(set(ENGLISH_STOP_WORDS) - {"not", "no", "never"}),
                sentence_tokenizer=lambda text: re.split(r"(?<=[.!?])\s+|\n+", text),
                word_tokenizer=tokens, include_repeated_phrases=False, max_length=30)
    rake.extract_keywords_from_text(reference)
    phrases = rake.get_ranked_phrases_with_scores()
    rake_scores = []
    for text in texts:
        present = set(tokens(text))
        total = sum(weight for weight, phrase in phrases)
        rake_scores.append(sum(weight * len(present & set(tokens(phrase))) / len(set(tokens(phrase)))
                               for weight, phrase in phrases) / total if total else None)
    return {"tfidf_cosine": tfidf, "tfidf_keyword_coverage": weighted, "rake_keyword_coverage": rake_scores}, {
        "tfidf_fit_scope": "question, model answer and rubric descriptions only; no student/test corpus fitting",
        "reference_keyword_weights": weights, "rake_phrases": phrases,
        "note": "Term presence does not establish relationships or detect contradictions."}


def fit_cutoff(calibration_scores, calibration_labels):
    if set(calibration_scores) != set(calibration_labels):
        raise ValueError("Calibration labels and scores must have matching IDs.")
    valid = [score for score in calibration_scores.values() if score is not None]
    if any(type(s) not in (int, float) or not math.isfinite(s) for s in valid):
        raise ValueError("Method scores must be finite or explicitly unavailable.")
    best, cutoff = 0, None
    for candidate in sorted(set(valid), reverse=True):
        selected = [aid for aid, score in calibration_scores.items() if score is not None and score >= candidate]
        if all(calibration_labels[aid] for aid in selected) and len(selected) > best:
            best, cutoff = len(selected), candidate
    return cutoff


def routing_decision(score, cutoff):
    if score is None or cutoff is None:
        return False
    if not math.isfinite(score) or not math.isfinite(cutoff):
        raise ValueError("Invalid method score or threshold.")
    return score >= cutoff


def summarize_method(scores, calibration_labels, stress_labels):
    if not set(calibration_labels).issubset(scores) or not set(stress_labels).issubset(scores):
        raise ValueError("Missing scheduled cases must not disappear from evaluation.")
    cutoff = fit_cutoff({aid: scores[aid] for aid in calibration_labels}, calibration_labels)
    accepted = {aid for aid, score in scores.items() if routing_decision(score, cutoff)}
    calibration_accepted = accepted & set(calibration_labels)
    unsafe = sorted(aid for aid, safe in stress_labels.items() if not safe and aid in accepted)
    missed_safe = sorted(aid for aid, safe in stress_labels.items() if safe and aid not in accepted)
    negative_count = sum(not safe for safe in stress_labels.values())
    referred = set(stress_labels) - accepted
    caught = sum(not stress_labels[aid] for aid in referred)
    precision = caught / len(referred) if referred else None
    recall = caught / negative_count if negative_count else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    return {"cutoff": cutoff, "calibration_resolved": len(calibration_accepted),
            "calibration_count": len(calibration_labels),
            "calibration_errors": sum(not calibration_labels[aid] for aid in calibration_accepted),
            "unsafe_stress_matches": unsafe, "safe_stress_referred": missed_safe,
            "stress_candidate_error_recall": recall, "stress_referral_precision": precision,
            "stress_referral_f1": f1,
            "note": "Threshold fitted on A/B only; stress expectations are constructed, not independent instructor labels."}
