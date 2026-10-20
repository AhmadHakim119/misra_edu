"""Isolated research proposals using the existing grading and verification contracts.

No live database reads/writes, guide approvals, reference labels or final grades.
Checked transcriptions isolate grading/retrieval from OCR in this experiment.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import uuid

from services.benchmark_metrics import CONDITIONS, SPLITS, digest, identifier, snapshot_hash
from services.free_model_gateway import complete_free
from services.grading_package_service import (provider_grading_package,
    restore_provider_citations, validate_evidence_references)
from services.grading_service import (GRADING_PROMPT, GRADING_PROMPT_VERSION,
    GradingResult, _validate_grading_against_rubric)
from services.material_retrieval_service import (MAX_CANDIDATES, MAX_CONTEXT_CHARS,
    MAX_PASSAGES, bm25_scores)
from services.openrouter_client import OpenRouterError
from services.verification_agent import verify

RUNNER_VERSION='2026-10-17.v1'
CASE_FIELDS={'answer_id','paper_id','group_id','exam_version','question_id','split',
    'student_text','transcription_checked','student_work_preserved','teacher_marks_absent',
    'group_checked','review_provenance'}
REVIEW_FLAGS=('transcription_checked','student_work_preserved','teacher_marks_absent','group_checked')


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def approved_inputs(guide_path, sources_path, approval_path):
    approval=json.loads(Path(approval_path).read_text(encoding='utf-8'))
    if approval.get('guide',{}).get('approved') is not True or approval['guide'].get('sha256')!=file_hash(guide_path):
        raise ValueError('The exact research guide needs explicit instructor approval.')
    source_approval=approval.get('source_pages',{})
    if source_approval.get('checked') is not True or source_approval.get('approved') is not True or source_approval.get('sha256')!=file_hash(sources_path):
        raise ValueError('The exact course pages need separate source verification and approval.')
    guide=json.loads(Path(guide_path).read_text(encoding='utf-8'))
    sources=json.loads(Path(sources_path).read_text(encoding='utf-8'))
    questions={}
    for q in guide['questions']:
        qid=identifier(q.get('id'),'question ID')
        if qid in questions:raise ValueError('Duplicate guide question.')
        if sum(c['points'] for c in q['criteria'])!=q['max_score']:
            raise ValueError('Guide criterion maxima do not sum to the question maximum.')
        questions[qid]=q
    chunks={}
    for page in sources['pages']:
        for chunk in page['chunks']:
            # Page membership and content are fixed in the explicitly approved file.
            if chunk['material_version_id']!=page['material_version_id'] or chunk['page_index']+1!=page['pdf_page']:
                raise ValueError('Source chunk belongs to a different page/version.')
            if hashlib.sha256(chunk['text'].encode()).hexdigest()!=chunk['text_sha256']:
                raise ValueError('Source passage text changed after its content hash.')
            chunks[chunk['id']]={**chunk,'document_sha256':page['document_sha256']}
    if not chunks or len(chunks)>MAX_CANDIDATES:raise ValueError('Approved research corpus is empty or too broad.')
    return {'guide':guide,'questions':questions,'chunks':list(chunks.values()),
        'guide_sha256':file_hash(guide_path),'sources_sha256':file_hash(sources_path),
        'approval_sha256':file_hash(approval_path)}


def validate_cases(cases, inputs):
    ids=set();groups={};papers={}
    for case in cases:
        if set(case)-CASE_FIELDS:raise ValueError('Unknown case fields; references/identities cannot enter grading inputs.')
        for key in ('answer_id','paper_id','group_id','exam_version','question_id','student_text','review_provenance'):
            identifier(case.get(key),key)
        if case['answer_id'] in ids:raise ValueError('Duplicate research answer.')
        ids.add(case['answer_id'])
        question=inputs['questions'].get(case['question_id'])
        if not question or case['exam_version']!=question['exam_version']:raise ValueError('Case and approved question version differ.')
        if case.get('split') not in SPLITS:raise ValueError('Declare a research partition.')
        if any(case.get(field) is not True for field in REVIEW_FLAGS):raise ValueError('Student input and group checks are incomplete.')
        if groups.setdefault(case['group_id'],case['split'])!=case['split']:raise ValueError('A student crosses research partitions.')
        assignment=(case['group_id'],case['split'],case['exam_version'])
        if papers.setdefault(case['paper_id'],assignment)!=assignment:raise ValueError('A paper has conflicting group/version assignments.')


def fixed_input_hash(case,inputs):
    return snapshot_hash({'case':case,'question':inputs['questions'][case['question_id']],
        'policy':inputs['guide']['policy'],'guide_sha256':inputs['guide_sha256'],
        'source_corpus_sha256':inputs['sources_sha256']})


def retrieval_context(question,inputs,*,strategy='bm25_v1',concept_queries=None):
    from services.material_retrieval_service import NEURAL_STRATEGIES
    from services.retrieval_query_service import validate_concept_queries,criterion_query,QUERY_VERSION
    if strategy not in {'bm25_v1', *NEURAL_STRATEGIES}:
        raise ValueError('Unknown research retrieval strategy.')
    concepts=validate_concept_queries(question['text'],question['criteria'],concept_queries)
    selected={};queries=[]
    for criterion in question['criteria']:
        query=criterion_query(question['text'],criterion,concepts)
        chunks=inputs['chunks']
        details=None
        if strategy=='bm25_v1':
            scores=bm25_scores([c['text'] for c in chunks],query)
        else:
            from services.neural_retrieval_service import rank_passages
            chunks=sorted(chunks,key=lambda c:c['id'])
            scores,details=rank_passages([c['text'] for c in chunks],query,
                namespace=snapshot_hash({'corpus':inputs['sources_sha256'],'guide':inputs['guide_sha256']}),strategy=strategy)
        ranked=sorted(zip(chunks,scores),
            key=lambda pair:(-pair[1],pair[0]['id']))
        hits=[(chunk,score) for chunk,score in ranked if score>0][:2]
        queries.append({'criterion_id':criterion['id'],'query':query,'candidate_count':len(ranked),
            'selected_chunk_ids':[chunk['id'] for chunk,_ in hits]})
        if details is not None:
            by_id={chunk['id']:detail for chunk,detail in zip(chunks,details)}
            queries[-1]['ranking']={chunk['id']:by_id[chunk['id']] for chunk,_ in hits}
        for chunk,score in hits:
            item=selected.setdefault(chunk['id'],{'id':'material:'+chunk['id'],'title':chunk['title'],
                'page_index':chunk['page_index'],'printed_page_label':chunk.get('printed_page_label'),
                'text':chunk['text'],'text_sha256':chunk['text_sha256'],'document_sha256':chunk['document_sha256'],
                'criterion_ids':[],'source_role':'approved_course_reference','retrieval_score':score})
            item['criterion_ids'].append(criterion['id'])
    passages=[];characters=0
    remaining=list(selected.values())
    if strategy!='bm25_v1':
        # Give each criterion context before spending the budget on extra passages.
        uncovered={c['id'] for c in question['criteria']}
        while uncovered and len(passages)<MAX_PASSAGES:
            fitting=[p for p in remaining if uncovered.intersection(p['criterion_ids']) and characters+len(p['text'])<=MAX_CONTEXT_CHARS]
            if not fitting:break
            passage=max(fitting,key=lambda p:len(uncovered.intersection(p['criterion_ids'])))
            passages.append(passage);characters+=len(passage['text']);uncovered.difference_update(passage['criterion_ids']);remaining.remove(passage)
    for passage in remaining:
        if len(passages)>=MAX_PASSAGES or characters+len(passage['text'])>MAX_CONTEXT_CHARS:continue
        passages.append(passage);characters+=len(passage['text'])
    covered={cid for p in passages for cid in p['criterion_ids']}
    if {c['id'] for c in question['criteria']}-covered:
        raise ValueError('Required course evidence is unavailable within the approved bounds.')
    context={'mode':'required','status':'retrieved','strategy':strategy,'passages':passages,
        'queries':queries,'total_context_chars':characters}
    if concepts is not None:
        context['query_strategy']=QUERY_VERSION
        context['concept_queries']=deepcopy(concepts)
    if strategy!='bm25_v1':
        from services.neural_retrieval_service import model_metadata
        context['neural_retrieval']=model_metadata(strategy)
    return context


def grading_package(case,inputs,condition,*,retrieval_strategy='bm25_v1',concept_queries=None):
    if condition not in CONDITIONS:raise ValueError('Unknown research condition.')
    if condition=='no_rag' and concept_queries is not None:
        raise ValueError('Concept queries require an explicit retrieval condition.')
    q=inputs['questions'][case['question_id']]
    context=retrieval_context(q,inputs,strategy=retrieval_strategy,concept_queries=concept_queries) if condition=='bm25' else {
        'mode':'disabled','status':'disabled','strategy':'research_no_retrieval','passages':[]}
    return {'schema_version':1,'question':{'id':q['id'],'number':q['number'],'text':q['text'],'max_score':q['max_score']},
        'rubric':{'max_score':q['max_score'],'criteria':deepcopy(q['criteria'])},
        'policy':deepcopy(inputs['guide']['policy']),
        'answer_key':{'reference_id':'key:'+q['id'],'mode':'reference','reference_text':q['answer_key'],'version':1},
        'routing':{'selected_mode':'text_only','research_only':True},'definition_consistency':{},
        'student_evidence':[{'id':'student-text:'+case['answer_id'],'kind':'ocr_segment','page_index':0,'segment_index':0,'text':case['student_text']}],
        'course_references':context}


def research_configuration(model,seed=171):
    if not isinstance(model,str) or not model.endswith(':free') or model.startswith('openrouter/'):
        raise ValueError('Research inference requires a fixed explicit free model.')
    common={'runner_version':RUNNER_VERSION,'prompt_version':GRADING_PROMPT_VERSION,
        'prompt_sha256':hashlib.sha256(GRADING_PROMPT.encode()).hexdigest(),'model':model,
        'verification':'existing bounded verification agent, same fixed free model',
        'temperature':0,'max_tokens':4000,'modality':'checked_transcription_text_only',
        'paid_fallback':False,'seed_for_arm_order':seed}
    return {**common,'comparison_sha256':snapshot_hash(common)}


def write_new(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False)


def run_case(case,inputs,condition,configuration,directory,*,transport=None):
    """One attempt. Uncertain/failed attempts survive; no best-of selection."""
    directory=Path(directory)
    fixed=fixed_input_hash(case,inputs)
    system=snapshot_hash({'configuration':configuration,'condition':condition,
        'sources_sha256':inputs['sources_sha256'],'max_passages':MAX_PASSAGES,'max_context_chars':MAX_CONTEXT_CHARS})
    identity={'answer_id':case['answer_id'],'condition':condition,'fixed_inputs_sha256':fixed,
        'system_sha256':system,'comparison_sha256':configuration['comparison_sha256']}
    if directory.exists():
        intent=json.loads((directory/'intent.json').read_text(encoding='utf-8'))
        if any(intent.get(key)!=value for key,value in identity.items()):raise ValueError('Saved attempt inputs/system changed.')
        if not (directory/'prediction.json').is_file():raise ValueError('An interrupted attempt is uncertain; preserve it, do not automatically call again.')
        return json.loads((directory/'prediction.json').read_text(encoding='utf-8'))
    directory.mkdir(parents=True)
    intent={**identity,'run_id':str(uuid.uuid4())}
    write_new(directory/'intent.json',intent)
    prediction={**intent,'status':'failed','score':None,'confidence':None,'hard_review_required':True,
        'retrieval_snapshot_sha256':snapshot_hash({'status':'not_retrieved','corpus':inputs['sources_sha256']}) if condition=='bm25' else None}
    complete=transport or (lambda contents,**_:complete_free(contents,model=configuration['model']))
    try:
        package=grading_package(case,inputs,condition)
        if condition=='bm25':prediction['retrieval_snapshot_sha256']=snapshot_hash(package['course_references'])
        safe,evidence_aliases,reference_aliases=provider_grading_package(package)
        write_new(directory/'package.json',package)
        write_new(directory/'provider-package.json',safe)
        completion=complete(GRADING_PROMPT+'\nGRADING PACKAGE JSON:\n'+json.dumps(safe,ensure_ascii=False),task='grading')
        write_new(directory/'assessment-response.json',{'text':completion.text,'inference':completion.metadata})
        result=GradingResult.model_validate_json(completion.text)
        _validate_grading_against_rubric(result,package['rubric'])
        candidate=result.model_dump()
        restore_provider_citations(result,evidence_aliases,reference_aliases)
        validate_evidence_references(result,package)
        def verification_completion(contents,**kwargs):
            response=complete(contents,**kwargs)
            write_new(directory/'verification-response.json',{'text':response.text,'inference':response.metadata})
            return response
        checked=verify(safe,candidate,completion_fn=verification_completion)
        write_new(directory/'verification.json',checked)
        write_new(directory/'proposal.json',result.model_dump())
        prediction.update(status='scored',score=result.score,confidence=result.llm_confidence,
            hard_review_required=checked['status']=='needs_review' or any(c.uncertainties for c in result.criteria_scores))
    except Exception as error:
        # Only bounded diagnostic codes are printed/stored outside raw private responses.
        failure={'error_type':type(error).__name__,'retry_automatically':False}
        if isinstance(error,OpenRouterError):failure['provider_message']=str(error)
        write_new(directory/'failure.json',failure)
    write_new(directory/'prediction.json',prediction)
    return prediction


def run_batch(cases,inputs,model,output,*,transport=None,seed=171,progress=None):
    validate_cases(cases,inputs)
    config=research_configuration(model,seed)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    manifest={'configuration':config,'cases_sha256':snapshot_hash(cases),
        'guide_sha256':inputs['guide_sha256'],'sources_sha256':inputs['sources_sha256'],
        'approval_sha256':inputs['approval_sha256']}
    manifest_path=output/'manifest.json'
    if manifest_path.exists():
        if json.loads(manifest_path.read_text())!=manifest:raise ValueError('Frozen batch changed; choose a new experiment directory.')
    else:write_new(manifest_path,manifest)
    rng=random.Random(seed);schedule=[]
    for case in cases:
        arms=list(CONDITIONS);rng.shuffle(arms)
        schedule.extend((case,arm) for arm in arms)
    predictions=[]
    for index,(case,condition) in enumerate(schedule):
        # IDs are hashes in directory names; never interpolate arbitrary paths.
        run_dir=output/'runs'/snapshot_hash([case['answer_id'],condition])
        record=run_case(case,inputs,condition,config,run_dir,transport=transport)
        predictions.append(record)
        if progress:progress({'completed':index+1,'total':len(schedule),'condition':condition,'status':record['status']})
    destination=output/'predictions.json'
    if not destination.exists():write_new(destination,predictions)
    elif json.loads(destination.read_text())!=predictions:raise ValueError('Saved predictions differ from frozen attempts.')
    return predictions
