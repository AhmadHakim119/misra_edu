"""Dependency-free lexical hybrid: BM25 + character TF-IDF with rank fusion.

Experimental, not a semantic embedding model. Inputs must already be restricted
to checked, approved course passages. This ranker cannot fetch or expand scope.
Queries come only from the approved question and criterion, never student text.
"""
from collections import Counter
import math
import re
import unicodedata

from services.material_retrieval_service import MAX_CANDIDATES, bm25_scores, tokens

STRATEGY = 'hybrid_rrf_v1'
RRF_K = 60
RANK_WINDOW = 50
MIN_CHARACTER_SIMILARITY = 0.10


def _features(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    text = re.sub('[\u064b-\u065f\u0670\u0640]', '', text)
    features = Counter()
    for word in tokens(text)[:4000]:
        padded = '^' + word + '$'
        features.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return features


def hybrid_scores(texts, query):
    if len(texts) > MAX_CANDIDATES or len(query) > 5000:
        raise ValueError('Hybrid retrieval exceeds approved candidate/query bounds.')
    if not texts:
        return [], []
    lexical = bm25_scores(texts, query)
    documents = [_features(text) for text in texts]
    frequency = Counter(term for doc in documents for term in doc)
    query_terms = _features(query)

    def vector(features):
        return {term: (1 + math.log(count)) * (1 + math.log((len(texts) + 1) /
                (frequency.get(term, 0) + 1))) for term, count in features.items()}

    q = vector(query_terms)
    qnorm = math.sqrt(sum(value * value for value in q.values()))
    character = []
    for document in documents:
        d = vector(document)
        denominator = qnorm * math.sqrt(sum(value * value for value in d.values()))
        character.append(sum(value * d.get(term, 0) for term, value in q.items()) /
                         denominator if denominator else 0.0)
    fused = [0.0] * len(texts)
    for scores, minimum in ((lexical, 0.0), (character, MIN_CHARACTER_SIMILARITY)):
        # Ties share ranks; input/database order cannot create a relevance boost.
        eligible = sorted((i for i, score in enumerate(scores) if score > minimum),
                          key=lambda i: (-scores[i], i))
        previous = None
        rank = 0
        for position, index in enumerate(eligible, 1):
            if scores[index] != previous:
                rank = position
                previous = scores[index]
            if rank > RANK_WINDOW:
                break
            fused[index] += 1 / (RRF_K + rank)
    details = [{'bm25': lexical[i], 'character_cosine': round(character[i], 8),
                'rrf': round(fused[i], 8)} for i in range(len(texts))]
    return [round(score, 8) for score in fused], details
