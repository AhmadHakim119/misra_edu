"""Course books, chapter scopes, extra attachments and OCR retry integrity."""
import asyncio
import io
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient, ASGITransport
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from models import CourseMaterial, MaterialVersion, MaterialPage, MaterialChapterIndex, AssessmentMaterialAttachment, Exam, ProcessingJob
from schemas.course_materials import MaterialTextRequest, MaterialApprovalRequest, AssessmentMaterialScopeRequest
from schemas.material_library import ChapterIndexRequest
from routers import course_materials as materials, material_library as api
from services import course_material_service as source, material_library_service as library
from scripts.upgrade_material_library import upgrade
from tests import test_course_materials as fixtures


class MaterialLibraryTests(unittest.TestCase):
    def setUp(self):
        with patch.object(fixtures,'create_engine',side_effect=lambda *_:create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)):
            fixtures.CourseMaterialTests.setUp(self)
        self.db.add(Exam(id='e2',institution_id='i',course_id='c',title='Other quiz'))
        self.db.commit()
    tearDown=fixtures.CourseMaterialTests.tearDown
    material=fixtures.CourseMaterialTests.material

    def book(self,count=10,pages_per_chapter=2,approved=True):
        data=materials.create_text('c',MaterialTextRequest(title='Synthetic course book',text='Chapter 1\nWork and energy'),self.db,self.user)
        version=self.db.get(MaterialVersion,data['versions'][0]['id']);version.page_count=count*pages_per_chapter
        for index in range(version.page_count):
            text=f'Chapter {index//pages_per_chapter+1}\nWork and energy' if index%pages_per_chapter==0 else 'Work equals force times distance.'
            source.replace_page(self.db,version,index,text,origin='native_text_unverified')
        version.content_sha256=source.content_hash(self.db,version);self.db.commit()
        material=self.db.get(CourseMaterial,data['id'])
        if approved:source.approve_material(self.db,version,MaterialApprovalRequest(page_indices=list(range(version.page_count)),confirm_content_reviewed=True),self.user);self.db.commit()
        return material,version

    def checked(self,material,version,chapters=None):
        catalog=library.chapter_catalog(self.db,material,version)
        body=ChapterIndexRequest(chapters=chapters or [{k:c[k] for k in ['title','start_page','end_page']} for c in catalog['chapters']],expected_text_fingerprint=catalog['text_fingerprint'],confirm_boundaries_reviewed=True)
        return api.save_chapters(material.id,version.id,body,self.db,self.user)

    def test_existing_course_files_visible_to_every_assessment_without_reupload(self):
        material,version=self.book()
        for exam in ['e','e2',None]:
            response=api.get_library('c',exam,self.db,self.user)
            self.assertEqual(response['items'][0]['id'],material.id)
            self.assertEqual(len(response['items'][0]['catalogs'][0]['chapters']),10)
        self.assertEqual(self.db.query(CourseMaterial).count(),1)

    def test_500_page_book_has_ten_nonoverlapping_proposed_ranges(self):
        material,version=self.book(pages_per_chapter=50)
        catalog=library.chapter_catalog(self.db,material,version)
        self.assertEqual([(c['start_page'],c['end_page']) for c in catalog['chapters']],[(n*50+1,(n+1)*50) for n in range(10)])
        self.assertFalse(catalog['boundaries_reviewed'])
        self.assertTrue(all(not c['selectable'] for c in catalog['chapters']))

    def test_named_chapter_files_include_every_page_despite_misleading_content(self):
        pages=[SimpleNamespace(page_index=11,text='Chapter 8.\nPICTURE THE PROBLEM'),SimpleNamespace(page_index=28,text='CHAPTER 5 REVIEW')]
        for title,number in [('Chapter_7-Walker_Physics',7),('Chapter_5-Walker_Physics.pdf',5),('Chapter_3-Walker_Physics(1)',3),('الفصل_١٠_الفيزياء',10)]:
            with self.subTest(title=title):
                chapters=library.propose_chapters(pages,41,title)
                self.assertEqual(len(chapters),1)
                self.assertEqual((chapters[0]['start_page'],chapters[0]['end_page']),(1,41))
                self.assertTrue(chapters[0]['whole_document'])
                self.assertEqual(library.chapter_file(title)['number'],number)
                self.assertNotIn('REVIEW',chapters[0]['title'])
        for title in ['Book','Chapters 1 and 2','Chapter 1-10 textbook','Chapter 1 & 2']:
            self.assertIsNone(library.chapter_file(title))

    def test_named_chapter_does_not_approve_sources_or_replace_reviewed_boundaries(self):
        material,version=self.book(count=1,pages_per_chapter=28,approved=False)
        material.title='Chapter_7-Walker_Physics';self.db.commit()
        catalog=library.chapter_catalog(self.db,material,version)
        self.assertTrue(catalog['chapter_file']);self.assertEqual(catalog['chapter_number'],7)
        self.assertEqual(catalog['chapters'][0]['page_indices'],list(range(28)))
        self.assertFalse(catalog['chapters'][0]['selectable']);self.assertEqual(version.approved_page_indices,[])
        source.approve_material(self.db,version,MaterialApprovalRequest(page_indices=list(range(28)),confirm_content_reviewed=True),self.user);self.db.commit()
        self.assertTrue(library.chapter_catalog(self.db,material,version)['chapters'][0]['selectable'])
        self.checked(material,version,[{'title':'Instructor checked range','start_page':2,'end_page':25}])
        catalog=library.chapter_catalog(self.db,material,version)
        self.assertFalse(catalog['chapter_file']);self.assertEqual(catalog['chapters'][0]['title'],'Instructor checked range')
        self.assertEqual(catalog['chapters'][0]['page_indices'],list(range(1,25)))

    def test_contents_and_running_headers_do_not_create_duplicate_chapters(self):
        pages=[SimpleNamespace(page_index=0,text='Contents\nChapter 1 .... 3\nChapter 2 .... 7'),SimpleNamespace(page_index=2,text='Chapter 1\nWork'),SimpleNamespace(page_index=3,text='Chapter 1\nWork continues'),SimpleNamespace(page_index=6,text='Chapter 2\nEnergy')]
        chapters=library.propose_chapters(pages,10,'Book')
        self.assertEqual([(c['start_page'],c['end_page']) for c in chapters],[(3,6),(7,10)])
        arabic=library.propose_chapters([SimpleNamespace(page_index=0,text='الفصل ١\nالحركة'),SimpleNamespace(page_index=3,text='الفصل ٢\nالطاقة')],6,'كتاب')
        self.assertEqual(len(arabic),2)

    def test_chapter_review_preserves_approved_content_and_old_scopes(self):
        material,version=self.book();before=version.content_sha256
        checked=self.checked(material,version)
        self.assertTrue(all(c['selectable'] for c in checked['chapters']))
        body=AssessmentMaterialScopeRequest(mode='required',bindings=[{'version_id':version.id,'page_indices':[0,1,2,3]}])
        from routers.course_materials import create_assessment_scope
        scope=create_assessment_scope('e',body,self.db,self.user)
        self.checked(material,version,[{'title':'Combined chapter','start_page':1,'end_page':20}])
        self.assertEqual(version.content_sha256,before)
        self.assertEqual(scope['bindings'][0]['page_indices'],[0,1,2,3])
        self.assertEqual(self.db.query(MaterialChapterIndex).count(),2)
        self.assertEqual(library.chapter_catalog(self.db,material,version)['chapters'][0]['title'],'Combined chapter')

    def test_bad_and_stale_boundaries_are_rejected_without_source_approval(self):
        material,version=self.book(approved=False);catalog=library.chapter_catalog(self.db,material,version)
        for ranges in [[{'title':'A','start_page':1,'end_page':4},{'title':'B','start_page':4,'end_page':6}],[{'title':'A','start_page':1,'end_page':21}]]:
            request=ChapterIndexRequest(chapters=ranges,expected_text_fingerprint=catalog['text_fingerprint'],confirm_boundaries_reviewed=True)
            with self.assertRaises(HTTPException):api.save_chapters(material.id,version.id,request,self.db,self.user)
        source.replace_page(self.db,version,0,'Corrected chapter heading',origin='instructor_corrected');self.db.commit()
        request=ChapterIndexRequest(chapters=[{'title':'A','start_page':1,'end_page':20}],expected_text_fingerprint=catalog['text_fingerprint'],confirm_boundaries_reviewed=True)
        with self.assertRaises(HTTPException):api.save_chapters(material.id,version.id,request,self.db,self.user)
        self.assertEqual(version.status,'draft');self.assertEqual(version.approved_page_indices,[])

    def test_extra_material_does_not_leak_between_quizzes_or_into_course_library(self):
        data,version=self.material()
        self.db.add(AssessmentMaterialAttachment(material_id=data['id'],exam_id='e'));self.db.commit()
        self.assertEqual(materials.list_materials('c',self.db,self.user),[])
        self.assertEqual(api.get_library('c','e2',self.db,self.user)['items'],[])
        self.assertEqual(api.get_library('c','e',self.db,self.user)['items'][0]['scope'],'assessment')
        request=AssessmentMaterialScopeRequest(bindings=[{'version_id':version.id,'page_indices':[0]}])
        with self.assertRaisesRegex(ValueError,'another assessment'):source.validate_exam_bindings(self.db,self.db.get(Exam,'e2'),request)
        source.validate_exam_bindings(self.db,self.db.get(Exam,'e'),request)
        from services.source_question_draft_service import source_package
        from schemas.source_question_drafts import SourceQuestionDraftRequest
        draft=SourceQuestionDraftRequest(bindings=[{'version_id':version.id,'page_indices':[0]}],topic='Work against gravity')
        with self.assertRaisesRegex(ValueError,'another assessment'):source_package(self.db,self.db.get(Exam,'e2'),draft)
        MaterialChapterIndex.__table__.drop(self.engine)
        self.assertEqual(api.get_library('c','e2',self.db,self.user)['items'],[])
        with self.assertRaisesRegex(ValueError,'another assessment'):source.validate_exam_bindings(self.db,self.db.get(Exam,'e2'),request)

    def test_foreign_library_and_chapter_index_are_not_disclosed(self):
        material,version=self.book()
        with self.assertRaises(HTTPException):api.get_library('c',None,self.db,self.other)
        with self.assertRaises(HTTPException):api.chapters(material.id,version.id,self.db,self.other)

    def test_approved_book_cannot_be_sent_for_scan_reading(self):
        material,version=self.book()
        version.media_type='application/pdf';self.db.commit()
        with patch.object(api,'dispatch_processing_job') as dispatch:
            with self.assertRaises(HTTPException):api.read_scanned_pages(material.id,version.id,self.db,self.user)
            dispatch.assert_not_called()

    def test_ocr_resumes_saved_pages_after_failure_and_never_autoapproves(self):
        stream=io.BytesIO();writer=PdfWriter()
        for _ in range(2):writer.add_blank_page(width=100,height=100)
        writer.write(stream);stream.seek(0)
        from starlette.datastructures import UploadFile
        with patch.object(materials,'dispatch_processing_job'):
            data=asyncio.run(materials.upload_material('c',UploadFile(filename='scan.pdf',file=stream),'Scanned book',self.db,self.user,ocr_scans=True))
        version=self.db.get(MaterialVersion,data['versions'][0]['id']);job=self.db.get(ProcessingJob,version.processing_job_id)
        with patch('services.material_ocr_service.read_page',side_effect=['Chapter 1\nWork',RuntimeError('Synthetic provider interruption')]) as read:
            with self.assertRaises(RuntimeError):source.ingest_material_job(job,self.db,lambda *_:self.db.commit())
        self.db.rollback()
        self.assertEqual(self.db.query(MaterialPage).filter_by(version_id=version.id).count(),1)
        with patch('services.material_ocr_service.read_page',return_value='Chapter 2\nEnergy') as read:
            source.ingest_material_job(job,self.db,lambda *_:self.db.commit());self.db.commit()
            self.assertEqual(read.call_count,1);self.assertEqual(read.call_args.args[1],1)
        self.assertEqual(version.status,'draft');self.assertEqual(version.approved_page_indices,[])
        self.assertEqual(version.ingestion_status,'ready')
        self.assertEqual(len(library.chapter_catalog(self.db,self.db.get(CourseMaterial,data['id']),version)['chapters']),2)

    def test_additive_upgrade_is_idempotent_and_existing_books_remain_visible(self):
        material,version=self.book()
        for model in reversed(library.LIBRARY_TABLES):model.__table__.drop(self.engine)
        self.assertFalse(library.available(self.db))
        self.assertEqual(api.get_library('c',None,self.db,self.user)['items'][0]['id'],material.id)
        upgrade(self.engine);upgrade(self.engine)
        self.assertTrue(library.available(self.db));self.assertEqual(self.db.query(CourseMaterial).count(),1)

    def test_http_extra_upload_and_library_contract(self):
        from database import get_db
        from services.auth_dependencies import require_instructor
        app=FastAPI();app.include_router(api.router)
        app.dependency_overrides[get_db]=lambda:self.db;app.dependency_overrides[require_instructor]=lambda:self.user
        stream=io.BytesIO();writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(stream)
        async def exercise():
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                with patch.object(materials,'dispatch_processing_job'):
                    response=await client.post('/api/exams/e/materials',files={'file':('slides.pdf',stream.getvalue(),'application/pdf')},data={'title':'Quiz slides','ocr_scans':'true'})
                self.assertEqual(response.status_code,202,response.text)
                version=self.db.get(MaterialVersion,response.json()['versions'][0]['id'])
                self.assertIs(self.db.get(ProcessingJob,version.processing_job_id).payload['ocr_scans'],True)
                response=await client.get('/api/courses/c/library?exam_id=e');self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['items'][0]['scope'],'assessment')
                self.assertEqual((await client.get('/api/courses/c/library?exam_id=e2')).json()['items'],[])
        asyncio.run(exercise())

    def test_extra_pptx_ingestion_keeps_slides_as_unapproved_source_pages(self):
        from tests.test_presentation_materials import presentation
        from starlette.datastructures import UploadFile
        with patch.object(materials,'dispatch_processing_job'):
            data=asyncio.run(api.upload_extra('e',UploadFile(filename='Quiz1.pptx',file=io.BytesIO(presentation())),'Quiz 1 slides',False,self.db,self.user))
        version=self.db.get(MaterialVersion,data['versions'][0]['id']);job=self.db.get(ProcessingJob,version.processing_job_id)
        with patch('services.material_ocr_service.read_page') as read:
            source.ingest_material_job(job,self.db,lambda *_:None);self.db.commit();read.assert_not_called()
        pages=self.db.query(MaterialPage).filter_by(version_id=version.id).order_by(MaterialPage.page_index).all()
        self.assertEqual(len(pages),2);self.assertTrue(pages[0].text.startswith('Chapter 2'))
        self.assertEqual(version.status,'draft');self.assertEqual(version.approved_page_indices,[])
        self.assertEqual(api.get_library('c','e2',self.db,self.user)['items'],[])


if __name__=='__main__':unittest.main()
