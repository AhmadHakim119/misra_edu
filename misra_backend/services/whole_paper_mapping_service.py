"""Conservative, document-wide OCR assignment before answer rows are written.

This stage uses only approved question text and the OCR already produced for the
paper. It never treats student text as an instruction. Ambiguity remains visible
instead of being silently attached to the nearest question.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


_COMMON = {
    "about", "answer", "apply", "based", "code", "complete", "data",
    "describe", "develop", "each", "explain", "following", "from", "given",
    "have", "into", "model", "more", "question", "result", "show", "student",
    "system", "task", "that", "their", "them", "these", "this", "using",
    "what", "when", "where", "which", "with", "write", "your",
    "اكتب", "اشرح", "اذكر", "السؤال", "الطالب", "المطلوب", "باستخدام", "على", "هذه", "هذا", "التي", "الذي",
}


def _words(value: str) -> set[str]:
    value = unicodedata.normalize("NFC",value).casefold().replace("_"," ")
    value = re.sub(r"[\u064b-\u065f\u0670\u0640]","",value)
    return {
        word for word in re.findall(r"\w+",value,re.UNICODE)
        if len(word) >= 3 and any(char.isalpha() for char in word) and word not in _COMMON
    }


@dataclass(frozen=True)
class MappingDecision:
    question_number: str | None
    question_id: str | None
    method: str
    candidates: tuple[str, ...] = ()
    reason: str | None = None
    original_label: str | None = None


def reconcile_paper(pages, questions, normalize_label, resolve_label, is_cover_mark):
    """Return decisions indexed by (zero-based page, zero-based segment).

    A label is evidence, not ground truth. Unique terminology can correct a
    contradictory OCR label; otherwise a contradiction is left for visual
    adjudication. Unlabelled continuation inherits only a unanimous page (or
    matching pages on both sides), never simply the closest page.
    """
    lookup = {q.question_number: q.id for q in questions}
    terms = {q.question_number: _words(q.question_text or "") for q in questions}
    unique_terms = {
        number: own - set().union(*(other for key, other in terms.items() if key != number))
        for number, own in terms.items()
    }
    decisions: dict[tuple[int, int], MappingDecision] = {}
    previous_base = None

    for page_index, page in enumerate(pages):
        for segment_index, segment in enumerate(page.segments):
            key = (page_index, segment_index)
            original = segment.question_number
            if segment.content_role != "answer" or is_cover_mark(
                segment, page, len(pages), page_index
            ):
                decisions[key] = MappingDecision(None, None, "excluded", original_label=original)
                continue
            label, previous_base = normalize_label(original, previous_base)
            mapped, question_id = resolve_label(label, lookup)
            printed_raw = getattr(segment,"printed_question_number",None)
            printed_label,_ = normalize_label(printed_raw,None)
            printed_number,printed_id = resolve_label(printed_label,lookup)
            # Two question-specific terms are required before text can challenge
            # a label. This deliberately avoids a generic word like "data".
            text_terms = _words(segment.text)
            hits = {
                number: len(text_terms & distinguishing)
                for number, distinguishing in unique_terms.items()
            }
            ranked = sorted(hits, key=lambda number: hits[number], reverse=True)
            best = ranked[0] if ranked else None
            runner_up = hits[ranked[1]] if len(ranked) > 1 else 0
            strong = bool(best and hits[best] >= 2 and hits[best] >= runner_up + 2)
            if printed_id and strong and best != printed_number:
                decisions[key] = MappingDecision(None,None,"anchor_conflict",
                    candidates=tuple(dict.fromkeys([printed_number,best])),
                    reason="Printed question anchor and distinctive answer terminology disagree; visual confirmation is needed.",
                    original_label=original)
            elif printed_id:
                decisions[key] = MappingDecision(printed_number,printed_id,"printed_anchor",original_label=original)
            elif strong and best != mapped:
                decisions[key] = MappingDecision(
                    best, lookup[best], "semantic_correction",
                    candidates=tuple(dict.fromkeys([best, mapped] if mapped else [best])),
                    reason="OCR label conflicts with question-specific answer terms.",
                    original_label=original,
                )
            elif question_id:
                decisions[key] = MappingDecision(
                    mapped, question_id, "label", original_label=original
                )
            elif strong:
                decisions[key] = MappingDecision(
                    best, lookup[best], "semantic_match", original_label=original
                )
            else:
                decisions[key] = MappingDecision(
                    None, None, "unresolved", original_label=original,
                    reason="No reliable question label or unique content match.",
                )

    page_votes: list[set[str]] = []
    for page_index, page in enumerate(pages):
        page_votes.append({
            decisions[(page_index, index)].question_number
            for index in range(len(page.segments))
            if decisions[(page_index, index)].question_number
        })
    for page_index, page in enumerate(pages):
        for segment_index, segment in enumerate(page.segments):
            key = (page_index, segment_index)
            if decisions[key].method != "unresolved" or not segment.text.strip():
                continue
            number = None
            if len(page_votes[page_index]) == 1:
                number = next(iter(page_votes[page_index]))
            elif not page_votes[page_index] and 0 < page_index < len(pages) - 1:
                before, after = page_votes[page_index - 1], page_votes[page_index + 1]
                if len(before) == len(after) == 1 and before == after:
                    number = next(iter(before))
            if number:
                decisions[key] = MappingDecision(
                    number, lookup[number], "page_continuation",
                    original_label=decisions[key].original_label,
                )
            else:
                candidates = tuple(sorted(page_votes[page_index]))
                decisions[key] = MappingDecision(
                    None, None, "unresolved", candidates=candidates,
                    reason="Multiple or no question anchors on this page.",
                    original_label=decisions[key].original_label,
                )
    return decisions
