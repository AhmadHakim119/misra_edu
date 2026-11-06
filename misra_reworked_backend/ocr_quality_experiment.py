"""Source-preserving development OCR diagnostics against provisional visual references."""
import argparse
import json
from pathlib import Path
from statistics import median

from comparison_methods import tokens
from evaluate_local_ocr import edit_distance,normalize
from local_ocr import private_path
from paragraph_experiment import local_answers,paragraph_config_path
from rubric_pilot import save_new


def errors(reference,candidate,*,content=False):
    ref=" ".join(tokens(reference)) if content else normalize(reference)
    hyp=" ".join(tokens(candidate)) if content else normalize(candidate)
    chars=edit_distance(ref,hyp);words=edit_distance(ref.split(),hyp.split())
    return {"character_errors":chars,"reference_characters":len(ref),
            "word_errors":words,"reference_words":len(ref.split()),
            "cer":chars/len(ref) if ref else None,"wer":words/len(ref.split()) if ref.split() else None}


def report(root, *, output=None, mcq_references=None):
    root=private_path(root)
    config=json.loads(paragraph_config_path(root).read_text(encoding="utf-8"))
    refs=json.loads((root/"development-annotations-draft.json").read_text(encoding="utf-8"))
    refs+=json.loads((root/"model-transcriptions-draft.json").read_text(encoding="utf-8"))
    rows=[]
    for source in (root/"local-runs").iterdir():
        if not (source/"summary.json").is_file():raise ValueError("Local run still in progress.")
        for ref in refs:
            case=source/f"page-{ref['pdf_page']:02}"
            if not case.exists():continue
            meta=json.loads((case/"result.json").read_text())
            text=None
            if meta["status"]=="extracted":
                spans=json.loads((case/"spans.json").read_text(encoding="utf-8"))
                answers=local_answers(spans,1 if ref["question_id"].startswith("q1") else 3,meta["width"],meta["height"],config)
                text=next(a["text"] for a in answers if a["question_id"]==ref["question_id"])
            rows.append({"source":source.name,"paper_id":ref["paper_id"],"question_id":ref["question_id"],
                         "reference_kind":ref["split"],"text":text,"mapping_resolved":text is not None,
                         "strict":errors(ref["text"],text or ""),"content":errors(ref["text"],text or ""),
                         "note":"Unresolved mapping is counted as missing text in end-to-end error totals; never a zero grade."})
            rows[-1]["content"]=errors(ref["text"],text or "",content=True)
    for source in (root/"cloud-runs/first").iterdir():
        if not source.is_dir():continue
        for ref in refs:
            path=source/f"page-{ref['pdf_page']:02}"/"transcription.json"
            text=None
            if path.exists():text=next(a["text"] for a in json.loads(path.read_text(encoding="utf-8"))["answers"] if a["question_id"]==ref["question_id"])
            rows.append({"source":source.name,"paper_id":ref["paper_id"],"question_id":ref["question_id"],
                         "reference_kind":ref["split"],"text":text,"mapping_resolved":text is not None,
                         "strict":errors(ref["text"],text or ""),"content":errors(ref["text"],text or "",content=True)})
    summaries=[]
    for source in sorted({r["source"] for r in rows}):
        for kind in ["development","reference"]:
            group=[r for r in rows if r["source"]==source and r["reference_kind"]==kind]
            if not group:continue
            summary={"source":source,"reference_kind":kind,"questions":len(group),"resolved":sum(r["mapping_resolved"] for r in group)}
            for norm in ["strict","content"]:
                chars=sum(r[norm]["character_errors"] for r in group);n=sum(r[norm]["reference_characters"] for r in group)
                words=sum(r[norm]["word_errors"] for r in group);w=sum(r[norm]["reference_words"] for r in group)
                summary[norm+"_cer"]=chars/n if n else None;summary[norm+"_wer"]=words/w if w else None
            summaries.append(summary)
    timings=[]
    for source in (root/"local-runs").iterdir():
        values=json.loads((source/"summary.json").read_text())["results"]
        timings.append({"source":source.name,"pages":len(values),"median_page_seconds":median(r["seconds"] for r in values),
                        "cost_usd":0,"cost_scope":"no API charge; hardware/electricity/human effort not measured"})
    cloud=json.loads((root/"cloud-runs/first/summary.json").read_text())
    for source in sorted({r["model"] for r in cloud["records"]}):
        values=[r for r in cloud["records"] if r["model"]==source]
        timings.append({"source":source,"pages":len(values),"median_page_seconds":median(r["seconds"] for r in values),
                        "reported_cost_usd":sum(r.get("reported_cost_usd") or 0 for r in values),
                        "failed":sum(r["status"]!="extracted" for r in values)})
    mcq=[]
    path=Path(mcq_references) if mcq_references else root/"mcq-visual-references-draft.json"
    if path.exists():
        for ref in json.loads(path.read_text()):
            for source in (root/"cloud-runs/first").iterdir():
                if not source.is_dir():continue
                result=source/f"page-{ref['pdf_page']:02}/transcription.json"
                extracted=json.loads(result.read_text())["answers"] if result.exists() else []
                lookup={a["question_id"]:a for a in extracted}
                for q,expected in ref["selected_options"].items():
                    got=lookup.get(q,{}).get("selected_options")
                    mcq.append({"source":source.name,"paper_id":ref["paper_id"],"question_id":q,
                                "expected_student_choice":expected,"observed":got,"match":got==expected,
                                "note":"Choice transcription agreement, not grading accuracy."})
    output_data={"rows":rows,"summaries":summaries,"timings":timings,"mcq":mcq,
            "reference_status":"assistant visual draft; instructor confirmation pending",
            "timing_scope":"shared machine; concurrent experiment workloads; not controlled latency benchmarks",
            "test_papers_used":False,"grading_accuracy":None,"cancellation_accuracy":None,
            "content_normalization":"Unicode tokens, lower case; preserves negation/digits/operators; punctuation spacing ignored"}
    target=private_path(output) if output is not None else root/"ocr-quality.json"
    save_new(target,output_data)
    print(json.dumps({"output":str(target),"summaries":summaries,"timings":timings},indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",type=Path,required=True)
    p.add_argument("--output",type=Path);p.add_argument("--mcq-references",type=Path)
    args=p.parse_args();report(args.root,output=args.output,mcq_references=args.mcq_references)
