"""Structural citation coverage and observed performance, not semantic accuracy."""
import math
from collections import defaultdict
from models import Answer, GradingRun, Question, Submission
from services.grading_scope_service import is_external_question


def finite_number(value):
    if isinstance(value,bool):
        return None
    try:
        number = float(value)
    except (TypeError,ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def median(values):
    ordered = sorted(values)
    if not ordered: return None
    middle = len(ordered) // 2
    return (ordered[middle] + ordered[~middle]) / 2


def saved_run_diagnostics(db, *, institution_id, exam_id=None):
    query = db.query(GradingRun,Question).join(Answer,GradingRun.answer_id == Answer.id).join(Question,Answer.question_id == Question.id).join(Submission,Answer.submission_id == Submission.id).filter(
        Submission.institution_id == institution_id, Answer.institution_id == institution_id, Question.institution_id == institution_id)
    if exam_id: query = query.filter(Submission.exam_id == exam_id)
    buckets, covered, total, invalid, package_count, run_count = defaultdict(list), 0, 0, 0, 0, 0
    for run, question in query.all():
        if is_external_question(question): continue
        run_count += 1
        response = run.response_json or {}
        inference = response.get("inference") or {}
        key = (inference.get("provider") or "historical_unknown",run.model_name,run.prompt_version,run.mode)
        buckets[key].append({"latency_ms":finite_number(run.latency_ms),
            "prompt_tokens":finite_number(inference.get("prompt_tokens")),
            "completion_tokens":finite_number(inference.get("completion_tokens")),
            "cost":finite_number(inference.get("reported_cost_usd"))})
        package = response.get("grading_package")
        if not isinstance(package,dict): continue
        package_count += 1
        student_ids = {item.get("id") for item in package.get("student_evidence",[])}
        traceable_ids = {item.get("id") for item in package.get("student_evidence",[]) if item.get("kind") in {"ocr_segment","student_image"}}
        key = package.get("answer_key") or {}
        key_id = key.get("reference_id") if key.get("mode") != "no_fixed_answer" else None
        sources = {item["id"]:set(item.get("criterion_ids",[])) for item in (package.get("course_references") or {}).get("passages",[])}
        allowed_policy = set(package.get("policy") or {})
        for item in run.criteria_scores or []:
            total += 1
            refs = set(item.get("evidence_refs") or [])
            if refs and refs.issubset(student_ids) and (not traceable_ids or refs.intersection(traceable_ids)): covered += 1
            invalid += len(refs - student_ids)
            for ref in item.get("reference_refs") or []:
                if ref != key_id and item.get("criterion_id") not in sources.get(ref,set()): invalid += 1
            invalid += len(set(item.get("policy_applied") or []) - allowed_policy)
    performance = []
    for (provider,model,prompt,mode), rows in sorted(buckets.items(),key=lambda item:str(item[0])):
        latencies = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
        costs = [row["cost"] for row in rows if row["cost"] is not None]
        performance.append({"provider":provider,"model":model,"prompt_version":prompt,"mode":mode,"run_count":len(rows),
            "median_latency_ms":median(latencies),"mean_latency_ms":round(sum(latencies)/len(latencies)) if latencies else None,
            "latency_observation_count":len(latencies),"reported_cost_usd":round(sum(costs),8) if costs else None,
            "cost_observation_count":len(costs),"prompt_tokens":sum(row["prompt_tokens"] for row in rows if row["prompt_tokens"] is not None) if any(row["prompt_tokens"] is not None for row in rows) else None,
            "completion_tokens":sum(row["completion_tokens"] for row in rows if row["completion_tokens"] is not None) if any(row["completion_tokens"] is not None for row in rows) else None,
            "token_observation_count":sum(row["prompt_tokens"] is not None and row["completion_tokens"] is not None for row in rows)})
    return {"run_count":run_count,"package_run_count":package_count,"criterion_count":total,"cited_criterion_count":covered,
        "student_citation_coverage":round(covered/total,4) if total else None,"invalid_reference_count":invalid,
        "performance":performance,"interpretation":"Observed saved runs only; not a controlled held-out comparison. Structural citation validity does not establish semantic support. Missing cost is unknown, not free."}
