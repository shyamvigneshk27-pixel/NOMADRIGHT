#!/usr/bin/env python3
"""
Tests for the curated scenario cache.

Two things have to hold, and the second matters more than the first:
  1. The demo questions hit their curated answer, including when ASR mangles
     them (which it does - see the deliberately misspelt cases below).
  2. Anything NOT curated misses and falls through to the full pipeline. A
     false hit is far worse than a miss: a miss costs a few seconds, a false
     hit confidently speaks the wrong scheme's answer to a migrant worker.

Uses the real multilingual-e5-small embedder, since the thresholds only mean
anything against real vectors. Loaded once for the whole class (~20s).
"""
import os
import sys
import unittest
import warnings

warnings.filterwarnings("ignore")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..")))

from pocketinfer.applications.nomad_right import constants
from pocketinfer.applications.nomad_right.scenario_cache import (
    MATCH_THRESHOLD,
    ScenarioCache,
)

PDS = constants.SCHEME_CODE_PDS


# Module-level so the ~20s model load and the one-off phrasing embedding are
# paid once for the whole file, not once per TestCase subclass.
_SHARED = {}


def _shared_cache():
    if "cache" not in _SHARED:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(constants.EMBEDDING_MODEL_NAME, device="cpu")
        cache = ScenarioCache(lambda: model)
        assert cache._ensure_ready(), "cache failed to build"
        _SHARED["cache"] = cache
    return _SHARED["cache"]


class _RealEmbedderCase(unittest.TestCase):
    cache = None

    @classmethod
    def setUpClass(cls):
        cls.cache = _shared_cache()

    def hit(self, query, context=None):
        return self.cache.match(query, context_scheme_code=context)


class TestDemoScenario(_RealEmbedderCase):
    """The exact three-turn sequence being recorded for the demo video."""

    def test_turn1_portability_question(self):
        # Verbatim as written, ASR-style typo ("raion") included.
        got = self.hit("Im a migrant worker from uttar pradesh Can I get my raion goods in Tamil Nadu")
        self.assertIsNotNone(got, "turn 1 must hit the cache")
        self.assertEqual(got.entry.entry_id, "PDS_ONORC_PORTABILITY")
        self.assertEqual(got.entry.scheme_code, PDS)

    def test_turn1_maharashtra_variant(self):
        got = self.hit("i am a migrant worker maharastra can i get ration goods in tamilnadu")
        self.assertIsNotNone(got)
        self.assertEqual(got.entry.entry_id, "PDS_ONORC_PORTABILITY")

    def test_turn2_how_to_apply(self):
        got = self.hit("How to apply for PDS scheme?", context=PDS)
        self.assertIsNotNone(got, "turn 2 must hit the cache")
        self.assertEqual(got.entry.entry_id, "PDS_HOW_TO_APPLY")

    def test_turn3_documents_with_pds_context(self):
        got = self.hit("what are the documents required?", context=PDS)
        self.assertIsNotNone(got, "turn 3 must hit once turn 1/2 established PDS")
        self.assertEqual(got.entry.entry_id, "PDS_DOCUMENTS_ELIGIBILITY")

    def test_full_three_turn_sequence_carries_context(self):
        """Replays the demo the way app.py drives it: last_scheme_code from
        each turn feeds the next, which is what lets the bare 'what documents
        are required?' resolve to PDS."""
        context = None
        expected = [
            ("Im a migrant worker from uttar pradesh Can I get my raion goods in Tamil Nadu",
             "PDS_ONORC_PORTABILITY"),
            ("How to apply for PDS scheme?", "PDS_HOW_TO_APPLY"),
            ("what are the documents required?", "PDS_DOCUMENTS_ELIGIBILITY"),
        ]
        for query, entry_id in expected:
            got = self.hit(query, context=context)
            self.assertIsNotNone(got, f"{query!r} missed")
            self.assertEqual(got.entry.entry_id, entry_id, f"{query!r} matched the wrong entry")
            context = got.entry.scheme_code


class TestHindiAndTamil(_RealEmbedderCase):
    """The demo may be spoken in Hindi or Tamil; ASR emits native script."""

    def test_hindi_portability(self):
        got = self.hit("क्या मैं दूसरे राज्य में अपना राशन ले सकता हूं")
        self.assertIsNotNone(got)
        self.assertEqual(got.entry.entry_id, "PDS_ONORC_PORTABILITY")

    def test_hindi_how_to_apply(self):
        got = self.hit("पीडीएस योजना के लिए आवेदन कैसे करें", context=PDS)
        self.assertIsNotNone(got)
        self.assertEqual(got.entry.entry_id, "PDS_HOW_TO_APPLY")

    def test_hindi_documents(self):
        got = self.hit("कौन से दस्तावेज चाहिए", context=PDS)
        self.assertIsNotNone(got)
        self.assertEqual(got.entry.entry_id, "PDS_DOCUMENTS_ELIGIBILITY")

    def test_tamil_portability(self):
        got = self.hit("என் ரேஷன் கார்டு வேறு மாநிலத்தில் வேலை செய்யுமா")
        self.assertIsNotNone(got)
        self.assertEqual(got.entry.entry_id, "PDS_ONORC_PORTABILITY")

    def test_asr_dropped_character_still_matches(self):
        """Real ASR output observed on-device drops characters ('मुे' for
        'मुझे'); that must not cost a hit."""
        got = self.hit("मेरा राशन कार्ड उतर प्रदेश का है कया तमिलनाडु में चलेगा")
        self.assertIsNotNone(got)
        self.assertEqual(got.entry.entry_id, "PDS_ONORC_PORTABILITY")


class TestMissesFallThrough(_RealEmbedderCase):
    """Everything not curated must return None so the real pipeline answers."""

    def test_generic_scheme_question_is_not_hijacked(self):
        """'tell me about the schemes' is far too broad to answer with a PDS
        script - it belongs to the RAG path."""
        self.assertIsNone(self.hit("can you tell me about the schemes?"))

    def test_unrelated_scheme_falls_through(self):
        for query in [
            "how do I get health insurance under PMJAY",
            "what is the pension scheme for old age",
            "I want to register for e-shram card",
            "how many days of work does MGNREGS guarantee",
        ]:
            self.assertIsNone(self.hit(query), f"{query!r} wrongly hit the PDS cache")

    def test_completely_unrelated_falls_through(self):
        for query in ["what is the weather today", "what time is the next bus", "मुझे भूख लगी है"]:
            self.assertIsNone(self.hit(query), f"{query!r} wrongly hit the cache")

    def test_empty_input_falls_through(self):
        self.assertIsNone(self.hit(""))
        self.assertIsNone(self.hit("   "))


class TestContextGate(_RealEmbedderCase):
    """'What documents are required?' is meaningless without a subject."""

    def test_documents_question_without_context_falls_through(self):
        self.assertIsNone(
            self.hit("what are the documents required?"),
            "with no scheme established, this must go to the pipeline rather "
            "than assume PDS",
        )

    def test_documents_question_under_other_scheme_falls_through(self):
        self.assertIsNone(
            self.hit("what are the documents required?", context="PMJAY"),
            "the previous turn was about PMJAY - answering with PDS documents "
            "would be a confident wrong answer",
        )

    def test_hindi_documents_question_without_context_falls_through(self):
        self.assertIsNone(self.hit("कौन से दस्तावेज चाहिए"))


class TestSeparationMargin(_RealEmbedderCase):
    """The threshold must sit in real space, not squeak past by luck."""

    def test_hits_clear_the_threshold_with_margin(self):
        for query in [
            "Im a migrant worker from uttar pradesh Can I get my raion goods in Tamil Nadu",
            "How to apply for PDS scheme?",
        ]:
            got = self.hit(query, context=PDS)
            self.assertIsNotNone(got)
            self.assertGreaterEqual(
                got.score, MATCH_THRESHOLD,
                f"{query!r} scored {got.score:.3f}, at/below the {MATCH_THRESHOLD} threshold",
            )

    def test_lookup_returns_a_response_package(self):
        pkg = self.cache.lookup("How to apply for PDS scheme?", context_scheme_code=PDS)
        self.assertIsNotNone(pkg)
        self.assertEqual(pkg.scheme_code, PDS)
        self.assertTrue(pkg.voice_text)
        self.assertTrue(pkg.display_top_text)
        self.assertLessEqual(
            len(pkg.voice_text.split()), constants.MAX_VOICE_WORDS,
            "answer exceeds the spoken-length ceiling",
        )


class TestDisabledCacheIsSafe(unittest.TestCase):
    """A cache that can't build must be invisible, not fatal."""

    def test_no_embedder_means_every_query_falls_through(self):
        cache = ScenarioCache(lambda: None)
        self.assertIsNone(cache.lookup("How to apply for PDS scheme?"))

    def test_broken_embedder_means_every_query_falls_through(self):
        def boom():
            raise RuntimeError("model gone")
        cache = ScenarioCache(boom)
        self.assertIsNone(cache.lookup("How to apply for PDS scheme?"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
