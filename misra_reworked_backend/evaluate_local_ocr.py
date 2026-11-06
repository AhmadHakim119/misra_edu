"""Offline transcription evaluation. References are never sent to OCR engines."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import unicodedata

from pydantic import Field, model_validator

from local_ocr import Extraction, file_hash, private_path
from rubric_pilot import StrictModel, save_new


class OcrReference(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: str = Field(min_length=1, max_length=80)
    reference_text: str = Field(min_length=1, max_length=10000)
    page: int = Field(ge=1)
    # Explicit, manually located answer region; not an automatic extraction result.
    region: list[float] = Field(min_length=4, max_length=4)
    literal_probes: list[str] = Field(max_length=30)

    @model_validator(mode="after")
    def valid_region(self):
        a, b, c, d = self.region
        if not 0 <= a < c <= 1 or not 0 <= b < d <= 1:
            raise ValueError("Expected a nonempty normalized page region.")
        if any(not p.strip() for p in self.literal_probes):
            raise ValueError("Empty probe.")
        return self


def normalize(text):
    # Keep Arabic negation, diacritics, digits, operators, case and punctuation.
    return " ".join(unicodedata.normalize("NFC", text).split())


def edit_distance(reference, candidate):
    previous = list(range(len(candidate) + 1))
    for i, a in enumerate(reference, 1):
        current = [i]
        for j, b in enumerate(candidate, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(a != b)))
        previous = current
    return previous[-1]


def transcription_metrics(reference, candidate):
    ref, hyp = normalize(reference), normalize(candidate)
    if not ref:
        raise ValueError("An empty OCR reference has undefined error rates.")
    char_errors = edit_distance(ref, hyp)
    word_errors = edit_distance(ref.split(), hyp.split())
    return {"character_errors": char_errors, "reference_characters": len(ref),
            "cer": char_errors / len(ref), "word_errors": word_errors,
            "reference_words": len(ref.split()), "wer": word_errors / len(ref.split()),
            "exact_match": ref == hyp}


def evaluate(doc, reference):
    if doc.source_sha256 != reference.source_sha256:
        raise ValueError("OCR reference belongs to a different original file.")
    page = next((p for p in doc.pages if p.number == reference.page), None)
    if page is None:
        raise ValueError("Reference page missing from OCR result.")
    a, b, c, d = reference.region
    selected = [s for s in doc.spans if s.page == page.number
                and a <= (s.bbox.x0+s.bbox.x1)/(2*page.width) <= c
                and b <= (s.bbox.y0+s.bbox.y1)/(2*page.height) <= d]
    text = "\n".join(s.text for s in selected)
    compact = "".join(unicodedata.normalize("NFC", text).split())
    probes = {p: "".join(unicodedata.normalize("NFC", p).split()) in compact
              for p in reference.literal_probes}
    return {"case": reference.id, "kind": reference.kind, "metrics": transcription_metrics(reference.reference_text, text),
            "selected_span_ids": [s.id for s in selected], "extracted_text": text,
            "literal_probe_presence": probes, "all_literal_probes_present": all(probes.values()) if probes else None,
            "needs_transcription_review": True,
            "cancellation_detection": "not_implemented_unknown",
            "region_method": "manual_reference_region_span_center_selection",
            "reading_order": "engine_native_span_order",
            "note": "Literal presence and low CER/WER do not establish grading correctness."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True, help="<config>/<case>/extraction.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    references = [OcrReference.model_validate(r) for r in json.loads(args.references.read_text(encoding="utf-8-sig"))]
    if len({r.id for r in references}) != len(references):
        raise ValueError("Duplicate reference IDs.")
    results = []
    for config in sorted(p for p in args.runs.iterdir() if p.is_dir()):
        for reference in references:
            path = config / reference.id / "extraction.json"
            if not path.is_file():
                results.append({"config": config.name, "case": reference.id, "status": "missing_or_failed", "metrics": None})
                continue
            doc = Extraction.model_validate_json(path.read_text(encoding="utf-8"))
            result = evaluate(doc, reference)
            result.update(config=config.name, status="evaluated", extraction_sha256=file_hash(path))
            run = json.loads((path.parent / "run.json").read_text(encoding="utf-8"))
            result["timing"] = {k: run[k] for k in ("setup_seconds", "pages", "total_seconds")}
            results.append(result)
    output = private_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_new(output, {"references_sha256": file_hash(args.references), "results": results,
                      "normalization": "NFC_and_whitespace_only",
                      "limitations": ["Small diagnostic sample; no model training or threshold calibration.",
                                      "Printed Arabic controls do not validate Arabic handwriting.",
                                      "Manually specified answer regions; no automated question mapping measured.",
                                      "No grade accuracy, review-routing recall or human time savings measured."]})
    print(json.dumps({"output": str(output), "evaluated": sum(r["status"] == "evaluated" for r in results),
                      "missing_or_failed": sum(r["status"] != "evaluated" for r in results)}))


if __name__ == "__main__":
    main()
