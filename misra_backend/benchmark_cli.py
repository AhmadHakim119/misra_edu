"""Private offline GPHY benchmark preparation/scoring. Never calls a model or DB."""
import argparse
import csv
import json
import hashlib
from pathlib import Path

from services.benchmark_metrics import MetricPolicy, build_benchmark_report, fit_calibration, snapshot_hash

REFERENCE_FIELDS=['answer_id','paper_id','group_id','exam_version','question_id','unit_level','split',
    'max_score','score_step','reference_score','independent_reference','label_checked','input_reviewed',
    'guide_checked','group_checked','fixed_inputs_sha256']
PREDICTION_FIELDS=['answer_id','condition','run_id','status','score','confidence','hard_review_required',
    'fixed_inputs_sha256','system_sha256','comparison_sha256','retrieval_snapshot_sha256']
BOOLEAN_FIELDS={'independent_reference','label_checked','input_reviewed','guide_checked','group_checked','hard_review_required'}
NUMERIC_FIELDS={'max_score','score_step','reference_score','score','confidence'}


def private_output(root,path):
    path=Path(path).resolve();root=Path(root).resolve()
    if not any(path.is_relative_to(root/name) for name in ('private','evaluation-artifacts')):
        raise ValueError('Evaluation outputs must stay in ignored private/ or evaluation-artifacts/.')
    path.parent.mkdir(parents=True,exist_ok=True)
    return path


def write_new_json(path,value):
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False)


def read_records(path):
    path=Path(path)
    if path.suffix.lower()=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
        for row in rows:
            for key,value in list(row.items()):
                if key is None or not isinstance(value,str):raise ValueError('CSV columns do not match the header.')
                if key in BOOLEAN_FIELDS:
                    if value.lower() not in ('true','false'):raise ValueError(f'{key} needs true or false.')
                    row[key]=value.lower()=='true'
                elif key in NUMERIC_FIELDS:row[key]=float(value) if value.strip() else None
                elif not value.strip():row[key]=None
        return rows
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,list):raise ValueError('Input JSON must contain an array of records.')
    return value


def prepare(root,output,pages_per_paper=11):
    """Candidate boundaries only. Human checks are deliberately left false."""
    from pypdf import PdfReader
    if pages_per_paper<1:raise ValueError('Candidate page count must be positive.')
    root=Path(root).resolve();output=private_output(root,Path(output)/'prepared-inventory.json').parent
    for name in ('prepared-inventory.json','reference-template.csv','prediction-template.csv','metric-policy.json'):
        if (output/name).exists():raise ValueError('Preparation output already exists. Keep reviewed files; choose a fresh output folder.')
    documents=[];papers=[];labels=[]
    splits={'F23':'development','F24':'calibration','F25':'test'}
    suggested_maxima={'F23':[8,10,10,10,10,12],'F24':[20,16,12,12],'F25':[20,16,12,12]}
    for year in splits:
        folder=root/f'GPHY171_01_Final Exam_{year}'
        for path in sorted(folder.iterdir()):
            if path.suffix.lower()!='.pdf':continue
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            reader=PdfReader(path);count=len(reader.pages)
            is_key=any(term in path.stem.upper() for term in ('_AK','ANSWER','KEY','SOLUTION'))
            documents.append({'document_id':digest[:16],'year':year,'original_path':str(path.relative_to(root)),
                'sha256':digest,'page_count':count,'candidate_role':'answer_key' if is_key else 'paper_bundle',
                'review_status':'unreviewed'})
            if is_key:continue
            if count%pages_per_paper:continue
            for start in range(0,count,pages_per_paper):
                paper_id=f'{year}-{digest[:12]}-p{start+1:04d}'
                papers.append({'paper_id':paper_id,'document_id':digest[:16],'first_page_1based':start+1,
                    'last_page_1based':start+pages_per_paper,'candidate_split':splits[year],
                    'boundary_checked':False,'group_checked':False,'redaction_checked':False,
                    'original_sha256':digest,'clean_input_path':None,'clean_input_sha256':None})
                for index,maximum in enumerate(suggested_maxima[year],1):
                    labels.append(dict(answer_id=f'{paper_id}-part{index}',paper_id=paper_id,group_id=paper_id,
                        exam_version=year,question_id=f'part{index}',unit_level='exam_part',split=splits[year],
                        max_score=maximum,score_step='',reference_score='',independent_reference=True,
                        label_checked=False,input_reviewed=False,guide_checked=False,group_checked=False,fixed_inputs_sha256=''))
    inventory={'schema_version':1,'status':'needs_boundary_label_redaction_and_guide_review',
        'independent_reference_provenance':'User confirmed original instructor marks and answer keys for all years on 2026-10-17.',
        'candidate_pages_per_paper':pages_per_paper,'documents':documents,'papers':papers,
        'quality_flags':[{'year':'F23','code':'key_cover_maxima_conflict',
            'message':'Inspected key cover lists 6/9/12/9/10/14; inspected student cover lists 8/10/10/10/10/12. First question page agrees with student cover. Verify every question allocation; do not infer marks from the key cover.'}],
        'warnings':['All paper boundaries are candidates, not confirmed individual exams.',
            'Part maxima are inspection-based suggestions pending guide review.',
            'Labels are exam-part totals, not individual question or criterion scores.',
            'Student identity deduplication across years is required before confirming group assignments.',
            'No grade, mark or redaction is inferred automatically. Original PDFs are unchanged.']}
    write_new_json(output/'prepared-inventory.json',inventory)
    with (output/'reference-template.csv').open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=REFERENCE_FIELDS);writer.writeheader();writer.writerows(labels)
    with (output/'prediction-template.csv').open('x',encoding='utf-8',newline='') as stream:
        csv.DictWriter(stream,fieldnames=PREDICTION_FIELDS).writeheader()
    write_new_json(output/'metric-policy.json',MetricPolicy().__dict__)
    return {'pdf_count':len(documents),'page_count':sum(item['page_count'] for item in documents),
        'candidate_paper_count':len(papers),'candidate_part_label_count':len(labels),'output':str(output)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    commands=parser.add_subparsers(dest='command',required=True)
    initial=commands.add_parser('prepare');initial.add_argument('--output',type=Path,required=True)
    for name in ('fit','report'):
        command=commands.add_parser(name)
        command.add_argument('--references',type=Path,required=True);command.add_argument('--predictions',type=Path,required=True)
        command.add_argument('--policy',type=Path,required=True);command.add_argument('--output',type=Path,required=True)
        if name=='fit':command.add_argument('--condition',choices=('no_rag','bm25'),required=True)
        else:command.add_argument('--calibration',type=Path)
    args=parser.parse_args()
    try:
        if args.command=='prepare':result=prepare(args.root,args.output)
        else:
            references=read_records(args.references);predictions=read_records(args.predictions)
            policy=MetricPolicy(**json.loads(args.policy.read_text(encoding='utf-8')))
            if args.command=='fit':result=fit_calibration(references,predictions,args.condition,policy)
            else:
                calibration=json.loads(args.calibration.read_text(encoding='utf-8')) if args.calibration else None
                result=build_benchmark_report(references,predictions,policy,calibration)
            result['input_file_sha256']={name:hashlib.sha256(Path(path).read_bytes()).hexdigest()
                for name,path in [('references',args.references),('predictions',args.predictions),('policy',args.policy)]}
            output=private_output(args.root,args.output);write_new_json(output,result)
            result={'output':str(output),'status':result.get('status','report_written')}
        print(json.dumps(result))
    except (ValueError,OSError,TypeError,KeyError) as error:parser.exit(2,f'{error}\n')


if __name__=='__main__':main()
