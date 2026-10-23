"""Locate literal word/symbol differences for review, without selecting a reading.

This offline helper compares two untrusted transcriptions. It neither decides
which is correct nor clears the independent-reader/instructor grading gate.
Token agreement is not transcription accuracy; shared mistakes remain possible.
"""
from difflib import SequenceMatcher
from hashlib import sha256
import re

VERSION = '2026-10-20.literal-diff.v1'
MAX_CHARACTERS = 50_000
MAX_TOKENS = 2_000
TOKEN = re.compile(r"\w+(?:['’]\w+)*|[^\w\s]", re.UNICODE)


def _kinds(value):
    kinds = set()
    if any(character.isdecimal() for character in value):
        kinds.add('number')
    if any(character.isalpha() for character in value):
        kinds.add('word')
    if not kinds:
        kinds.add('symbol')
    return kinds


def _span(text, tokens, start, end):
    if start == end:
        position = tokens[start].start() if start < len(tokens) else len(text)
        return {'start': position, 'end': position, 'text': ''}
    left, right = tokens[start].start(), tokens[end - 1].end()
    return {'start': left, 'end': right, 'text': text[left:right]}


def compare_literal_text(left, right):
    """Return exact character locations of changed word/number/symbol tokens.

    Only whitespace between existing tokens is ignored. Word boundaries, case,
    spelling, negation, punctuation, digits and operators remain distinct. No
    stemming, semantic matching, dictionary correction or key is used. A bounded
    split-required result avoids truncating or aligning very large regions.
    Character offsets refer to the untouched Python strings (Unicode code points).
    """
    if not isinstance(left, str) or not isinstance(right, str):
        raise ValueError('Compare two literal transcription strings.')
    if max(len(left), len(right)) > MAX_CHARACTERS:
        raise ValueError('Transcription exceeds the literal-difference character bound.')
    result = {
        'version': VERSION,
        'left_sha256': sha256(left.encode('utf8')).hexdigest(),
        'right_sha256': sha256(right.encode('utf8')).hexdigest(),
        'status': 'same_tokens', 'operations': [],
        'correct_reading_selected': False,
        'can_clear_grading_gate': False,
    }
    a, b = list(TOKEN.finditer(left)), list(TOKEN.finditer(right))
    if max(len(a), len(b)) > MAX_TOKENS:
        return {**result, 'status': 'split_required',
                'reason': 'Use smaller located regions; no text was truncated or silently accepted.'}
    matcher = SequenceMatcher(None, [t.group() for t in a], [t.group() for t in b], autojunk=False)
    for tag, i, j, k, end in matcher.get_opcodes():
        if tag == 'equal':
            continue
        changed = [token.group() for token in a[i:j]] + [token.group() for token in b[k:end]]
        result['operations'].append({
            'operation': tag,
            'left': _span(left, a, i, j), 'right': _span(right, b, k, end),
            'token_kinds': sorted(set().union(*(_kinds(value) for value in changed))),
        })
    if result['operations']:
        result['status'] = 'different_tokens'
    return result
