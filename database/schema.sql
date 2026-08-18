-- MariaDB dump 10.19  Distrib 10.4.32-MariaDB, for Win64 (AMD64)
--
-- Host: localhost    Database: misra_edu
-- ------------------------------------------------------
-- Server version	10.4.32-MariaDB

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `answer_sources`
--

DROP TABLE IF EXISTS `answer_sources`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `answer_sources` (
  `id` char(36) NOT NULL,
  `answer_id` char(36) NOT NULL,
  `page_index` int(11) NOT NULL,
  `segment_index` int(11) NOT NULL,
  `question_number` text DEFAULT NULL,
  `extracted_text` longtext NOT NULL,
  `has_math` tinyint(1) NOT NULL DEFAULT 0,
  `ocr_segment` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`ocr_segment`)),
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `ix_answer_sources_answer_id` (`answer_id`),
  KEY `ix_answer_sources_answer_page` (`answer_id`,`page_index`,`segment_index`),
  CONSTRAINT `fk_answer_sources_answer` FOREIGN KEY (`answer_id`) REFERENCES `answers` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `answers`
--

DROP TABLE IF EXISTS `answers`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `answers` (
  `id` char(36) NOT NULL,
  `institution_id` char(36) NOT NULL,
  `submission_id` char(36) NOT NULL,
  `question_id` char(36) NOT NULL,
  `raw_ocr_text` text DEFAULT NULL,
  `ocr_legibility` enum('clear','partial','illegible') DEFAULT NULL,
  `ocr_raw_response` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`ocr_raw_response`)),
  `score` decimal(6,2) DEFAULT NULL,
  `max_score` decimal(6,2) DEFAULT NULL,
  `grade_letter` varchar(5) DEFAULT NULL,
  `feedback` text DEFAULT NULL,
  `reasoning` text DEFAULT NULL,
  `criteria_scores` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`criteria_scores`)),
  `llm_confidence` decimal(5,2) DEFAULT NULL,
  `final_confidence` decimal(5,2) DEFAULT NULL,
  `grading_raw_response` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`grading_raw_response`)),
  `needs_review` tinyint(1) DEFAULT 0,
  `review_status` enum('none','pending','approved','overridden') DEFAULT 'none',
  `teacher_override_score` decimal(6,2) DEFAULT NULL,
  `teacher_notes` text DEFAULT NULL,
  `reviewed_by` char(36) DEFAULT NULL,
  `reviewed_at` timestamp NULL DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `review_reasons` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`review_reasons`)),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_submission_question` (`submission_id`,`question_id`),
  KEY `question_id` (`question_id`),
  KEY `reviewed_by` (`reviewed_by`),
  KEY `idx_answers_institution` (`institution_id`),
  KEY `idx_answers_submission` (`submission_id`),
  KEY `idx_answers_needs_review` (`needs_review`),
  CONSTRAINT `answers_ibfk_1` FOREIGN KEY (`institution_id`) REFERENCES `institutions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `answers_ibfk_2` FOREIGN KEY (`submission_id`) REFERENCES `submissions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `answers_ibfk_3` FOREIGN KEY (`question_id`) REFERENCES `questions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `answers_ibfk_4` FOREIGN KEY (`reviewed_by`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `audit_log`
--

DROP TABLE IF EXISTS `audit_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `audit_log` (
  `id` char(36) NOT NULL,
  `institution_id` char(36) DEFAULT NULL,
  `actor_id` char(36) DEFAULT NULL,
  `action` varchar(100) NOT NULL,
  `entity_type` varchar(50) NOT NULL,
  `entity_id` char(36) DEFAULT NULL,
  `metadata` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`metadata`)),
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `actor_id` (`actor_id`),
  KEY `idx_audit_institution` (`institution_id`),
  KEY `idx_audit_entity` (`entity_type`,`entity_id`),
  CONSTRAINT `audit_log_ibfk_1` FOREIGN KEY (`institution_id`) REFERENCES `institutions` (`id`) ON DELETE SET NULL,
  CONSTRAINT `audit_log_ibfk_2` FOREIGN KEY (`actor_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `batches`
--

DROP TABLE IF EXISTS `batches`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `batches` (
  `id` char(36) NOT NULL,
  `institution_id` char(36) NOT NULL,
  `exam_id` char(36) NOT NULL,
  `total_count` int(11) NOT NULL DEFAULT 1,
  `completed_count` int(11) DEFAULT 0,
  `failed_count` int(11) DEFAULT 0,
  `status` enum('queued','processing','completed','completed_with_errors') DEFAULT 'queued',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_batches_institution` (`institution_id`),
  KEY `idx_batches_exam` (`exam_id`),
  CONSTRAINT `batches_ibfk_1` FOREIGN KEY (`institution_id`) REFERENCES `institutions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `batches_ibfk_2` FOREIGN KEY (`exam_id`) REFERENCES `exams` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `course_enrollments`
--

DROP TABLE IF EXISTS `course_enrollments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `course_enrollments` (
  `id` char(36) NOT NULL,
  `course_id` char(36) NOT NULL,
  `student_id` char(36) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_enrollment` (`course_id`,`student_id`),
  KEY `student_id` (`student_id`),
  CONSTRAINT `course_enrollments_ibfk_1` FOREIGN KEY (`course_id`) REFERENCES `courses` (`id`) ON DELETE CASCADE,
  CONSTRAINT `course_enrollments_ibfk_2` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `courses`
--

DROP TABLE IF EXISTS `courses`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `courses` (
  `id` char(36) NOT NULL,
  `institution_id` char(36) NOT NULL,
  `teacher_id` char(36) NOT NULL,
  `instructor_name` varchar(255) DEFAULT NULL,
  `course_code` varchar(50) DEFAULT NULL,
  `title` varchar(255) NOT NULL,
  `term` varchar(50) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_courses_institution` (`institution_id`),
  KEY `idx_courses_teacher` (`teacher_id`),
  CONSTRAINT `courses_ibfk_1` FOREIGN KEY (`institution_id`) REFERENCES `institutions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `courses_ibfk_2` FOREIGN KEY (`teacher_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `exams`
--

DROP TABLE IF EXISTS `exams`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exams` (
  `id` char(36) NOT NULL,
  `institution_id` char(36) NOT NULL,
  `course_id` char(36) NOT NULL,
  `title` varchar(255) NOT NULL,
  `language` enum('ar','en','mixed') DEFAULT 'mixed',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_exams_institution` (`institution_id`),
  KEY `idx_exams_course` (`course_id`),
  CONSTRAINT `exams_ibfk_1` FOREIGN KEY (`institution_id`) REFERENCES `institutions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `exams_ibfk_2` FOREIGN KEY (`course_id`) REFERENCES `courses` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `grading_runs`
--

DROP TABLE IF EXISTS `grading_runs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `grading_runs` (
  `id` char(36) NOT NULL,
  `answer_id` char(36) NOT NULL,
  `mode` varchar(20) NOT NULL,
  `model_name` varchar(100) NOT NULL,
  `prompt_version` varchar(50) NOT NULL,
  `source_page_indices` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`source_page_indices`)),
  `ocr_text_snapshot` longtext NOT NULL,
  `rubric_snapshot` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`rubric_snapshot`)),
  `score` decimal(6,2) NOT NULL,
  `max_score` decimal(6,2) NOT NULL,
  `grade_letter` char(5) DEFAULT NULL,
  `feedback` longtext NOT NULL,
  `reasoning` longtext NOT NULL,
  `criteria_scores` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`criteria_scores`)),
  `llm_confidence` decimal(5,2) NOT NULL,
  `final_confidence` decimal(5,2) NOT NULL,
  `needs_review` tinyint(1) NOT NULL,
  `response_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`response_json`)),
  `latency_ms` int(11) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `rubric_version_id` char(36) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_grading_runs_answer_created` (`answer_id`,`created_at`),
  KEY `ix_grading_runs_rubric_version_id` (`rubric_version_id`),
  CONSTRAINT `fk_grading_runs_answer` FOREIGN KEY (`answer_id`) REFERENCES `answers` (`id`),
  CONSTRAINT `fk_grading_runs_rubric_version` FOREIGN KEY (`rubric_version_id`) REFERENCES `rubric_versions` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `institutions`
--

DROP TABLE IF EXISTS `institutions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `institutions` (
  `id` char(36) NOT NULL,
  `name` varchar(255) NOT NULL,
  `country` varchar(100) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `question_grading_policies`
--

DROP TABLE IF EXISTS `question_grading_policies`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `question_grading_policies` (
  `question_id` char(36) NOT NULL,
  `mode` varchar(30) NOT NULL DEFAULT 'pilot',
  `audit_rate` decimal(5,4) NOT NULL DEFAULT 0.1000,
  `min_validated_samples` int(11) NOT NULL DEFAULT 10,
  `material_absolute_points` decimal(6,2) NOT NULL DEFAULT 0.50,
  `material_relative_ratio` decimal(5,4) NOT NULL DEFAULT 0.2000,
  `enabled` tinyint(1) NOT NULL DEFAULT 1,
  `notes` longtext DEFAULT NULL,
  PRIMARY KEY (`question_id`),
  CONSTRAINT `fk_question_grading_policies_question` FOREIGN KEY (`question_id`) REFERENCES `questions` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `questions`
--

DROP TABLE IF EXISTS `questions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `questions` (
  `id` char(36) NOT NULL,
  `institution_id` char(36) NOT NULL,
  `exam_id` char(36) NOT NULL,
  `question_number` varchar(20) NOT NULL,
  `question_text` text DEFAULT NULL,
  `max_score` decimal(6,2) NOT NULL,
  `rubric_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`rubric_json`)),
  `order_index` int(11) NOT NULL,
  `language` enum('ar','en','mixed') DEFAULT 'mixed',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `active_rubric_version_id` char(36) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_questions_institution` (`institution_id`),
  KEY `idx_questions_exam` (`exam_id`),
  KEY `ix_questions_active_rubric_version_id` (`active_rubric_version_id`),
  CONSTRAINT `fk_questions_active_rubric_version` FOREIGN KEY (`active_rubric_version_id`) REFERENCES `rubric_versions` (`id`),
  CONSTRAINT `questions_ibfk_1` FOREIGN KEY (`institution_id`) REFERENCES `institutions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `questions_ibfk_2` FOREIGN KEY (`exam_id`) REFERENCES `exams` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `review_labels`
--

DROP TABLE IF EXISTS `review_labels`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `review_labels` (
  `id` char(36) NOT NULL,
  `answer_id` char(36) NOT NULL,
  `ai_score_snapshot` decimal(6,2) NOT NULL,
  `human_score` decimal(6,2) NOT NULL,
  `was_review_warranted` tinyint(1) NOT NULL,
  `human_criteria_scores` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`human_criteria_scores`)),
  `reviewer_notes` longtext DEFAULT NULL,
  `label_source` varchar(50) NOT NULL DEFAULT 'instructor_review',
  `labeled_by` char(36) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `ai_final_confidence_snapshot` decimal(5,2) DEFAULT NULL,
  `ai_needs_review_snapshot` tinyint(1) DEFAULT NULL,
  `ai_criteria_scores_snapshot` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`ai_criteria_scores_snapshot`)),
  `grading_run_id` char(36) DEFAULT NULL,
  `rubric_version_id` char(36) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_review_labels_grading_run_id` (`grading_run_id`),
  KEY `ix_review_labels_created_at` (`created_at`),
  KEY `fk_review_labels_user` (`labeled_by`),
  KEY `ix_review_labels_answer_id_lookup` (`answer_id`),
  KEY `ix_review_labels_rubric_version_id` (`rubric_version_id`),
  CONSTRAINT `fk_review_labels_answer` FOREIGN KEY (`answer_id`) REFERENCES `answers` (`id`),
  CONSTRAINT `fk_review_labels_grading_run` FOREIGN KEY (`grading_run_id`) REFERENCES `grading_runs` (`id`),
  CONSTRAINT `fk_review_labels_rubric_version` FOREIGN KEY (`rubric_version_id`) REFERENCES `rubric_versions` (`id`),
  CONSTRAINT `fk_review_labels_user` FOREIGN KEY (`labeled_by`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `rubric_suggestions`
--

DROP TABLE IF EXISTS `rubric_suggestions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `rubric_suggestions` (
  `id` char(36) NOT NULL,
  `question_id` char(36) DEFAULT NULL,
  `suggested_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`suggested_json`)),
  `status` enum('pending','accepted','edited','rejected') DEFAULT 'pending',
  `final_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`final_json`)),
  `generated_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `resolved_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_suggestions_question` (`question_id`),
  CONSTRAINT `rubric_suggestions_ibfk_1` FOREIGN KEY (`question_id`) REFERENCES `questions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `rubric_versions`
--

DROP TABLE IF EXISTS `rubric_versions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `rubric_versions` (
  `id` char(36) NOT NULL,
  `question_id` char(36) NOT NULL,
  `version_number` int(11) NOT NULL,
  `schema_version` int(11) NOT NULL DEFAULT 2,
  `rubric_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`rubric_json`)),
  `grading_approach` varchar(20) NOT NULL DEFAULT 'balanced',
  `source` varchar(20) NOT NULL DEFAULT 'manual',
  `status` varchar(20) NOT NULL DEFAULT 'draft',
  `change_summary` longtext DEFAULT NULL,
  `created_by` char(36) DEFAULT NULL,
  `approved_by` char(36) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `approved_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_rubric_version_question_number` (`question_id`,`version_number`),
  KEY `ix_rubric_versions_question_id` (`question_id`),
  KEY `ix_rubric_versions_status` (`status`),
  KEY `fk_rubric_versions_created_by` (`created_by`),
  KEY `fk_rubric_versions_approved_by` (`approved_by`),
  CONSTRAINT `fk_rubric_versions_approved_by` FOREIGN KEY (`approved_by`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_rubric_versions_created_by` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_rubric_versions_question` FOREIGN KEY (`question_id`) REFERENCES `questions` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `students`
--

DROP TABLE IF EXISTS `students`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `students` (
  `id` char(36) NOT NULL,
  `institution_id` char(36) NOT NULL,
  `student_number` varchar(100) DEFAULT NULL,
  `full_name` varchar(255) NOT NULL,
  `email` varchar(255) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_student_number_per_institution` (`institution_id`,`student_number`),
  KEY `idx_students_institution` (`institution_id`),
  CONSTRAINT `students_ibfk_1` FOREIGN KEY (`institution_id`) REFERENCES `institutions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `submissions`
--

DROP TABLE IF EXISTS `submissions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `submissions` (
  `id` char(36) NOT NULL,
  `institution_id` char(36) NOT NULL,
  `exam_id` char(36) NOT NULL,
  `batch_id` char(36) DEFAULT NULL,
  `student_id` char(36) DEFAULT NULL,
  `extracted_student_name` varchar(255) DEFAULT NULL,
  `extracted_student_number` varchar(100) DEFAULT NULL,
  `identity_status` enum('matched','unmatched_extracted','unmatched_blank','unmatched_illegible') DEFAULT 'unmatched_blank',
  `original_file_path` text NOT NULL,
  `page_count` int(11) DEFAULT 1,
  `status` enum('uploaded','extracting','extracted','grading','graded','needs_review','reviewed','error') DEFAULT 'uploaded',
  `error_message` text DEFAULT NULL,
  `uploaded_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `unmatched_segments` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`unmatched_segments`)),
  PRIMARY KEY (`id`),
  KEY `idx_submissions_institution` (`institution_id`),
  KEY `idx_submissions_exam` (`exam_id`),
  KEY `idx_submissions_batch` (`batch_id`),
  KEY `idx_submissions_student` (`student_id`),
  KEY `idx_submissions_status` (`status`),
  KEY `idx_submissions_identity_status` (`identity_status`),
  CONSTRAINT `submissions_ibfk_1` FOREIGN KEY (`institution_id`) REFERENCES `institutions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `submissions_ibfk_2` FOREIGN KEY (`exam_id`) REFERENCES `exams` (`id`) ON DELETE CASCADE,
  CONSTRAINT `submissions_ibfk_3` FOREIGN KEY (`batch_id`) REFERENCES `batches` (`id`) ON DELETE SET NULL,
  CONSTRAINT `submissions_ibfk_4` FOREIGN KEY (`student_id`) REFERENCES `students` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `users` (
  `id` char(36) NOT NULL,
  `institution_id` char(36) NOT NULL,
  `email` varchar(255) NOT NULL,
  `hashed_password` varchar(255) NOT NULL,
  `full_name` varchar(255) DEFAULT NULL,
  `role` enum('teacher','admin') NOT NULL DEFAULT 'teacher',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_email_per_institution` (`institution_id`,`email`),
  KEY `idx_users_institution` (`institution_id`),
  CONSTRAINT `users_ibfk_1` FOREIGN KEY (`institution_id`) REFERENCES `institutions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed
