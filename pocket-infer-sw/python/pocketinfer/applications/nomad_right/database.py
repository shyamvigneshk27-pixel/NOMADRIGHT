"""
NomadRight SQLite Database Access Layer Module

Provides thread-safe, WAL-mode SQLite access to the nomadright_kb.db welfare
knowledge base.  All queries are parameterised and 100% offline.

Tables used  (nomadright_kb.db)
─────────────────────────────────
  schemes                   – master record per scheme
  eligibility               – eligibility criteria rows
  beneficiary_categories    – AAY / PHH / migrant etc.
  documents                 – required documents per scheme
  benefits                  – scheme benefits
  application_steps         – offline / online process steps
  state_rules               – state-specific notes
  exceptions_and_limitations
  faq                       – frequently asked questions
  important_definitions     – glossary terms
  official_contacts         – helplines & portals
"""

import os
import sqlite3
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from pocketinfer.applications.nomad_right import constants
from pocketinfer.applications.nomad_right.config import NomadRightConfig

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Data Transfer Objects
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PortabilityRecord:
    """Aggregated portability record for a welfare scheme pulled from the DB."""
    scheme_id: str
    scheme_code: str                          # e.g. "PDS"
    eligibility_criteria: List[str] = field(default_factory=list)
    required_documents: List[str] = field(default_factory=list)
    benefits: List[str] = field(default_factory=list)
    application_steps_offline: List[str] = field(default_factory=list)
    state_rules: List[str] = field(default_factory=list)
    exceptions: List[str] = field(default_factory=list)
    faq_matches: List[Dict[str, str]] = field(default_factory=list)
    helpline: Optional[str] = None


@dataclass
class CitizenQueryLogDTO:
    """Data Transfer Object for citizen query audit records."""
    session_id: str
    intent: str
    scheme_code: str
    transcribed_text: str
    response_summary: str
    language: str = "en"
    status: str = "OK"
    timestamp: Optional[str] = None
    id: Optional[int] = None


# ──────────────────────────────────────────────────────────────────────────────
# Abstract Interface
# ──────────────────────────────────────────────────────────────────────────────

class IDatabaseAccess(ABC):
    """Abstract interface for the NomadRight SQLite Access Layer."""

    @abstractmethod
    def get_portability_record(self, scheme_code: str) -> Optional[PortabilityRecord]:
        """Returns a fully-populated PortabilityRecord for the given scheme."""
        pass

    @abstractmethod
    def get_faq_matches(self, scheme_id: str, keywords: List[str]) -> List[Dict[str, str]]:
        """Returns FAQ rows whose question or answer contains any keyword."""
        pass

    @abstractmethod
    def insert_query_log(self, log_dto: CitizenQueryLogDTO) -> bool:
        """Persists a citizen query audit record."""
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Concrete Implementation
# ──────────────────────────────────────────────────────────────────────────────

class SQLiteAccessLayer(IDatabaseAccess):
    """
    High-performance, thread-safe SQLite Access Layer for nomadright_kb.db.

    The database is opened in WAL journal mode for concurrent reads.
    All public methods return typed DTOs; no raw SQL leaks to callers.
    Schema-init only creates the audit log table — the KB tables are
    pre-populated by build_sqlite_db.py.
    """

    def __init__(self, config: Optional[NomadRightConfig] = None):
        self.config = config or NomadRightConfig()
        self.db_path = self.config.db_path
        self.logger = logging.getLogger(self.__class__.__name__)

        # Resolve path relative to CWD when not absolute
        if not os.path.isabs(self.db_path):
            self.db_path = os.path.join(os.getcwd(), self.db_path)

        if not os.path.exists(self.db_path):
            self.logger.error(
                f"Database not found at '{self.db_path}'. "
                "Run nomadright/build_sqlite_db.py to create it."
            )
        else:
            self.logger.info(f"Using nomadright KB at: {self.db_path}")

        self._ensure_audit_table()

    # ── Connection helper ──────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Opens a WAL-mode connection with Row factory enabled."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Schema: audit table only ───────────────────────────────────────────

    def _ensure_audit_table(self) -> None:
        """Creates citizen_query_log table if it does not exist yet."""
        conn = None
        try:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS citizen_query_log (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp        DATETIME DEFAULT CURRENT_TIMESTAMP,
                    session_id       TEXT NOT NULL,
                    intent           TEXT,
                    scheme_code      TEXT,
                    transcribed_text TEXT,
                    response_summary TEXT,
                    language         TEXT DEFAULT 'en',
                    status           TEXT DEFAULT 'OK'
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_log_session "
                "ON citizen_query_log (session_id);"
            )
            conn.commit()
        except Exception as exc:
            self.logger.error(f"Failed to initialise audit table: {exc}")
        finally:
            if conn is not None:
                conn.close()

    # ── Scheme ID resolution ───────────────────────────────────────────────

    @staticmethod
    def _resolve_scheme_id(scheme_code: str) -> Optional[str]:
        """Converts short scheme code ('PDS') to DB scheme_id ('PDS_ONORC_001')."""
        return constants.SCHEME_CODE_TO_DB_ID.get(scheme_code.upper())

    # ── Public query methods ───────────────────────────────────────────────

    def get_portability_record(self, scheme_code: str) -> Optional[PortabilityRecord]:
        """
        Fetches all portability-relevant data for a scheme from the KB.

        Queries:  eligibility, documents, benefits, application_steps (offline),
                  state_rules, exceptions_and_limitations, official_contacts, faq.

        Args:
            scheme_code: Short scheme code, e.g. "PDS".

        Returns:
            PortabilityRecord populated from live DB data, or None if not found.
        """
        scheme_id = self._resolve_scheme_id(scheme_code)
        if not scheme_id:
            self.logger.warning(f"Unknown scheme code: '{scheme_code}'")
            return None

        self.logger.debug(f"Querying KB for scheme_id='{scheme_id}'")

        conn = None
        try:
            conn = self._get_conn()
            record = PortabilityRecord(
                scheme_id=scheme_id,
                scheme_code=scheme_code.upper(),
            )

            # Eligibility criteria
            cur = conn.execute(
                "SELECT criterion FROM eligibility WHERE scheme_id = ? ORDER BY id",
                (scheme_id,)
            )
            record.eligibility_criteria = [r["criterion"] for r in cur.fetchall()]

            # Required documents (mandatory only)
            cur = conn.execute(
                "SELECT document_name FROM documents "
                "WHERE scheme_id = ? AND is_mandatory = 1 ORDER BY id",
                (scheme_id,)
            )
            record.required_documents = [r["document_name"] for r in cur.fetchall()]

            # Key benefits (first 3 most relevant)
            cur = conn.execute(
                "SELECT benefit_description FROM benefits "
                "WHERE scheme_id = ? ORDER BY id LIMIT 3",
                (scheme_id,)
            )
            record.benefits = [r["benefit_description"] for r in cur.fetchall()]

            # Offline application steps
            cur = conn.execute(
                "SELECT description FROM application_steps "
                "WHERE scheme_id = ? AND mode = 'offline' ORDER BY step_number",
                (scheme_id,)
            )
            record.application_steps_offline = [r["description"] for r in cur.fetchall()]

            # State-specific rules
            cur = conn.execute(
                "SELECT rule_note FROM state_rules WHERE scheme_id = ? ORDER BY id",
                (scheme_id,)
            )
            record.state_rules = [r["rule_note"] for r in cur.fetchall()]

            # Exceptions (not limitations — just the blockers)
            cur = conn.execute(
                "SELECT description FROM exceptions_and_limitations "
                "WHERE scheme_id = ? AND entry_type = 'exception' ORDER BY id",
                (scheme_id,)
            )
            record.exceptions = [r["description"] for r in cur.fetchall()]

            # Primary helpline number
            cur = conn.execute(
                "SELECT number_or_url FROM official_contacts "
                "WHERE scheme_id = ? AND contact_type = 'Helpline' ORDER BY id LIMIT 1",
                (scheme_id,)
            )
            row = cur.fetchone()
            record.helpline = row["number_or_url"] if row else None

            # FAQ matches for dynamic lookup
            cur = conn.execute(
                "SELECT question, answer, source FROM faq WHERE scheme_id = ? ORDER BY id LIMIT 5",
                (scheme_id,)
            )
            record.faq_matches = [
                {"question": r["question"], "answer": r["answer"], "source": r["source"]}
                for r in cur.fetchall()
            ]

            self.logger.info(
                f"KB query OK: scheme_id={scheme_id}, "
                f"eligibility={len(record.eligibility_criteria)}, "
                f"docs={len(record.required_documents)}, "
                f"benefits={len(record.benefits)}, "
                f"faqs={len(record.faq_matches)}"
            )
            return record

        except Exception as exc:
            self.logger.error(f"DB query failed for scheme '{scheme_code}': {exc}")
            return None
        finally:
            if conn is not None:
                conn.close()

    def get_faq_matches(self, scheme_id: str, keywords: List[str]) -> List[Dict[str, str]]:
        """
        Returns FAQ rows whose question or answer contains any of the keywords.

        Args:
            scheme_id: DB scheme_id string.
            keywords:  List of lowercase keyword strings to match.

        Returns:
            List of dicts with keys: question, answer, source.
        """
        results: List[Dict[str, str]] = []
        if not keywords:
            return results
        conn = None
        try:
            conn = self._get_conn()
            cur = conn.execute(
                "SELECT question, answer, source FROM faq "
                "WHERE scheme_id = ? ORDER BY id",
                (scheme_id,)
            )
            for row in cur.fetchall():
                row_text = (row["question"] + " " + row["answer"]).lower()
                if any(kw in row_text for kw in keywords):
                    results.append({
                        "question": row["question"],
                        "answer": row["answer"],
                        "source": row["source"],
                    })
        except Exception as exc:
            self.logger.error(f"FAQ query failed: {exc}")
        finally:
            if conn is not None:
                conn.close()
        return results

    # ── Audit Logging & PII Masking ────────────────────────────────────────

    @staticmethod
    def _mask_pii(text: str) -> str:
        """
        Masks Personally Identifiable Information (Aadhaar 12-digit numbers
        and 10-digit phone numbers) before writing to audit log tables.
        """
        if not text:
            return ""
        import re
        # Mask 12-digit Aadhaar numbers (with optional space/dash separators)
        masked = re.sub(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "XXXX-XXXX-XXXX", text)
        # Mask 10-digit Indian phone numbers
        masked = re.sub(r"\b[6-9]\d{9}\b", "XXXXXX-XXXX", masked)
        return masked

    def insert_query_log(self, log_dto: CitizenQueryLogDTO) -> bool:
        """Persists a citizen query audit record to citizen_query_log."""
        conn = None
        try:
            conn = self._get_conn()
            sanitized_text = self._mask_pii(log_dto.transcribed_text)
            conn.execute(
                "INSERT INTO citizen_query_log "
                "(session_id, intent, scheme_code, transcribed_text, "
                " response_summary, language, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    log_dto.session_id,
                    log_dto.intent,
                    log_dto.scheme_code,
                    sanitized_text,
                    log_dto.response_summary,
                    log_dto.language,
                    log_dto.status,
                )
            )
            conn.commit()
            self.logger.debug(
                f"Audit log saved: session={log_dto.session_id}, "
                f"intent={log_dto.intent}"
            )
            return True
        except Exception as exc:
            self.logger.error(f"Failed to write audit log: {exc}")
            return False
        finally:
            if conn is not None:
                conn.close()

