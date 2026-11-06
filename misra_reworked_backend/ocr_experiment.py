"""Private, immutable OCR comparison artifacts; no grading or database writes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from PIL import Image

from local_ocr import (OcrConfig, PaddleBackend, TesseractBackend, file_hash, model_files,
                       offline_python, parse_paddle, parse_tesseract, private_path)
from rubric_pilot import save_new


def redact_page(image, position):
    """Template-specific reviewed crop: omit headers/identity/footer, whiten red marks.

    This is not general PII detection. New layouts require a new visual review.
    Original full pages remain preserved separately. Pixel removal cannot recover
    writing obscured by teacher ink and can remove red student writing.
    """
    import numpy as np
    top, bottom = {1: (0.275, 0.895), 2: (0.13, 0.895), 3: (0.13, 0.895)}[position]
    width, height = image.size
    box = (round(width*.095), round(height*top), width, round(height*bottom))
    array = np.array(image.convert("RGB").crop(box))
    r, g, b = [array[:, :, i].astype("int16") for i in range(3)]
    red = (r-g > 35) & (r-b > 25) & (r > 100)
    # One-pixel dilation covers colored antialiasing; do not erase entire text lines.
    import cv2
    mask = cv2.dilate(red.astype("uint8"), np.ones((3,3), dtype="uint8")) > 0
    array[mask] = 255
    return Image.fromarray(array), {"crop_xyxy": list(box), "original_size": [width,height],
                                   "red_pixels_whitened": int(mask.sum()),
                                   "limitations": ["red_student_ink_would_also_be_removed",
                                                   "overwritten_or_obscured_ink_is_not_recoverable"]}


def enhanced(image):
    import cv2
    import numpy as np
    gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    output = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8,8)).apply(gray)
    return Image.fromarray(output).convert("RGB")


def prepare(root):
    root = private_path(root)
    manifest = json.loads((root / "dataset-manifest.json").read_text(encoding="utf-8"))
    directory = root / "redacted-v2"
    directory.mkdir(exist_ok=False)
    entries = []
    for group in manifest["groups"]:
        for position, number in enumerate(group["pdf_pages"],1):
            source = root / "pages" / f"page-{number:02}.png"
            with Image.open(source) as image:
                result, metadata = redact_page(image, position)
            path = directory / f"page-{number:02}.png"
            result.save(path)  # Fresh PNG strips source metadata; original is untouched.
            entries.append({"page": number, "position": position, "paper_id": group["paper_id"],
                            "split": group["split"], "path": str(path.resolve()), "sha256": file_hash(path),
                            "source_image_sha256": file_hash(source), "redaction": metadata,
                            "privacy_review": "pending_visual_check"})
    save_new(root / "redaction-manifest-v2.json", {"source_sha256": manifest["source_sha256"],
                                               "entries": entries, "version": "reviewed-template-v1"})


def validate_packet(root, entry):
    path = Path(entry["path"]).resolve()
    if not path.is_relative_to((root / "redacted-v2").resolve()) or path.suffix != ".png":
        raise ValueError("Only approved redacted PNGs are eligible for this benchmark.")
    if entry["privacy_review"] != "checked_by_agent_against_full_page":
        raise ValueError("Redacted image needs a visual privacy check.")
    if file_hash(path) != entry["sha256"]:
        raise ValueError("Redacted image changed after privacy check.")
    return path


def run_local(root, config_path, *, splits, variant="original"):
    root = private_path(root)
    config = OcrConfig.model_validate_json(Path(config_path).read_text(encoding="utf-8"))
    name = f"{config.engine}-{variant}"
    output = root / "local-runs" / name
    output.mkdir(parents=True, exist_ok=False)
    packet = json.loads((root / "redaction-manifest-reviewed.json").read_text(encoding="utf-8"))
    entries = [e for e in packet["entries"] if e["split"] in splits]
    limit = 3200 if variant == "upscaled" else 1600
    save_new(output / "protocol.json", {"config": config.model_dump(), "models": model_files(config),
                                      "variant": variant, "splits": splits,
                                      "source_code_sha256": file_hash(__file__), "grading_requested": False,
                                      "transcription_status": "unchecked_ocr_draft",
                                      "detector_settings": {"text_det_limit_type":"max", "text_det_limit_side_len":limit}})
    started = perf_counter()
    factory = PaddleBackend if config.engine == "paddle" else TesseractBackend
    records = []
    with offline_python():
        engine = factory(config)
        setup_seconds = perf_counter()-started
        for entry in entries:
            case = output / f"page-{entry['page']:02}"
            case.mkdir()
            tick = perf_counter()
            try:
                source = validate_packet(root, entry)
                with Image.open(source) as image:
                    image = image.convert("RGB")
                    if variant == "enhanced":
                        image = enhanced(image)
                    elif variant == "upscaled":
                        image = image.resize((image.width*2,image.height*2), Image.Resampling.LANCZOS)
                    image.save(case / "input.png")
                    width,height = image.size
                if config.engine == "paddle":
                    result = list(engine.ocr.predict(str(case / "input.png"), text_rec_score_thresh=0.0,
                                                     text_det_limit_type="max", text_det_limit_side_len=limit))
                    if len(result) != 1:
                        raise ValueError("Expected a single page result.")
                    raw = result[0].json
                    if isinstance(raw,str): raw=json.loads(raw)
                else:
                    raw = engine.recognize(case / "input.png", entry["page"], width,height)
                save_new(case / "raw.json", raw)
                spans = (parse_paddle(raw,entry["page"],width,height) if config.engine == "paddle"
                         else parse_tesseract(raw["tsv"],entry["page"],width,height))
                save_new(case / "spans.json", [s.model_dump() for s in spans])
                record = {"page":entry["page"], "split":entry["split"], "status":"extracted",
                          "input_sha256":file_hash(case/"input.png"), "span_count":len(spans),
                          "seconds":perf_counter()-tick, "width":width, "height":height,
                          "source":entry, "cancellations":"unknown", "grading_requested":False}
            except Exception as error:
                record = {"page":entry["page"], "split":entry["split"], "status":"failed",
                          "failure_type":type(error).__name__, "seconds":perf_counter()-tick,
                          "grading_requested":False}
            save_new(case / "result.json", record)
            records.append(record)
            print(json.dumps({k:record[k] for k in ("page","split","status","seconds")}),flush=True)
    save_new(output / "summary.json", {"setup_seconds":setup_seconds,"results":records,
                                      "failed":sum(r["status"]=="failed" for r in records)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["prepare","local"])
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--config",type=Path)
    parser.add_argument("--splits",default="train,development,reference")
    parser.add_argument("--variant",choices=["original","enhanced","upscaled"],default="original")
    args=parser.parse_args()
    if args.action=="prepare": prepare(args.root)
    else: run_local(args.root,args.config,splits=args.splits.split(","),variant=args.variant)


if __name__=="__main__":
    main()
