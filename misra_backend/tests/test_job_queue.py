import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
os.environ.setdefault("DB_URL", "sqlite://")

from database import Base  # noqa: E402
from models import (  # noqa: E402
    Answer,
    AnswerSource,
    Batch,
    Course,
    Exam,
    GradingRun,
    Institution,
    ProcessingJob,
    Question,
    Submission,
    User,
)
from routers.jobs import _owned_job, list_workspace_jobs, stop_job  # noqa: E402
from services.job_execution_service import _grade_submission, execute_processing_job  # noqa: E402
from services.job_queue_service import dispatch_processing_job, retry_processing_job  # noqa: E402
from services.job_recovery_service import recover_orphaned_jobs  # noqa: E402
from services.ocr_service import _clear_incomplete_extraction  # noqa: E402
from services.grading_errors import GradingResponseValidationError


class ProcessingJobTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.institution = Institution(id="institution-1", name="Queue University")
        self.other_institution = Institution(id="institution-2", name="Other University")
        self.user = User(
            id="teacher-1",
            institution_id=self.institution.id,
            email="teacher@example.edu",
            hashed_password="unused",
            role="teacher",
        )
        self.other_user = User(
            id="teacher-2",
            institution_id=self.other_institution.id,
            email="other@example.edu",
            hashed_password="unused",
            role="teacher",
        )
        self.colleague = User(
            id="teacher-3",
            institution_id=self.institution.id,
            email="colleague@example.edu",
            hashed_password="unused",
            role="teacher",
        )
        self.course = Course(
            id="course-1",
            institution_id=self.institution.id,
            teacher_id=self.user.id,
            course_code="CS101",
            title="Queues",
        )
        self.exam = Exam(
            id="exam-1",
            institution_id=self.institution.id,
            course_id=self.course.id,
            title="Queue Test",
            language="en",
        )
        self.submission = Submission(
            id="submission-1",
            institution_id=self.institution.id,
            exam_id=self.exam.id,
            original_file_path="unused.pdf",
            page_count=2,
            status="uploaded",
        )
        self.db.add_all(
            [
                self.institution,
                self.other_institution,
                self.user,
                self.other_user,
                self.colleague,
                self.course,
                self.exam,
                self.submission,
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _job(self, **overrides):
        values = {
            "id": "job-1",
            "institution_id": self.institution.id,
            "requested_by": self.user.id,
            "submission_id": self.submission.id,
            "job_type": "ocr_submission",
            "status": "queued",
            "progress_total": 2,
            "max_attempts": 2,
            "payload": {},
        }
        values.update(overrides)
        job = ProcessingJob(**values)
        self.db.add(job)
        self.db.commit()
        return job

    def test_job_status_is_tenant_scoped(self):
        job = self._job()
        self.assertEqual(_owned_job(job.id, self.db, self.user).id, job.id)
        self.assertIsNone(_owned_job(job.id, self.db, self.other_user))

    def test_workspace_jobs_persist_with_assessment_context(self):
        own_job = self._job()
        self.db.add(ProcessingJob(
            id="colleague-job",
            institution_id=self.institution.id,
            requested_by=self.colleague.id,
            submission_id=self.submission.id,
            job_type="ocr_submission",
            status="processing",
            progress_total=2,
            payload={},
        ))
        self.db.commit()

        response = list_workspace_jobs(limit=8, db=self.db, user=self.user)

        self.assertEqual(response["active_count"], 1)
        self.assertEqual([item["id"] for item in response["items"]], [own_job.id])
        self.assertEqual(response["items"][0]["exam_id"], self.exam.id)
        self.assertEqual(response["items"][0]["exam_title"], self.exam.title)
        self.assertEqual(response["items"][0]["course_code"], self.course.course_code)

    def test_workspace_jobs_keeps_recent_completion_visible(self):
        completed = self._job(
            status="completed",
            completed_at=datetime.now(),
            progress_current=2,
        )

        response = list_workspace_jobs(limit=8, db=self.db, user=self.user)

        self.assertEqual(response["active_count"], 0)
        self.assertEqual(response["items"][0]["id"], completed.id)
        self.assertEqual(response["items"][0]["status"], "completed")

    def test_workspace_batch_job_reports_paper_level_failures(self):
        batch = Batch(
            id="batch-1",
            institution_id=self.institution.id,
            exam_id=self.exam.id,
            total_count=11,
            completed_count=0,
            failed_count=11,
            status="completed_with_errors",
        )
        self.db.add(batch)
        self.db.commit()
        self._job(
            submission_id=None,
            batch_id=batch.id,
            job_type="ocr_batch",
            status="completed",
            completed_at=datetime.now(),
            progress_current=11,
            progress_total=11,
        )

        response = list_workspace_jobs(limit=8, db=self.db, user=self.user)

        item = response["items"][0]
        self.assertEqual(item["batch_status"], "completed_with_errors")
        self.assertEqual(item["batch_completed_count"], 0)
        self.assertEqual(item["batch_failed_count"], 11)
        self.assertEqual(item["batch_total_count"], 11)

    def test_worker_persists_progress_and_completion(self):
        job = self._job()

        def fake_ocr(submission_id, db, progress_callback=None, processing_job_id=None):
            self.assertEqual(submission_id, self.submission.id)
            progress_callback(1, 2, "Extracted page 1 of 2")
            progress_callback(2, 2, "Extracted page 2 of 2")

        with (
            patch("services.job_execution_service.SessionLocal", self.Session),
            patch("services.job_execution_service.process_submission", side_effect=fake_ocr),
        ):
            execute_processing_job(job.id)

        self.db.expire_all()
        saved = self.db.get(ProcessingJob, job.id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.progress_current, 2)
        self.assertEqual(saved.attempt_count, 1)

    def test_invalid_grading_response_stops_automatic_retries_but_allows_manual_retry(self):
        job = self._job(job_type='grade_submission', max_attempts=3,
                        payload={'completed_answer_ids': ['already-completed']})
        self.submission.status = 'grading'
        self.db.commit()
        with patch('services.job_execution_service.SessionLocal', self.Session), \
             patch('services.job_execution_service._grade_submission', side_effect=GradingResponseValidationError(
                 'missing_traceable_evidence', 'Missing tracked evidence after correction.', 1)) as grade:
            with self.assertRaises(GradingResponseValidationError):
                execute_processing_job(job.id)
            execute_processing_job(job.id)  # Stale RQ delivery must not invoke a model again.
            self.assertEqual(grade.call_count, 1)
        self.db.expire_all()
        saved = self.db.get(ProcessingJob, job.id)
        self.assertEqual(saved.status, 'failed')
        self.assertEqual(saved.attempt_count, 1)
        self.assertEqual(saved.payload['completed_answer_ids'], ['already-completed'])
        self.assertIn('Missing tracked evidence', saved.error_message)
        self.assertEqual(self.db.get(Submission, self.submission.id).status, 'extracted')
        from services.job_queue_service import retry_processing_job
        with patch('services.job_queue_service.dispatch_processing_job', side_effect=lambda job, db: job):
            retry_processing_job(saved, self.db)
        with patch('services.job_execution_service.SessionLocal', self.Session), \
             patch('services.job_execution_service._grade_submission') as grade:
            execute_processing_job(job.id)
            grade.assert_called_once()
        self.db.expire_all()
        self.assertEqual(self.db.get(ProcessingJob, job.id).status, 'completed')

    def test_worker_passes_explicit_reprocess_intent_to_ocr(self):
        job = self._job()
        job.payload = {"reprocess": True}
        self.db.commit()
        with (
            patch("services.job_execution_service.SessionLocal", self.Session),
            patch("services.job_execution_service.process_submission") as process,
        ):
            execute_processing_job(job.id)
        self.assertEqual(process.call_args.kwargs["reprocess"], True)

    def test_worker_marks_retrying_then_failed_at_limit(self):
        job = self._job()
        with (
            patch("services.job_execution_service.SessionLocal", self.Session),
            patch(
                "services.job_execution_service.process_submission",
                side_effect=RuntimeError("OCR provider unavailable"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                execute_processing_job(job.id)
            self.db.expire_all()
            self.assertEqual(self.db.get(ProcessingJob, job.id).status, "retrying")
            with self.assertRaises(RuntimeError):
                execute_processing_job(job.id)

        self.db.expire_all()
        saved = self.db.get(ProcessingJob, job.id)
        self.assertEqual(saved.status, "failed")
        self.assertIn("OCR provider unavailable", saved.error_message)

    def test_dispatch_uses_an_rq_safe_job_id(self):
        job = self._job()

        class QueuedJob:
            id = "accepted-job-id"

        with patch("services.job_queue_service.queue_for") as queue_for:
            queue_for.return_value.enqueue.return_value = QueuedJob()
            dispatch_processing_job(job, self.db)

        rq_job_id = queue_for.return_value.enqueue.call_args.kwargs["job_id"]
        self.assertRegex(rq_job_id, r"^[A-Za-z0-9_-]+$")
        self.assertNotIn(":", rq_job_id)
        self.db.refresh(job)
        self.assertEqual(job.rq_job_id, rq_job_id)
        self.assertEqual(job.status, "queued")

    def test_retry_rejects_a_second_job_on_the_same_paper(self):
        old = self._job(job_type='grade_submission', status='failed')
        self._job(id='active', job_type='grade_submission', status='processing')
        with patch('services.job_queue_service.dispatch_processing_job') as dispatch:
            with self.assertRaisesRegex(ValueError, 'already active'):
                retry_processing_job(old, self.db)
        dispatch.assert_not_called()

    def test_same_second_grading_jobs_cannot_retry_an_ambiguous_old_attempt(self):
        now = datetime.now().replace(microsecond=0)
        old = self._job(job_type='grade_submission', status='failed', created_at=now)
        self._job(id='other-attempt', job_type='grade_submission', status='failed', created_at=now)
        with self.assertRaisesRegex(ValueError, 'same time or later'):
            retry_processing_job(old, self.db)

    def test_stopped_queued_job_cannot_grade_stale_delivery(self):
        from fastapi import HTTPException
        job = self._job(job_type='grade_submission')
        with self.assertRaises(HTTPException) as error:
            stop_job(job.id, self.db, self.colleague)
        self.assertEqual(error.exception.status_code, 404)
        result = stop_job(job.id, self.db, self.user)
        self.assertEqual(result['status'], 'stopped')
        with patch('services.job_execution_service.SessionLocal', self.Session), \
                patch('services.job_execution_service._grade_submission') as grade:
            execute_processing_job(job.id)
        grade.assert_not_called()

    def test_running_job_stops_at_checkpoint_without_retries(self):
        from services.grading_control import check_grading_active
        job = self._job(job_type='grade_submission', payload={'completed_answer_ids': ['saved']})

        def interrupt(job, db):
            with self.Session() as api:
                result = stop_job(job.id, api, self.user)
                self.assertEqual(result['status'], 'stopping')
            check_grading_active(lock=True)
            self.fail('Stopped work continued after the checkpoint')

        with patch('services.job_execution_service.SessionLocal', self.Session), \
                patch('services.job_execution_service._grade_submission', side_effect=interrupt) as grade:
            execute_processing_job(job.id)
            execute_processing_job(job.id)
        grade.assert_called_once()
        self.db.refresh(job)
        self.assertEqual(job.payload['completed_answer_ids'], ['saved'])
        self.assertEqual(job.progress_message, 'Grading stopped')

    def test_superseded_worker_cannot_complete_or_fail_replacement(self):
        from services.grading_control import check_grading_active
        job = self._job(job_type='grade_submission', rq_job_id='old-dispatch')

        def orphaned(job, db):
            with self.Session() as api:
                replacement = api.get(ProcessingJob, job.id)
                replacement.rq_job_id = 'new-dispatch'
                replacement.status = 'queued'
                api.commit()
            check_grading_active(lock=True)
            self.fail('A superseded attempt kept running')

        with patch('services.job_execution_service.SessionLocal', self.Session), \
                patch('services.job_execution_service._grade_submission', side_effect=orphaned):
            execute_processing_job(job.id)
        self.db.refresh(job)
        self.assertEqual((job.status, job.rq_job_id), ('queued', 'new-dispatch'))

    def test_restart_keeps_a_primary_grade_saved_before_its_progress_checkpoint(self):
        question = Question(id='q-checkpoint', exam_id=self.exam.id, institution_id=self.institution.id,
                            question_number='1', max_score=1, order_index=1, rubric_json={'criteria': []})
        self.db.add(question)
        answer = Answer(id='a-checkpoint', question_id=question.id, submission_id=self.submission.id,
                        institution_id=self.institution.id, score=1, max_score=1, teacher_override_score=.75)
        self.db.add(answer)
        self.db.commit()
        job = self._job(job_type='grade_submission', payload={'mode':'auto','completed_answer_ids':[]})
        primary = GradingRun(id='primary-run', answer_id=answer.id, processing_job_id=job.id,
                             mode='text_only', model_name='synthetic', prompt_version='synthetic',
                             ocr_text_snapshot='synthetic', rubric_snapshot={}, score=1, max_score=1,
                             feedback='', reasoning='', criteria_scores=[], llm_confidence=90,
                             final_confidence=85, needs_review=True,
                             response_json={'grading_package': {'routing': {'comparison_pair_id': 'pair', 'image_audit_pending': True}}})
        self.db.add(primary)
        self.db.commit()
        with patch('services.job_execution_service.process_grading_with_policy') as grade:
            _grade_submission(job, self.db)
        grade.assert_not_called()
        self.assertEqual(job.payload['completed_answer_ids'], [answer.id])
        self.assertEqual(job.payload['incomplete_comparison_count'], 1)
        self.assertEqual(self.db.get(Submission, self.submission.id).status, 'needs_review')
        self.assertIsNotNone(self.db.get(GradingRun, primary.id))
        self.assertEqual(float(self.db.get(Answer, answer.id).teacher_override_score), .75)

    def test_orphan_recovery_requeues_missing_redis_job_once(self):
        job = self._job(
            status="processing",
            attempt_count=1,
            rq_job_id="missing-rq-job",
        )
        now = datetime.now()
        old = now - timedelta(hours=2)
        self.db.query(ProcessingJob).filter(ProcessingJob.id == job.id).update(
            {ProcessingJob.updated_at: old}, synchronize_session=False
        )
        self.db.commit()

        def fake_dispatch(recovered, db):
            recovered.status = "queued"
            recovered.rq_job_id = "replacement-rq-job"
            db.commit()
            return recovered

        with patch(
            "services.job_recovery_service.dispatch_processing_job",
            side_effect=fake_dispatch,
        ) as dispatch:
            summary = recover_orphaned_jobs(
                self.db,
                now=now,
                stale_after_seconds=60,
                inspector=lambda _job, _connection: {
                    "status": "missing",
                    "last_heartbeat": None,
                },
            )

        self.assertEqual(summary["requeued"], 1)
        dispatch.assert_called_once()
        self.db.refresh(job)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.rq_job_id, "replacement-rq-job")

    def test_orphan_recovery_leaves_live_started_job_alone(self):
        job = self._job(status="processing", attempt_count=1, rq_job_id="live-rq-job")
        now = datetime.now()
        self.db.query(ProcessingJob).filter(ProcessingJob.id == job.id).update(
            {ProcessingJob.updated_at: now - timedelta(hours=2)},
            synchronize_session=False,
        )
        self.db.commit()

        with patch("services.job_recovery_service.dispatch_processing_job") as dispatch:
            summary = recover_orphaned_jobs(
                self.db,
                now=now,
                stale_after_seconds=60,
                inspector=lambda _job, _connection: {
                    "status": "started",
                    "last_heartbeat": now,
                },
            )

        self.assertEqual(summary["healthy"], 1)
        self.assertEqual(summary["requeued"], 0)
        dispatch.assert_not_called()

    def test_finished_rq_delivery_alone_does_not_complete_grading(self):
        job = self._job(job_type='grade_submission', status='processing', attempt_count=1)
        self.db.query(ProcessingJob).filter_by(id=job.id).update({ProcessingJob.updated_at: datetime.now()-timedelta(hours=2)})
        self.db.commit()
        with patch('services.job_recovery_service.dispatch_processing_job', side_effect=lambda job, db: job):
            summary = recover_orphaned_jobs(self.db, stale_after_seconds=60,
                inspector=lambda job, connection: {'status': 'finished'})
        self.assertEqual(summary['reconciled_completed'], 0)
        self.db.refresh(job)
        self.assertEqual(job.status, 'retrying')

    def test_orphan_recovery_reports_queue_dispatch_failure(self):
        job = self._job(status="processing", attempt_count=1, rq_job_id="missing-rq-job")
        now = datetime.now()
        self.db.query(ProcessingJob).filter(ProcessingJob.id == job.id).update(
            {ProcessingJob.updated_at: now - timedelta(hours=2)},
            synchronize_session=False,
        )
        self.db.commit()

        def failed_dispatch(recovered, db):
            recovered.status = "failed"
            recovered.error_message = "Queue unavailable"
            db.commit()
            return recovered

        with patch(
            "services.job_recovery_service.dispatch_processing_job",
            side_effect=failed_dispatch,
        ):
            summary = recover_orphaned_jobs(
                self.db,
                now=now,
                stale_after_seconds=60,
                inspector=lambda _job, _connection: {
                    "status": "missing",
                    "last_heartbeat": None,
                },
            )

        self.assertEqual(summary["requeued"], 0)
        self.assertEqual(summary["dispatch_failed"], 1)
        self.db.refresh(job)
        self.assertEqual(job.status, "failed")

    def test_orphan_recovery_fails_exhausted_job_without_requeue(self):
        job = self._job(status="processing", attempt_count=2, max_attempts=2)
        now = datetime.now()
        self.db.query(ProcessingJob).filter(ProcessingJob.id == job.id).update(
            {ProcessingJob.updated_at: now - timedelta(hours=2)},
            synchronize_session=False,
        )
        self.db.commit()

        with patch("services.job_recovery_service.dispatch_processing_job") as dispatch:
            summary = recover_orphaned_jobs(
                self.db,
                now=now,
                stale_after_seconds=60,
                inspector=lambda _job, _connection: {
                    "status": "failed",
                    "last_heartbeat": None,
                },
            )

        self.assertEqual(summary["failed_at_limit"], 1)
        dispatch.assert_not_called()
        self.db.refresh(job)
        self.assertEqual(job.status, "failed")

    def test_ocr_retry_removes_partial_ungraded_artifacts(self):
        question = Question(
            id="question-1",
            institution_id=self.institution.id,
            exam_id=self.exam.id,
            question_number="1",
            question_text="Test",
            max_score=1,
            rubric_json={"criteria": []},
            order_index=1,
        )
        answer = Answer(
            id="answer-1",
            institution_id=self.institution.id,
            submission_id=self.submission.id,
            question_id=question.id,
            raw_ocr_text="partial text",
        )
        source = AnswerSource(
            id="source-1",
            answer_id=answer.id,
            page_index=0,
            segment_index=0,
            extracted_text="partial text",
            has_math=False,
            ocr_segment={"text": "partial text"},
        )
        self.db.add_all([question, answer, source])
        self.db.commit()

        _clear_incomplete_extraction(self.submission, self.db)

        self.assertEqual(self.db.query(Answer).count(), 0)
        self.assertEqual(self.db.query(AnswerSource).count(), 0)

    def test_grading_retry_skips_answers_already_completed_by_same_job(self):
        questions = [
            Question(
                id=f"question-{index}",
                institution_id=self.institution.id,
                exam_id=self.exam.id,
                question_number=str(index),
                question_text=f"Question {index}",
                max_score=1,
                rubric_json={"criteria": []},
                order_index=index,
            )
            for index in (1, 2)
        ]
        answers = [
            Answer(
                id=f"answer-{index}",
                institution_id=self.institution.id,
                submission_id=self.submission.id,
                question_id=questions[index - 1].id,
                raw_ocr_text="answer",
            )
            for index in (1, 2)
        ]
        self.db.add_all([*questions, *answers])
        answers[0].score = 1
        self.db.commit()
        job = self._job(
            job_type="grade_submission",
            payload={"mode": "auto", "completed_answer_ids": [answers[0].id]},
        )

        with patch("services.job_execution_service.process_grading_with_policy") as grade:
            with self.assertRaisesRegex(GradingResponseValidationError, 'expected grade is missing'):
                _grade_submission(job, self.db)
            self.assertNotIn(answers[1].id, job.payload['completed_answer_ids'])
            grade.reset_mock()
            def save_proposal(answer_id, db, **kwargs):
                db.get(Answer, answer_id).score = 0
                db.commit()
            grade.side_effect = save_proposal
            _grade_submission(job, self.db)

        grade.assert_called_once_with(answers[1].id, self.db, processing_job_id=job.id)
        self.assertEqual(job.progress_current, 2)
        self.assertEqual(set(job.payload["completed_answer_ids"]), {answer.id for answer in answers})


if __name__ == "__main__":
    unittest.main()
