"""Bounded, approved-source BM25 RAG; query construction never uses student text."""
from collections import Counter
from copy import deepcopy
import math
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


def retrieve_for_question(db, question, rubric, *, proposal_scope=None):
    empty = {"strategy":"bm25_v1", "scope_version_id":None, "scope_version_number":None,
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
    selected, query_snapshots = {}, []
    required_criteria = {c['id'] for c in rubric.get('criteria', [])} if scope.mode == 'required' else set()
    for criterion in rubric.get("criteria", []):
        cid = criterion["id"]
        eligible = [item for item in candidates.values() if None in binding_criteria[item[0].id] or cid in binding_criteria[item[0].id]]
        if not eligible:
            continue
        required_criteria.add(cid)
        query = " ".join(str(value or "") for value in (question.question_text, criterion.get("title"), criterion.get("description"), criterion.get("full_credit_conditions")))[:5000]
        scores = bm25_scores([item[0].text for item in eligible], query)
        ranked = sorted(zip(eligible, scores), key=lambda pair:(pair[0][0].id not in exact_ids, -pair[1], pair[0][0].id))
        hits = [(item,score) for item,score in ranked if score > 0 or item[0].id in exact_ids][:2]
        query_snapshots.append({"criterion_id":cid, "query":query, "candidate_count":len(eligible), "selected_chunk_ids":[item[0].id for item,score in hits]})
        for item,score in hits:
            chunk,version,material,page = item
            if chunk.id not in selected:
                selected[chunk.id] = {"id":f"material:{chunk.id}", "chunk_id":chunk.id, "material_id":material.id,
                    "material_version_id":version.id, "material_version_number":version.version_number,
                    "title":material.title, "page_index":chunk.page_index, "printed_page_label":page.printed_page_label,
                    "char_start":chunk.char_start, "char_end":chunk.char_end, "text":chunk.text,
                    "text_sha256":chunk.text_sha256, "document_sha256":version.document_sha256,
                    "content_sha256":version.content_sha256, "parser_version":version.parser_version,
                    "selection":"exact_link" if chunk.id in exact_ids else "bm25", "retrieval_score":score,
                    "criterion_ids":[], "source_role":"approved_course_reference"}
            selected[chunk.id]["criterion_ids"].append(cid)
    passages, total_chars = [], 0
    for item in selected.values():
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
