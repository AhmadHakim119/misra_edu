"""Validate an OFFLINE instructor review and write a new extraction revision.

Run only with locally reviewed decisions from the instructor. Provider responses
are evidence, never decisions. This command does not authenticate an instructor,
call a model, regrade an answer or update the application/database. The existing
authenticated answer-area workflow is the app's correction path.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.ocr_verification import grading_gate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comparisons', required=True, type=Path)
    parser.add_argument('--decisions', type=Path, help='Trusted local instructor decisions JSON; omit to inspect pending review')
    parser.add_argument('--output', required=True, type=Path, help='New private output path; existing files are never overwritten')
    args = parser.parse_args()
    comparisons = json.loads(args.comparisons.read_text(encoding='utf-8-sig'))
    decisions = json.loads(args.decisions.read_text(encoding='utf-8-sig')) if args.decisions else []
    if isinstance(decisions, dict):
        decisions = decisions['decisions']
    result = grading_gate(comparisons, decisions)
    result['comparison_file_sha256'] = hashlib.sha256(args.comparisons.read_bytes()).hexdigest()
    result['instructor_decision_file_sha256'] = hashlib.sha256(args.decisions.read_bytes()).hexdigest() if args.decisions else None
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
    print(result['status'] + ': ' + str(len(result['pending_region_ids'])) + ' pending regions')


if __name__ == '__main__':
    main()
