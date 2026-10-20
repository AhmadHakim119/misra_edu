"""Create three private, unapproved PDF redaction drafts for pilot inspection."""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image,ImageDraw
from pdf2image import convert_from_path
from pypdf import PdfReader,PdfWriter

from benchmark_cli import private_output,write_new_json
from services.benchmark_redaction import append_lossless_page,redact_red_ink


def create_pilot(root,inventory_path,output,cover_review_path,dpi=200):
    root=Path(root).resolve();inventory=json.loads(Path(inventory_path).read_text(encoding='utf-8'))
    if type(dpi) is not int or not 72<=dpi<=600:raise ValueError('Review rendering DPI must be between 72 and 600.')
    output=private_output(root,Path(output)/'redaction-review.json').parent
    if any(output.iterdir()):raise ValueError('Redaction output must be empty; preserve prior artifacts and choose a new folder.')
    records={row['document_id']:row for row in inventory['documents']}
    selected=[next(row for row in inventory['papers'] if row['paper_id'].startswith(year+'-')) for year in ('F23','F24','F25')]
    cover_review=json.loads(Path(cover_review_path).read_text(encoding='utf-8'))
    approved={row['paper_id']:row for row in cover_review['covers'] if row.get('cover_contains_no_answers') is True}
    for paper in selected:
        source=(root/records[paper['document_id']]['original_path']).resolve()
        if not source.is_relative_to(root) or source.suffix.lower()!='.pdf':
            raise ValueError('Original PDF must stay inside the evaluation workspace.')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=paper['original_sha256']:
            raise ValueError('Original PDF changed after inventory.')
        cover=approved.get(paper['paper_id'],{})
        if cover.get('original_sha256')!=paper['original_sha256'] or cover.get('source_page_1based')!=paper['first_page_1based']:
            raise ValueError('Administrative cover concealment requires a checked cover and matching original hash/page.')
        if (output/(paper['paper_id']+'-DRAFT.pdf')).exists():raise ValueError('Draft already exists; refusing to overwrite.')
    review={'schema_version':1,'status':'DRAFT_REQUIRES_HUMAN_REVIEW','renderer_dpi':dpi,
        'purpose':'candidate_mask_inspection_only_not_model_inputs','ready_for_inference':False,
        'method':'Red-chromatic pixels whitened; administrative cover concealed; lossless RGB image PDF.',
        'limits':['Colour does not prove who wrote a mark. Teacher ink that is black/blue may remain.',
            'Red student work or printed problem content may be masked. Review every page; rebuild accepted masks from originals.',
            'Overlap with student writing is not reconstructed. Exclude or obtain independently checked text for affected units.',
            'Do not use these drafts for inference until boundaries, identities, teacher marks and retained student work are checked.'],
        'papers':[]}
    for paper in selected:
        record=records[paper['document_id']];source=root/record['original_path']
        before=hashlib.sha256(source.read_bytes()).hexdigest()
        if before!=paper['original_sha256']:raise ValueError('Original PDF changed after inventory.')
        reader=PdfReader(source);writer=PdfWriter();pages=[];thumbnails=[]
        for index in range(paper['first_page_1based']-1,paper['last_page_1based']):
            original=convert_from_path(source,dpi=dpi,first_page=index+1,last_page=index+1)[0].convert('RGB')
            if index==paper['first_page_1based']-1:
                # Only the sampled first covers were visually inspected. Do not
                # apply this administrative-page concealment to arbitrary pages.
                cleaned=Image.new('RGB',original.size,'white');draw=ImageDraw.Draw(cleaned)
                draw.text((80,100),'Administrative cover concealed for evaluation',fill='black',font_size=32)
                mask=Image.new('L',original.size,255)
                diagnostics={'administrative_cover_concealed':True,'pixel_preservation_verified':True,
                    'overlap_review_required':False,'red_pixel_count':None}
            else:
                try:cleaned,mask,diagnostics=redact_red_ink(original)
                except ValueError as error:
                    cleaned=original.copy();mask=Image.new('L',original.size,0)
                    diagnostics={'automatic_mask_rejected':str(error),'overlap_review_required':True,'pixel_preservation_verified':True}
            page=reader.pages[index];width,height=float(page.mediabox.width),float(page.mediabox.height)
            if page.rotation%180:width,height=height,width
            append_lossless_page(writer,cleaned,width,height)
            mask_path=output/f'{paper["paper_id"]}-source-page-{index+1:03d}-mask.png';mask.save(mask_path)
            pages.append({'source_page_1based':index+1,'draft_page_1based':len(pages)+1,'width_points':width,
                'height_points':height,'mask_file':mask_path.name,'mask_sha256':hashlib.sha256(mask_path.read_bytes()).hexdigest(),
                'reviewed':False,'student_work_preserved':False,'teacher_marks_fully_concealed':False,**diagnostics})
            thumb=cleaned.copy();thumb.thumbnail((400,560));thumbnails.append(thumb)
        writer.add_metadata({'/Title':paper['paper_id']+' - REDACTION DRAFT - NOT APPROVED','/Author':'MISRA local evaluation'})
        draft=output/(paper['paper_id']+'-DRAFT.pdf')
        with draft.open('xb') as stream:writer.write(stream)
        reopened=PdfReader(draft)
        if len(reopened.pages)!=len(pages) or any(page.get('/Annots') for page in reopened.pages):raise ValueError('Draft PDF structural validation failed.')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=before:raise ValueError('Original PDF changed during preparation.')
        # A private contact sheet is for locating pages; detailed review uses PDFs.
        sheet=Image.new('RGB',(1200,4*600),'#eeeeee');draw=ImageDraw.Draw(sheet)
        for position,thumb in enumerate(thumbnails):
            x=(position%3)*400;y=(position//3)*600
            sheet.paste(thumb,(x,y+24));draw.text((x+8,y+4),f'Draft page {position+1}',fill='black',font_size=16)
        sheet.save(output/(paper['paper_id']+'-review.png'))
        review['papers'].append({'paper_id':paper['paper_id'],'original_sha256':before,'draft_file':draft.name,
            'draft_sha256':hashlib.sha256(draft.read_bytes()).hexdigest(),'page_count':len(pages),
            'input_reviewed':False,'boundary_checked':False,'pages':pages})
    write_new_json(output/'redaction-review.json',review)
    return {'draft_count':len(review['papers']),'page_count':sum(row['page_count'] for row in review['papers']),
        'status':review['status'],'output':str(output)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--inventory',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cover-review',type=Path,required=True)
    args=parser.parse_args()
    try:print(json.dumps(create_pilot(args.root,args.inventory,args.output,args.cover_review)))
    except (ValueError,OSError,StopIteration) as error:parser.exit(2,str(error)+'\n')
