"""Local cosine retrieval, optional BM25 fusion and cross-encoder reranking.

Callers MUST restrict inputs to checked, approved, institution-owned passages.
No student answer, reference mark, network call or model download belongs here.
Scores express relevance/rank, never grading confidence or academic correctness.
"""
from collections import OrderedDict
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid

import numpy as np

from services.material_retrieval_service import MAX_CANDIDATES, NEURAL_STRATEGIES, bm25_scores

STRATEGIES = NEURAL_STRATEGIES
ROOT = Path(__file__).resolve().parents[2]
MODELS = {
    'embedding': {'id':'BAAI/bge-m3', 'revision':'5617a9f61b028005a4858fdac845db406aefb181',
                  'license':'MIT', 'directory':'bge-m3'},
    'reranker': {'id':'BAAI/bge-reranker-v2-m3', 'revision':'953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e',
                 'license':'Apache-2.0', 'directory':'bge-reranker-v2-m3'},
}
DIMENSION = 1024
TOKEN_LIMIT = 2048
BATCH_SIZE = 2
RETRIEVE_K = 20
RERANK_K = 24
RRF_K = 60


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def model_root():
    return Path(os.getenv('MISRA_NEURAL_MODEL_DIR', str(ROOT/'.local/neural-models'))).resolve()


def model_metadata(strategy='neural_hybrid_v1'):
    if strategy not in STRATEGIES:
        raise ValueError('Unknown neural retrieval strategy.')
    dense_only = strategy in {'dense_v1', 'dense_rerank_v1'}
    roles = ['embedding'] if strategy == 'dense_v1' else ['reranker'] if strategy == 'bm25_rerank_v1' else list(MODELS)
    return {'models':{role:dict(MODELS[role]) for role in roles},
            'embedding_pooling':'l2_normalized_cls', 'dimension':DIMENSION,
            'token_limit':TOKEN_LIMIT, 'retrieve_k_per_ranker':RETRIEVE_K,
            'rerank_k':0 if strategy == 'dense_v1' else RERANK_K,
            'rrf_k':None if dense_only else RRF_K,
            'score_kind':('reciprocal_dense_cosine_rank; raw cosine is not a probability' if strategy == 'dense_v1'
                          else 'reciprocal_reranker_rank; raw logits are not probabilities')}


def verify_model(role, root=None):
    """Verify a provisioned local snapshot before importing model weights."""
    spec = MODELS[role]
    folder = (root or model_root())/spec['directory']/spec['revision']
    try:
        manifest = json.loads((folder/'misra-model.json').read_text(encoding='utf-8'))
        if manifest['model'] != spec['id'] or manifest['revision'] != spec['revision']:
            raise ValueError()
        required = {'config.json','tokenizer.json','tokenizer_config.json','model.safetensors'}
        if not required <= manifest['files'].keys():
            raise ValueError()
        for name,digest in manifest['files'].items():
            # The provisioner records only these flat model assets.
            if Path(name).name != name or '/' in name or '\\' in name or file_hash(folder/name) != digest:
                raise ValueError()
    except (OSError,ValueError,KeyError,TypeError):
        raise ValueError('Neural retrieval model is missing or changed. Run scripts/setup_neural_retrieval.py before selecting this strategy.') from None
    return folder


class LocalNeuralBackend:
    """Lazy, serialized inference; runtime is offline and accepts safe weights only."""
    def __init__(self):
        self.models = {}
        self.lock = threading.RLock()
        self.cache = ROOT/'.local/neural-embeddings'
        self.memory = OrderedDict()
        self.device = None

    def _load(self, role):
        if role not in self.models:
            folder = verify_model(role)
            try:
                import torch
                from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer
            except ImportError:
                raise ValueError('Install requirements-neural.txt in the project environment before enabling neural retrieval.') from None
            requested = os.getenv('MISRA_RETRIEVAL_DEVICE','cpu')
            if requested not in {'cpu','cuda'}:
                raise ValueError('MISRA_RETRIEVAL_DEVICE must be cpu or cuda.')
            if requested == 'cuda' and not torch.cuda.is_available():
                raise ValueError('CUDA was selected but is unavailable; choose cpu explicitly.')
            self.device = requested
            tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True, trust_remote_code=False)
            loader = AutoModel if role == 'embedding' else AutoModelForSequenceClassification
            model = loader.from_pretrained(folder, local_files_only=True, trust_remote_code=False,
                use_safetensors=True, dtype=torch.float16 if requested == 'cuda' else torch.float32)
            model.eval().requires_grad_(False)
            self.models[role] = (tokenizer,model)
        # Keep only the active model on the GPU; no hidden device/model fallback.
        for key,(_,model) in self.models.items():
            if key != role:
                model.to('cpu')
        tokenizer,model = self.models[role]
        model.to(self.device)
        return tokenizer,model

    def _inputs(self, tokenizer, texts, pairs=None):
        inputs = tokenizer(texts, text_pair=pairs, padding=True, truncation=False, return_tensors='pt')
        if inputs['input_ids'].shape[1] > TOKEN_LIMIT:
            raise ValueError('Approved passage/query exceeds the neural ranking token budget. Ranking cannot silently truncate evidence.')
        return {key:value.to(self.device) for key,value in inputs.items()}

    def _cache_key(self, text, namespace):
        return fingerprint({'namespace':namespace, 'model':MODELS['embedding'], 'pooling':'cls_l2',
                            'token_limit':TOKEN_LIMIT, 'text_sha256':hashlib.sha256(text.encode()).hexdigest()})

    def _cached(self, key):
        if key in self.memory:
            self.memory.move_to_end(key)
            return self.memory[key].copy()
        try:
            payload = json.loads((self.cache/(key+'.json')).read_text(encoding='utf-8'))
            if payload['key'] != key or payload['checksum'] != fingerprint(payload['vector']):
                return None
            vector = np.asarray(payload['vector'], dtype=np.float32)
            if vector.shape != (DIMENSION,) or not np.isfinite(vector).all() or not np.isclose(np.linalg.norm(vector),1,atol=.002):
                return None
            self._remember(key,vector)
            return vector
        except (OSError,ValueError,KeyError,TypeError):
            return None  # Recompute a corrupt/stale derived cache; no provider calls.

    def _remember(self,key,vector):
        self.memory[key] = vector.copy()
        self.memory.move_to_end(key)
        while len(self.memory) > 512:
            self.memory.popitem(last=False)

    def _save(self,key,vector):
        self._remember(key,vector)
        self.cache.mkdir(parents=True,exist_ok=True)
        temporary = self.cache/(key+'.'+uuid.uuid4().hex+'.tmp')
        values = vector.tolist()
        try:
            temporary.write_text(json.dumps({'key':key,'vector':values,'checksum':fingerprint(values)},allow_nan=False),encoding='utf-8')
            temporary.replace(self.cache/(key+'.json'))
        finally:
            temporary.unlink(missing_ok=True)

    def embed(self,texts,*,namespace):
        with self.lock:
            # Always verify/load the pinned model even if all vectors are cached.
            tokenizer,model = self._load('embedding')
            import torch
            keys = [self._cache_key(text,namespace) for text in texts]
            vectors = [self._cached(key) for key in keys]
            missing = [i for i,value in enumerate(vectors) if value is None]
            for start in range(0,len(missing),BATCH_SIZE):
                indices = missing[start:start+BATCH_SIZE]
                encoded = self._inputs(tokenizer,[texts[i] for i in indices])
                with torch.inference_mode():
                    pooled = model(**encoded).last_hidden_state[:,0].float()
                    pooled = torch.nn.functional.normalize(pooled,p=2,dim=1).cpu().numpy()
                for i,vector in zip(indices,pooled):
                    if vector.shape != (DIMENSION,) or not np.isfinite(vector).all() or not np.isclose(np.linalg.norm(vector),1,atol=.002):
                        raise ValueError('Embedding model returned an invalid vector.')
                    vectors[i] = vector
                    self._save(keys[i],vector)
            return np.asarray(vectors,dtype=np.float32)

    def rerank(self,query,texts):
        with self.lock:
            tokenizer,model = self._load('reranker')
            import torch
            scores = []
            for start in range(0,len(texts),BATCH_SIZE):
                batch = texts[start:start+BATCH_SIZE]
                encoded = self._inputs(tokenizer,[query]*len(batch),batch)
                with torch.inference_mode():
                    scores.extend(model(**encoded).logits.view(-1).float().cpu().tolist())
            return scores


@lru_cache(maxsize=1)
def get_backend():
    return LocalNeuralBackend()


def _ranks(values, *, positive_only=False):
    order = sorted((i for i,v in enumerate(values) if not positive_only or v>0),key=lambda i:(-values[i],i))
    ranks = {}; previous = None; rank = 0
    for position,index in enumerate(order,1):
        if values[index] != previous:
            rank = position
            previous = values[index]
        ranks[index] = rank
    return ranks


def rank_passages(texts,query,*,namespace,strategy='neural_hybrid_v1',pinned_indices=(),backend=None):
    """No corpus expansion: dense/BM25 see the same already-approved candidates."""
    if strategy not in STRATEGIES:
        raise ValueError('Unknown neural retrieval strategy.')
    if not isinstance(query,str) or not query.strip() or len(query)>5000 or len(texts)>MAX_CANDIDATES:
        raise ValueError('Neural retrieval exceeds approved query/candidate bounds.')
    if not isinstance(namespace,str) or not namespace:
        raise ValueError('An institution/scope cache namespace is required.')
    if any(not isinstance(t,str) or not t.strip() for t in texts):
        raise ValueError('Neural candidates must be nonempty approved passages.')
    pinned = set(pinned_indices)
    if any(type(i) is not int or not 0<=i<len(texts) for i in pinned) or len(pinned)>RERANK_K:
        raise ValueError('Exact-passage links exceed the neural ranking budget.')
    if not texts:
        return [],[]
    backend = backend or get_backend()
    uses_bm25 = strategy in {'bm25_rerank_v1','neural_hybrid_v1'}
    lexical = bm25_scores(texts,query) if uses_bm25 else [None]*len(texts)
    dense = [None]*len(texts)
    rankers = [_ranks(lexical,positive_only=True)] if uses_bm25 else []
    if strategy != 'bm25_rerank_v1':
        vectors = np.asarray(backend.embed([query,*texts],namespace=namespace),dtype=np.float32)
        if vectors.ndim!=2 or vectors.shape[0]!=len(texts)+1 or vectors.shape[1]<1 or not np.isfinite(vectors).all():
            raise ValueError('Embedding output shape/content is invalid.')
        norms = np.linalg.norm(vectors,axis=1)
        if not np.isfinite(norms).all() or np.any(norms<1e-8):
            raise ValueError('Embedding output contains invalid vector norms.')
        vectors = vectors/norms[:,None]
        dense = (vectors[1:]@vectors[0]).tolist()
        rankers.append(_ranks(dense))
    rankers = [{i:ranks[i] for i in sorted(ranks,key=lambda i:(ranks[i],i))[:RETRIEVE_K]} for ranks in rankers]
    # Pure dense modes use cosine order, including negative similarities. Rank
    # scores keep the callers' positive-score gate from changing that ordering.
    # No lexical function, fusion or reranker runs for dense_v1.
    fused = ([sum(1/(RRF_K+ranks[i]) for ranks in rankers if i in ranks) for i in range(len(texts))]
             if uses_bm25 else [1/rankers[0][i] if i in rankers[0] else 0 for i in range(len(texts))])
    eligible = sorted((i for i,s in enumerate(fused) if s>0 or i in pinned),key=lambda i:(i not in pinned,-fused[i],i))[:RERANK_K]
    if not eligible:
        return [0.0]*len(texts),[{'bm25':v,'dense_cosine':None,'rrf':0,'reranker_logit':None} for v in lexical]
    details = [{'bm25':lexical[i],'dense_cosine':round(dense[i],8) if dense[i] is not None else None,
                'rrf':round(fused[i],8) if uses_bm25 else None,'reranker_logit':None} for i in range(len(texts))]
    if strategy == 'dense_v1':
        ranks = _ranks(dense)
        return [round(1/ranks[i],8) if i in eligible else 0.0 for i in range(len(texts))],details
    raw = np.asarray(backend.rerank(query,[texts[i] for i in eligible]),dtype=np.float64)
    if raw.shape!=(len(eligible),) or not np.isfinite(raw).all():
        raise ValueError('Reranker returned invalid scores.')
    reranked = _ranks(raw.tolist())
    scores = [0.0]*len(texts)
    for local,index in enumerate(eligible):
        scores[index] = round(1/reranked[local],8)
        details[index]['reranker_logit'] = round(float(raw[local]),8)
    return scores,details
