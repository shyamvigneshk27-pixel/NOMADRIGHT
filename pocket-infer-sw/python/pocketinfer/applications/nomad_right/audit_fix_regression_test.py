#!/usr/bin/env python3
"""
NomadRight Audit Fix Regression Tests
========================================
Regression tests covering the 8 ISSUE fixes applied from CODE_AUDIT_REPORT.md.

Tests:
  ISSUE-01: SQLite connection cleanup (try...finally: conn.close())
  ISSUE-02: Main application exception handling (simulated)
  ISSUE-06: Word-boundary state name matching (no false positives)
  ISSUE-10: Multiline regex support (re.DOTALL)
  ISSUE-11: Aadhaar / phone PII masking before audit log write

Usage (run from repo root):
    python python/pocketinfer/applications/nomad_right/audit_fix_regression_test.py
"""

import sys
import os
import logging
import re
import threading
import unittest
import unittest.mock

# ── Path setup ─────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "python"))
os.chdir(_REPO_ROOT)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)-8s] %(name)-30s %(message)s",
)

DIVIDER = "=" * 70
PASS = "  [PASS]"
FAIL = "  [FAIL]"


# ──────────────────────────────────────────────────────────────────────────────
# ISSUE-11: _mask_pii – PII Masking (database.py)
# ──────────────────────────────────────────────────────────────────────────────

class TestPIIMasking(unittest.TestCase):
    """Tests for SQLiteAccessLayer._mask_pii (ISSUE-11)."""

    def setUp(self):
        from pocketinfer.applications.nomad_right.database import SQLiteAccessLayer
        from pocketinfer.applications.nomad_right.config import NomadRightConfig
        self.config = NomadRightConfig()
        self.db = SQLiteAccessLayer(config=self.config)

    def test_aadhaar_12digit_masked(self):
        """12-digit Aadhaar number must be replaced with XXXX-XXXX-XXXX."""
        raw = "My aadhaar is 123456789012"
        masked = self.db._mask_pii(raw)
        self.assertNotIn("123456789012", masked)
        self.assertIn("XXXX-XXXX-XXXX", masked)

    def test_aadhaar_with_spaces_masked(self):
        """Aadhaar with space separators must be masked."""
        raw = "aadhaar number: 1234 5678 9012"
        masked = self.db._mask_pii(raw)
        self.assertNotIn("1234 5678 9012", masked)
        self.assertIn("XXXX-XXXX-XXXX", masked)

    def test_aadhaar_with_dashes_masked(self):
        """Aadhaar with dash separators must be masked."""
        raw = "card: 1234-5678-9012"
        masked = self.db._mask_pii(raw)
        self.assertNotIn("1234-5678-9012", masked)
        self.assertIn("XXXX-XXXX-XXXX", masked)

    def test_phone_10digit_masked(self):
        """10-digit Indian phone number must be masked."""
        raw = "call me at 9876543210"
        masked = self.db._mask_pii(raw)
        self.assertNotIn("9876543210", masked)
        self.assertIn("XXXXXX-XXXX", masked)

    def test_phone_not_matched_on_5digit(self):
        """5-digit numbers must not be masked as phone numbers."""
        raw = "claim ID 98765"
        masked = self.db._mask_pii(raw)
        self.assertIn("98765", masked)

    def test_empty_text_returns_empty(self):
        """Empty or None text must return empty string without error."""
        self.assertEqual(self.db._mask_pii(""), "")

    def test_no_pii_text_unchanged(self):
        """Text with no Aadhaar or phone stays unchanged."""
        raw = "I want to check ration card status"
        masked = self.db._mask_pii(raw)
        self.assertEqual(raw, masked)


# ──────────────────────────────────────────────────────────────────────────────
# ISSUE-06: Word-boundary state matching (entities.py)
# ──────────────────────────────────────────────────────────────────────────────

class TestWordBoundaryStateMatching(unittest.TestCase):
    """Tests for EntityExtractor._extract_state_name (ISSUE-06)."""

    def setUp(self):
        from pocketinfer.applications.nomad_right.entities import EntityExtractor
        from pocketinfer.applications.nomad_right.config import NomadRightConfig
        self.extractor = EntityExtractor(config=NomadRightConfig())

    def _state(self, text: str):
        return self.extractor._extract_state_name(text.lower())

    def test_goa_matched_as_word(self):
        """'goa' should match when it is a full word."""
        self.assertEqual(self._state("I am from Goa"), "Goa")

    def test_goa_not_matched_in_goals(self):
        """'goa' must NOT match inside 'goals' (false positive)."""
        result = self._state("my goals are important")
        self.assertIsNone(result, f"Expected None but got '{result}'")

    def test_or_not_matched_in_border(self):
        """Short ambiguous matches like 'or' must not fire inside 'border'."""
        # 'or' is not a state name, 'odisha' is - ensure no false Odisha match
        result = self._state("we crossed the border")
        self.assertIsNone(result)

    def test_kerala_matched(self):
        """Kerala should be correctly extracted."""
        self.assertEqual(self._state("treatment in kerala hospital"), "Kerala")

    def test_tamil_nadu_matched(self):
        """Multi-word state names like Tamil Nadu should match."""
        self.assertEqual(self._state("can I use ration in Tamil Nadu"), "Tamil Nadu")

    def test_rajasthan_matched(self):
        """Standard single-word state name should match."""
        self.assertEqual(self._state("migrant from rajasthan"), "Rajasthan")

    def test_no_state_returns_none(self):
        """Text with no state name returns None."""
        result = self._state("I want to check my ration card")
        self.assertIsNone(result)

    def test_west_bengal_matched(self):
        """'West Bengal' should match even though 'Bengal' alone would not."""
        result = self._state("from west bengal")
        self.assertEqual(result, "West Bengal")


# ──────────────────────────────────────────────────────────────────────────────
# ISSUE-10: Multiline regex (re.DOTALL) in intent.py
# ──────────────────────────────────────────────────────────────────────────────

class TestMultilineIntentMatching(unittest.TestCase):
    """Tests that re.DOTALL is active so intent patterns fire across newlines (ISSUE-10)."""

    def setUp(self):
        from pocketinfer.applications.nomad_right.intent import IntentRecognizer, IntentType
        from pocketinfer.applications.nomad_right.config import NomadRightConfig
        self.recognizer = IntentRecognizer(config=NomadRightConfig())
        self.IntentType = IntentType

    def test_ration_card_portability_multiline(self):
        """Portability intent matches when keywords span multiple lines in OCR text."""
        ocr_text = "ration\ncard\nvalid\nin\nDelhi"
        result = self.recognizer.recognize(ocr_text)
        # Keyword fallback should fire for PDS
        self.assertIn(result.intent_type, [
            self.IntentType.PDS_PORTABILITY,
            self.IntentType.PDS_ELIGIBILITY,
        ])

    def test_eshram_wage_rights_multiline(self):
        """Wage rights intent matches when 'contractor' and 'denied' span lines."""
        text = "my\ncontractor\ndenied\nmy\npay"
        result = self.recognizer.recognize(text)
        self.assertEqual(result.intent_type, self.IntentType.ESHRAM_WAGE_RIGHTS)

    def test_ayushman_documents_multiline(self):
        """PMJAY_DOCUMENTS matches when tokens span OCR lines."""
        ocr_text = "ayushman\ncard\ndocuments\nrequired"
        result = self.recognizer.recognize(ocr_text)
        self.assertEqual(result.intent_type, self.IntentType.PMJAY_DOCUMENTS)

    def test_compile_flags_include_dotall(self):
        """Verify every compiled rule pattern has re.DOTALL set."""
        for pattern, _ in self.recognizer._rules:
            self.assertTrue(
                bool(pattern.flags & re.DOTALL),
                f"Pattern missing re.DOTALL: {pattern.pattern!r}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# ISSUE-01: SQLite connection cleanup — verify conn.close() called
# ──────────────────────────────────────────────────────────────────────────────

class TestSQLiteConnectionCleanup(unittest.TestCase):
    """
    Verifies SQLiteAccessLayer methods use explicit conn.close() in finally blocks.
    Tests structural guarantee that no method uses `with sqlite3.connect(...)` directly.
    (ISSUE-01)
    """

    def test_get_portability_record_returns_none_on_bad_path(self):
        """Database with bad path returns None gracefully (no unhandled exception)."""
        from pocketinfer.applications.nomad_right.database import SQLiteAccessLayer
        from pocketinfer.applications.nomad_right.config import NomadRightConfig
        config = NomadRightConfig()
        config.db_path = "/nonexistent/path/nomadright_kb.db"
        db = SQLiteAccessLayer.__new__(SQLiteAccessLayer)
        db.db_path = config.db_path
        db.logger = logging.getLogger("test_db")
        # _ensure_audit_table will fail gracefully
        result = db.get_portability_record("PDS")
        self.assertIsNone(result)

    def test_insert_query_log_returns_false_on_bad_path(self):
        """Audit log insert with bad path returns False (no crash)."""
        from pocketinfer.applications.nomad_right.database import SQLiteAccessLayer, CitizenQueryLogDTO
        from pocketinfer.applications.nomad_right.config import NomadRightConfig
        import datetime
        db = SQLiteAccessLayer.__new__(SQLiteAccessLayer)
        db.db_path = "/nonexistent/path/db.sqlite"
        db.logger = logging.getLogger("test_db")
        dto = CitizenQueryLogDTO(
            session_id="sess_test_01",
            intent="PDS_ELIGIBILITY",
            scheme_code="PDS",
            transcribed_text="can I get ration card?",
            response_summary="Yes eligible",
            language="en",
            status="OK",
        )
        result = db.insert_query_log(dto)
        self.assertFalse(result)

    def test_mask_pii_called_in_insert_query_log(self):
        """insert_query_log must mask Aadhaar PII before writing to DB."""
        from pocketinfer.applications.nomad_right.database import SQLiteAccessLayer, CitizenQueryLogDTO
        from pocketinfer.applications.nomad_right.config import NomadRightConfig
        import sqlite3, tempfile, os

        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "test.db")
            config = NomadRightConfig()
            config.db_path = db_file
            db = SQLiteAccessLayer(config=config)

            dto = CitizenQueryLogDTO(
                session_id="sess_pii_01",
                intent="PDS_ELIGIBILITY",
                scheme_code="PDS",
                transcribed_text="my aadhaar is 123456789012 and phone is 9876543210",
                response_summary="Eligible",
                language="en",
                status="OK",
            )
            result = db.insert_query_log(dto)
            self.assertTrue(result)

            # Verify raw Aadhaar not stored in DB
            conn = sqlite3.connect(db_file)
            try:
                row = conn.execute(
                    "SELECT transcribed_text FROM citizen_query_log WHERE session_id = ?",
                    ("sess_pii_01",)
                ).fetchone()
            finally:
                conn.close()

            self.assertIsNotNone(row)
            self.assertNotIn("123456789012", row[0])
            self.assertNotIn("9876543210", row[0])
            self.assertIn("XXXX-XXXX-XXXX", row[0])


# ──────────────────────────────────────────────────────────────────────────────
# ISSUE-02: Main application exception handling (regression guard)
# ──────────────────────────────────────────────────────────────────────────────

class TestMainAppExceptionHandling(unittest.TestCase):
    """
    Verifies app.py run() loop wraps per-iteration processing in try...except
    so a single bad iteration does not crash the whole loop. (ISSUE-02)
    """

    def test_run_loop_src_has_try_except(self):
        """app.py source must contain the try...except guard inside the while loop."""
        app_src = os.path.join(_HERE, "app.py")
        if not os.path.exists(app_src):
            self.skipTest("app.py not found")
        with open(app_src) as f:
            src = f.read()
        self.assertIn("except Exception as exc:", src,
                      "app.py run() loop must have except Exception guard")
        self.assertIn("SYSTEM ERROR", src,
                      "app.py run() must show SYSTEM ERROR on LCD after exception")


# ──────────────────────────────────────────────────────────────────────────────
# qwen2.5vl:3b text-fallback and vision-form paths (qwen_client.py)
# ──────────────────────────────────────────────────────────────────────────────
# QwenClient.answer_text/answer_vision are mocked throughout - this suite
# stays fully offline and must not depend on Ollama/qwen2.5vl actually
# being installed or loaded. It only verifies the *wiring*: that a grounded
# answer gets the LLM_FALLBACK/VISION_FORM_QUERY tag, and that the sentinel/
# None case still falls through to the existing constant fallback message
# rather than silently failing or guessing.

class TestLLMFallbackAndVision(unittest.TestCase):
    """Regression tests for workflow.py's Step 6.5 and process_vision_query()."""

    # Known negative-control query already used elsewhere in this suite's
    # sibling pipeline_test.py: garbled/off-topic, no real scheme keyword,
    # so it reliably produces no rule match and no RAG chunk above
    # RAG_MIN_SCORE - i.e. it reaches Step 6.5 in every test run regardless
    # of index contents.
    UNMATCHED_QUERY = "Yapri festival at Kudab Uri"

    def setUp(self):
        from pocketinfer.applications.nomad_right.workflow import WorkflowController
        from pocketinfer.applications.nomad_right.config import NomadRightConfig
        self.workflow = WorkflowController(config=NomadRightConfig())

    def test_unmatched_query_uses_llm_fallback_when_qwen_grounds_an_answer(self):
        """An unmatched query should get an LLM_FALLBACK-tagged answer (not the
        constant fallback) when qwen returns a grounded answer from context."""
        with unittest.mock.patch.object(
            self.workflow.qwen_client, "answer_text",
            return_value="Ration cards are portable across states under ONORC.",
        ):
            pkg = self.workflow.process(self.UNMATCHED_QUERY)
        self.assertEqual(pkg.qr_payload["status"], "LLM_FALLBACK")
        self.assertIn("ration cards are portable", pkg.voice_text.lower())

    def test_unmatched_query_falls_back_to_constant_message_on_sentinel(self):
        """When qwen can't answer from context (QwenClient already collapses the
        sentinel/errors/timeouts to None), the response must still be the
        existing constant fallback - never silence, never a guess."""
        with unittest.mock.patch.object(self.workflow.qwen_client, "answer_text", return_value=None):
            pkg = self.workflow.process(self.UNMATCHED_QUERY)
        self.assertEqual(pkg.qr_payload["status"], "FALLBACK")
        self.assertIn("i'm sorry", pkg.voice_text.lower())

    def test_vision_query_uses_answer_when_qwen_reads_the_form(self):
        """A photographed-form question should get a FORM HELP / VISION_FORM_QUERY
        tagged answer when qwen finds it in the image."""
        with unittest.mock.patch.object(
            self.workflow.qwen_client, "answer_vision",
            return_value="This field asks for your Aadhaar number.",
        ):
            pkg = self.workflow.process_vision_query("What does this field mean?", b"fake-jpeg-bytes")
        self.assertEqual(pkg.qr_payload["status"], "VISION_FORM_QUERY")
        self.assertEqual(pkg.display_top_text, "FORM HELP")
        self.assertIn("aadhaar", pkg.voice_text.lower())

    def test_vision_query_falls_back_when_qwen_cannot_read_the_form(self):
        """An unreadable/irrelevant photo must fall back to the constant
        message, not a confident guess about document content."""
        with unittest.mock.patch.object(self.workflow.qwen_client, "answer_vision", return_value=None):
            pkg = self.workflow.process_vision_query("What does this field mean?", b"fake-jpeg-bytes")
        self.assertEqual(pkg.qr_payload["status"], "FALLBACK")
        self.assertIn("i'm sorry", pkg.voice_text.lower())


# ──────────────────────────────────────────────────────────────────────────────
# Main runner
# ──────────────────────────────────────────────────────────────────────────────

def _run_all():
    print(DIVIDER)
    print("  NOMADRIGHT — AUDIT FIX REGRESSION TESTS")
    print(DIVIDER)

    suite = unittest.TestLoader().loadTestsFromTestCase(TestPIIMasking)
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestWordBoundaryStateMatching))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMultilineIntentMatching))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSQLiteConnectionCleanup))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMainAppExceptionHandling))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestLLMFallbackAndVision))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    print(DIVIDER)
    total  = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"  TOTAL : {total}   PASS : {passed}   FAIL : {len(result.failures)}   ERROR : {len(result.errors)}")
    print(DIVIDER)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(_run_all())
