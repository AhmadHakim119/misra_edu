"""Chapter proposals never approve source text or change historical scopes."""
import re
from sqlalchemy import inspect,func
from models import MaterialPage, MaterialVersion, MaterialChapterIndex, AssessmentMaterialAttachment
from services.course_material_service import text_hash, public_version

LIBRARY_TABLES=(MaterialChapterIndex,AssessmentMaterialAttachment)
HEADING=re.compile(r'^\s*(?:chapter|unit|الفصل|الوحدة)\s+([0-9٠-٩]+|[IVXLCDM]+)\b[\s.:—–-]*(.*)$',re.I)
CHAPTER_FILE=re.compile(r'^\s*(chapter|unit|الفصل|الوحدة)[\s_-]+([0-9٠-٩۰-۹]+)(?=$|[\s_.()—–-])',re.I)


def chapter_file(title):
    """A named chapter file is already partitioned by the instructor.

    Do not reinterpret exercise numbers or review headings as book boundaries.
    Ambiguous chapter ranges still use the whole-book review workflow.
    """
    name=re.sub(r'\.pdf$', '', title.strip(), flags=re.I)
    match=CHAPTER_FILE.match(name)
    if not match:return None
    rest=name[match.end():]
    if re.match(r'\s*(?:[-–—&+,]|and|to|و)\s*[0-9٠-٩۰-۹]',rest,re.I):return None
    number=int(match.group(2))
    if number<1:return None
    label=f'{match.group(1).capitalize()} {number}'
    return {'number':number,'title':label}


def available(db):
    tables=inspect(db.connection())
    return all(tables.has_table(model.__tablename__) for model in LIBRARY_TABLES)


def attachment_exam(db,material_id):
    # A partially installed chapter schema must not expose another quiz's extras.
    if not inspect(db.connection()).has_table(AssessmentMaterialAttachment.__tablename__):return None
    row=db.query(AssessmentMaterialAttachment).filter_by(material_id=material_id).first()
    return row.exam_id if row else None


def inventory(db,version,*,lock=False):
    query=db.query(MaterialPage).filter_by(version_id=version.id).order_by(MaterialPage.page_index)
    pages=query.with_for_update().populate_existing().all() if lock else query.all()
    fingerprint=text_hash(f'{version.document_sha256}:{version.page_count}|'+ '|'.join(f'{p.page_index}:{p.text_sha256}' for p in pages))
    return pages,fingerprint


def propose_chapters(pages,page_count,title):
    named=chapter_file(title)
    if named:
        return [dict(title=named['title'],start_page=1,end_page=page_count,whole_document=True)]
    starts=[];seen=set()
    for page in pages:
        lines=[line.strip() for line in page.text.splitlines() if line.strip()]
        # Multiple chapter labels indicate contents pages; do not treat them as starts.
        labels=[HEADING.match(line) for line in lines]
        if sum(bool(label) for label in labels)>1:continue
        for offset,line in enumerate(lines[:8]):
            split_heading=bool(re.fullmatch(r'chapter|unit|الفصل|الوحدة',line,re.I)) and offset+1<len(lines)
            candidate=f'{line} {lines[offset+1]}' if split_heading else line
            match=HEADING.match(candidate)
            if not match or re.search(r'\.{2,}|\s{2,}\d+\s*$',line):continue
            number=match.group(1).upper()
            if number in seen:break # repeated running header
            seen.add(number)
            name=candidate[:255]
            following_offset=offset+(2 if split_heading else 1)
            if not match.group(2).strip() and following_offset<len(lines):
                following=lines[following_offset]
                if len(following)<120 and not following.isdigit():name=f'{candidate} · {following}'[:255]
            starts.append((page.page_index+1,name));break
    if not starts:return [dict(title=title,start_page=1,end_page=page_count,whole_document=True)]
    return [dict(title=name,start_page=start,end_page=starts[i+1][0]-1 if i+1<len(starts) else page_count,whole_document=False)
            for i,(start,name) in enumerate(starts)]


def chapter_catalog(db,material,version):
    pages,fingerprint=inventory(db,version)
    index=db.query(MaterialChapterIndex).filter_by(version_id=version.id,text_fingerprint=fingerprint).order_by(MaterialChapterIndex.revision_number.desc()).first() if available(db) else None
    chapters=index.chapters if index else propose_chapters(pages,version.page_count,material.title)
    approved=set(version.approved_page_indices or [])
    named=chapter_file(material.title)
    return {'version':public_version(db,version),'text_fingerprint':fingerprint,
            'chapter_file':bool(named) and not bool(index),
            'chapter_number':named['number'] if named else None,
            'boundaries_reviewed':bool(index),'index_available':available(db),
            'chapters':[{**chapter,'key':f'{version.id}:{chapter["start_page"]}-{chapter["end_page"]}',
                'page_indices':list(range(chapter['start_page']-1,chapter['end_page'])),
                'approved':version.status in {'approved','superseded'} and set(range(chapter['start_page']-1,chapter['end_page'])).issubset(approved),
                'selectable':(bool(index) or chapter.get('whole_document',False)) and version.status in {'approved','superseded'} and set(range(chapter['start_page']-1,chapter['end_page'])).issubset(approved)} for chapter in chapters]}


def save_index(db,material,version,request,user):
    db.query(MaterialVersion).filter_by(id=version.id).with_for_update().one()
    db.refresh(version)
    if version.original_file_path:
        from services.course_material_service import document_path
        document_path(version)
    pages,fingerprint=inventory(db,version,lock=True)
    if fingerprint!=request.expected_text_fingerprint:
        raise ValueError('Reference text changed. Reload the chapter proposals before saving.')
    if version.ingestion_status not in {'ready','needs_transcription'} or len(pages)!=version.page_count:
        raise ValueError('Wait for the complete page inventory before reviewing chapters.')
    chapters=sorted([chapter.model_dump() for chapter in request.chapters],key=lambda c:c['start_page'])
    previous=0
    for chapter in chapters:
        if chapter['start_page']<=previous or chapter['end_page']>version.page_count:
            raise ValueError('Chapter ranges must not overlap or exceed the document page count.')
        previous=chapter['end_page']
    revision=db.query(func.max(MaterialChapterIndex.revision_number)).filter_by(version_id=version.id).scalar() or 0
    row=MaterialChapterIndex(version_id=version.id,revision_number=revision+1,chapters=chapters,text_fingerprint=fingerprint,created_by=user.id)
    db.add(row);db.flush()
    return row
