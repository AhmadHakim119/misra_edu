"""Read-only display locations; never changes OCR, grades or saved run evidence.

Poppler's word rectangles use the full media box, like the existing page renderer.
Only a unique, complete normalized token match qualifies as native text location.
Scans, altered text and ambiguous repeats retain explicitly approximate OCR boxes.
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Protocol, TypeAlias
from xml.etree import ElementTree

MAX_XML_BYTES = 8 * 1024 * 1024
MAX_TOKENS = 50000
WordBox: TypeAlias = tuple[float, float, float, float]
PageWords: TypeAlias = tuple[float, float, list[tuple[str, WordBox]]]


class TextSource(Protocol):
    id: str
    extracted_text: str


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    for old, new in (("\\times", "*"), ("\\cdot", "*"), ("×", "*"),
                     ("·", "*"), ("−", "-"), ("÷", "/")):
        text = text.replace(old, new)
    # Preserve numbers, decimal places and mathematical signs. No fuzzy matching,
    # number correction, sign removal or algebraic rewriting for localization.
    return re.findall(r"\d+(?:[.,]\d+)*|[^\W\d_]+|[=+*/^<>%_()\[\]{}-]", text)


def parse_page_words(xml: bytes) -> PageWords | None:
    if len(xml) > MAX_XML_BYTES or b"<!ENTITY" in xml.upper():
        return None
    try:
        root = ElementTree.fromstring(xml)
        pages = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "page"]
        if len(pages) != 1:
            return None
        page = pages[0]
        width, height = float(page.attrib["width"]), float(page.attrib["height"])
        if not all(math.isfinite(v) and v > 0 for v in (width, height)):
            return None
        tokens = []
        for word in page.iter():
            if word.tag.rsplit("}", 1)[-1] != "word":
                continue
            box = tuple(float(word.attrib[name]) for name in ("xMin", "yMin", "xMax", "yMax"))
            left, top, right, bottom = box
            if not all(math.isfinite(v) for v in box) or not (0 <= left < right <= width and 0 <= top < bottom <= height):
                return None
            tokens.extend((token, box) for token in _tokens("".join(word.itertext())))
            if len(tokens) > MAX_TOKENS:
                return None
        return width, height, tokens
    except (ElementTree.ParseError, KeyError, ValueError, OverflowError):
        return None


def read_page_words(path: Path, page_index: int) -> PageWords | None:
    executable = shutil.which("pdftotext")
    if not executable or path.suffix.lower() != ".pdf" or not path.is_file():
        return None
    try:
        # Bounded read/output and timeout; no shell, network or temporary paper copy.
        with tempfile.TemporaryFile() as output:
            subprocess.run(
                [executable, "-q", "-f", str(page_index + 1), "-l", str(page_index + 1),
                 "-bbox-layout", "-enc", "UTF-8", str(path.resolve()), "-"],
                stdout=output, stderr=subprocess.DEVNULL, timeout=5, check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if output.tell() > MAX_XML_BYTES:
                return None
            output.seek(0)
            return parse_page_words(output.read(MAX_XML_BYTES + 1))
    except (OSError, subprocess.SubprocessError):
        return None


def locate_text(text: str, page_words: PageWords | None) -> dict[str, Any]:
    if not page_words:
        return {"status": "unverified", "method": "ocr_estimate", "reason": "native_text_unavailable"}
    width, height, words = page_words
    target = _tokens(text)
    # A single token (often an MCQ choice/number) is not distinctive enough.
    if len(target) < 2 or len(target) > 3000:
        return {"status": "unverified", "method": "ocr_estimate", "reason": "insufficient_text"}
    values = [word[0] for word in words]
    matches = []
    for index, value in enumerate(values):
        if value == target[0] and values[index:index + len(target)] == target:
            matches.append(index)
            if len(matches) > 1:
                break
    if len(matches) != 1:
        return {"status": "unverified", "method": "ocr_estimate",
                "reason": "ambiguous_text" if matches else "text_not_found"}
    boxes = [word[1] for word in words[matches[0]:matches[0] + len(target)]]
    left = max(0, min(box[0] for box in boxes) - 1)
    top = max(0, min(box[1] for box in boxes) - 1)
    right = min(width, max(box[2] for box in boxes) + 1)
    bottom = min(height, max(box[3] for box in boxes) + 1)
    return {"status": "located", "method": "native_pdf_text", "bounding_box": {
        "x": left / width, "y": top / height, "width": (right - left) / width,
        "height": (bottom - top) / height,
    }}


def page_source_locations(path: Path, page_index: int, sources: Iterable[TextSource]) -> dict[str, Any]:
    words = read_page_words(path, page_index)
    return {"page_index": page_index, "display_only": True,
            "sources": {source.id: locate_text(source.extracted_text or "", words) for source in sources}}
