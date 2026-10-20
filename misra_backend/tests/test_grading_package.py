import json
import os
import unittest
from copy import deepcopy
from unittest.mock import patch
from types import SimpleNamespace

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import Answer, AnswerKeyVersion, AnswerSource, Exam, GradingRun, Question, RubricVersion, Submission
from schemas.rubric_v2 import RubricPolicy
from services.grading_package_service import (
    build_grading_package,
    provider_grading_package,
    validate_evidence_references,
)
from services.grading_service import (GradingResult, process_grading, process_grading_with_policy,
    _aggregate_criterion_total, _validate_grading_against_rubric)
from services.grading_errors import GradingResponseValidationError
from services.run_comparison_service import apply_material_disagreement_gate
from tests.inference_fixtures import isolate_grading_provider
from tests.test_grading_decisions import check


class GradingPackageTests(unittest.TestCase):
    def setUp(self):
        isolate_grading_provider(self)
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.rubric = {"max_score": 2, "criteria": [{"id": "logic", "description": "Correct logic", "points": 2}],
                       "reference_context": "Old key", "acceptable_answers": ["Equivalent method"],
                       "policy": {"handwritten_syntax_policy": "accept_unambiguous"}}
        self.q = Question(id="q", institution_id="i", exam_id="e", question_number="1",
            question_text="Explain your solution.", max_score=2, order_index=0, rubric_json=deepcopy(self.rubric))
        self.answer = Answer(id="a", institution_id="i", submission_id="s", question_id="q",
            raw_ocr_text="My solution", ocr_legibility="clear")
        self.db.add_all([Exam(id="e", institution_id="i", course_id="c", title="Synthetic exam"), self.q,
            Submission(id="s", institution_id="i", exam_id="e", original_file_path="missing-synthetic.png",
                page_count=1), self.answer,
            AnswerSource(id="source", answer_id="a", page_index=0, segment_index=0,
                extracted_text="My solution", ocr_segment={}),
            RubricVersion(id="rubric1", question_id="q", version_number=1, status="approved",
                rubric_json=deepcopy(self.rubric))])
        self.q.active_rubric_version_id = "rubric1"
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def result(self, **criterion_changes):
        criterion = dict(criterion_id="logic", max_points=2, points_earned=2, feedback="Valid reasoning",
            evidence_refs=["source:source"], reference_refs=["key:legacy"],
            policy_applied=["handwritten_syntax_policy"], uncertainties=[],
            decision_check=check(criterion_kind='other', method_status='not_assessed'))
        criterion.update(criterion_changes)
        return dict(score=2, max_score=2, feedback="Correct", reasoning="Logic meets criteria",
                    criteria_scores=[criterion], llm_confidence=95)

    def test_legacy_reference_and_policy_are_separate_and_copied(self):
        package, _, _, version = build_grading_package(self.answer, self.q, self.db, "text_only")
        self.assertEqual(version, "rubric1")
        self.assertEqual(package["answer_key"]["reference_text"], "Old key")
        self.assertEqual(package["answer_key"]["alternatives"], ["Equivalent method"])
        self.assertNotIn("reference_context", package["rubric"])
        self.assertEqual(package["policy"]["handwritten_syntax_policy"], "accept_unambiguous")
        self.assertNotIn("missing-synthetic", json.dumps(package))
        self.assertEqual(len(package["snapshot_sha256"]), 64)

    def test_criterion_total_preserves_original_and_forces_review(self):
        response = self.result(evidence_refs=['student:segment:1'], reference_refs=['instructor:answer_key'])
        response['score'] = 0
        response['grade_letter'] = 'F'
        with patch('services.grading_service.generate', return_value=json.dumps(response)):
            process_grading('a', self.db)
        run = self.db.query(GradingRun).one()
        self.assertEqual(run.score, 2)
        self.assertIsNone(run.grade_letter)
        self.assertTrue(run.needs_review)
        snapshot = run.response_json
        self.assertEqual(snapshot['original_model_response']['attempts'][0]['score'], 0)
        self.assertEqual(snapshot['score_aggregation']['model_reported_total'], 0)
        self.assertFalse(snapshot['score_aggregation']['criterion_marks_changed'])
        self.assertIn('model_total_discrepancy', snapshot['review_policy']['reasons'])
        self.db.expire_all()
        self.assertEqual(self.db.query(GradingRun).one().response_json, snapshot)

    def test_aggregation_never_relaxes_criterion_or_original_benchmark_validation(self):
        response = self.result()
        response['score'] = 0
        result = GradingResult(**response)
        with self.assertRaisesRegex(ValueError, 'criterion total'):
            _validate_grading_against_rubric(result, self.rubric)
        for changes in ({'points_earned': 3}, {'criterion_id': 'invented'}, {'max_points': 3}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _aggregate_criterion_total(GradingResult(**self.result(**changes)), self.rubric)
        binary = deepcopy(self.rubric)
        binary['criteria'][0]['scoring_type'] = 'binary'
        with self.assertRaisesRegex(ValueError, 'partial credit'):
            _aggregate_criterion_total(GradingResult(**self.result(points_earned=1)), binary)

    def test_citation_correction_keeps_initial_aggregation_discrepancy(self):
        initial = self.result(evidence_refs=['invented'], reference_refs=['instructor:answer_key'])
        initial['score'] = 0
        corrected = self.result(evidence_refs=['student:segment:1'], reference_refs=['instructor:answer_key'])
        with patch('services.grading_service.generate', side_effect=[json.dumps(initial), json.dumps(corrected)]):
            process_grading('a', self.db)
        saved = self.db.query(GradingRun).one().response_json
        self.assertEqual(len(saved['original_model_response']['attempts']), 2)
        self.assertTrue(saved['score_aggregation']['discrepancy'])
        self.assertIn('model_total_discrepancy', saved['review_policy']['reasons'])

    def test_draft_does_not_change_effective_key(self):
        self.db.add(AnswerKeyVersion(question_id="q", version_number=1, status="draft",
            mode="reference", reference_text="Draft key", acceptable_answers=[], document_refs=[]))
        self.db.commit()
        package, *_ = build_grading_package(self.answer, self.q, self.db, "text_only")
        self.assertEqual(package["answer_key"]["reference_text"], "Old key")

    def test_cross_assessment_and_bad_page_rejected(self):
        self.q.exam_id = "other"
        with self.assertRaisesRegex(ValueError, "belong"):
            build_grading_package(self.answer, self.q, self.db, "text_only")
        self.q.exam_id = "e"
        self.db.query(AnswerSource).first().page_index = -1
        with self.assertRaisesRegex(ValueError, "unavailable page"):
            build_grading_package(self.answer, self.q, self.db, "text_only")

    def test_invalid_citations_and_numeric_values_rejected(self):
        package, *_ = build_grading_package(self.answer, self.q, self.db, "text_only")
        for changes in ({"evidence_refs": ["source:another"]}, {"reference_refs": ["key:other"]},
                        {"policy_applied": ["invented"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_evidence_references(GradingResult(**self.result(**changes)), package)
        for value in (-1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GradingResult(**self.result(points_earned=value))

    def test_combined_text_cannot_replace_tracked_source_citation(self):
        package, *_ = build_grading_package(self.answer, self.q, self.db, "text_only")
        combined_id = next(
            item["id"] for item in package["student_evidence"]
            if item["kind"] == "combined_ocr"
        )
        with self.assertRaisesRegex(ValueError, "tracked source"):
            validate_evidence_references(
                GradingResult(**self.result(evidence_refs=[combined_id])),
                package,
            )

    def test_provider_receives_safe_projection_while_full_snapshot_is_saved(self):
        provider_result = self.result(
            evidence_refs=["student:segment:1"],
            reference_refs=["instructor:answer_key"],
        )
        with patch(
            "services.grading_service.generate",
            return_value=json.dumps(provider_result),
        ) as generate:
            process_grading("a", self.db)

        prompt = generate.call_args.kwargs["contents"]
        self.assertIsInstance(prompt, str)
        for forbidden in (
            '"institution_id"', '"assessment_id"', '"submission_id"',
            '"answer_id"', '"rubric_version_id"', '"policy_version_id"',
            '"student_document_sha256"', '"snapshot_sha256"', '"job_id"',
            '"sha256"', 'source:source', 'key:legacy',
        ):
            self.assertNotIn(forbidden, prompt)

        run = self.db.query(GradingRun).one()
        local = run.response_json["grading_package"]
        self.assertEqual(local["institution_id"], "i")
        self.assertEqual(local["assessment_id"], "e")
        self.assertEqual(local["submission_id"], "s")
        self.assertEqual(local["answer_id"], "a")
        self.assertIn("snapshot_sha256", local)
        saved_criterion = run.criteria_scores[0]
        self.assertEqual(saved_criterion["evidence_refs"], ["source:source"])
        self.assertEqual(saved_criterion["reference_refs"], ["key:legacy"])

    def test_provider_projection_omits_internal_routing_pair(self):
        package, *_ = build_grading_package(
            self.answer,
            self.q,
            self.db,
            "text_only",
            routing_context={
                "requested_mode": "auto",
                "policy_mode": "pilot",
                "selected_mode": "text_only",
                "route_reasons": [{"code": "pilot_primary"}],
                "image_audit_performed": True,
                "comparison_pair_id": "internal-pair-id",
            },
        )
        safe, *_ = provider_grading_package(package)
        self.assertNotIn("comparison_pair_id", safe["routing"])
        self.assertEqual(
            package["routing"]["comparison_pair_id"],
            "internal-pair-id",
        )

    def test_no_fixed_key_does_not_advertise_a_citable_key(self):
        package, *_ = build_grading_package(self.answer, self.q, self.db, 'text_only')
        package['answer_key']['mode'] = 'no_fixed_answer'
        before = deepcopy(package)
        safe, _, refs = provider_grading_package(package)
        self.assertIsNone(safe['answer_key']['reference_id'])
        self.assertNotIn('instructor:answer_key', refs)
        self.assertEqual(safe['citation_contract']['criteria'], [{
            'criterion_id':'logic', 'reference_refs':[], 'required_course_reference_refs':[]}])
        self.assertEqual(safe['citation_contract']['tracked_evidence_refs'], ['student:segment:1'])
        self.assertEqual(package, before)
        # A forbidden key citation must still fail: do not repair it by erasure.
        with self.assertRaisesRegex(ValueError, 'unavailable answer-key'):
            validate_evidence_references(GradingResult(**self.result()), package)

    def test_citation_contract_limits_course_references_to_each_criterion(self):
        package, *_ = build_grading_package(self.answer, self.q, self.db, 'text_only')
        package['answer_key']['mode'] = 'no_fixed_answer'
        package['course_references'] = {'mode':'required','passages':[
            {'id':'material:one','title':'Synthetic chapter','page_index':0,
             'printed_page_label':'1','text':'Approved concept','criterion_ids':['logic']},
            {'id':'material:two','title':'Synthetic chapter','page_index':1,
             'printed_page_label':'2','text':'Different concept','criterion_ids':['other']}]}
        safe, _, _ = provider_grading_package(package)
        self.assertEqual(safe['citation_contract']['criteria'], [{
            'criterion_id':'logic','reference_refs':['instructor:source:1'],
            'required_course_reference_refs':['instructor:source:1']}])

    def test_no_fixed_key_citation_repair_uses_empty_reference_list(self):
        key = AnswerKeyVersion(id='no-key',question_id='q',version_number=1,
            status='approved',mode='no_fixed_answer',reference_text='',
            acceptable_answers=[],document_refs=[])
        self.db.add(key)
        self.db.commit()
        first=self.result(evidence_refs=['student:segment:1'],reference_refs=['instructor:answer_key'])
        second=self.result(evidence_refs=['student:segment:1'],reference_refs=[])
        with patch('services.grading_service.generate',side_effect=[json.dumps(first),json.dumps(second)]) as generate:
            process_grading('a',self.db)
        self.assertEqual(generate.call_count,2)
        self.assertIn('"reference_id": null',generate.call_args_list[0].kwargs['contents'])
        self.assertIn('allowed reference_refs list is empty',generate.call_args_list[1].kwargs['contents'])
        run=self.db.query(GradingRun).one()
        self.assertEqual(run.criteria_scores[0]['reference_refs'],[])
        self.assertEqual(float(run.score),2)
        self.assertTrue(run.needs_review)

    def test_real_processing_saves_snapshot_unchanged_after_edits(self):
        with patch("services.grading_service.generate", return_value=json.dumps(self.result())) as generate:
            process_grading("a", self.db)
        run = self.db.query(GradingRun).one()
        original = deepcopy(run.response_json["grading_package"])
        self.assertEqual(run.prompt_version, "v14-approved-data-copy-error")
        self.assertIn("GRADING PACKAGE JSON", generate.call_args.kwargs["contents"])
        self.q.question_text = "Changed question"
        self.db.query(RubricVersion).first().rubric_json = {**self.rubric, "reference_context": "Changed reference"}
        self.db.commit()
        self.db.expire_all()
        self.assertEqual(self.db.query(GradingRun).one().response_json["grading_package"], original)

    def test_uncertainty_requires_review_and_invalid_output_never_saves(self):
        with patch("services.grading_service.generate", return_value=json.dumps(self.result(uncertainties=["Symbol unclear"]))):
            process_grading("a", self.db)
        self.assertTrue(self.answer.needs_review)
        self.assertEqual(float(self.answer.final_confidence), 40)
        with patch("services.grading_service.generate", return_value=json.dumps(self.result(evidence_refs=["invented"]))):
            with self.assertRaisesRegex(ValueError, "No grade was saved"):
                process_grading("a", self.db)
        self.assertEqual(self.db.query(GradingRun).count(), 1)

    def test_explicit_policies_validate_values(self):
        policy = RubricPolicy(handwritten_syntax_policy="accept_unambiguous",
                              language_quality_policy="ignore_unless_assessed", error_carried_forward="single_penalty")
        self.assertEqual(policy.error_carried_forward, "single_penalty")
        with self.assertRaises(ValueError):
            RubricPolicy(handwritten_syntax_policy="always_full_marks")

    def test_missing_tracked_citation_gets_one_correction_same_package_and_marks(self):
        first = self.result(evidence_refs=['student:combined:1'], reference_refs=['instructor:answer_key'])
        second = self.result(evidence_refs=['student:segment:1'], reference_refs=['instructor:answer_key'])
        with patch('services.grading_service.generate', side_effect=[json.dumps(first), json.dumps(second)]) as generate:
            process_grading('a', self.db)
        self.assertEqual(generate.call_count, 2)
        initial = generate.call_args_list[0].kwargs['contents']
        corrected = generate.call_args_list[1].kwargs['contents']
        self.assertTrue(corrected.startswith(initial))
        self.assertIn('EVERY criterion', initial)
        self.assertIn('zero-credit', initial)
        self.assertIn('CITATION CORRECTION', corrected)
        self.assertIn('Keep every criterion', corrected)
        self.assertNotIn('source:source', corrected)
        run = self.db.query(GradingRun).one()
        self.assertEqual(float(run.score), 2)
        self.assertEqual(run.criteria_scores[0]['evidence_refs'], ['source:source'])
        self.assertEqual(run.response_json['inference']['call_count'], 2)
        self.assertIsNone(run.response_json['inference']['reported_cost_usd'])
        self.assertTrue(run.response_json['validation']['citation_correction_performed'])
        self.assertTrue(run.needs_review)
        self.assertEqual(float(run.final_confidence), 40)

    def test_zero_credit_missing_step_still_cites_inspected_work(self):
        first = self.result(points_earned=0, evidence_refs=[], uncertainties=['No comparison stated'])
        first['score'] = 0
        second = deepcopy(first)
        second['criteria_scores'][0]['evidence_refs'] = ['student:segment:1']
        with patch('services.grading_service.generate', side_effect=[json.dumps(first), json.dumps(second)]):
            process_grading('a', self.db)
        self.assertEqual(float(self.answer.score), 0)
        self.assertEqual(self.answer.criteria_scores[0]['evidence_refs'], ['source:source'])
        self.assertTrue(self.answer.needs_review)

    def test_repeated_invalid_citation_never_saves_and_stops_after_two_calls(self):
        response = json.dumps(self.result(evidence_refs=['invented']))
        with patch('services.grading_service.generate', return_value=response) as generate:
            with self.assertRaises(GradingResponseValidationError) as failure:
                process_grading('a', self.db)
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(failure.exception.code, 'invalid_student_reference')
        self.assertIn('one correction attempt', str(failure.exception))
        self.assertEqual(self.db.query(GradingRun).count(), 0)
        self.assertIsNone(self.answer.score)

    def test_citation_correction_may_not_change_marks(self):
        first = self.result(evidence_refs=[])
        second = self.result(points_earned=1)
        second['score'] = 1
        with patch('services.grading_service.generate', side_effect=[json.dumps(first), json.dumps(second)]) as generate:
            with self.assertRaises(GradingResponseValidationError) as failure:
                process_grading('a', self.db)
        self.assertEqual(failure.exception.code, 'correction_changed_marks')
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(self.db.query(GradingRun).count(), 0)

    def test_schema_and_score_failures_do_not_trigger_citation_repair(self):
        for response in ['not JSON', json.dumps({'score': 1}), json.dumps(self.result(points_earned=3))]:
            with self.subTest(response=response), patch('services.grading_service.generate', return_value=response) as generate:
                with self.assertRaises(GradingResponseValidationError):
                    process_grading('a', self.db)
                self.assertEqual(generate.call_count, 1)
        self.assertEqual(self.db.query(GradingRun).count(), 0)

    def test_multimodal_correction_reuses_original_images_and_references(self):
        first = self.result(evidence_refs=[])
        second = self.result(evidence_refs=['student:page:1'])
        image = object()
        with patch('services.grading_service._load_answer_source_images', return_value=([image], [0])), \
             patch('services.grading_service.generate', side_effect=[json.dumps(first), json.dumps(second)]) as generate:
            process_grading('a', self.db, mode='image_text')
        initial, corrected = [call.kwargs['contents'] for call in generate.call_args_list]
        self.assertEqual(corrected[:-1], initial)
        self.assertIs(corrected[2], image)
        self.assertEqual(self.db.query(GradingRun).one().criteria_scores[0]['evidence_refs'], ['page:0'])

    def test_free_only_repair_keeps_provider_and_aggregates_usage(self):
        first = self.result(evidence_refs=[])
        second = self.result(evidence_refs=['student:segment:1'])
        metadata = {'provider': 'openrouter_free', 'model': 'synthetic:free',
                    'prompt_tokens': 10, 'completion_tokens': 5, 'reported_cost_usd': 0}
        responses = [SimpleNamespace(text=json.dumps(item), metadata=metadata) for item in (first, second)]
        with patch.dict(os.environ, {'GRADING_PROVIDER': 'openrouter_free'}), \
             patch('services.free_model_gateway.complete_free', side_effect=responses) as provider, \
             patch('services.grading_service.generate') as gemini:
            process_grading('a', self.db)
        self.assertEqual(provider.call_count, 2)
        gemini.assert_not_called()
        inference = self.db.query(GradingRun).one().response_json['inference']
        self.assertEqual(inference['prompt_tokens'], 20)
        self.assertEqual(inference['completion_tokens'], 10)
        self.assertEqual(inference['reported_cost_usd'], 0)

    def test_uncertain_audit_gates_primary_without_replacing_score(self):
        with patch("services.grading_service.generate", return_value=json.dumps(self.result())):
            process_grading("a", self.db)
        for existing_reason in (None, {"code": "visual_evidence_not_seen", "required_mode": "image_text"}):
            with self.subTest(existing_reason=existing_reason):
                self.answer.needs_review = False
                self.answer.review_status = "none"
                self.answer.final_confidence = 97.5
                self.answer.review_reasons = existing_reason
                self.db.commit()
                with patch("services.grading_service.generate", return_value=json.dumps(
                    self.result(uncertainties=["Cannot read the student work"]))), patch(
                    "services.grading_service._load_answer_source_images", return_value=([], [0])):
                    process_grading("a", self.db, mode="image_text", update_answer=False)
                self.assertEqual(float(self.answer.score), 2)
                self.assertEqual(self.answer.grading_raw_response["mode"], "text_only")
                self.assertTrue(self.answer.needs_review)
                self.assertEqual(self.answer.review_status, "pending")
                self.assertEqual(float(self.answer.final_confidence), 40)
                if existing_reason:
                    self.assertEqual(self.answer.review_reasons["code"], existing_reason["code"])
                    self.assertIn("criterion_evidence_issues", self.answer.review_reasons)
                else:
                    self.assertEqual(self.answer.review_reasons["code"], "criterion_evidence_uncertain")

    def test_uncertain_audit_preserves_disagreement_and_human_override(self):
        routing = {"comparison_pair_id": "pair-1"}
        with patch("services.grading_service.generate", return_value=json.dumps(self.result())):
            process_grading("a", self.db, routing_context=routing)
        self.answer.teacher_override_score = 1.5
        self.answer.review_status = "overridden"
        self.db.commit()
        audit = self.result(points_earned=1, uncertainties=["Symbol unclear"])
        audit["score"] = 1
        with patch("services.grading_service.generate", return_value=json.dumps(audit)), patch(
            "services.grading_service._load_answer_source_images", return_value=([], [0])):
            process_grading(
                "a", self.db, mode="image_text", update_answer=False,
                routing_context=routing,
            )
        self.assertEqual(float(self.answer.score), 2)
        self.assertEqual(float(self.answer.teacher_override_score), 1.5)
        self.assertFalse(self.answer.needs_review)
        self.assertEqual(self.answer.review_status, "overridden")
        self.assertEqual(self.answer.review_reasons["code"], "material_mode_disagreement")
        self.assertIn("criterion_evidence_issues", self.answer.review_reasons)

    def test_mode_comparison_requires_matching_definitions_and_evidence(self):
        pair_id = "pair-definitions"
        routing = {"comparison_pair_id": pair_id}
        with patch("services.grading_service.generate", return_value=json.dumps(self.result())):
            process_grading("a", self.db, routing_context=routing)
            with patch("services.grading_service._load_answer_source_images", return_value=([], [0])):
                process_grading(
                    "a", self.db, mode="image_text", update_answer=False,
                    routing_context=routing,
                )
        # Matching modes do not flag disagreement, but an absent verifier now
        # independently requires review even when their scores agree.
        self.assertTrue(self.answer.needs_review)
        self.assertNotEqual((self.answer.review_reasons or {}).get('code'), 'material_mode_disagreement')
        image_run = self.db.query(GradingRun).filter(GradingRun.mode == "image_text").one()
        original = deepcopy(image_run.response_json)
        changes = {
            "question": {"id": "q", "text": "Changed task"},
            "rubric_version_id": "new-rubric",
            "answer_key": {"id": "new-key", "reference_text": "Changed key"},
            "course_references": {"scope_version_id":"changed","passages":[{"text":"Changed source"}]},
            "policy": {"handwritten_syntax_policy": "require_correct"},
            "student_evidence": [{"id": "answer:a:text", "kind": "combined_ocr", "text": "Corrected OCR"}],
            "student_document_sha256": "changed-file",
        }
        for field, changed in changes.items():
            with self.subTest(field=field):
                response = deepcopy(original)
                response["grading_package"][field] = changed
                image_run.response_json = response
                self.assertTrue(apply_material_disagreement_gate(
                    self.answer, self.db, comparison_pair_id=pair_id
                ))
                self.assertTrue(self.answer.needs_review)
                self.assertEqual(self.answer.review_reasons["code"], "grading_context_changed")
                self.assertEqual(float(self.answer.final_confidence), 40)
        self.assertFalse(apply_material_disagreement_gate(self.answer, self.db))

    def test_unpaired_regrade_cannot_clear_a_paired_disagreement(self):
        pair_id = "pair-disagreement"
        routing = {"comparison_pair_id": pair_id}
        with patch("services.grading_service.generate", return_value=json.dumps(self.result())):
            process_grading("a", self.db, routing_context=routing)
        image_result = self.result(points_earned=1)
        image_result["score"] = 1
        with patch("services.grading_service.generate", return_value=json.dumps(image_result)), patch(
            "services.grading_service._load_answer_source_images", return_value=([], [0])
        ):
            process_grading(
                "a", self.db, mode="image_text", update_answer=False,
                routing_context=routing,
            )
        self.assertEqual(self.answer.review_reasons["code"], "material_mode_disagreement")

        self.q.question_text = "Inspect the diagram and explain the result."
        self.db.commit()
        with patch("services.grading_service.generate", return_value=json.dumps(image_result)):
            process_grading("a", self.db, mode="text_only")
        self.assertEqual(self.answer.review_reasons["code"], "material_mode_disagreement")
        self.assertEqual(
            self.answer.review_reasons["visual_evidence_guard"]["code"],
            "visual_evidence_not_seen",
        )

    def test_agreeing_pair_cannot_clear_independent_review_gate(self):
        routing = {'comparison_pair_id': 'fresh-pair'}
        response = self.result()
        response['llm_confidence'] = 80
        with patch('services.grading_service.generate', return_value=json.dumps(response)):
            process_grading('a', self.db, routing_context=routing)
            with patch('services.grading_service._load_answer_source_images', return_value=([], [0])):
                process_grading('a', self.db, mode='image_text', update_answer=False, routing_context=routing)
        self.answer.review_reasons = {'code': 'material_mode_disagreement',
                                     'criterion_evidence_issues': [{'uncertainties': ['unclear']} ]}
        self.answer.needs_review = True
        self.db.commit()
        self.assertFalse(apply_material_disagreement_gate(self.answer, self.db, comparison_pair_id='fresh-pair'))
        self.assertTrue(self.answer.needs_review)
        self.assertEqual(self.answer.review_status, 'pending')
        self.assertIn('criterion_evidence_issues', self.answer.review_reasons)
        self.assertIn('paired_review_policies', self.answer.review_reasons)

    def test_audit_review_gate_reaches_queue_without_replacing_displayed_grade(self):
        with patch('services.grading_service.generate', return_value=json.dumps(self.result())):
            process_grading('a', self.db)
        self.answer.needs_review = False
        self.answer.review_status = 'none'
        self.db.commit()
        displayed = deepcopy(self.answer.grading_raw_response)
        response = self.result(points_earned=1)
        response.update(score=1, llm_confidence=70)
        with patch('services.grading_service.generate', return_value=json.dumps(response)), \
             patch('services.grading_service._load_answer_source_images', return_value=([], [0])):
            process_grading('a', self.db, mode='image_text', update_answer=False)
        self.assertEqual(float(self.answer.score), 2)
        self.assertEqual(self.answer.grading_raw_response, displayed)
        self.assertTrue(self.answer.needs_review)
        self.assertIn('low_model_confidence', self.answer.review_reasons['audit_review_policy']['reasons'])

    def test_structural_key_conflict_fails_before_provider_call(self):
        self.db.add(AnswerKeyVersion(id='bad-key', question_id='q', version_number=2,
            status='approved', mode='no_fixed_answer', reference_text='Fixed answer',
            acceptable_answers=[], document_refs=[]))
        self.db.commit()
        with patch('services.grading_service.generate') as generate:
            with self.assertRaisesRegex(ValueError, 'no-fixed-answer'):
                process_grading('a', self.db)
        generate.assert_not_called()
        self.assertEqual(self.db.query(GradingRun).count(), 0)

    def test_definition_advisory_is_snapshotted_and_preserves_override(self):
        self.db.add(AnswerKeyVersion(id='new-key', question_id='q', version_number=2,
            status='approved', mode='reference', reference_text='New key',
            acceptable_answers=[], document_refs=[]))
        self.answer.teacher_override_score = 1.5
        self.answer.review_status = 'overridden'
        self.db.commit()
        result = self.result(reference_refs=['key:new-key'])
        with patch('services.grading_service.generate', return_value=json.dumps(result)):
            process_grading('a', self.db)
        run = self.db.query(GradingRun).one()
        advisories = run.response_json['validation']['definition_advisories']
        self.assertEqual([item['code'] for item in advisories],
                         ['approved_key_legacy_reference_mismatch'])
        self.assertEqual(float(run.final_confidence), 40)
        self.assertTrue(run.needs_review)
        self.assertEqual(self.answer.review_status, 'overridden')
        self.assertFalse(self.answer.needs_review)
        self.assertEqual(float(self.answer.teacher_override_score), 1.5)
        self.assertIn('definition_advisories', self.answer.review_reasons)

    def test_auto_routing_reason_is_saved_on_answer_and_run(self):
        from models import QuestionGradingPolicy
        self.db.add(QuestionGradingPolicy(question_id='q', mode='text_only', enabled=True))
        self.db.commit()
        with patch('services.grading_service.generate', return_value=json.dumps(self.result())):
            process_grading_with_policy('a', self.db)
        routing = self.answer.grading_raw_response['routing']
        package_routing = self.db.query(GradingRun).one().response_json['grading_package']['routing']
        self.assertEqual(routing['requested_mode'], 'auto')
        self.assertEqual(routing['route_reasons'][0]['code'], 'explicit_question_policy')
        self.assertEqual(package_routing['route_reasons'], routing['route_reasons'])
        self.assertEqual(package_routing['selected_mode'], 'text_only')

    def test_confident_conceptual_method_flag_is_persisted_without_changing_proposal(self):
        response = self.result(points_earned=0, decision_check=check(method_status='invalid', error_type='conceptual'),
                               evidence_refs=['student:segment:1'], reference_refs=['instructor:answer_key'])
        response.update(score=0, llm_confidence=100)
        verification = {'criteria': [{'criterion_id':'logic', 'verdict':'supported',
            'explanation':'Incorrect direction under the supplied criterion.',
            'decision_check':check(method_status='invalid', error_type='conceptual')}], 'summary':'Checked.'}
        from services.free_model_gateway import FreeCompletion
        with patch.dict(os.environ, {'VERIFICATION_ENABLED':'true'}), \
             patch('services.grading_service.generate', return_value=json.dumps(response)), \
             patch('services.verification_agent.complete', return_value=FreeCompletion(json.dumps(verification), {})), \
             patch('services.source_consultation_service.prepare_consultation_context', return_value=None):
            process_grading('a', self.db)
        run = self.db.query(GradingRun).one()
        self.assertEqual(float(run.score), 0)
        self.assertTrue(run.needs_review)
        self.assertTrue(self.answer.needs_review)
        self.assertEqual(self.answer.review_status, 'pending')
        self.assertIn('conceptual_partial_credit_check', run.response_json['review_policy']['reasons'])
        self.assertEqual(run.response_json['verification']['original_model_response']['criteria'][0]['verdict'], 'supported')
        self.assertEqual(run.response_json['original_model_response']['attempts'][0]['score'], 0)
        self.db.expire_all()
        saved = self.db.query(GradingRun).one().response_json
        self.assertEqual(saved['decision_review']['version'], '2026-10-19.v8')
        self.assertTrue(saved['validation']['evidence_issues'][0]['decision_checks'])

    def test_new_decision_guard_preserves_instructor_override_and_earlier_run(self):
        with patch('services.grading_service.generate', return_value=json.dumps(self.result())):
            process_grading('a', self.db)
        original = self.db.query(GradingRun).one()
        snapshot = deepcopy(original.response_json)
        self.answer.teacher_override_score = 1.5
        self.answer.review_status = 'overridden'
        self.answer.needs_review = False
        self.db.commit()
        changed = self.result(points_earned=0, decision_check=check(method_status='uncertain', policy_status='ambiguous'))
        changed.update(score=0, llm_confidence=100)
        with patch('services.grading_service.generate', return_value=json.dumps(changed)):
            process_grading('a', self.db)
        self.db.expire_all()
        self.assertEqual(self.db.get(GradingRun, original.id).response_json, snapshot)
        self.assertEqual(float(self.answer.teacher_override_score), 1.5)
        self.assertEqual(self.answer.review_status, 'overridden')
        self.assertFalse(self.answer.needs_review)
        latest = self.db.query(GradingRun).filter(GradingRun.id != original.id).one()
        self.assertTrue(latest.needs_review)
        self.assertIn('marking_policy_uncertain', latest.response_json['review_policy']['reasons'])

    def test_citation_correction_cannot_clear_initial_method_uncertainty(self):
        initial = self.result(evidence_refs=['invented'], reference_refs=['instructor:answer_key'],
                              decision_check=check(work_status='unclear', error_type='unclear'))
        corrected = self.result(evidence_refs=['student:segment:1'], reference_refs=['instructor:answer_key'],
                                decision_check=check())
        with patch('services.grading_service.generate', side_effect=[json.dumps(initial), json.dumps(corrected)]):
            process_grading('a', self.db)
        saved = self.db.query(GradingRun).one().response_json
        self.assertEqual(saved['criteria_scores'][0]['decision_check']['work_status'], 'complete')
        self.assertIn('unclear_student_work', saved['review_policy']['reasons'])
        self.assertEqual(len(saved['original_model_response']['attempts']), 2)


if __name__ == "__main__":
    unittest.main()
