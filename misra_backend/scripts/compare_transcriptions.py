"""Offline, local-only OCR metrics; no document text is emitted in the report."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.text_quality_metrics import text_metrics


def compare(path, *, normalize_whitespace=False):
    data = path.read_bytes()
    pairs = json.loads(data)
    if not isinstance(pairs,list) or not 1 <= len(pairs) <= 500:
        raise ValueError("Supply 1–500 aligned transcription pairs.")
    results = []
    for index,pair in enumerate(pairs):
        if not isinstance(pair,dict) or not isinstance(pair.get("reference"),str) or not isinstance(pair.get("candidate"),str):
            raise ValueError(f"Pair {index + 1} needs reference and candidate text.")
        results.append({"pair_number":index + 1,**text_metrics(pair["reference"],pair["candidate"],normalize_whitespace=normalize_whitespace)})
    return {"input_sha256":hashlib.sha256(data).hexdigest(),"pair_count":len(results),"pairs":results,
        "note":"Aligned manual transcriptions are required. This report is not grading accuracy or a held-out pipeline comparison."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairs",type=Path,help="Private JSON array of {reference, candidate} objects")
    parser.add_argument("--normalize-whitespace",action="store_true")
    arguments = parser.parse_args()
    try:
        print(json.dumps(compare(arguments.pairs,normalize_whitespace=arguments.normalize_whitespace),ensure_ascii=False,indent=2))
    except (ValueError,OSError) as error:
        parser.exit(2,f"Comparison could not finish ({type(error).__name__}). Check input shape and segment size.\n")
