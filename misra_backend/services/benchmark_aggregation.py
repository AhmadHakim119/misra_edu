"""Explicit section aggregation for offline research; never changes live guides.

Best-N whole questions and a cap on summed marks are different academic rules.
Callers must obtain the actual approved rule before invoking this helper. A blank
answer confirmed in the scan can score zero; a missing/failed prediction cannot.
"""
from services.benchmark_metrics import identifier, number, snapshot_hash


def aggregate_section(scores, maxima, *, best_n=None, cap=None):
    if not isinstance(scores,dict) or not isinstance(maxima,dict) or not maxima:
        raise ValueError('Section scores/maxima must be nonempty question mappings.')
    if set(scores)-set(maxima):
        raise ValueError('Unknown question in section scores.')
    limits={identifier(key,'question_id'):number(value,'question maximum') for key,value in maxima.items()}
    if any(value<=0 for value in limits.values()):
        raise ValueError('Question maxima must be positive.')
    count=len(limits) if best_n is None else best_n
    if type(count) is not int or not 1<=count<=len(limits):
        raise ValueError('Best-N must count whole questions within this section.')
    maximum=sum(sorted(limits.values(),reverse=True)[:count])
    if cap is not None:
        cap=number(cap,'section cap')
        if not 0<cap<=maximum:raise ValueError('Section cap must fit the available marks.')
        maximum=cap
    rule={'question_maxima':limits,'best_n':best_n,'cap':cap}
    checked={}
    for key in limits:
        value=scores.get(key)
        if value is None:continue
        value=number(value,'question score')
        if not 0<=value<=limits[key]:raise ValueError('Question score exceeds its approved scale.')
        checked[key]=value
    missing=sorted(set(limits)-set(checked))
    result={'status':'incomplete' if missing else 'scored','max_score':maximum,
        'score':None,'uncapped_selected_total':None,'selected_question_ids':[],
        'missing_question_ids':missing,'rule':rule,'rule_sha256':snapshot_hash(rule),
        'question_scores':{key:checked.get(key) for key in sorted(limits)}}
    if not missing:
        selected=sorted(checked,key=lambda key:(-checked[key],key))[:count]
        total=sum(checked[key] for key in selected)
        result.update(score=min(total,cap) if cap is not None else total,
            uncapped_selected_total=total,selected_question_ids=selected)
    return result
