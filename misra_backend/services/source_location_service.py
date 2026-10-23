"""Read-only display locations; never changes OCR, grades or saved run evidence.

Poppler's word rectangles use the full media box, like the existing page renderer.
Only a unique, complete normalized token match qualifies as native text location.
Scans, altered text and ambiguous repeats retain explicitly approximate OCR boxes.
"""
from __future__ import annotations

import math
from copy import deepcopy
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


def refine_scan_location(image, location: dict) -> dict:
    """Bounded display refinement of a coarse grid rectangle, without reading text.

    Expand intersecting ink bands, excluding near-continuous ruled lines. A seed
    on blank space is rejected, never moved to a different nearby answer. This
    checks geometry only: ink presence does not verify the answer's identity.
    Original provider coordinates remain in the saved run and are returned here
    as reported_bounding_box. No extraction, grade or confirmation is changed.
    """
    from schemas.ocr_evidence import NormalizedBoundingBox
    from pydantic import ValidationError
    from PIL import Image

    if location.get('method') != 'vision_grid' or location.get('status') != 'located':
        return deepcopy(location)
    result = deepcopy(location)
    reported = result.pop('bounding_box', None)
    result['reported_bounding_box'] = reported
    def unavailable(reason):
        return {**result, 'status': 'unverified', 'reason': reason,
                'geometry_check': 'ink_support_unavailable'}
    try:
        box = NormalizedBoundingBox.model_validate(reported).model_dump()
    except (ValidationError, TypeError):
        return unavailable('invalid_reported_rectangle')
    page = image.convert('L')
    page.thumbnail((1800, 1800))
    width, height = page.size
    # Search at most two 40-grid cells beyond the seed. Never select a band
    # that does not intersect the original proposed vertical extent.
    margin = 2 / 40
    left = max(0, math.floor((box['x'] - margin) * width))
    top = max(0, math.floor((box['y'] - margin) * height))
    right = min(width, math.ceil((box['x'] + box['width'] + margin) * width))
    bottom = min(height, math.ceil((box['y'] + box['height'] + margin) * height))
    if right - left < 3 or bottom - top < 3:
        return unavailable('reported_rectangle_too_small')
    mask = page.crop((left, top, right, bottom)).point(lambda value: 255 if value < 140 else 0)
    span, depth = mask.size
    rows, active = [], []
    rule = re.compile(b'\xff{%d,}' % max(30, round(span * .08)))
    for y in range(depth):
        line = mask.crop((0, y, span, y + 1))
        pixels = bytearray(line.tobytes())
        joined = re.sub(b'(?<=\xff)\x00{1,3}(?=\xff)', lambda match: b'\xff' * len(match[0]), bytes(pixels))
        for match in rule.finditer(joined):
            pixels[match.start():match.end()] = b'\x00' * (match.end() - match.start())
        count = pixels.count(255)
        line = Image.frombytes('L', (span, 1), bytes(pixels))
        # Page rules are not answer ink. Leave their pixels out of the bounds.
        useful = max(2, math.ceil(span * .003)) <= count < span * .7
        rows.append(line if useful else None)
        if useful:
            active.append(y)
    if not active:
        return unavailable('no_ink_support_at_reported_location')
    bands = []
    gap = max(2, round(height * .002))
    for y in active:
        if not bands or y - bands[-1][-1] > gap:
            bands.append([y])
        else:
            bands[-1].append(y)
    seed_top, seed_bottom = box['y'] * height - top, (box['y'] + box['height']) * height - top
    selected = [band for band in bands if band[-1] >= seed_top and band[0] < seed_bottom]
    if not selected:
        return unavailable('no_ink_support_at_reported_location')
    ink_rows = [y for band in selected for y in band]
    # Search-edge contact means the complete ink band is not established.
    if min(ink_rows) <= 1 or max(ink_rows) >= depth - 2:
        return unavailable('ink_extends_beyond_location_search')
    seed_left = max(0, math.floor(box['x'] * width) - left)
    seed_right = min(span, math.ceil((box['x'] + box['width']) * width) - left)
    if not any(rows[y].crop((seed_left, 0, seed_right, 1)).getbbox() for y in ink_rows):
        return unavailable('no_ink_support_at_reported_location')
    pad = max(2, round(min(width, height) * .003))
    # Keep the proposed horizontal scope. Ruled lines can extend beyond the
    # writing and must not stretch a box across neighbouring answer columns.
    x0, x1 = box['x'] * width, min(width, (box['x'] + box['width']) * width)
    y0 = max(0, min(box['y'] * height, top + min(ink_rows)) - pad)
    y1 = min(height, max((box['y'] + box['height']) * height, top + max(ink_rows) + 1) + pad)
    result.update(bounding_box={'x': x0 / width, 'y': y0 / height,
                               'width': (x1 - x0) / width, 'height': (y1 - y0) / height},
                  geometry_check='vertical_ink_extent_checked',
                  geometry_note='Vertical display extent checked against nearby ink; horizontal placement and answer identity remain unverified.')
    return result
