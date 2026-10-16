"""Synthetic whole-page accounting regressions; no model calls or real papers."""
import os
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
os.environ.setdefault("GEMINI_API_KEY","test-key-not-used")
from database import Base
from models import Answer,AnswerSource,Exam,ExtractionInventory,Question,RubricVersion,Submission
from services.ocr_service import OCRSegment,OCRPageResult,_normalize_question_number,_question_for_segment,_is_cover_mark,process_submission,_visual_mapping_second_pass
from services.whole_paper_mapping_service import reconcile_paper,MappingDecision
from services.extraction_review_service import build_extraction_review,resolve_unmatched_segment
from services.grading_package_service import build_grading_package
from services.grading_service import process_grading
from services.page_recovery_service import confirm_page_recovery, preview_page_recovery, RecoveryPageResult, _sign_preview
from schemas.page_recovery_input import RecoverySegmentInput
from scripts.upgrade_extraction_coverage import upgrade
from tests.inference_fixtures import isolate_grading_provider

BOX = {"x":.1,"y":.2,"width":.8,"height":.2}


class PrintedAnchorTests(unittest.TestCase):
    def segment(self,label,text,**values):
        return OCRSegment(question_number=label,text=text,language="en",legibility="clear",has_math=False,**values)

    def test_dotted_and_arabic_question_numbers_do_not_collapse(self):
        self.assertEqual(_normalize_question_number("Q1.2(b)",None),("1.2b","1.2"))
        self.assertEqual(_normalize_question_number("السؤال ٣",None),("3","3"))
        self.assertEqual(_question_for_segment("1.2b",{"1.2":"q"}),("1.2","q"))
        self.assertEqual(_question_for_segment("1",{"1a":"a","1b":"b"}),(None,None))

    def test_printed_anchor_can_correct_short_label_without_guessing_from_content(self):
        questions = [Question(id="a",question_number="1",question_text="Calculate force"),Question(id="b",question_number="2",question_text="Calculate energy")]
        page = OCRPageResult(page_language="en",identity_legibility="not_found",segments=[self.segment("1","15 J",printed_question_number="2")])
        decision = reconcile_paper([page],questions,_normalize_question_number,_question_for_segment,_is_cover_mark)[(0,0)]
        self.assertEqual(decision.question_id,"b"); self.assertEqual(decision.method,"printed_anchor")

    def test_anchor_content_conflict_is_not_smoothed_into_page_continuation(self):
        questions = [Question(id="a",question_number="1",question_text="Use NLTK stemmers stopwords"),Question(id="b",question_number="2",question_text="Explain amplitude frequency spectrum")]
        page = OCRPageResult(page_language="en",identity_legibility="not_found",segments=[self.segment("2","NLTK stemmers stopwords",printed_question_number="2"),self.segment("2","amplitude frequency spectrum")])
        decision = reconcile_paper([page],questions,_normalize_question_number,_question_for_segment,_is_cover_mark)[(0,0)]
        self.assertIsNone(decision.question_id); self.assertEqual(decision.method,"anchor_conflict")

    def test_arabic_terminology_and_numeric_continuations_are_accounted(self):
        questions = [Question(id="a",question_number="1",question_text="احسب الطاقة الحركية"),Question(id="b",question_number="2",question_text="اشرح الجهد الكهربائي")]
        page = OCRPageResult(page_language="ar",identity_legibility="not_found",segments=[self.segment(None,"الطاقة الحركية تساوي نصف الكتلة"),self.segment(None,"15")])
        decisions = reconcile_paper([page],questions,_normalize_question_number,_question_for_segment,_is_cover_mark)
        self.assertEqual(decisions[(0,0)].question_id,"a"); self.assertEqual(decisions[(0,1)].question_id,"a")

    def test_explicit_answers_page_preserves_numeric_quiz_with_identity(self):
        page = OCRPageResult(page_language="en",identity_legibility="clear",student_name="Synthetic",student_id="TEST",page_role="answers",
            segments=[self.segment(str(i),str(i)) for i in range(1,4)])
        self.assertFalse(_is_cover_mark(page.segments[0],page,2,0))

    def test_visual_conflicting_assignments_remain_unresolved(self):
        from PIL import Image
        image = io.BytesIO(); Image.new("RGB",(20,20),"white").save(image,format="PNG")
        page = OCRPageResult(page_language="en",identity_legibility="not_found",segments=[self.segment(None,"15")])
        decisions = {(0,0):MappingDecision(None,None,"unresolved")}
        response = {"assignments":[{"page_index":0,"segment_index":0,"question_number":"1"},
                                   {"page_index":0,"segment_index":0,"question_number":"2"}]}
        questions = [Question(id="a",question_number="1"),Question(id="b",question_number="2")]
        with patch.dict(os.environ,{"OCR_MAPPING_SECOND_PASS_ENABLED":"true"}), \
             patch("services.ocr_service.generate",return_value=json.dumps(response)):
            result, unavailable = _visual_mapping_second_pass(decisions,[page],[image.getvalue()],questions)
        self.assertFalse(unavailable); self.assertEqual(result[(0,0)].method,"unresolved")


class CoverageTests(unittest.TestCase):
    def setUp(self):
        isolate_grading_provider(self)
        self.engine = create_engine("sqlite://"); Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)(); self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/"synthetic.pdf"; self.path.write_bytes(b"synthetic private fixture")
        self.rubric = {"max_score":2,"criteria":[{"id":"method","description":"Correct method","points":2}]}
        self.q = Question(id="q",institution_id="i",exam_id="e",question_number="1",question_text="Calculate work",max_score=2,rubric_json=self.rubric,active_rubric_version_id="r",order_index=0)
        self.s = Submission(id="s",institution_id="i",exam_id="e",page_count=1,original_file_path=str(self.path),status="uploaded")
        self.db.add_all([Exam(id="e",institution_id="i",course_id="c",title="Synthetic"),self.q,self.s,
            RubricVersion(id="r",question_id="q",version_number=1,status="approved",rubric_json=self.rubric)]); self.db.commit()

    def tearDown(self):
        self.db.close(); self.engine.dispose(); self.temp.cleanup()

    def extract(self, regions, **changes):
        page = OCRPageResult(page_language="en",identity_legibility="not_found",segments=[OCRSegment(question_number="1",text="W = Fd",language="en",legibility="clear",has_math=False,bounding_box=BOX)],
            answer_regions=regions,coverage_reported_complete=True,**changes)
        with patch("services.ocr_service._split_pdf",return_value=[b"page"]),patch("services.ocr_service.extract_page",return_value=page):
            process_submission("s",self.db,reprocess=self.s.status == "extracted")
        return build_extraction_review("s",self.db)

    def test_accounted_inventory_persists_and_versions_are_immutable(self):
        report = self.extract([{"bounding_box":BOX,"segment_indices":[0]}])
        self.assertEqual(report["coverage"]["status"],"provider_accounted")
        self.assertTrue(report["readiness"]["bulk_grading_allowed"])
        first = self.db.query(ExtractionInventory).one(); original = first.manifest_sha256
        self.extract([{"bounding_box":BOX,"segment_indices":[0]}])
        self.assertEqual(self.db.query(ExtractionInventory).count(),2); self.assertEqual(first.manifest_sha256,original)
        package,*_ = build_grading_package(self.db.query(Answer).one(),self.q,self.db,"text_only")
        self.assertEqual(package["extraction_coverage"]["inventory_version"],2)

    def test_untranscribed_region_blocks_grading_before_any_provider_call(self):
        report = self.extract([{"bounding_box":BOX,"segment_indices":[0]},
            {"bounding_box":dict(BOX,y=.6),"segment_indices":[],"note":"Unclear handwritten line"}])
        self.assertEqual(report["readiness"]["mapped_answer_count"],1)
        self.assertFalse(report["readiness"]["bulk_grading_allowed"])
        self.assertEqual(report["coverage"]["unaccounted_region_count"],1)
        self.assertEqual(report["coverage"]["issues"][0]["bounding_box"]["y"],.6)
        with patch("services.grading_service.generate") as generate:
            with self.assertRaisesRegex(ValueError,"not fully accounted"):
                process_grading(self.db.query(Answer).one().id,self.db)
            generate.assert_not_called()

    def test_unknown_inventory_is_not_reported_as_verified(self):
        report = self.extract([])
        self.assertEqual(report["coverage"]["status"],"unverified")
        self.assertIn("transcribed_segments_not_in_region_inventory",str(report["coverage"]["warnings"]))

    def test_unverified_inventory_caps_confidence_and_preserves_run_reason(self):
        self.extract([])
        source = self.db.query(AnswerSource).one()
        result = {"score":2,"max_score":2,"feedback":"Correct method","reasoning":"Work matches the rubric",
                  "llm_confidence":99,"criteria_scores":[{"criterion_id":"method","max_points":2,
                  "points_earned":2,"feedback":"Correct","evidence_refs":[f"source:{source.id}"],
                  "reference_refs":[],"policy_applied":[],"uncertainties":[]}]}
        with patch("services.grading_service.generate",return_value=json.dumps(result)):
            graded = process_grading(self.db.query(Answer).one().id,self.db)
        answer = self.db.query(Answer).one()
        self.assertLessEqual(float(answer.final_confidence),40)
        self.assertTrue(answer.needs_review)
        self.assertIn("page_coverage_unverified",str(answer.review_reasons))

    def test_tampered_manifest_is_detected(self):
        self.extract([{"bounding_box":BOX,"segment_indices":[0]}])
        inventory = self.db.query(ExtractionInventory).one(); inventory.page_count = 99; self.db.commit()
        report = build_extraction_review("s",self.db)
        self.assertEqual(report["coverage"]["status"],"invalid")
        self.assertFalse(report["readiness"]["bulk_grading_allowed"])

    def test_upgrade_is_additive_and_idempotent(self):
        upgrade(self.engine); upgrade(self.engine)
        self.assertEqual(self.db.query(Question).count(),1)

    def test_legacy_database_without_inventory_table_keeps_existing_workflow(self):
        ExtractionInventory.__table__.drop(self.engine)
        report = self.extract([{"bounding_box":BOX,"segment_indices":[0]}])
        self.assertEqual(report["coverage"]["status"],"not_recorded")
        self.assertTrue(report["readiness"]["bulk_grading_allowed"])
        package,*_ = build_grading_package(self.db.query(Answer).one(),self.q,self.db,"text_only")
        self.assertIsNone(package["extraction_coverage"]["inventory_id"])

    def recover(self, box):
        segment = RecoverySegmentInput(question_number="1", text="F = 12 N", bounding_box=box)
        with patch.dict(os.environ, {"RECOVERY_SIGNING_KEY":"synthetic-signing-key"}):
            signature = _sign_preview("s", 0, ["1"], [segment.model_dump()])
            return confirm_page_recovery("s", 0, ["1"], [segment], signature, self.db)

    def test_confirmed_recovery_accounts_only_for_matching_region(self):
        missing = dict(BOX, y=.6)
        self.extract([{"bounding_box":BOX,"segment_indices":[0]},
                      {"bounding_box":missing,"segment_indices":[]}])
        report = self.recover(missing)
        self.assertEqual(report["coverage"]["unaccounted_region_count"], 0)
        self.assertTrue(report["coverage"]["pages"][0]["regions"][1]["confirmed_recovery"])
        self.assertTrue(report["readiness"]["bulk_grading_allowed"])
        self.recover(missing)
        self.assertEqual(self.db.query(AnswerSource).count(), 2)

    def test_whole_page_recovery_cannot_clear_small_missing_region(self):
        self.extract([{"bounding_box":BOX,"segment_indices":[0]},
                      {"bounding_box":dict(BOX,y=.6),"segment_indices":[]}])
        report = self.recover({"x":0,"y":0,"width":1,"height":1})
        self.assertEqual(report["coverage"]["unaccounted_region_count"], 1)
        self.assertFalse(report["readiness"]["bulk_grading_allowed"])

    def test_recovery_preview_does_not_duplicate_already_accounted_work(self):
        missing = dict(BOX, y=.6)
        self.extract([{"bounding_box":BOX,"segment_indices":[0]},
                      {"bounding_box":missing,"segment_indices":[]}])
        proposal = RecoveryPageResult(segments=[
            RecoverySegmentInput(question_number="1", text="W = Fd", bounding_box=BOX),
            RecoverySegmentInput(question_number="1", text="F = 12 N", bounding_box=missing),
        ])
        with patch("services.page_recovery_service.load_submission_page_bytes",return_value=b"synthetic"), \
             patch("services.page_recovery_service.extract_recovery_page",return_value=proposal), \
             patch.dict(os.environ,{"RECOVERY_SIGNING_KEY":"synthetic-signing-key"}):
            preview = preview_page_recovery("s",0,["1"],self.db)
        self.assertEqual([item["text"] for item in preview["segments"]],["F = 12 N"])

    def test_explicit_exclusion_preserves_provenance_and_clears_region(self):
        from services.extraction_review_service import bulk_resolve_segments
        self.extract([{"bounding_box":BOX,"segment_indices":[0]}])
        source = self.db.query(AnswerSource).one()
        report = bulk_resolve_segments("s", action="ignore", question_id=None,
                                       source_ids=[source.id], unmatched_indices=[], db=self.db)
        self.assertEqual(report["coverage"]["unaccounted_region_count"], 0)
        self.assertEqual(len(report["excluded_segments"]),1)
        self.assertEqual(report["excluded_segments"][0]["ocr_origin"]["inventory_id"],report["coverage"]["inventory_id"])


if __name__ == "__main__": unittest.main()
