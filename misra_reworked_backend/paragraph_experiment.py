"""Paragraph comparison diagnostics. Similarities are features, never marks."""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import math
from pathlib import Path
import re
from time import perf_counter

from comparison_methods import (keyword_scores, lexical_scores, normalize_scores,
                                 tokens, vector_scores, fit_cutoff)
from local_ocr import file_hash, offline_python, private_path
from rubric_pilot import Guide, local_request, save_new
from semantic_comparison import validate_vectors

ESSAYS=("q1a","q1b","q1c","q3a","q3b","q3c")


def simplified(text):
    return " ".join(tokens(text))


def nli_input_pairs(text,reference,claims):
    sentences=[s for s in re.split(r"(?<=[.!?])\s+|\n+",text) if s.strip()]
    return ([(text,reference),(reference,text)]+[(text,c) for c in claims]
            +[(s,reference) for s in sentences]+[(s,c) for s in sentences for c in claims])


def context_eligible(pairs,token_count,limit=512):
    """A full input must fit; no silent truncation or partial-answer acceptance."""
    return all(token_count(a,b)<=limit for a,b in pairs)


def bounded_neural(model_manifest,reference,texts,claims):
    from transformers import AutoTokenizer
    from neural_comparison_methods import bertscore_scores,nli_scores
    result={};metadata={};rejected=set()
    for family,names in (("bertscore",["bertscore_precision","bertscore_recall","bertscore_f1"]),
                         ("nli",["nli_entailment","nli_bidirectional","nli_sentence_guard","nli_criterion_support"])):
        path=model_manifest[family]["path"]
        tokenizer=AutoTokenizer.from_pretrained(path,local_files_only=True,trust_remote_code=False)
        limit=min(int(tokenizer.model_max_length),512)
        # Count full tokens without the tokenizer warning/truncation path; only
        # eligible complete inputs are subsequently sent to the fixed-size model.
        tokenizer.model_max_length=10**9
        def count(a,b):
            return len(tokenizer(a,b,add_special_tokens=True,truncation=False)["input_ids"])
        indices=[];unsupported=[]
        for i,text in enumerate(texts):
            pairs=nli_input_pairs(text,reference,claims) if family=="nli" else [(reference,None),(text,None)]
            if context_eligible(pairs,count,limit):indices.append(i)
            else:unsupported.append(i);rejected.add(i)
        for name in names:result[name]=[None]*len(texts)
        if indices:
            eligible=[texts[i] for i in indices]
            values,meta=(bertscore_scores(path,reference,eligible) if family=="bertscore"
                         else nli_scores(path,reference,eligible,claims))
            for name,items in values.items():
                for index,value in zip(indices,normalize_scores(items)):result[name][index]=value
        else:meta={"status":"all_inputs_exceed_context"}
        metadata[family]={**meta,"context_limit":limit,"unsupported_observation_indices":unsupported,
                          "policy":"complete_input_or_null; no truncation; full answer preserved"}
    return result,metadata,rejected


def anchor(spans,phrase,lo,hi,height):
    target=simplified(phrase);matches=[]
    for s in spans:
        y=(s["bbox"]["y0"]+s["bbox"]["y1"])/(2*height)
        if lo<=y<=hi:
            ratio=SequenceMatcher(None,simplified(s["text"]),target).ratio()
            if ratio>=.63:matches.append((ratio,s))
    return max(matches,key=lambda x:x[0])[1] if matches else None


def group_lines(spans):
    """English-only row grouping; preserve original spans separately."""
    rows=[]
    for span in sorted(spans,key=lambda s:s["bbox"]["y0"]):
        box=span["bbox"];center=(box["y0"]+box["y1"])/2;h=box["y1"]-box["y0"]
        if rows and abs(center-rows[-1][0])<=max(h,rows[-1][1])*.5:
            rows[-1][2].append(span)
        else:rows.append([center,h,[span]])
    lines=[]
    for row in rows:
        ordered=sorted(row[2],key=lambda s:s["bbox"]["x0"])
        lines.append({"id":ordered[0]["id"],"source_span_ids":[s["id"] for s in ordered],
                      "text":" ".join(s["text"] for s in ordered),
                      "engine_confidence":min(s["engine_confidence"] or 0 for s in ordered),
                      "bbox":{"x0":min(s["bbox"]["x0"] for s in ordered),
                              "y0":min(s["bbox"]["y0"] for s in ordered),
                              "x1":max(s["bbox"]["x1"] for s in ordered),
                              "y1":max(s["bbox"]["y1"] for s in ordered)}})
    return lines


def ordered_text(spans):
    return "\n".join(s["text"] for s in group_lines(spans))


def paragraph_config_path(root):
    return private_path(root/"paragraph-config.json")


def local_answers(spans,position,width,height,config):
    if position==2:
        return []  # Ordinary OCR text cannot establish which printed option is circled.
    section=1 if position==1 else 3
    spans=group_lines(spans)  # Tesseract emits words, Paddle emits lines; same anchor logic.
    found=[anchor(spans,p,lo,hi,height) for _,p,lo,hi in config["anchors"][str(position)]]
    if any(s is None for s in found):
        return [{"question_id":f"q{section}{letter}","text":None,"issues":["printed_anchor_unresolved"]}
                for letter in "abc"]
    bands=[(0,found[0]["bbox"]["y0"]),(found[0]["bbox"]["y0"],found[1]["bbox"]["y0"]),
           (found[1]["bbox"]["y0"],height)]
    results=[]
    for letter,(top,bottom) in zip("abc",bands):
        selected=[s for s in spans if top<=(s["bbox"]["y0"]+s["bbox"]["y1"])/2<bottom]
        issues=["unchecked_transcription","cancellations_unverified"]
        question_id=f"q{section}{letter}"
        prompt=anchor(selected,config["prompt_endings"][question_id],0,1,height)
        if prompt:
            selected=[s for s in selected if s["bbox"]["y0"]>=prompt["bbox"]["y1"]]
        elif section==3:
            results.append({"question_id":question_id,"text":None,
                            "issues":["printed_prompt_end_unresolved"]})
            continue
        elif letter=="a":
            issues.append("first_prompt_anchor_not_found")
        # Never silently discard fragments. Record that uncertain text is present.
        if any(s["engine_confidence"] is None or s["engine_confidence"]<.5 for s in selected):
            issues.append("low_engine_score_fragments_present")
        results.append({"question_id":f"q{section}{letter}","text":ordered_text(selected),
                        "span_ids":[s["id"] for s in selected],"issues":issues})
    return results


def collect(root):
    root=private_path(root)
    config=json.loads(paragraph_config_path(root).read_text(encoding="utf-8"))
    packet=json.loads((root/"redaction-manifest-reviewed.json").read_text())["entries"]
    observations=[]
    for source in (root/"local-runs").iterdir():
        if not (source/"summary.json").exists():raise ValueError("Wait for the local run to finish before freezing observations.")
        for e in packet:
            if e["split"] in {"test","reference"} or e["position"]==2:continue
            case=source/f"page-{e['page']:02}"
            if not (case/"result.json").exists():continue
            result=json.loads((case/"result.json").read_text())
            if result["status"]!="extracted":
                answers=[{"question_id":q,"text":None,"issues":["extraction_failed"]}
                         for q in (ESSAYS[:3] if e["position"]==1 else ESSAYS[3:])]
            else:
                spans=json.loads((case/"spans.json").read_text(encoding="utf-8"))
                answers=local_answers(spans,e["position"],result["width"],result["height"],config)
            for a in answers:
                observations.append({**a,"source":source.name,"paper_id":e["paper_id"],
                                     "split":e["split"],"pdf_page":e["page"]})
    for source in (root/"cloud-runs/first").iterdir():
        if not source.is_dir():continue
        for e in packet:
            if e["split"] in {"test","reference"} or e["position"]==2:continue
            path=source/f"page-{e['page']:02}"/"transcription.json"
            if not path.exists():
                answers=[{"question_id":q,"text":None,"needs_review":True}
                         for q in (ESSAYS[:3] if e["position"]==1 else ESSAYS[3:])]
            else:answers=json.loads(path.read_text(encoding="utf-8"))["answers"]
            for a in answers:
                observations.append({**a,"source":source.name,"paper_id":e["paper_id"],
                                     "split":e["split"],"pdf_page":e["page"],
                                     "issues":["unchecked_transcription"]+(["extraction_failed_or_missing"] if a["text"] is None
                                                else ["engine_reported_uncertainty"] if a["needs_review"] else [])})
    for a in json.loads((root/"development-annotations-draft.json").read_text(encoding="utf-8")):
        observations.append({**a,"source":"assistant_visual_draft","issues":["instructor_confirmation_pending"]})
    controlled=root/"controlled-paragraphs.json"
    if controlled.exists():
        observations.extend(json.loads(controlled.read_text(encoding="utf-8")))
    for row in observations:
        row.setdefault("id",f"{row['source']}__{row['paper_id']}__{row['question_id']}")
        row["word_count"]=len(tokens(row["text"])) if row["text"] is not None else None
        row["eligible_for_automatic_grading"]=False
    if len({r["id"] for r in observations})!=len(observations):raise ValueError("Duplicate observations.")
    save_new(root/"paragraph-observations.json",observations)
    return observations


def score(root, *, neural=False, embed=False,resume=False):
    root=private_path(root);output=root/"comparison-runs/first"
    if neural:
        config_path=paragraph_config_path(root)
        claims=json.loads(config_path.read_text(encoding="utf-8"))["claims"]
    output.mkdir(parents=True,exist_ok=resume)
    obs=json.loads((root/"paragraph-observations.json").read_text(encoding="utf-8"))
    guides={g["question_id"]:Guide.model_validate(g) for g in json.loads((root/"rubric-draft.json").read_text(encoding="utf-8"))["guides"]}
    if any(r["split"]=="test" for r in obs):raise ValueError("Test papers cannot enter this development comparison.")
    protocol={"observations_sha256":file_hash(root/"paragraph-observations.json"),
              "rubric_sha256":file_hash(root/"rubric-draft.json"),"neural":neural,"embed":embed,
              "scores_are_not_marks":True,"automatic_grading":False,"test_split_used":False,
              "source_code_sha256":file_hash(__file__),"label_status":"instructor_labels_pending",
              "threshold_training_status":"not_started_without_checked_training_labels"}
    if neural:
        protocol["paragraph_config_sha256"]=file_hash(config_path)
    if resume:
        previous=json.loads((output/"protocol.json").read_text())
        for key in ("observations_sha256","rubric_sha256","neural","embed"):
            if previous[key]!=protocol[key]:raise ValueError("Resume inputs/config changed.")
        if "paragraph_config_sha256" in previous and previous["paragraph_config_sha256"]!=protocol.get("paragraph_config_sha256"):
            raise ValueError("Resume paragraph config changed.")
        save_new(output/"resume-context-bounds.json",{"source_code_sha256":file_hash(__file__),
                    "reason":"Handle over-context observations individually; reuse completed groups without overwriting or repeated provider calls."})
    else:save_new(output/"protocol.json",protocol)
    model_manifest=json.loads((Path(__file__).resolve().parents[1]/"private/method-comparison-20261105/models-manifest.json").read_text())
    if neural:
        import torch
        torch.set_num_threads(4)
    if embed:
        tags=local_request("/api/tags")
        available=[m for m in tags["models"] if m["name"]=="qwen3-embedding:0.6b" and not m.get("remote_host")]
        if len(available)!=1:raise ValueError("Expected the installed local embedding model.")
        if not resume:save_new(output/"embedding-model.json",available[0])
    all_results=[]
    for qid in ESSAYS:
        guide=guides[qid];rows=[r for r in obs if r["question_id"]==qid and r["text"] is not None]
        if resume and (output/f"{qid}-scores.json").exists():
            previous=json.loads((output/f"{qid}-scores.json").read_text(encoding="utf-8"))
            if {r["id"] for r in previous["results"]}!={r["id"] for r in rows}:
                raise ValueError("Completed group disagrees with frozen observations.")
            all_results.extend(previous["results"]);continue
        texts=[r["text"] for r in rows];started=perf_counter();features=[{} for _ in rows]
        # Full-level descriptions define accepted ideas; the reference is one valid answer.
        alias_path=root/"concept-aliases.json"
        concepts=(json.loads(alias_path.read_text(encoding="utf-8"))[qid] if alias_path.exists()
                  else {c.id:[c.title] for c in guide.criteria})
        setup=[guide.question,guide.model_answer]+[l.description for c in guide.criteria for l in c.levels]
        for i,text in enumerate(texts):
            values,details=lexical_scores(guide.model_answer,text,concepts)
            from rouge_score.rouge_scorer import RougeScorer
            rouge=RougeScorer(["rouge1","rouge2","rougeL"],use_stemmer=False).score(guide.model_answer,text)
            for name,s in rouge.items():values.update({name+"_precision":s.precision,name+"_recall":s.recall})
            features[i].update(values)
        keywords,keyword_meta=keyword_scores(guide.model_answer,texts,setup)
        for name,values in keywords.items():
            for f,value in zip(features,normalize_scores(values)):f[name]=value
        meta={"keyword":keyword_meta,"lexical_seconds":perf_counter()-started,
              "concept_aliases":concepts,"concept_note":"Presence only; negation and relationships are not resolved by aliases."}
        rejected=set()
        if neural:
            with offline_python():
                neural_values,neuralmeta,rejected=bounded_neural(model_manifest,guide.model_answer,texts,claims[qid])
            for name,values in neural_values.items():
                for f,value in zip(features,normalize_scores(values)):f[name]=value
            meta.update(neuralmeta)
        if embed:
            request={"model":"qwen3-embedding:0.6b","input":[guide.model_answer]+texts,"truncate":False,"keep_alive":"5m"}
            save_new(output/f"{qid}-embedding-request.json",request)
            response=local_request("/api/embed",request)
            save_new(output/f"{qid}-embedding-response.json",response)
            vectors=validate_vectors(response,request["model"],len(texts)+1)
            for f,v in zip(features,vectors[1:]):f.update(vector_scores(vectors[0],v))
        result=[{"id":r["id"],"source":r["source"],"paper_id":r["paper_id"],"split":r["split"],
                 "question_id":qid,"word_count":r["word_count"],"scores":f,
                 "issues":r["issues"]+(["neural_context_limit"] if i in rejected else []),
                 "eligible_for_automatic_grading":False} for i,(r,f) in enumerate(zip(rows,features))]
        save_new(output/f"{qid}-scores.json",{"results":result,"metadata":meta})
        all_results+=result
        print(json.dumps({"question_id":qid,"observations":len(rows),"methods":len(features[0]) if features else 0}),flush=True)
    missing=[{"id":r["id"],"status":"mapping_unresolved","scores":None} for r in obs if r["text"] is None]
    save_new(output/"scores.json",{"results":all_results,"unresolved":missing,"grades_produced":0})


def train_thresholds(scores,labels,manifest,guides):
    """Only explicit checked instructor labels may train the real-paper router."""
    split={g["paper_id"]:g["split"] for g in manifest["groups"]}
    if any(g.approval_status!="approved" for q,g in guides.items() if q in ESSAYS):
        raise ValueError("An approved rubric is required to train the real-paper router.")
    if not labels or any(not row.get("instructor_checked") for row in labels):
        raise ValueError("Checked instructor training labels are required; no Qwen pseudo-label substitution.")
    if any(split.get(row["paper_id"])!="train" for row in labels):
        raise ValueError("Only training papers may fit thresholds.")
    if len({(r["paper_id"],r["question_id"]) for r in labels})!=len(labels):
        raise ValueError("Duplicate training labels.")
    if any(not r.get("instructor_levels") or any(v not in {"full","zero"} for v in r["instructor_levels"].values()) for r in labels):
        raise ValueError("Training labels must explicitly resolve every binary criterion.")
    for row in labels:
        guide=guides.get(row["question_id"])
        if guide is None or set(row["instructor_levels"])!={c.id for c in guide.criteria}:
            raise ValueError("Instructor criterion IDs disagree with the approved rubric.")
    label_map={(r["paper_id"],r["question_id"]):r for r in labels}
    output={}
    for qid in ESSAYS:
        eligible=[r for r in scores if r["question_id"]==qid and (r["paper_id"],qid) in label_map]
        output[qid]={}
        for source in sorted({r["source"] for r in eligible}):
            rows=[r for r in eligible if r["source"]==source]
            output[qid][source]={}
            for method in sorted({m for row in rows for m in row["scores"]}):
                values={r["id"]:r["scores"].get(method) for r in rows}
                truth={r["id"]:all(v=="full" for v in label_map[(r["paper_id"],qid)]["instructor_levels"].values()) for r in rows}
                output[qid][source][method]=fit_cutoff(values,truth) if len(set(truth.values()))==2 else None
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["collect","score"])
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--neural",action="store_true");parser.add_argument("--embed",action="store_true")
    parser.add_argument("--resume-existing",action="store_true")
    args=parser.parse_args()
    if args.action=="collect":
        rows=collect(args.root);print(json.dumps({"observations":len(rows),"test_used":False}))
    else:score(args.root,neural=args.neural,embed=args.embed,resume=args.resume_existing)


if __name__=="__main__":main()
