import unittest
from services.hybrid_retrieval_service import hybrid_scores


class HybridRankingTests(unittest.TestCase):
    def test_empty_and_no_overlap_do_not_invent_evidence(self):
        self.assertEqual(hybrid_scores([], 'work'), ([], []))
        scores, _ = hybrid_scores(['xyzzy qqqq'], 'force work')
        self.assertEqual(scores, [0])
        self.assertEqual(hybrid_scores(['work force'], '')[0], [0])

    def test_morphological_match_recovers_zero_bm25_candidate(self):
        scores, details = hybrid_scores(['Accelerating objects gain velocity.',
                                          'Water boils in a kettle.'], 'acceleration')
        self.assertEqual(details[0]['bm25'], 0)
        self.assertGreater(details[0]['character_cosine'], .1)
        self.assertGreater(scores[0], scores[1])

    def test_arabic_diacritics_and_unicode_are_normalized(self):
        scores, _ = hybrid_scores(['القُوَّة والشغل', 'زهور وماء'], 'القوة')
        self.assertGreater(scores[0], scores[1])

    def test_bounds_and_determinism(self):
        texts = ['work force', 'work force']
        first = hybrid_scores(texts, 'work')
        self.assertEqual(first, hybrid_scores(texts, 'work'))
        self.assertEqual(first[0][0], first[0][1])
        tied_scores, _ = hybrid_scores(['work force'] * 60, 'work')
        self.assertEqual(len(set(tied_scores)), 1)  # Ties at the rank window boundary remain equal.
        self.assertGreater(tied_scores[-1], 0)
        for texts, query in [(['x'] * 6001, 'x'), (['x'], 'x' * 5001)]:
            with self.assertRaises(ValueError):
                hybrid_scores(texts, query)
