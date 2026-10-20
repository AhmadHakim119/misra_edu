"""Bounded, approved-source RAG; query construction never uses student text."""
from collections import Counter
from copy import deepcopy
import math
import os
import re

from models import CourseMaterial, MaterialVersion, MaterialPage, MaterialChunk
from schemas.course_materials import MaterialScopeRequest, AssessmentMaterialScopeRequest
from services.course_material_service import schema_available, validate_bindings
from services.assessment_source_service import resolve_scope
from sqlalchemy import inspect

STOPWORDS = frozenset("a an the of in to for and or on with as is are was be by from this that its it what how which".split())
MAX_PASSAGES = 8
MAX_CONTEXT_CHARS = 12000
MAX_CANDIDATES = 6000
NEURAL_STRATEGIES = frozenset({'bm25_rerank_v1', 'neural_hybrid_v1', 'dense_v1', 'dense_rerank_v1'})
STRATEGIES = {'bm25_v1', 'hybrid_rrf_v1', *NEURAL_STRATEGIES}


def configured_strategy():
    strategy = os.getenv('MISRA_RETRIEVAL_STRATEGY', 'bm25_v1')
    if strategy not in STRATEGIES:
        raise ValueError('Unknown configured course retrieval strategy.')
    return strategy


def tokens(text):
    return [word for word in re.findall(r"\w+", text.casefold(), flags=re.UNICODE) if word not in STOPWORDS][:20000]


def bm25_scores(texts, query):
    documents = [tokens(text) for text in texts]
    if not documents:
        return []
    count = len(documents)
    average = sum(map(len, documents)) / count or 1
    frequency = Counter(word for document in documents for word in set(document))
    query_terms = set(tokens(query)[:200])
    result = []
    for document in documents:
        term_counts = Counter(document)
        score = 0.0
        for term in query_terms:
            occurrences = term_counts[term]
            if occurrences:
                inverse = math.log(1 + (count - frequency[term] + .5) / (frequency[term] + .5))
                score += inverse * occurrences * 2.5 / (occurrences + 1.5 * (.25 + .75 * len(document) / average))
        result.append(round(score, 6))
    return result


def retrieve_for_question(db, question, rubric, *, proposal_scope=None, strategy='bm25_v1', hits_per_criterion=2, concept_queries=None):
    if strategy not in STRATEGIES:
        raise ValueError('Unknown approved-source retrieval strategy.')
    if type(hits_per_criterion) is not int or not 1 <= hits_per_criterion <= 4:
        raise ValueError('Choose between one and four approved passages per criterion.')
    empty = {"strategy":strategy, "scope_version_id":None, "scope_version_number":None,
        "mode":"disabled", "status":"not_configured", "passages":[], "queries":[]}
    # Additive rollout: existing assessments work before the explicit migration.
    if not schema_available(db):
        from services.course_material_service import MATERIAL_TABLES
        inspector = inspect(db.connection())
        if any(inspector.has_table(model.__tablename__) for model in MATERIAL_TABLES):
            raise ValueError("Course-reference schema is incomplete. Finish the additive upgrade before grading.")
        return empty
    if proposal_scope is None:
        scope, origin, override = resolve_scope(db, question)
    else:
        # Only authoring proposals may read draft scope choices. The bound pages
        # still pass the same approved-content/ownership validation below.
        scope = proposal_scope
        if hasattr(scope, 'exam_id'):
            if scope.exam_id != question.exam_id:
                raise ValueError('Proposal sources belong to another assessment.')
            origin, override = 'assessment', None
        else:
            if scope.question_id != question.id:
                raise ValueError('Proposal sources belong to another question.')
            origin, override = 'question', scope
    if not scope:
        return {**empty, "scope_origin": origin, "question_scope_version_id": override.id if override else None}
    request_type = AssessmentMaterialScopeRequest if origin == "assessment" else MaterialScopeRequest
    request = request_type(mode=scope.mode, bindings=scope.bindings)
    validate_bindings(db, question, request, rubric)
    context = {**empty, "scope_version_id":scope.id, "scope_version_number":scope.version_number,
        "scope_sha256":scope.scope_sha256, "mode":scope.mode, "status":"disabled", "scope_origin":origin,
        "assessment_id":question.exam_id, "question_scope_version_id":override.id if override else None,
        "question_scope_version_number":override.version_number if override else None,
        "question_scope_sha256":override.scope_sha256 if override else None}
    if scope.mode == "disabled":
        return context
    candidates, exact_ids, binding_criteria = {}, set(), {}
    for binding in request.bindings:
        version = db.get(MaterialVersion, binding.version_id)
        material = db.get(CourseMaterial, version.material_id)
        pages = {p.page_index:p for p in db.query(MaterialPage).filter(MaterialPage.version_id == version.id).all()}
        query = db.query(MaterialChunk).filter(MaterialChunk.version_id == version.id, MaterialChunk.page_index.in_(binding.page_indices))
        if binding.chunk_ids:
            query = query.filter(MaterialChunk.id.in_(binding.chunk_ids))
            exact_ids.update(binding.chunk_ids)
        for chunk in query.order_by(MaterialChunk.page_index, MaterialChunk.ordinal).limit(MAX_CANDIDATES + 1).all():
            candidates[chunk.id] = (chunk, version, material, pages[chunk.page_index])
            binding_criteria.setdefault(chunk.id, set()).add(binding.criterion_id)
        if len(candidates) > MAX_CANDIDATES:
            raise ValueError("Reference scope is too broad. Select relevant chapter pages or exact passages.")
    from services.retrieval_query_service import validate_concept_queries,criterion_query,QUERY_VERSION
    concepts=validate_concept_queries(question.question_text,rubric.get('criteria',[]),concept_queries)
    if concepts is not None:
        context['query_strategy']=QUERY_VERSION
        context['concept_queries']=deepcopy(concepts)
    selected, query_snapshots = {}, []
    required_criteria = {c['id'] for c in rubric.get('criteria', [])} if scope.mode == 'required' else set()
    for criterion in rubric.get("criteria", []):
        cid = criterion["id"]
        eligible = [item for item in candidates.values() if None in binding_criteria[item[0].id] or cid in binding_criteria[item[0].id]]
        if not eligible:
            continue
        required_criteria.add(cid)
        query = criterion_query(question.question_text,criterion,concepts)
        ranking_details = None
        if strategy == 'hybrid_rrf_v1':
            from services.hybrid_retrieval_service import hybrid_scores
            scores, ranking_details = hybrid_scores([item[0].text for item in eligible], query)
        elif strategy in NEURAL_STRATEGIES:
            from services.neural_retrieval_service import rank_passages, model_metadata, fingerprint
            # Stable tie handling and institution/scope-specific cache isolation.
            eligible.sort(key=lambda item:item[0].id)
            namespace = fingerprint({'institution':question.institution_id,
                'assessment':question.exam_id, 'scope':scope.scope_sha256})
            scores, ranking_details = rank_passages([item[0].text for item in eligible], query,
                namespace=namespace, strategy=strategy,
                pinned_indices=[i for i,item in enumerate(eligible) if item[0].id in exact_ids])
            context['neural_retrieval'] = model_metadata(strategy)
        else:
            scores = bm25_scores([item[0].text for item in eligible], query)
        ranked = sorted(zip(eligible, scores), key=lambda pair:(pair[0][0].id not in exact_ids, -pair[1], pair[0][0].id))
        hits = [(item,score) for item,score in ranked if score > 0 or item[0].id in exact_ids][:hits_per_criterion]
        query_snapshots.append({"criterion_id":cid, "query":query, "candidate_count":len(eligible), "selected_chunk_ids":[item[0].id for item,score in hits]})
        if ranking_details is not None:
            by_id = {item[0].id: detail for item, detail in zip(eligible, ranking_details)}
            query_snapshots[-1]['ranking'] = {
                item[0].id: by_id[item[0].id] for item, _ in hits}
        for item,score in hits:
            chunk,version,material,page = item
            if chunk.id not in selected:
                selected[chunk.id] = {"id":f"material:{chunk.id}", "chunk_id":chunk.id, "material_id":material.id,
                    "material_version_id":version.id, "material_version_number":version.version_number,
                    "title":material.title, "page_index":chunk.page_index, "printed_page_label":page.printed_page_label,
                    "char_start":chunk.char_start, "char_end":chunk.char_end, "text":chunk.text,
                    "text_sha256":chunk.text_sha256, "document_sha256":version.document_sha256,
                    "content_sha256":version.content_sha256, "parser_version":version.parser_version,
                    "selection":"exact_link" if chunk.id in exact_ids else strategy.removesuffix('_v1'), "retrieval_score":score,
                    "criterion_ids":[], "source_role":"approved_course_reference"}
            selected[chunk.id]["criterion_ids"].append(cid)
    passages, total_chars = [], 0
    remaining = list(selected.values())
    if hits_per_criterion > 2 or strategy in NEURAL_STRATEGIES:
        # Supplemental retrieval must not spend its entire budget on the first
        # criterion. Cover criteria before adding extra explanatory passages.
        uncovered = set(required_criteria)
        while uncovered and len(passages) < MAX_PASSAGES:
            fitting = [item for item in remaining if uncovered.intersection(item['criterion_ids'])
                       and total_chars + len(item['text']) <= MAX_CONTEXT_CHARS]
            if not fitting:
                break
            item = max(fitting, key=lambda value: len(uncovered.intersection(value['criterion_ids'])))
            passages.append(item)
            total_chars += len(item['text'])
            uncovered.difference_update(item['criterion_ids'])
            remaining.remove(item)
    for item in remaining:
        if len(passages) == MAX_PASSAGES or total_chars + len(item["text"]) > MAX_CONTEXT_CHARS:
            continue  # Never cut a referenced passage or equation to fit a budget.
        passages.append(item)
        total_chars += len(item["text"])
    covered = {cid for item in passages for cid in item["criterion_ids"]}
    missing = sorted(required_criteria - covered)
    if scope.mode == "required" and (not passages or missing):
        raise ValueError("Approved-source retrieval lacks relevant context for the configured criteria. Select exact passages or narrow the reference scope.")
    context.update(status="retrieved" if passages and not missing else "incomplete", passages=passages,
        queries=query_snapshots, uncovered_criterion_ids=missing, total_context_chars=total_chars)
    return context


def provider_sources(context):
    aliases, passages = {}, []
    for number, passage in enumerate(context.get("passages", []), start=1):
        alias = f"instructor:source:{number}"
        aliases[alias] = passage["id"]
        passages.append({"id":alias, "title":passage["title"], "page_index":passage["page_index"],
            "printed_page_label":passage["printed_page_label"], "text":passage["text"],
            "criterion_ids":deepcopy(passage["criterion_ids"]), "source_role":"approved_course_reference"})
    return {"strategy":context.get("strategy"), "mode":context.get("mode"), "status":context.get("status"), "passages":passages}, aliases
