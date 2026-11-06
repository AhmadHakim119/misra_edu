"""Offline OCR pilot: preserve pages and raw output; never infer grades or cancellations."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
from time import perf_counter
from typing import Literal
from unittest.mock import patch

from pydantic import Field, model_validator

from rubric_pilot import Answer, StrictModel, json_text, save_new

VERSION = "local-ocr-pilot-v1"
PRIVATE_ROOT = Path(__file__).resolve().parents[1] / "private"


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def private_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError("Output must stay under the ignored repository private/ directory.")
    return path


class Box(StrictModel):
    x0: int = Field(ge=0)
    y0: int = Field(ge=0)
    x1: int = Field(gt=0)
    y1: int = Field(gt=0)

    @model_validator(mode="after")
    def nonempty(self):
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("Empty or reversed bounding box.")
        return self

    def inside(self, width, height):
        return self.x1 <= width and self.y1 <= height


class Span(StrictModel):
    id: str = Field(pattern=r"^p[0-9]+_s[0-9]+$")
    page: int = Field(ge=1)
    bbox: Box
    text: str = Field(min_length=1, max_length=10000)
    engine_confidence: float | None = Field(ge=0, le=1)
    cancellation: Literal["unknown"] = "unknown"
    role: Literal["unassigned"] = "unassigned"


class Page(StrictModel):
    number: int = Field(ge=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    image: str = Field(pattern=r"^pages/page-[0-9]+\.png$")
    issues: list[str]


class Extraction(StrictModel):
    version: Literal["local-ocr-pilot-v1"] = VERSION
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    engine: Literal["paddle", "tesseract"]
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["needs_transcription_review"] = "needs_transcription_review"
    pages: list[Page] = Field(min_length=1, max_length=20)
    spans: list[Span] = Field(max_length=10000)
    review_reasons: list[str]

    @model_validator(mode="after")
    def consistent(self):
        pages = {p.number: p for p in self.pages}
        if sorted(pages) != list(range(1, len(self.pages) + 1)):
            raise ValueError("Pages must be unique and contiguous.")
        if len({s.id for s in self.spans}) != len(self.spans):
            raise ValueError("Duplicate span IDs.")
        for s in self.spans:
            page = pages.get(s.page)
            if page is None or not s.bbox.inside(page.width, page.height):
                raise ValueError("Span is outside its source page.")
        return self


class OcrConfig(StrictModel):
    engine: Literal["paddle", "tesseract"]
    language: Literal["en", "ar", "ar+en"]
    detection_model_dir: str | None = None
    recognition_model_dir: str | None = None
    tesseract_exe: str | None = None
    tessdata_dir: str | None = None
    tesseract_psm: Literal[3, 6, 11] = 6

    @model_validator(mode="after")
    def configured(self):
        if self.engine == "paddle":
            if not self.detection_model_dir or not self.recognition_model_dir:
                raise ValueError("Paddle requires explicit local model directories.")
            if self.tesseract_exe or self.tessdata_dir:
                raise ValueError("Unexpected Tesseract configuration.")
        elif not self.tesseract_exe or not self.tessdata_dir:
            raise ValueError("Tesseract requires an explicit executable and local language data.")
        elif self.detection_model_dir or self.recognition_model_dir:
            raise ValueError("Unexpected Paddle configuration.")
        return self


@contextmanager
def offline_python():
    """Block Python socket connections, including implicit package model downloads.

    This is a CLI guard, not an OS sandbox. Native libraries are not a security boundary.
    """
    def deny(*args, **kwargs):
        raise RuntimeError("Network disabled during local OCR; prepare models separately.")
    with patch.dict(os.environ, {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                               "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True"}), \
         patch.object(socket.socket, "connect", deny), \
         patch.object(socket.socket, "connect_ex", deny), \
         patch.object(socket, "create_connection", deny), \
         patch.object(socket, "getaddrinfo", deny):
        yield


def parse_paddle(raw, page, width, height):
    data = raw.get("res", raw)
    texts, scores, polygons = data["rec_texts"], data["rec_scores"], data["rec_polys"]
    if not (len(texts) == len(scores) == len(polygons)):
        raise ValueError("Paddle text, confidence and geometry lengths disagree.")
    spans = []
    for i, (text, confidence, points) in enumerate(zip(texts, scores, polygons), 1):
        if not isinstance(text, str):
            raise ValueError("Invalid OCR text.")
        if not text.strip():
            continue
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("OCR confidence must be a finite numeric value.")
        if len(points) < 4 or any(len(p) != 2 for p in points):
            raise ValueError("Invalid OCR polygon.")
        coords = [float(v) for p in points for v in p]
        if not all(math.isfinite(v) for v in coords):
            raise ValueError("Non-finite OCR geometry.")
        xs, ys = coords[::2], coords[1::2]
        # Only round polygon extents outward, never silently clip out-of-page boxes.
        box = Box(x0=math.floor(min(xs)), y0=math.floor(min(ys)),
                  x1=math.ceil(max(xs)), y1=math.ceil(max(ys)))
        if not box.inside(width, height):
            raise ValueError("OCR polygon outside page.")
        spans.append(Span(id=f"p{page}_s{i}", page=page, bbox=box, text=text,
                          engine_confidence=float(confidence)))
    return spans


def parse_tesseract(tsv, page, width, height):
    spans = []
    rows = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    required = {"level", "text", "left", "top", "width", "height", "conf"}
    if not rows.fieldnames or not required.issubset(rows.fieldnames):
        raise ValueError("Tesseract did not return a valid TSV header.")
    for i, row in enumerate(rows, 1):
        if row["level"] != "5" or not row["text"].strip():
            continue
        x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        confidence = float(row["conf"])
        if not math.isfinite(confidence) or not 0 <= confidence <= 100:
            raise ValueError("Invalid Tesseract word confidence.")
        box = Box(x0=x, y0=y, x1=x+w, y1=y+h)
        if not box.inside(width, height):
            raise ValueError("OCR box outside page.")
        spans.append(Span(id=f"p{page}_s{i}", page=page, bbox=box,
                          text=row["text"], engine_confidence=confidence / 100))
    return spans


class PaddleBackend:
    def __init__(self, config):
        from paddleocr import PaddleOCR
        det, rec = Path(config.detection_model_dir), Path(config.recognition_model_dir)
        for path in (det, rec):
            for name in ("inference.json", "inference.pdiparams", "inference.yml"):
                if not (path / name).is_file():
                    raise ValueError("Local Paddle model files are incomplete.")
        import yaml
        def name(path):
            return yaml.safe_load((path / "inference.yml").read_text(encoding="utf-8"))["Global"]["model_name"]
        self.ocr = PaddleOCR(
            text_detection_model_name=name(det), text_detection_model_dir=str(det.resolve()),
            text_recognition_model_name=name(rec), text_recognition_model_dir=str(rec.resolve()),
            use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=False, device="cpu", enable_mkldnn=False, cpu_threads=4,
        )

    def recognize(self, image, page, width, height):
        results = list(self.ocr.predict(str(image), text_rec_score_thresh=0.0))
        if len(results) != 1:
            raise ValueError("Expected one OCR result per page.")
        raw = results[0].json
        if isinstance(raw, str):
            raw = json.loads(raw)
        return raw


class TesseractBackend:
    def __init__(self, config):
        self.exe = Path(config.tesseract_exe).resolve(strict=True)
        self.data = Path(config.tessdata_dir).resolve(strict=True)
        self.lang = {"en": "eng", "ar": "ara", "ar+en": "ara+eng"}[config.language]
        self.psm = config.tesseract_psm
        for lang in self.lang.split("+"):
            if not (self.data / f"{lang}.traineddata").is_file():
                raise ValueError("Required local Tesseract language data missing.")

    def recognize(self, image, page, width, height):
        # Only a resolved, locally rendered image is passed. Never URLs or user options.
        result = subprocess.run([str(self.exe), str(Path(image).resolve()), "stdout",
                                 "--tessdata-dir", str(self.data), "-l", self.lang,
                                 "--oem", "1", "--psm", str(self.psm),
                                 "-c", "tessedit_create_tsv=1"],
                                capture_output=True, timeout=120, check=True)
        tsv = result.stdout.decode("utf-8-sig")
        return {"tsv": tsv, "stderr": result.stderr.decode("utf-8", errors="replace")}


def preserve_pages(source, output, *, dpi=200):
    from PIL import Image, ImageOps
    source = Path(source).resolve(strict=True)
    if source.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Pilot input exceeds 50 MiB.")
    suffix = source.suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise ValueError("Use a local PDF, PNG or JPEG.")
    copy = output / f"original{suffix}"
    with source.open("rb") as src, copy.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    if file_hash(copy) != file_hash(source):
        raise ValueError("Source changed while copying.")
    pages_dir = output / "pages"
    pages_dir.mkdir()
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(copy)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
            raise ValueError("Pilot accepts 1–20 unencrypted PDF pages.")
        exe = shutil.which("pdftoppm")
        if not exe:
            raise RuntimeError("Poppler pdftoppm is required to preserve PDF pages.")
        subprocess.run([exe, "-png", "-r", str(dpi), "-scale-to", "3200",
                        str(copy), str(pages_dir / "render")],
                       capture_output=True, check=True, timeout=180)
        rendered = sorted(pages_dir.glob("render-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        if len(rendered) != len(reader.pages):
            raise ValueError("PDF renderer did not preserve every page.")
        for number, path in enumerate(rendered, 1):
            path.rename(pages_dir / f"page-{number}.png")
    else:
        with Image.open(copy) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Animated/multipage images require explicit PDF conversion.")
            ImageOps.exif_transpose(image).convert("RGB").save(pages_dir / "page-1.png")
    pages = []
    for number, image in enumerate(sorted(pages_dir.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1])), 1):
        with Image.open(image) as img:
            width, height = img.size
            if width * height > 40_000_000:
                raise ValueError("Page exceeds pilot pixel limit.")
        pages.append(Page(number=number, width=width, height=height,
                          image_sha256=file_hash(image), image=f"pages/{image.name}", issues=[]))
    return file_hash(copy), pages


def model_files(config):
    """Hash local weights/configs actually selected, rather than just model names."""
    result = {}
    if config.engine == "paddle":
        for label, directory in (("detector", config.detection_model_dir), ("recognizer", config.recognition_model_dir)):
            result[label] = {name: file_hash(Path(directory) / name)
                             for name in ("inference.json", "inference.pdiparams", "inference.yml")}
    else:
        result["executable"] = file_hash(config.tesseract_exe)
        for lang in {"en": ["eng"], "ar": ["ara"], "ar+en": ["ara", "eng"]}[config.language]:
            result[lang] = file_hash(Path(config.tessdata_dir) / f"{lang}.traineddata")
    return result


def extract(source, config, output, *, backend_factory=None):
    output = private_path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    save_new(output / "config.json", config.model_dump())
    try:
        source_hash, pages = preserve_pages(source, output)
        save_new(output / "source.json", {"sha256": source_hash, "page_count": len(pages)})
        if backend_factory is None:
            weights = model_files(config)
            factory = PaddleBackend if config.engine == "paddle" else TesseractBackend
        else:
            weights, factory = {"mocked": True}, backend_factory
        all_spans = []
        setup_start = perf_counter()
        timings = []
        with offline_python():
            backend = factory(config)
            setup_seconds = perf_counter() - setup_start
            for page in pages:
                tick = perf_counter()
                raw = backend.recognize(output / page.image, page.number, page.width, page.height)
                save_new(output / f"raw-page-{page.number}.json", raw)
                # Preserve raw output before parsing, including malformed engine results.
                spans = (parse_paddle(raw, page.number, page.width, page.height) if config.engine == "paddle"
                         else parse_tesseract(raw["tsv"], page.number, page.width, page.height))
                if not spans:
                    page.issues.append("no_text_detected_not_a_blank_answer_decision")
                all_spans.extend(spans)
                timings.append({"page": page.number, "seconds": perf_counter()-tick})
        doc = Extraction(source_sha256=source_hash, engine=config.engine,
                         config_sha256=file_hash(output / "config.json"), pages=pages, spans=all_spans,
                         review_reasons=["answer_regions_and_identity_not_verified",
                                         "text_completeness_and_math_symbols_not_verified",
                                         "cancellations_not_verified",
                                         "engine_confidence_is_not_correctness_probability"])
        save_new(output / "extraction.json", doc.model_dump())
        packages = {}
        for package in ("paddleocr", "paddlepaddle", "paddlex", "Pillow", "pypdf", "pydantic", "numpy"):
            try:
                packages[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                pass
        save_new(output / "run.json", {"version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                                     "status": doc.status, "source_sha256": source_hash, "models": weights,
                                     "packages": packages, "setup_seconds": setup_seconds,
                                     "pages": timings, "total_seconds": perf_counter()-started,
                                     "source_code_sha256": file_hash(__file__),
                                     "network_policy": "explicit_local_models; Python_sockets_blocked; no_cloud_fallback",
                                     "automatic_retries": 0, "grading_requested": False})
        return doc
    except Exception as error:
        # Don't leak OCR contents or exception messages into public diagnostics.
        save_new(output / "failure.json", {"status": "failed", "failure_type": type(error).__name__,
                                          "grading_requested": False, "score": None})
        raise


class ReviewedSegment(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    page: int = Field(ge=1)
    bbox: Box
    source_span_ids: list[str] = Field(max_length=100)
    text: str = Field(min_length=1, max_length=10000)
    crossed_out: bool | None
    checked_against_page: bool


class TranscriptionReview(StrictModel):
    extraction_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    answer_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    question_id: str = Field(min_length=1, max_length=80)
    reviewer: str = Field(min_length=1, max_length=200)
    answer_region_and_completeness_checked: bool
    excludes_identity_question_and_teacher_marks: bool
    segments: list[ReviewedSegment] = Field(min_length=1, max_length=100)


def export_reviewed(extraction_path, review_path, output):
    """Explicit instructor transcription review; never guide or grade approval."""
    extraction_path, review_path = Path(extraction_path), Path(review_path)
    doc = Extraction.model_validate_json(extraction_path.read_text(encoding="utf-8"))
    review = TranscriptionReview.model_validate_json(review_path.read_text(encoding="utf-8"))
    if review.extraction_sha256 != file_hash(extraction_path) or review.source_sha256 != doc.source_sha256:
        raise ValueError("Review is stale or belongs to another extraction.")
    if not review.answer_region_and_completeness_checked or not review.excludes_identity_question_and_teacher_marks:
        raise ValueError("Instructor must check answer completeness and evidence boundaries.")
    pages, spans = {p.number: p for p in doc.pages}, {s.id: s for s in doc.spans}
    for page in doc.pages:
        if file_hash(extraction_path.parent / page.image) != page.image_sha256:
            raise ValueError("Preserved page changed after extraction.")
    originals = list(extraction_path.parent.glob("original.*"))
    if len(originals) != 1 or file_hash(originals[0]) != doc.source_sha256:
        raise ValueError("Preserved original changed after extraction.")
    for s in review.segments:
        page = pages.get(s.page)
        if page is None or not s.bbox.inside(page.width, page.height):
            raise ValueError("Reviewed segment is outside its page.")
        if not s.checked_against_page or s.crossed_out is None:
            raise ValueError("Every segment needs an explicit text/cancellation check.")
        if len(set(s.source_span_ids)) != len(s.source_span_ids):
            raise ValueError("Duplicate source span references.")
        for ref in s.source_span_ids:
            if ref not in spans or spans[ref].page != s.page:
                raise ValueError("Unknown or wrong-page span reference.")
        # Empty references explicitly mean the instructor added text missed by OCR;
        # page/bbox still locate its visual evidence. Raw OCR is never overwritten.
    answer = Answer.model_validate({"answer_id": review.answer_id, "source_sha256": doc.source_sha256,
        "transcription_method": "local_ocr", "transcription_status": "checked_by_instructor_against_page",
        "extraction_provenance": {"extraction_sha256": file_hash(extraction_path),
                                  "review_sha256": file_hash(review_path), "engine": doc.engine,
                                  "question_id": review.question_id},
        "segments": [{"id": s.id, "text": s.text, "crossed_out": s.crossed_out} for s in review.segments]})
    output = private_path(output)
    output.mkdir(parents=True, exist_ok=False)
    save_new(output / "answers.json", [answer.model_dump()])
    save_new(output / "transcription-review.json", review.model_dump())
    return answer


def review_template(extraction_path, output, answer_id, question_id):
    extraction_path = Path(extraction_path)
    doc = Extraction.model_validate_json(extraction_path.read_text(encoding="utf-8"))
    # Deliberately incomplete: an OCR engine cannot check its own transcription.
    template = {"extraction_sha256": file_hash(extraction_path), "source_sha256": doc.source_sha256,
                "answer_id": answer_id, "question_id": question_id, "reviewer": "",
                "answer_region_and_completeness_checked": False,
                "excludes_identity_question_and_teacher_marks": False,
                "segments": [{"id": s.id, "page": s.page, "bbox": s.bbox.model_dump(),
                              "source_span_ids": [s.id], "text": s.text, "crossed_out": None,
                              "checked_against_page": False} for s in doc.spans]}
    output = private_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_new(output, template)
    return template


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("extract")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    review = commands.add_parser("export-reviewed")
    review.add_argument("--extraction", type=Path, required=True)
    review.add_argument("--review", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    template = commands.add_parser("review-template")
    template.add_argument("--extraction", type=Path, required=True)
    template.add_argument("--output", type=Path, required=True)
    template.add_argument("--answer-id", required=True)
    template.add_argument("--question-id", required=True)
    args = parser.parse_args()
    if args.command == "extract":
        config = OcrConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
        doc = extract(args.input, config, args.output)
        print(json.dumps({"status": doc.status, "pages": len(doc.pages), "spans": len(doc.spans),
                          "output": str(args.output.resolve()), "grading_requested": False}))
    elif args.command == "export-reviewed":
        export_reviewed(args.extraction, args.review, args.output)
        print(json.dumps({"status": "transcription_checked_grade_pending", "output": str(args.output.resolve())}))
    else:
        review_template(args.extraction, args.output, args.answer_id, args.question_id)
        print(json.dumps({"status": "unchecked_review_template", "output": str(args.output.resolve())}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "failure_type": type(error).__name__,
                          "note": "Inspect private run artifacts; no grade was inferred."}))
        raise SystemExit(1)
