import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers, UploadFile


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

from database import Base  # noqa: E402
import models  # noqa: E402,F401
from models import Course, Exam, Institution, Question, RubricVersion, Submission, User  # noqa: E402
from routers.exams import upload_exam, upload_batch  # noqa: E402
from services.ocr_service import create_submissions_from_stored_upload  # noqa: E402
from services.upload_security_service import (  # noqa: E402
    StoredUpload,
    UploadLimits,
    UploadValidationError,
    remove_stored_uploads,
    store_validated_batch,
    store_validated_upload,
)


def _image_bytes(image_format: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (24, 16), "white").save(output, format=image_format)
    return output.getvalue()


def _pdf_bytes(page_count: int = 1) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    writer.write(output)
    return output.getvalue()


def _upload(filename: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


class UploadSecurityServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.upload_dir = Path(self.temp.name)
        self.limits = UploadLimits(
            max_upload_bytes=1024 * 1024,
            max_batch_bytes=2 * 1024 * 1024,
            max_batch_files=5,
            max_pdf_pages=5,
            max_image_pixels=1_000_000,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _store(self, upload: UploadFile, limits: UploadLimits | None = None):
        return asyncio.run(
            store_validated_upload(upload, self.upload_dir, limits=limits or self.limits)
        )

    def test_valid_pdf_png_and_jpeg_are_detected_and_safely_named(self):
        fixtures = [
            ("paper.pdf", _pdf_bytes(), "application/pdf", ".pdf", 1),
            ("page.png", _image_bytes("PNG"), "image/png", ".png", 1),
            ("photo.jpeg", _image_bytes("JPEG"), "image/jpeg", ".jpg", 1),
        ]
        stored = []
        try:
            for filename, content, media_type, extension, page_count in fixtures:
                item = self._store(_upload(filename, content, media_type))
                stored.append(item)
                self.assertEqual(item.extension, extension)
                self.assertEqual(item.page_count, page_count)
                self.assertNotEqual(item.path.name, filename)
                self.assertEqual(item.path.suffix, extension)
                self.assertTrue(item.path.exists())
        finally:
            remove_stored_uploads(stored)

    def test_fake_pdf_with_png_contents_is_rejected_and_cleaned(self):
        with self.assertRaises(UploadValidationError) as context:
            self._store(_upload("spoofed.pdf", _image_bytes("PNG"), "application/pdf"))

        self.assertEqual(context.exception.status_code, 415)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_corrupt_pdf_and_image_are_rejected(self):
        fixtures = [
            _upload("broken.pdf", b"%PDF-1.7\nthis is not a PDF", "application/pdf"),
            _upload("broken.png", b"\x89PNG\r\n\x1a\nnot-an-image", "image/png"),
        ]
        for upload in fixtures:
            with self.subTest(upload=upload.filename):
                with self.assertRaises(UploadValidationError) as context:
                    self._store(upload)
                self.assertEqual(context.exception.status_code, 422)
                self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_oversized_upload_is_rejected_before_full_write(self):
        limits = UploadLimits(
            max_upload_bytes=64,
            max_batch_bytes=1024,
            max_batch_files=5,
            max_pdf_pages=5,
            max_image_pixels=1_000_000,
        )
        with self.assertRaises(UploadValidationError) as context:
            self._store(_upload("large.png", _image_bytes("PNG"), "image/png"), limits)

        self.assertEqual(context.exception.status_code, 413)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_excessive_pdf_page_count_is_rejected(self):
        limits = UploadLimits(
            max_upload_bytes=1024 * 1024,
            max_batch_bytes=2 * 1024 * 1024,
            max_batch_files=5,
            max_pdf_pages=1,
            max_image_pixels=1_000_000,
        )
        with self.assertRaises(UploadValidationError) as context:
            self._store(_upload("two-pages.pdf", _pdf_bytes(2), "application/pdf"), limits)

        self.assertEqual(context.exception.status_code, 413)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_oversized_batch_removes_every_file_from_request(self):
        first = _image_bytes("PNG")
        second = _image_bytes("PNG")
        env = {
            "MAX_UPLOAD_BYTES": "1048576",
            "MAX_BATCH_BYTES": str(len(first) + len(second) - 1),
            "MAX_BATCH_FILES": "5",
            "MAX_PDF_PAGES": "5",
            "MAX_IMAGE_PIXELS": "1000000",
        }
        with patch.dict(os.environ, env):
            with self.assertRaises(UploadValidationError) as context:
                asyncio.run(
                    store_validated_batch(
                        [
                            _upload("one.png", first, "image/png"),
                            _upload("two.png", second, "image/png"),
                        ],
                        self.upload_dir,
                    )
                )

        self.assertEqual(context.exception.status_code, 413)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_batch_file_count_limit_is_enforced_before_writing(self):
        content = _image_bytes("PNG")
        env = {
            "MAX_UPLOAD_BYTES": "1048576",
            "MAX_BATCH_BYTES": "2097152",
            "MAX_BATCH_FILES": "1",
            "MAX_PDF_PAGES": "5",
            "MAX_IMAGE_PIXELS": "1000000",
        }
        with patch.dict(os.environ, env):
            with self.assertRaises(UploadValidationError) as context:
                asyncio.run(
                    store_validated_batch(
                        [
                            _upload("one.png", content, "image/png"),
                            _upload("two.png", content, "image/png"),
                        ],
                        self.upload_dir,
                    )
                )

        self.assertEqual(context.exception.status_code, 413)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_valid_pdf_batch_is_split_by_page_range_without_loading_source_bytes(self):
        source_path = self.upload_dir / "validated.pdf"
        source_path.write_bytes(_pdf_bytes(3))
        stored = StoredUpload(
            path=source_path,
            original_filename="batch.pdf",
            media_type="application/pdf",
            extension=".pdf",
            size_bytes=source_path.stat().st_size,
            page_count=3,
        )
        db = MagicMock()
        rendered_pages = [
            [Image.new("RGB", (20, 20)), Image.new("RGB", (20, 20))],
            [Image.new("RGB", (20, 20))],
        ]

        with patch("services.ocr_service.convert_from_path", side_effect=rendered_pages) as convert:
            submissions, generated_paths, source_retained = create_submissions_from_stored_upload(
                exam_id="exam-1",
                institution_id="institution-1",
                batch_id="batch-1",
                stored_upload=stored,
                pages_per_student=2,
                db=db,
            )

        self.assertFalse(source_retained)
        self.assertEqual([submission.page_count for submission in submissions], [2, 1])
        self.assertEqual(len(generated_paths), 2)
        self.assertTrue(all(Path(path).exists() for path in generated_paths))
        self.assertEqual(
            convert.call_args_list,
            [
                call(str(source_path), first_page=1, last_page=2),
                call(str(source_path), first_page=3, last_page=3),
            ],
        )
        for path in generated_paths:
            Path(path).unlink(missing_ok=True)


class UploadRouteTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        institution = Institution(id="institution-1", name="Test University")
        self.teacher = User(
            id="teacher-1",
            institution_id=institution.id,
            email="teacher@example.edu",
            hashed_password="unused",
            role="teacher",
        )
        course = Course(
            id="course-1",
            institution_id=institution.id,
            teacher_id=self.teacher.id,
            course_code="CS101",
            title="Testing",
        )
        exam = Exam(
            id="exam-1",
            institution_id=institution.id,
            course_id=course.id,
            title="Secure Upload Test",
            language="en",
        )
        self.db.add_all([institution, self.teacher, course, exam])
        question = Question(id='upload-question', institution_id=institution.id, exam_id=exam.id,
            question_number='1', question_text='Test', max_score=1, rubric_json={}, order_index=1)
        version = RubricVersion(id='upload-rubric', question_id=question.id, version_number=1,
            schema_version=2, rubric_json={'max_score': 1, 'criteria': [
                {'id': 'answer', 'description': 'Correct answer', 'points': 1}]},
            grading_approach='balanced', source='manual', status='approved')
        self.db.add_all([question, version])
        self.db.flush()
        question.active_rubric_version_id = version.id
        self.db.commit()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_valid_upload_creates_submission_and_queues_ocr(self):
        with (
            patch("routers.exams.UPLOAD_DIR", self.temp.name),
            patch("routers.exams.create_processing_job") as create_job,
            patch("routers.exams.job_to_dict", return_value={"id": "job-1", "status": "queued"}),
        ):
            queued_job = MagicMock(id="job-1")
            create_job.return_value = (queued_job, True)
            response = asyncio.run(
                upload_exam(
                    exam_id="exam-1",
                    file=_upload("paper.png", _image_bytes("PNG"), "image/png"),
                    db=self.db,
                    user=self.teacher,
                )
            )

        # Encode before accessing ORM attributes: touching the record first hid
        # the expired-attribute bug seen by real HTTP clients.
        encoded = jsonable_encoder(response)
        submission = self.db.query(Submission).one()
        self.assertEqual(encoded['submission']['id'], submission.id)
        self.assertEqual(encoded['submission']['exam_id'], 'exam-1')
        self.assertEqual(encoded['submission']['page_count'], 1)
        self.assertNotIn('original_file_path', encoded['submission'])
        self.assertNotIn('institution_id', encoded['submission'])
        self.assertEqual(self.db.query(Submission).count(), 1)
        self.assertEqual(submission.page_count, 1)
        self.assertTrue(Path(submission.original_file_path).exists())
        self.assertEqual(response["job"]["id"], "job-1")
        create_job.assert_called_once()
        self.assertEqual(create_job.call_args.kwargs["submission_id"], submission.id)
        Path(submission.original_file_path).unlink(missing_ok=True)

    def test_database_failure_removes_validated_upload(self):
        with (
            patch("routers.exams.UPLOAD_DIR", self.temp.name),
            patch.object(self.db, "commit", side_effect=RuntimeError("database unavailable")),
        ):
            with self.assertRaises(RuntimeError):
                asyncio.run(
                    upload_exam(
                        exam_id="exam-1",
                        file=_upload("paper.png", _image_bytes("PNG"), "image/png"),
                        db=self.db,
                        user=self.teacher,
                    )
                )

        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_55_page_combined_batch_splits_into_five_11_page_papers(self):
        with (
            patch.dict(os.environ, {'MAX_PDF_PAGES':'50', 'MAX_BATCH_PDF_PAGES':'250'}),
            patch('routers.exams.UPLOAD_DIR', self.temp.name),
            patch('routers.exams.create_processing_job', return_value=(MagicMock(id='batch-job'), True)) as queue,
            patch('routers.exams.job_to_dict', return_value={'id':'batch-job', 'status':'queued'}),
            patch('services.ocr_service.convert_from_path', side_effect=lambda *args, **kwargs:
                [Image.new('RGB', (20, 20), 'white') for _ in range(kwargs['last_page']-kwargs['first_page']+1)]) as render,
        ):
            result = asyncio.run(upload_batch(exam_id='exam-1',
                files=[_upload('combined.pdf', _pdf_bytes(55), 'application/pdf')],
                pages_per_student=11, db=self.db, user=self.teacher))
        papers = self.db.query(Submission).all()
        self.assertEqual(result['total_submissions'], 5)
        self.assertEqual([paper.page_count for paper in papers], [11]*5)
        self.assertEqual(render.call_count, 5)
        self.assertEqual([(call.kwargs['first_page'],call.kwargs['last_page']) for call in render.call_args_list],
            [(1,11),(12,22),(23,33),(34,44),(45,55)])
        self.assertTrue(all(Path(paper.original_file_path).is_file() for paper in papers))
        self.assertEqual(len(list(Path(self.temp.name).iterdir())), 5)
        queue.assert_called_once()

    def test_split_batch_cap_and_per_student_cap_still_reject_before_queuing(self):
        with patch.dict(os.environ, {'MAX_PDF_PAGES':'50','MAX_BATCH_PDF_PAGES':'60'}), \
                patch('routers.exams.UPLOAD_DIR', self.temp.name), \
                patch('routers.exams.create_processing_job') as queue:
            for pages, per_student in [(61, 11), (55, 51), (55, None)]:
                with self.subTest(pages=pages,per_student=per_student), self.assertRaises(HTTPException) as error:
                    asyncio.run(upload_batch(exam_id='exam-1',
                        files=[_upload('combined.pdf',_pdf_bytes(pages),'application/pdf')],
                        pages_per_student=per_student,db=self.db,user=self.teacher))
                self.assertEqual(error.exception.status_code,413)
                self.assertEqual(list(Path(self.temp.name).iterdir()),[])
                self.assertEqual(self.db.query(Submission).count(),0)
            queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
