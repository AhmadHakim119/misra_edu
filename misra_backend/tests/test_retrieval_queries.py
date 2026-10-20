"""Synthetic exact-definition query binding; no real models or academic data."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from services.retrieval_query_service import bind_concept_query,criterion_query,validate_concept_queries
from services.benchmark_runner import grading_package,retrieval_context
from services.grading_package_service import provider_grading_package


class ConceptQueryTests(unittest.TestCase):
    def setUp(self):
        self.question=dict(id='q',number='1',text='Synthetic question about change in a measured quantity.',max_score=1,answer_key='Synthetic approved relation R.',
            criteria=[dict(id='c',title='Uses relation R.',description='Uses relation R.',full_credit_conditions='Uses relation R.',points=1)])
        self.criterion=self.question['criteria'][0]
        self.record=bind_concept_query(self.question['text'],self.criterion,'Measured quantity rate and interval relation',generator='synthetic-reader',request_id='synthetic-request')

    def test_default_query_bytes_remain_unchanged(self):
        expected=' '.join([self.question['text'],'Uses relation R.','Uses relation R.','Uses relation R.'])
        self.assertEqual(criterion_query(self.question['text'],self.criterion),expected)

    def test_bound_query_changes_search_only_without_mutating_definition(self):
        before=deepcopy(self.question);records=validate_concept_queries(self.question['text'],[self.criterion],{'c':self.record})
        self.assertEqual(criterion_query(self.question['text'],self.criterion,records),self.record['query'])
        self.assertEqual(self.question,before)
        records['c']['query']='changed caller copy'
        self.assertNotEqual(records['c']['query'],self.record['query'])

    def test_question_criterion_and_score_changes_invalidate_old_proposal(self):
        for question,criterion in [(self.question['text']+' changed',self.criterion),
                (self.question['text'],self.criterion|{'description':'Different requirement'}),
                (self.question['text'],self.criterion|{'points':2})]:
            with self.subTest(question=question,criterion=criterion),self.assertRaises(ValueError):
                validate_concept_queries(question,[criterion],{'c':self.record})

    def test_missing_unknown_duplicate_or_extra_records_cannot_silently_fall_back(self):
        for criteria,records in [([self.criterion],{}),([self.criterion],{'extra':self.record}),
                ([self.criterion,self.criterion],{'c':self.record}),
                ([self.criterion],{'c':self.record|{'student_text':'Untrusted search override'}}),
                ([self.criterion],{'c':self.record|{'reference_score':1}})]:
            with self.subTest(records=records),self.assertRaises(ValueError):
                validate_concept_queries(self.question['text'],criteria,records)

    def test_malformed_criterion_identifiers_fail_with_a_validation_error(self):
        for criteria in [[{'id':[]}],[None],{},None]:
            with self.subTest(criteria=criteria),self.assertRaises(ValueError):
                validate_concept_queries(self.question['text'],criteria,{'c':self.record})

    def test_untrusted_query_contract_and_version_are_bounded(self):
        for changes in [dict(query=''),dict(query='x'*501),dict(query='line\nbreak'),dict(generator=True),
                        dict(request_id=None),dict(version='invented'),dict(definition_sha256='0'*64)]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_concept_queries(self.question['text'],[self.criterion],{'c':self.record|changes})

    def test_arabic_concept_queries_are_preserved(self):
        r=bind_concept_query(self.question['text'],self.criterion,'العلاقة بين الكمية ومعدل التغير والزمن',generator='synthetic',request_id='r')
        self.assertEqual(validate_concept_queries(self.question['text'],[self.criterion],{'c':r})['c']['query'],r['query'])

    def test_nonfinite_definition_cannot_be_fingerprinted(self):
        with self.assertRaises(ValueError):
            bind_concept_query(self.question['text'],self.criterion|{'points':float('nan')},'concept',generator='s',request_id='r')

    def test_research_search_uses_bound_query_but_preserves_candidates_and_grading_contract(self):
        import hashlib
        text='Approved synthetic relation between quantity and interval.'
        inputs=dict(questions={'q':self.question},guide={'policy':{}},guide_sha256='a'*64,sources_sha256='b'*64,
            chunks=[dict(id='chunk',text=text,text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                document_sha256='c'*64,title='Synthetic course',page_index=0)])
        case=dict(answer_id='synthetic-answer',question_id='q',student_text='STUDENT_TOKEN_NOT_A_QUERY')
        before=deepcopy(inputs)
        with patch('services.neural_retrieval_service.rank_passages',return_value=([1],[dict(dense_cosine=.8,reranker_logit=2)])) as rank:
            package=grading_package(case,inputs,'bm25',retrieval_strategy='dense_rerank_v1',concept_queries={'c':self.record})
        args=rank.call_args.args
        self.assertEqual(args[0],[text]);self.assertEqual(args[1],self.record['query'])
        self.assertNotIn('STUDENT_TOKEN',args[1]);self.assertEqual(inputs,before)
        safe,_,_=provider_grading_package(package)
        self.assertNotIn('concept_queries',safe['course_references'])
        self.assertEqual(package['question']['text'],self.question['text'])
        with self.assertRaises(ValueError):grading_package(case,inputs,'no_rag',concept_queries={'c':self.record})


if __name__=='__main__':unittest.main()
