"""Exact question-linked retrieval. Snapshots contain no private filesystem paths."""
from copy import deepcopy
import hashlib
import json
from io import BytesIO
from pathlib import Path

from models import AnswerSource, Exam, QuestionGradingPolicy, Submission
from services.answer_key_service import resolve_answer_key, public_snapshot
from services.assessment_readiness_service import definition_consistency
from services.rubric_version_service import get_effective_rubric


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
    evidence = [{"id": f"answer:{answer.id}:text", "kind": "combined_ocr", "text": answer.raw_ocr_text or ""}]
    evidence.extend({"id": f"source:{s.id}", "kind": "ocr_segment", "page_index": s.page_index,
                     "segment_index": s.segment_index, "text": s.extracted_text} for s in sources)
    if mode == "image_text":
        evidence.extend({"id": f"page:{p}", "kind": "student_image", "page_index": p}
                        for p in sorted({s.page_index for s in sources}))
    public_key = public_snapshot(key)
    public_key["reference_id"] = f"key:{key['id'] or 'legacy'}"
    scoring_rubric = deepcopy(rubric)
    # The separately approved key is authoritative for references, never for marks.
    scoring_rubric.pop("reference_context", None)
    scoring_rubric.pop("acceptable_answers", None)
    routing = _routing_snapshot(answer, question, rubric, policy, mode, db, routing_context)
    package = {
        "schema_version": 1, "institution_id": answer.institution_id, "assessment_id": question.exam_id,
        "submission_id": submission.id, "answer_id": answer.id,
        "question": {"id": question.id, "number": question.question_number,
                     "text": question.question_text, "max_score": float(question.max_score)},
        "rubric_version_id": rubric_id, "rubric": scoring_rubric,
        "policy_version_id": rubric_id, "policy": deepcopy(rubric.get("policy") or {}),
        "answer_key": public_key, "routing": routing,
        "definition_consistency": consistency, "student_evidence": evidence,
        "student_document_sha256": None,
    }
    path = Path(submission.original_file_path)
    if path.is_file():
        with path.open("rb") as stream:
            package["student_document_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
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
        for field in ("page_index", "segment_index", "text"):
            if field in item:
                safe_item[field] = deepcopy(item[field])
        evidence.append(safe_item)

    local_key_id = package.get("answer_key", {}).get("reference_id")
    provider_key_id = "instructor:answer_key"
    key = package.get("answer_key", {})
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
    reference_aliases = {provider_key_id: local_key_id} if local_key_id else {}
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
    student_ids = {item["id"] for item in package["student_evidence"]}
    traceable_ids = {
        item["id"] for item in package["student_evidence"]
        if item.get("kind") in {"ocr_segment", "student_image"}
    }
    key_id = package["answer_key"]["reference_id"]
    for criterion in result.criteria_scores:
        if not set(criterion.evidence_refs).issubset(student_ids):
            raise ValueError("A criterion cites student evidence outside the grading package.")
        if traceable_ids and not set(criterion.evidence_refs).intersection(traceable_ids):
            raise ValueError(
                "A criterion must cite a tracked source segment or source page when one is available."
            )
        allowed_keys = {key_id} if package["answer_key"]["mode"] != "no_fixed_answer" else set()
        if not set(criterion.reference_refs).issubset(allowed_keys):
            raise ValueError("A criterion cites an unavailable answer-key reference.")
        if not set(criterion.policy_applied).issubset(set(package["policy"])):
            raise ValueError("A criterion cites an unknown marking-policy field.")
