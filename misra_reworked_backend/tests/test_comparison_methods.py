"""Method-comparison invariants; optional metric packages are tested when installed."""
import importlib.util
import math
import unittest

from comparison_methods import edit_distance, fit_cutoff, lexical_scores, normalize_scores, summarize_method, tokens, vector_scores
from rubric_pilot import Answer


class ComparisonMethodsTests(unittest.TestCase):
    def test_normalized_l2_dot_and_angular_cannot_improve_cosine_ranking(self):
        reference = [1.0, 0.0]
        vectors = [[0.9, math.sqrt(1 - 0.9 ** 2)], [0.5, math.sqrt(0.75)], [-1.0, 0.0]]
        values = [vector_scores(reference, v) for v in vectors]
        for value in values:
            self.assertAlmostEqual(value["cosine"], value["dot_product"])
            self.assertAlmostEqual(value["euclidean_similarity"] ** 2, 2 - 2 * value["cosine"])
        for method in ("cosine", "dot_product", "euclidean_similarity", "angular_similarity"):
            self.assertEqual(sorted(range(3), key=lambda i: values[i][method], reverse=True), [0, 1, 2])

    def test_negation_signs_and_operators_survive_custom_tokenization(self):
        self.assertEqual(tokens("not 246 J; 82 + 3; -246 × 1"), ["not", "246", "j", "82", "+", "3", "-", "246", "*", "1"])

    def test_edit_distance_counts_substitutions_insertions_and_deletions(self):
        self.assertEqual(edit_distance(["work", "is", "246"], ["work", "is", "not", "246"]), 1)
        self.assertEqual(edit_distance("abc", "adc"), 1)
        self.assertEqual(edit_distance([], ["x", "y"]), 2)

    def test_stress_errors_do_not_raise_the_calibration_threshold(self):
        result = summarize_method({"a": 0.8, "b": 0.5, "contradiction": 0.99, "paraphrase": 0.7},
                                  {"a": True, "b": False}, {"contradiction": False, "paraphrase": True})
        self.assertEqual(result["cutoff"], 0.8)
        self.assertEqual(result["unsafe_stress_matches"], ["contradiction"])
        self.assertEqual(result["safe_stress_referred"], ["paraphrase"])

    def test_inapplicable_method_does_not_become_a_perfect_match(self):
        result = summarize_method({"a": None, "b": None, "stress": None},
                                  {"a": True, "b": False}, {"stress": False})
        self.assertIsNone(result["cutoff"])
        self.assertEqual(result["calibration_resolved"], 0)

    def test_real_numeric_scalars_are_normalized_without_accepting_booleans(self):
        from fractions import Fraction
        values = normalize_scores([Fraction(1, 2), None, 1])
        self.assertEqual(values, [0.5, None, 1.0])
        self.assertIs(type(values[0]), float)
        for value in (True, float("nan"), "0.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_scores([value])

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "optional NumPy environment required")
    def test_numpy_keyword_scores_can_be_aggregated_as_native_json_numbers(self):
        import numpy as np
        values = normalize_scores([np.float64(0.8), np.float64(0.5), np.float64(0.99)])
        result = summarize_method(dict(zip(["a", "b", "stress"], values)),
                                  {"a": True, "b": False}, {"stress": False})
        self.assertEqual(result["unsafe_stress_matches"], ["stress"])

    def test_nonfinite_scores_and_missing_cases_are_rejected(self):
        with self.assertRaises(ValueError):
            fit_cutoff({"a": float("nan")}, {"a": True})
        with self.assertRaises(ValueError):
            summarize_method({"a": 1}, {"a": True}, {"missing": False})

    def test_constructed_fixtures_cannot_claim_manual_page_verification(self):
        value = {"answer_id": "synthetic", "source_sha256": "a" * 64,
                 "transcription_method": "synthetic_text", "transcription_status": "constructed_fixture",
                 "segments": [{"id": "s", "text": "Synthetic text.", "crossed_out": False}]}
        Answer.model_validate(value)
        with self.assertRaises(ValueError):
            Answer.model_validate({**value, "transcription_status": "checked_by_agent_against_page"})

    @unittest.skipUnless(importlib.util.find_spec("nltk") and importlib.util.find_spec("rouge_score"), "optional lexical metric environment required")
    def test_lexical_identity_and_math_operator_difference(self):
        reference = "W = 82 * 3 = 246 J"
        same, _ = lexical_scores(reference, reference, {"result": ["246"]})
        different, _ = lexical_scores(reference, "W = 82 + 3 = 246 J", {"result": ["246"]})
        self.assertAlmostEqual(same["bleu4"], 1)
        self.assertEqual(same["wer_similarity"], 1)
        self.assertLess(different["rouge1_operators_f1"], same["rouge1_operators_f1"])
        # Standard ROUGE discards this operator and cannot distinguish the texts.
        self.assertEqual(different["rouge1_f1"], same["rouge1_f1"])


if __name__ == "__main__":
    unittest.main()
