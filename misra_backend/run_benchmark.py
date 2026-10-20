"""Run an explicitly approved, private free-only research batch; never live grades."""
import argparse
import json
from pathlib import Path

from benchmark_cli import private_output
from services.benchmark_runner import approved_inputs,run_batch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    for name in ('guide','sources','approval','cases','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--model',required=True)
    args=parser.parse_args()
    try:
        inputs=approved_inputs(args.guide,args.sources,args.approval)
        cases=json.loads(args.cases.read_text(encoding='utf-8'))
        output=private_output(args.root,args.output/'manifest.json').parent
        records=run_batch(cases,inputs,args.model,output,progress=lambda value:print(json.dumps(value),flush=True))
        print(json.dumps({'expected_predictions':len(records),'scored':sum(r['status']=='scored' for r in records),
            'failed':sum(r['status']=='failed' for r in records),'live_records_changed':False}))
    except (ValueError,OSError,KeyError,TypeError) as error:
        # Input contents and credentials must never appear in terminal diagnostics.
        parser.exit(2,f'Research batch stopped: {type(error).__name__}. Check private review artifacts.\n')


if __name__=='__main__':main()
