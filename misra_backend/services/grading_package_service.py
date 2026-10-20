"""Exact question-linked retrieval. Snapshots contain no private filesystem paths."""
from copy import deepcopy
import hashlib
import json
from io import BytesIO
from pathlib import Path

from models import Answer, AnswerSource, Exam, QuestionGradingPolicy, Submission
from services.answer_key_service import resolve_answer_key, public_snapshot
from services.assessment_readiness_service import definition_consistency
from services.rubric_version_service import get_effective_rubric
from services.material_retrieval_service import retrieve_for_question, provider_sources, configured_strategy


def _routing_snapshot(answer, question, rubric, policy, mode, db, context=None):
    """Describe a routing decision without making a grading judgment."""
    if context is not None:
        snapshot = deepcopy(context)
    else:
        policy_mode = policy.mode if policy and policy.enabled else "adaptive"
        snapshot = {
            "requested_mode": mode,
            "policy_mode": policy_mode,
            "selected_mode": mode,
            "route_reasons": [{"code": "explicit_request", "detail": mode}],
            "image_audit_performed": False,
        }
    snapshot.setdefault("selected_mode", mode)
    snapshot.setdefault("route_reasons", [])
    snapshot["policy_enabled"] = bool(policy and policy.enabled)
    if policy:
        snapshot.update({field: float(getattr(policy, field)) for field in
                         ("audit_rate", "material_absolute_points", "material_relative_ratio")})
        snapshot["min_validated_samples"] = policy.min_validated_samples
    return snapshot


def build_grading_package(answer, question, db, mode, routing_context=None):
    submission = db.query(Submission).filter(Submission.id == answer.submission_id).first()
    exam = db.query(Exam).filter(Exam.id == question.exam_id).first()
    if not submission or not exam or submission.exam_id != question.exam_id or not (
        answer.institution_id == question.institution_id == submission.institution_id == exam.institution_id
    ):
        raise ValueError("Answer evidence does not belong to this assessment.")
    rubric, rubric_id = get_effective_rubric(question, db)
    if (rubric.get("policy") or {}).get("assessment_scope") == "external":
        raise ValueError("This question is assessed outside MISRA. No AI grade may be generated.")
    key = resolve_answer_key(question, db, rubric)
    policy = db.query(QuestionGradingPolicy).filter(QuestionGradingPolicy.question_id == question.id).first()
    consistency = definition_consistency(question, rubric, key, policy)
    if consistency["blocking_errors"]:
        messages = " ".join(item["message"] for item in consistency["blocking_errors"])
        raise ValueError("Assessment setup needs attention: " + messages)
    sources = db.query(AnswerSource).filter(AnswerSource.answer_id == answer.id).order_by(
        AnswerSource.page_index, AnswerSource.segment_index).all()
    if any(s.page_index < 0 or s.page_index >= submission.page_count for s in sources):
        raise ValueError("Student evidence references an unavailable page. Review extraction mapping.")
    from services.answer_area_service import answer_revisions
    areas = answer_revisions(db,answer,sources)
    revised = {area['source_id']:area for area in areas}
    effective_text = '\n'.join(revised[s.id]['text'] if s.id in revised else s.extracted_text for s in sources) if areas else answer.raw_ocr_text or ''
    evidence = [{"id": f"answer:{answer.id}:text", "kind": "combined_ocr", "text": effective_text}]
    evidence.extend({"id": f"source:{s.id}", "kind": "ocr_segment", "page_index": s.page_index,
                     "segment_index": s.segment_index, "text": revised[s.id]['text'] if s.id in revised else s.extracted_text} for s in sources)
    if mode == "image_text":
        evidence.extend({"id": f"page:{p}", "kind": "student_image", "page_index": p}
                        for p in sorted({s.page_index for s in sources}))
        evidence.extend({'id':f"area:{area['id']}",'kind':'student_image','page_index':area['page_index'],
            'image_role':'instructor_selected_region','bounding_box':deepcopy(area['bounding_box']),
            'source_segment_index':next(s.segment_index for s in sources if s.id==area['source_id'])} for area in areas)
    public_key = public_snapshot(key)
    public_key["reference_id"] = f"key:{key['id'] or 'legacy'}"
    scoring_rubric = deepcopy(rubric)
    # The separately approved key is authoritative for references, never for marks.
    scoring_rubric.pop("reference_context", None)
    scoring_rubric.pop("acceptable_answers", None)
    routing = _routing_snapshot(answer, question, rubric, policy, mode, db, routing_context)
    course_references = retrieve_for_question(db, question, rubric, strategy=configured_strategy())
    from services.extraction_coverage_service import coverage_report
    all_sources = db.query(AnswerSource).join(Answer,Answer.id == AnswerSource.answer_id).filter(Answer.submission_id == submission.id).all()
    coverage = coverage_report(db,submission,all_sources,[item for item in (submission.unmatched_segments or []) if item.get("excluded_reason")])
    if coverage["issues"]:
        raise ValueError("Visible student work is not fully accounted for. Re-scan the indicated paper regions before grading; no grade was saved.")
    if course_references["status"] == "incomplete":
        consistency["advisories"].append({"code":"reference_retrieval_incomplete",
            "message":"Optional course retrieval found incomplete context. Verify against the approved key and criteria."})
    package = {
        "schema_version": 1, "institution_id": answer.institution_id, "assessment_id": question.exam_id,
        "submission_id": submission.id, "answer_id": answer.id,
        "question": {"id": question.id, "number": question.question_number,
                     "text": question.question_text, "max_score": float(question.max_score)},
        "rubric_version_id": rubric_id, "rubric": scoring_rubric,
        "policy_version_id": rubric_id, "policy": deepcopy(rubric.get("policy") or {}),
        "answer_key": public_key, "routing": routing,
        "definition_consistency": consistency, "student_evidence": evidence,
        "course_references": course_references,
        "extraction_coverage":coverage,
        "student_document_sha256": None,
    }
    if areas:
        package['selected_answer_areas'] = deepcopy(areas)
        package['original_student_evidence'] = {'combined_ocr':answer.raw_ocr_text,
            'sources':[{'id':s.id,'text':s.extracted_text,'ocr_segment':deepcopy(s.ocr_segment)} for s in sources]}
    from services.answer_location_service import stored_path
    path = stored_path(submission.original_file_path) if areas else Path(submission.original_file_path)
    if path.is_file():
        with path.open("rb") as stream:
            package["student_document_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    if any(area['document_sha256']!=package['student_document_sha256'] for area in areas):
        raise ValueError('The original paper changed after the area correction. Review extraction again.')
    package["snapshot_sha256"] = hashlib.sha256(json.dumps(package, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return package, key, deepcopy(rubric), rubric_id


def provider_grading_package(package):
    """Return the minimum grading context that may leave MISRA.

    The persisted package is an internal audit snapshot and intentionally keeps
    database identifiers and content hashes.  Providers need the academic
    definition and evidence, not tenant, assessment, submission, answer,
    processing-job, filesystem-integrity, or snapshot metadata.

    The returned maps translate provider-safe citation aliases back to the
    identifiers in the immutable local snapshot after the model responds.
    """
    evidence = []
    evidence_aliases = {}
    counters = {"combined_ocr": 0, "ocr_segment": 0, "student_image": 0}
    prefixes = {
        "combined_ocr": "student:combined",
        "ocr_segment": "student:segment",
        "student_image": "student:page",
    }
    for item in package.get("student_evidence", []):
        kind = item.get("kind")
        if kind not in prefixes:
            continue
        counters[kind] += 1
        alias = f"{prefixes[kind]}:{counters[kind]}"
        evidence_aliases[alias] = item["id"]
        safe_item = {"id": alias, "kind": kind}
        for field in ("page_index", "segment_index", "text", "image_role", "bounding_box", "source_segment_index"):
            if field in item:
                safe_item[field] = deepcopy(item[field])
        evidence.append(safe_item)

    local_key_id = package.get("answer_key", {}).get("reference_id")
    key = package.get("answer_key", {})
    # A no-fixed-answer rubric has no citable answer key. Advertising a key ID
    # here invites a citation which the local validator must then reject.
    provider_key_id = "instructor:answer_key" if key.get("mode") != "no_fixed_answer" and local_key_id else None
    safe_key = {
        "reference_id": provider_key_id,
        "version": key.get("version"),
        "mode": key.get("mode"),
        "reference_text": deepcopy(key.get("reference_text") or ""),
        "alternatives": deepcopy(key.get("alternatives") or []),
        "document_refs": [
            {
                "page_indices": deepcopy(ref.get("page_indices") or []),
                "media_type": ref.get("media_type"),
            }
            for ref in key.get("document_refs", [])
        ],
        "is_legacy_fallback": bool(key.get("is_legacy_fallback")),
    }
    local_routing = package.get("routing") or {}
    safe_routing = {
        field: deepcopy(local_routing[field])
        for field in (
            "requested_mode",
            "policy_mode",
            "selected_mode",
            "route_reasons",
            "image_audit_performed",
            "policy_enabled",
            "audit_rate",
            "material_absolute_points",
            "material_relative_ratio",
            "min_validated_samples",
        )
        if field in local_routing
    }
    safe_package = {
        "schema_version": package.get("schema_version"),
        "question": {
            field: deepcopy(package.get("question", {}).get(field))
            for field in ("number", "text", "max_score")
        },
        "rubric": deepcopy(package.get("rubric") or {}),
        "policy": deepcopy(package.get("policy") or {}),
        "answer_key": safe_key,
        "routing": safe_routing,
        "definition_consistency": deepcopy(package.get("definition_consistency") or {}),
        "student_evidence": evidence,
    }
    safe_sources, source_aliases = provider_sources(package.get("course_references") or {})
    safe_package["course_references"] = safe_sources
    from services.grading_numeric_checks import numeric_context
    arithmetic = numeric_context(evidence)
    if arithmetic['checks']:
        safe_package['numeric_checks'] = arithmetic
    reference_aliases = {provider_key_id: local_key_id} if provider_key_id else {}
    reference_aliases.update(source_aliases)
    safe_package["citation_contract"] = {
        "evidence_refs": [item["id"] for item in evidence],
        "tracked_evidence_refs": [item["id"] for item in evidence
                                  if item["kind"] in {"ocr_segment", "student_image"}],
        "policy_applied": list(safe_package["policy"]),
        "criteria": [
            {"criterion_id": criterion["id"],
             "reference_refs": ([provider_key_id] if provider_key_id else []) + [
                 passage["id"] for passage in safe_sources["passages"]
                 if criterion["id"] in passage["criterion_ids"]],
             "required_course_reference_refs": [
                 passage["id"] for passage in safe_sources["passages"]
                 if criterion["id"] in passage["criterion_ids"]]
                 if safe_sources["mode"] == "required" else []}
            for criterion in safe_package["rubric"].get("criteria", [])
        ],
    }
    return safe_package, evidence_aliases, reference_aliases


def restore_provider_citations(result, evidence_aliases, reference_aliases):
    """Translate provider aliases before local citation validation/persistence."""
    for criterion in result.criteria_scores:
        criterion.evidence_refs = [evidence_aliases.get(ref, ref) for ref in criterion.evidence_refs]
        criterion.reference_refs = [reference_aliases.get(ref, ref) for ref in criterion.reference_refs]


def reference_images(key):
    """Load only approved reference pages, labeled separately from student images."""
    from pdf2image import convert_from_bytes
    from PIL import Image
    content = []
    for document_number, ref in enumerate(key["document_refs"], start=1):
        # Decode the exact bytes verified here, not a path that could change
        # between approval validation and provider request construction.
        document = Path(ref["path"]).read_bytes()
        if hashlib.sha256(document).hexdigest() != ref["sha256"]:
            raise ValueError("Approved answer-key document has changed. Approve a new key version.")
        for page in ref["page_indices"]:
            content.append(
                f"INSTRUCTOR REFERENCE: answer-key document {document_number}, "
                f"page {page + 1}. Not student work."
            )
            if ref["media_type"] == "application/pdf":
                images = convert_from_bytes(document, first_page=page + 1, last_page=page + 1)
                content.extend(images)
            else:
                with Image.open(BytesIO(document)) as image:
                    content.append(image.convert("RGB").copy())
    return content


def validate_evidence_references(result, package):
    from services.grading_errors import CitationValidationError
    student_ids = {item["id"] for item in package["student_evidence"]}
    traceable_ids = {
        item["id"] for item in package["student_evidence"]
        if item.get("kind") in {"ocr_segment", "student_image"}
    }
    key_id = package["answer_key"]["reference_id"]
    for criterion in result.criteria_scores:
        if not set(criterion.evidence_refs).issubset(student_ids):
            raise CitationValidationError("invalid_student_reference", "A criterion cites student evidence outside the grading package.")
        if traceable_ids and not set(criterion.evidence_refs).intersection(traceable_ids):
            raise CitationValidationError("missing_traceable_evidence",
                "A criterion must cite a tracked source segment or source page when one is available."
            )
        allowed_keys = {key_id} if package["answer_key"]["mode"] != "no_fixed_answer" else set()
        allowed_keys.update(p["id"] for p in package.get("course_references", {}).get("passages", [])
            if criterion.criterion_id in p["criterion_ids"])
        if not set(criterion.reference_refs).issubset(allowed_keys):
            raise CitationValidationError("invalid_reference", "A criterion cites an unavailable answer-key or course-source reference.")
        course_context = package.get('course_references') or {}
        if course_context.get('mode') == 'required':
            applicable = {p['id'] for p in course_context.get('passages', [])
                          if criterion.criterion_id in p['criterion_ids']}
            if not applicable or not applicable.intersection(criterion.reference_refs):
                raise CitationValidationError('missing_course_reference',
                    'Source-grounded grading must cite an approved course passage for every criterion. '
                    'An answer-key citation alone does not establish lecture grounding.')
        if not set(criterion.policy_applied).issubset(set(package["policy"])):
            raise CitationValidationError("invalid_policy", "A criterion cites an unknown marking-policy field.")
