"""Synthetic ranking, local cache and scope regressions; no model downloads/calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from services.neural_retrieval_service import (
    DIMENSION, LocalNeuralBackend, MODELS, RERANK_K, get_backend, model_metadata,
    rank_passages, verify_model,
)
from services.material_retrieval_service import configured_strategy, retrieve_for_question
from services.grading_package_service import build_grading_package
from tests import test_course_materials as fixtures
from scripts.setup_neural_retrieval import validate_converter_version


class FakeBackend:
    def __init__(self,vectors=None,logits=None):
        self.vectors=vectors
        self.logits=logits
        self.reranked=[]
        self.embedded=[]

    def embed(self,texts,*,namespace):
        self.embedded.append((list(texts),namespace))
        if self.vectors is not None:return self.vectors
        return [[1,0]]+[[0,1] for _ in texts[1:]]

    def rerank(self,query,texts):
        self.reranked.append((query,list(texts)))
        if self.logits is not None:return self.logits
        return list(range(len(texts)))


class NeuralRankingTests(unittest.TestCase):
    def test_cosine_only_never_calls_bm25_or_reranker_and_keeps_negative_cosines(self):
        backend=FakeBackend(vectors=[[1,0],[0,1],[-1,0],[1,1]])
        with patch('services.neural_retrieval_service.bm25_scores',side_effect=AssertionError('BM25 must not run')):
            scores,details=rank_passages(['irrelevant word','opposite','semantic match'],'word',
                namespace='scope',strategy='dense_v1',backend=backend)
        self.assertEqual(backend.reranked,[])
        self.assertEqual(len(backend.embedded),1)
        self.assertGreater(scores[2],scores[0]);self.assertGreater(scores[0],scores[1])
        self.assertGreater(scores[1],0)
        self.assertEqual(details[1]['dense_cosine'],-1)
        self.assertTrue(all(d['bm25'] is None and d['rrf'] is None and d['reranker_logit'] is None for d in details))
        self.assertEqual(set(model_metadata('dense_v1')['models']),{'embedding'})
        self.assertEqual(model_metadata('dense_v1')['rerank_k'],0)

    def test_dense_reranker_never_calls_bm25_and_can_change_cosine_order(self):
        backend=FakeBackend(vectors=[[1,0],[1,0],[0,1]],logits=[-5,3])
        with patch('services.neural_retrieval_service.bm25_scores',side_effect=AssertionError('BM25 must not run')):
            scores,details=rank_passages(['first cosine hit','reranker prefers this'],'question',
                namespace='scope',strategy='dense_rerank_v1',backend=backend)
        self.assertGreater(scores[1],scores[0]);self.assertEqual(len(backend.reranked),1)
        self.assertTrue(all(d['bm25'] is None and d['rrf'] is None for d in details))
        self.assertEqual(details[1]['reranker_logit'],3)
        self.assertEqual(set(model_metadata('dense_rerank_v1')['models']),{'embedding','reranker'})

    def test_dense_pool_bounds_pins_and_failures_never_trigger_bm25_fallback(self):
        for strategy in ['dense_v1','dense_rerank_v1']:
            texts=[f'passage {i}' for i in range(80)]
            backend=FakeBackend(vectors=[[1,0]]+[[80-i,1] for i in range(80)])
            with self.subTest(strategy=strategy),patch('services.neural_retrieval_service.bm25_scores',side_effect=AssertionError('BM25 must not run')):
                scores,_=rank_passages(texts,'question',namespace='scope',strategy=strategy,pinned_indices=[79],backend=backend)
                self.assertGreater(scores[79],0)
                self.assertLessEqual(sum(s>0 for s in scores),RERANK_K)
                if strategy=='dense_rerank_v1':self.assertIn(texts[79],backend.reranked[0][1])
                for vectors in [[[0,0],[1,0]],[[1,0],[float('nan'),0]]]:
                    with self.assertRaises(ValueError):
                        rank_passages(['passage'],'question',namespace='scope',strategy=strategy,backend=FakeBackend(vectors=vectors))

    def test_dense_retrieval_recovers_no_lexical_overlap_and_reranks(self):
        backend=FakeBackend(vectors=[[1,0],[0,1],[1,0]],logits=[-5,3])
        scores,details=rank_passages(['gravity word distractor','potential converted to motion'],
            'gravity',namespace='approved-scope',backend=backend)
        self.assertGreater(scores[1],scores[0])
        self.assertEqual(len(backend.embedded),1)
        self.assertEqual(len(backend.reranked),1)
        self.assertEqual(details[1]['dense_cosine'],1)
        self.assertEqual(details[0]['reranker_logit'],-5)
        self.assertGreater(scores[0],0)  # Negative logits are ranks, not invalid scores/probabilities.

    def test_bm25_reranker_ablation_never_calls_embedding_model(self):
        backend=FakeBackend(logits=[4])
        scores,_=rank_passages(['gravity work','different topic'],'gravity',namespace='scope',strategy='bm25_rerank_v1',backend=backend)
        self.assertEqual(backend.embedded,[])
        self.assertEqual(backend.reranked[0][1],['gravity work'])
        self.assertEqual(scores,[1,0])

    def test_reranker_pool_is_bounded_and_explicit_links_survive_candidate_selection(self):
        texts=[f'gravity {i}' for i in range(80)]
        backend=FakeBackend()
        scores,_=rank_passages(texts,'gravity',namespace='scope',pinned_indices=[79],backend=backend)
        self.assertLessEqual(len(backend.reranked[0][1]),RERANK_K)
        self.assertIn(texts[79],backend.reranked[0][1])
        self.assertLessEqual(sum(s>0 for s in scores),RERANK_K)

    def test_bad_outputs_fail_without_lexical_fallback(self):
        for backend in [FakeBackend(vectors=[[1,0]]),FakeBackend(vectors=[[0,0],[1,0]]),
                        FakeBackend(logits=[float('nan')]),FakeBackend(logits=[]),
                        FakeBackend(vectors=[[1,0],[float('inf'),0]])]:
            with self.subTest(backend=backend),self.assertRaises(ValueError):
                rank_passages(['gravity'],'gravity',namespace='scope',backend=backend)

    def test_query_namespace_and_exact_link_bounds(self):
        for changes in [dict(namespace=''),dict(query='x'*5001),dict(strategy='invented'),
                        dict(pinned_indices=[-1]),dict(pinned_indices=[True])]:
            kwargs=dict(texts=['gravity'],query='gravity',namespace='scope',backend=FakeBackend())|changes
            with self.subTest(changes=changes),self.assertRaises(ValueError):rank_passages(**kwargs)

    def test_empty_pool_never_loads_models_and_baseline_configuration_is_explicit(self):
        with patch('services.neural_retrieval_service.get_backend') as backend:
            self.assertEqual(rank_passages([],'gravity',namespace='scope'),([],[]))
            backend.assert_not_called()
        with patch.dict(os.environ,{'MISRA_RETRIEVAL_STRATEGY':'neural_hybrid_v1'}):
            self.assertEqual(configured_strategy(),'neural_hybrid_v1')
        with patch.dict(os.environ,{'MISRA_RETRIEVAL_STRATEGY':'invented'}):
            with self.assertRaises(ValueError):configured_strategy()

    def test_embedding_cache_is_content_model_and_scope_specific_and_never_unpickles(self):
        backend=LocalNeuralBackend()
        vector=np.zeros(DIMENSION,dtype=np.float32);vector[0]=1
        with tempfile.TemporaryDirectory() as directory:
            backend.cache=Path(directory)
            key=backend._cache_key('approved gravity','institution-a/scope1')
            self.assertNotEqual(key,backend._cache_key('approved gravity','institution-b/scope1'))
            self.assertNotEqual(key,backend._cache_key('changed gravity','institution-a/scope1'))
            backend._save(key,vector);backend.memory.clear()
            np.testing.assert_array_equal(backend._cached(key),vector)
            raw=(backend.cache/(key+'.json')).read_text()
            self.assertNotIn('approved gravity',raw)
            (backend.cache/(key+'.json')).write_text('corrupt cache')
            backend.memory.clear();self.assertIsNone(backend._cached(key))

    def test_unprovisioned_model_fails_without_importing_or_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'missing or changed'):
                verify_model('embedding',Path(directory))

    def test_model_identity_is_pinned_and_metadata_has_no_private_paths(self):
        metadata=model_metadata()
        for spec in MODELS.values():self.assertEqual(len(spec['revision']),40)
        self.assertNotIn(str(Path.home()),json.dumps(metadata))
        self.assertIn('not probabilities',metadata['score_kind'])

    def test_provisioning_rejects_vulnerable_checkpoint_converters(self):
        for version in ['2.7.1+cu118','2.9.1','unknown']:
            with self.subTest(version=version),self.assertRaisesRegex(ValueError,'patched PyTorch'):
                validate_converter_version(version)
        for version in ['2.10.0','2.10.0+cpu','2.11.1']:
            validate_converter_version(version)

    def test_ranking_token_budget_never_silently_truncates(self):
        class Oversized:
            shape=(1,2049)
        backend=LocalNeuralBackend()
        with patch('builtins.print'),patch.object(backend,'device','cpu'):
            tokenizer=unittest.mock.Mock(return_value={'input_ids':Oversized()})
            with self.assertRaisesRegex(ValueError,'silently truncate'):
                backend._inputs(tokenizer,['approved passage'])
            self.assertFalse(tokenizer.call_args.kwargs['truncation'])


class NeuralScopeTests(unittest.TestCase):
    setUp=fixtures.CourseMaterialTests.setUp
    tearDown=fixtures.CourseMaterialTests.tearDown
    material=fixtures.CourseMaterialTests.material
    scope=fixtures.CourseMaterialTests.scope

    def test_only_owned_approved_bound_pages_reach_neural_backend(self):
        _,version=self.material()
        self.material(text='TOP SECRET unrelated course gravity work',course='c2')
        self.material(text='DRAFT UNAPPROVED gravity work',approved=False)
        self.scope(version)
        self.db.get(__import__('models').Answer,'a').raw_ocr_text='INJECTED STUDENT QUERY'
        backend=FakeBackend()
        with patch('services.neural_retrieval_service.get_backend',return_value=backend):
            context=retrieve_for_question(self.db,self.q,self.rubric,strategy='neural_hybrid_v1')
        sent=json.dumps(backend.embedded+backend.reranked)
        for forbidden in ['TOP SECRET','DRAFT UNAPPROVED','INJECTED STUDENT QUERY']:
            self.assertNotIn(forbidden,sent)
        self.assertEqual(context['strategy'],'neural_hybrid_v1')
        self.assertIn('neural_retrieval',context)
        self.assertIn('reranker_logit',next(iter(context['queries'][0]['ranking'].values())))
        self.assertEqual(context['passages'][0]['material_version_id'],version.id)

    def test_dense_strategies_use_owned_scope_without_any_lexical_ranking(self):
        _,version=self.material();self.scope(version)
        self.material(text='UNAPPROVED gravity work',approved=False)
        self.material(text='OTHER COURSE gravity work',course='c2')
        for strategy in ['dense_v1','dense_rerank_v1']:
            backend=FakeBackend()
            with self.subTest(strategy=strategy), \
                 patch('services.neural_retrieval_service.bm25_scores',side_effect=AssertionError('BM25 must not run')), \
                 patch('services.material_retrieval_service.bm25_scores',side_effect=AssertionError('BM25 must not run')), \
                 patch('services.neural_retrieval_service.get_backend',return_value=backend):
                context=retrieve_for_question(self.db,self.q,self.rubric,strategy=strategy)
            self.assertEqual(context['strategy'],strategy)
            self.assertEqual(context['passages'][0]['material_version_id'],version.id)
            for text in ['UNAPPROVED','OTHER COURSE']:self.assertNotIn(text,str(backend.embedded+backend.reranked))

    def test_approval_integrity_failure_happens_before_neural_inference(self):
        _,version=self.material();self.scope(version)
        from models import MaterialPage
        self.db.query(MaterialPage).filter_by(version_id=version.id).one().text+=' tampered'
        self.db.flush()
        with patch('services.neural_retrieval_service.get_backend') as backend:
            with self.assertRaisesRegex(ValueError,'integrity'):
                retrieve_for_question(self.db,self.q,self.rubric,strategy='neural_hybrid_v1')
            backend.assert_not_called()

    def test_missing_models_block_selected_neural_grading_before_provider_call(self):
        _,version=self.material();self.scope(version)
        from models import Answer
        answer=self.db.get(Answer,'a')
        with patch.dict(os.environ,{'MISRA_RETRIEVAL_STRATEGY':'neural_hybrid_v1'}), \
             patch('services.neural_retrieval_service.rank_passages',side_effect=ValueError('model missing')):
            with self.assertRaisesRegex(ValueError,'model missing'):
                build_grading_package(answer,self.q,self.db,'text_only')
        self.assertIsNone(answer.score)

    def test_exact_pin_reaches_ranker_and_remains_priority(self):
        _,version=self.material()
        from models import MaterialChunk
        chunk=self.db.query(MaterialChunk).filter_by(version_id=version.id).one()
        self.scope(version,bindings=[{'version_id':version.id,'page_indices':[0],
            'chunk_ids':[chunk.id],'criterion_id':'work'}])
        with patch('services.neural_retrieval_service.rank_passages',return_value=([.1],[{'reranker_logit':-2}])) as rank:
            context=retrieve_for_question(self.db,self.q,self.rubric,strategy='neural_hybrid_v1')
        self.assertEqual(rank.call_args.kwargs['pinned_indices'],[0])
        self.assertEqual(context['passages'][0]['selection'],'exact_link')

    def test_preview_uses_same_selected_strategy_as_grading(self):
        _,version=self.material();self.scope(version)
        from routers.course_materials import retrieval_preview
        with patch.dict(os.environ,{'MISRA_RETRIEVAL_STRATEGY':'neural_hybrid_v1'}), \
             patch('services.neural_retrieval_service.get_backend',return_value=FakeBackend()):
            context=retrieval_preview('q',self.db,self.user)
        self.assertEqual(context['strategy'],'neural_hybrid_v1')


if __name__=='__main__':unittest.main()
