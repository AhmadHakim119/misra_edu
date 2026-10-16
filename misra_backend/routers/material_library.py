from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile
from sqlalchemy.orm import Session
from database import get_db
from models import CourseMaterial, MaterialVersion, ProcessingJob
from services.auth_dependencies import require_instructor
from services import material_library_service as library
from services.job_queue_service import dispatch_processing_job, ACTIVE_JOB_STATUSES, job_to_dict
from schemas.material_library import ChapterIndexRequest
from routers.course_materials import owned_course, owned_exam, owned_material, owned_version, public_material, finish, store_pdf, ready

router=APIRouter(prefix='/api',tags=['material-library'])


def metadata_ready(db):
    if not library.available(db):
        raise HTTPException(503,'Chapter metadata needs the additive upgrade: back up the database, then run scripts/upgrade_material_library.py. Existing course files are already saved.')


@router.get('/courses/{course_id}/library')
def get_library(course_id:str,exam_id:str|None=None,db:Session=Depends(get_db),user=Depends(require_instructor)):
    owned_course(db,user,course_id);ready(db)
    if exam_id and owned_exam(db,user,exam_id).course_id!=course_id:
        raise HTTPException(404,'Assessment not found in this course')
    items=[]
    for material in db.query(CourseMaterial).filter_by(course_id=course_id,institution_id=user.institution_id).order_by(CourseMaterial.created_at.desc()).limit(200).all():
        attached=library.attachment_exam(db,material.id)
        if attached and attached!=exam_id:continue
        public=public_material(db,material)
        candidates=db.query(MaterialVersion).filter_by(material_id=material.id).order_by(MaterialVersion.version_number.desc()).all()
        latest={}
        for version in candidates:
            if version.status in {'approved','draft'} and version.status not in latest:latest[version.status]=version
        public.update(scope='assessment' if attached else 'course',exam_id=attached,
                      catalogs=[library.chapter_catalog(db,material,v) for v in latest.values()])
        items.append(public)
    return {'course_id':course_id,'exam_id':exam_id,'metadata_available':library.available(db),'items':items}


@router.get('/materials/{material_id}/versions/{version_id}/chapters')
def chapters(material_id:str,version_id:str,db:Session=Depends(get_db),user=Depends(require_instructor)):
    material=owned_material(db,user,material_id);version=owned_version(db,material,version_id)
    return library.chapter_catalog(db,material,version)


@router.post('/materials/{material_id}/versions/{version_id}/chapters',status_code=201)
def save_chapters(material_id:str,version_id:str,payload:ChapterIndexRequest,db:Session=Depends(get_db),user=Depends(require_instructor)):
    material=owned_material(db,user,material_id);version=owned_version(db,material,version_id);metadata_ready(db)
    try:library.save_index(db,material,version,payload,user)
    except ValueError as error:
        db.rollback();raise HTTPException(409,str(error)) from error
    finish(db,user,material,'material_chapters_reviewed')
    return library.chapter_catalog(db,material,version)


@router.post('/exams/{exam_id}/materials',status_code=202)
async def upload_extra(exam_id:str,file:UploadFile=File(...),title:str|None=Form(None),ocr_scans:bool=Form(False),db:Session=Depends(get_db),user=Depends(require_instructor)):
    try:
        exam=owned_exam(db,user,exam_id);metadata_ready(db)
        course=owned_course(db,user,exam.course_id,lock=True)
        return await store_pdf(db,user,course,file,title,attachment_exam_id=exam.id,ocr_scans=ocr_scans is True)
    finally:await file.close()


@router.post('/materials/{material_id}/versions/{version_id}/read-scanned-pages',status_code=202)
def read_scanned_pages(material_id:str,version_id:str,db:Session=Depends(get_db),user=Depends(require_instructor)):
    material=owned_material(db,user,material_id);version=owned_version(db,material,version_id)
    db.query(MaterialVersion).filter_by(id=version.id).with_for_update().one();db.refresh(version)
    current=db.get(ProcessingJob,version.processing_job_id) if version.processing_job_id else None
    if current and current.status in ACTIVE_JOB_STATUSES:return job_to_dict(current)
    if version.status!='draft' or version.media_type!='application/pdf':
        raise HTTPException(409,'Only a draft PDF can be read again. Approved source content is immutable.')
    job=ProcessingJob(institution_id=user.institution_id,requested_by=user.id,job_type='material_ingestion',status='queued',max_attempts=3,
        progress_total=version.page_count,progress_message='Waiting to read scanned source pages',
        payload={'material_version_id':version.id,'material_id':material.id,'course_id':material.course_id,'ocr_scans':True})
    db.add(job);db.flush();version.processing_job_id=job.id;version.ingestion_status='queued'
    finish(db,user,material,'material_scan_reading_requested');dispatch_processing_job(job,db)
    return job_to_dict(job)
