"""Page/region accounting, not independent proof that a vision model saw all ink."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from typing import Any, Callable, Iterable, TYPE_CHECKING
from sqlalchemy import func, inspect
from sqlalchemy.orm import Session
from models import AnswerSource, ExtractionInventory, Submission

if TYPE_CHECKING:
    from services.ocr_service import OCRPageResult, OCRSegment
    from services.whole_paper_mapping_service import MappingDecision


def confirmed_recovery_regions(
    db: Session, submission: Submission, page_index: int,
    bounding_box: dict[str, float] | None,
) -> list[dict[str, Any]]:
    """Link a signed, instructor-confirmed recovery only to a tightly matching region.

    A whole-page rectangle must not silently clear several small missing regions.
    This is geometric accounting, not a claim that the recovered text is correct.
    """
    if not bounding_box or not schema_available(db):
        return []
    inventory = db.query(ExtractionInventory).filter(
        ExtractionInventory.submission_id == submission.id,
        ExtractionInventory.institution_id == submission.institution_id,
    ).order_by(ExtractionInventory.version_number.desc()).first()
    if not inventory or inventory.manifest_sha256 != _seal(inventory):
        return []
    result = []
    for page in inventory.pages:
        if page["page_index"] != page_index:
            continue
        for index, region in enumerate(page["answer_regions"]):
            if _tight_region_match(bounding_box, region["bounding_box"]):
                result.append({"inventory_id": inventory.id, "page_index": page_index,
                               "region_index": index})
    return result


def _tight_region_match(candidate: dict[str, float], region: dict[str, float]) -> bool:
    left = max(candidate["x"], region["x"])
    top = max(candidate["y"], region["y"])
    right = min(candidate["x"] + candidate["width"], region["x"] + region["width"])
    bottom = min(candidate["y"] + candidate["height"], region["y"] + region["height"])
    intersection = max(0, right - left) * max(0, bottom - top)
    region_area = region["width"] * region["height"]
    union = candidate["width"] * candidate["height"] + region_area - intersection
    return region_area > 0 and union > 0 and intersection / region_area >= .95 and intersection / union >= .8


def schema_available(db: Session) -> bool:
    return inspect(db.connection()).has_table(ExtractionInventory.__tablename__)


def _seal(inventory: ExtractionInventory) -> str:
    value = {"submission_id":inventory.submission_id,"institution_id":inventory.institution_id,
        "schema_version":inventory.schema_version,"page_count":inventory.page_count,
        "document_sha256":inventory.document_sha256,"pages":inventory.pages}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def save_inventory(
    db: Session, submission: Submission, pages: list[OCRPageResult],
    mapping: dict[tuple[int, int], MappingDecision], file_bytes: bytes,
    is_cover_mark: Callable[[OCRSegment, OCRPageResult, int, int], bool],
) -> ExtractionInventory | None:
    if not schema_available(db):
        return None
    db.query(Submission).filter(Submission.id == submission.id).with_for_update().one()
    version = db.query(func.max(ExtractionInventory.version_number)).filter(ExtractionInventory.submission_id == submission.id).scalar() or 0
    records = []
    for page_index,page in enumerate(pages):
        segments = []
        for index,segment in enumerate(page.segments):
            decision = mapping[(page_index,index)]
            excluded = segment.content_role != "answer" or is_cover_mark(segment,page,len(pages),page_index)
            segments.append({"segment_index":index,"content_role":segment.content_role,
                "excluded":excluded,"mapped_question_id":decision.question_id,"mapping_method":decision.method,
                "printed_question_number":segment.printed_question_number,
                "bounding_box":segment.bounding_box.model_dump() if segment.bounding_box else None})
        records.append({"page_index":page_index,"page_role":page.page_role,"segments":segments,
            "answer_regions":[region.model_dump() for region in page.answer_regions],
            "coverage_reported_complete":page.coverage_reported_complete,"coverage_notes":page.coverage_notes})
    inventory = ExtractionInventory(submission_id=submission.id,institution_id=submission.institution_id,
        version_number=version+1,schema_version=1,page_count=len(pages),document_sha256=hashlib.sha256(file_bytes).hexdigest(),
        pages=records,manifest_sha256="pending")
    inventory.manifest_sha256 = _seal(inventory)
    db.add(inventory)
    db.flush()
    return inventory


def coverage_report(
    db: Session, submission: Submission, sources: Iterable[AnswerSource],
    excluded_segments: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    base = {"status":"not_recorded","inventory_id":None,"inventory_version":None,"pages":[],
        "page_count":submission.page_count,"accounted_region_count":0,"answer_region_count":0,
        "unaccounted_region_count":0,"warnings":[],"issues":[],
        "interpretation":"This is provider-reported page/region accounting, not independent verification that all handwriting was seen."}
    if not schema_available(db):
        return base
    inventory = db.query(ExtractionInventory).filter(ExtractionInventory.submission_id == submission.id,
        ExtractionInventory.institution_id == submission.institution_id).order_by(ExtractionInventory.version_number.desc()).first()
    if not inventory:
        return base
    base.update(inventory_id=inventory.id,inventory_version=inventory.version_number,document_sha256=inventory.document_sha256,manifest_sha256=inventory.manifest_sha256)
    if inventory.manifest_sha256 != _seal(inventory) or inventory.page_count != submission.page_count:
        base.update(status="invalid",issues=[{"code":"coverage_inventory_changed","message":"The saved extraction inventory changed. Reprocess this ungraded paper or review its history."}])
        return base
    assigned = set()
    recovered = set()
    for source in sources:
        raw = source.ocr_segment or {}
        origin = raw.get("ocr_origin") or {}
        if origin.get("inventory_id") == inventory.id and source.page_index == origin.get("page_index"):
            assigned.add((source.page_index,origin.get("segment_index")))
        recovery = raw.get("recovery") or {}
        if recovery.get("approved") is True and recovery.get("preview_signature"):
            for ref in recovery.get("coverage_region_refs", []):
                if ref.get("inventory_id") == inventory.id and ref.get("page_index") == source.page_index:
                    recovered.add((source.page_index, ref.get("region_index")))
    excluded = set()
    for segment in excluded_segments:
        origin = segment.get("ocr_origin") or {}
        if origin.get("inventory_id") == inventory.id:
            excluded.add((origin.get("page_index"),origin.get("segment_index")))
    unknown = False
    for record in inventory.pages:
        page_index = record["page_index"]
        segments = {item["segment_index"]:item for item in record["segments"]}
        regions = record["answer_regions"]
        page_result = {"page_index":page_index,"page_number":page_index+1,"page_role":record["page_role"],
            "coverage_reported_complete":record["coverage_reported_complete"],"coverage_notes":record["coverage_notes"],"regions":[],"issues":[]}
        if record["coverage_reported_complete"] is not True:
            unknown = True
            base["warnings"].append({"code":"page_coverage_unverified","page_index":page_index,"page_number":page_index+1,
                "message":"The OCR provider did not confirm a full-page answer-region inventory."})
        inventoried = set()
        for index,region in enumerate(regions):
            links = region["segment_indices"]
            inventoried.update(links)
            valid = bool(links) and len(links) == len(set(links)) and all(type(link) is int and link in segments and segments[link]["content_role"] == "answer" for link in links)
            confirmed_recovery = (page_index, index) in recovered
            accounted = confirmed_recovery or (valid and all((page_index,link) in assigned or (page_index,link) in excluded for link in links))
            if not accounted:
                issue = {"code":"unaccounted_answer_region","page_index":page_index,"page_number":page_index+1,"region_index":index,
                    "bounding_box":deepcopy(region["bounding_box"]),"message":"Visible student work in this region has no complete mapped transcription or explicit instructor exclusion."}
                page_result["issues"].append(issue)
                base["issues"].append(issue)
            page_result["regions"].append({"region_index":index,"bounding_box":deepcopy(region["bounding_box"]),
                "segment_indices":list(links),"accounted":accounted,"confirmed_recovery":confirmed_recovery,"note":region.get("note")})
            base["answer_region_count"] += 1
            base["accounted_region_count"] += int(accounted)
        unlisted = [index for index,item in segments.items() if item["content_role"] == "answer" and not item["excluded"] and index not in inventoried]
        if record["coverage_reported_complete"] is True and unlisted:
            unknown = True
            base["warnings"].append({"code":"transcribed_segments_not_in_region_inventory","page_index":page_index,"page_number":page_index+1,
                "segment_indices":unlisted,"message":"Some transcribed student work has no corresponding page-region inventory."})
        base["pages"].append(page_result)
    base["unaccounted_region_count"] = base["answer_region_count"] - base["accounted_region_count"]
    base["status"] = "needs_attention" if base["issues"] else "unverified" if unknown else "provider_accounted"
    return base
