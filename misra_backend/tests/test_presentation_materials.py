import asyncio
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from starlette.datastructures import UploadFile
from services.presentation_material_service import read_slides,PPTX_TYPE
from services.upload_security_service import store_validated_upload,UploadValidationError


def presentation(*,unsafe=False):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types><Override ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/></Types>')
        archive.writestr('ppt/presentation.xml','<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId r:id="second"/><p:sldId r:id="first"/></p:sldIdLst></p:presentation>')
        archive.writestr('ppt/_rels/presentation.xml.rels','<Relationships><Relationship Id="first" Target="slides/slide1.xml"/><Relationship Id="second" Target="slides/slide2.xml"/></Relationships>')
        for index in [1,2]:archive.writestr(f'ppt/slides/slide{index}.xml',f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>Chapter {index}</a:t><a:t>Synthetic teaching text</a:t></p:sld>')
        if unsafe:archive.writestr('../outside.xml','unsafe')
    return stream.getvalue()


class PresentationMaterialTests(unittest.TestCase):
    def test_real_presentation_order_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'slides.pptx';path.write_bytes(presentation())
            self.assertEqual(read_slides(path),['Chapter 2\nSynthetic teaching text','Chapter 1\nSynthetic teaching text'])

    def test_course_opt_in_accepts_pptx_but_student_uploads_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            accepted=asyncio.run(store_validated_upload(UploadFile(filename='slides.pptx',file=io.BytesIO(presentation())),directory,allow_pptx=True))
            self.assertEqual((accepted.page_count,accepted.media_type),(2,PPTX_TYPE))
            with self.assertRaises(UploadValidationError):asyncio.run(store_validated_upload(UploadFile(filename='slides.pptx',file=io.BytesIO(presentation())),directory))
            self.assertEqual(len(list(Path(directory).iterdir())),1)

    def test_unsafe_zip_is_rejected_and_partial_file_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(UploadValidationError):asyncio.run(store_validated_upload(UploadFile(filename='slides.pptx',file=io.BytesIO(presentation(unsafe=True))),directory,allow_pptx=True))
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_arbitrary_zip_is_not_accepted_as_powerpoint(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:archive.writestr('notes.txt','Synthetic notes')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(UploadValidationError):asyncio.run(store_validated_upload(UploadFile(filename='fake.pptx',file=io.BytesIO(stream.getvalue())),directory,allow_pptx=True))
            self.assertEqual(list(Path(directory).iterdir()),[])
