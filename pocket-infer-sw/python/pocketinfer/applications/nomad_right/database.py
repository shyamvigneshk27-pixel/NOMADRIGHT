"""
NomadRight SQLite Database Access Layer Module

Provides high-performance, thread-safe SQLite access to the nomadright_kb.db
welfare knowledge base. Implements L1 RAM caching, L2 Memory-Mapped Consolidated
Querying, and Async Non-Blocking Audit Logging for microsecond-level retrieval.
"""

import os
import re
import json
import sqlite3
import logging
import threading
import queue
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

    @abstractmethod
    def preload_cache(self) -> None:
        """Warm up the L1 cache for instant memory lookups."""
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Async Audit Logger
# ──────────────────────────────────────────────────────────────────────────────

class AsyncAuditLogger:
    """Background worker thread to handle audit logging asynchronously."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.log_queue: queue.Queue = queue.Queue()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    @staticmethod
    def _mask_pii(text: str) -> str:
        if not text:
            return ""
        # Mask 12-digit Aadhaar numbers (with optional space/dash separators)
        masked = re.sub(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "XXXX-XXXX-XXXX", text)
        # Mask 10-digit Indian phone numbers
        masked = re.sub(r"\b[6-9]\d{9}\b", "XXXXXX-XXXX", masked)
        return masked

    def _worker_loop(self):
        conn = None
        try:
            conn = self._get_conn()
            while True:
                try:
                    log_dto: CitizenQueryLogDTO = self.log_queue.get()
                    if log_dto is None:  # Sentinel to stop
                        break
                    
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
                    self.log_queue.task_done()
                except Exception as exc:
                    self.logger.error(f"Async log failed: {exc}")
        finally:
            if conn:
                conn.close()

    def log(self, dto: CitizenQueryLogDTO):
        self.log_queue.put(dto)


# ──────────────────────────────────────────────────────────────────────────────
# Concrete Implementation
# ──────────────────────────────────────────────────────────────────────────────

class SQLiteAccessLayer(IDatabaseAccess):
    """
    High-performance, thread-safe SQLite Access Layer for nomadright_kb.db.
    Implements L1 RAM Caching, L2 Memory-Mapped Consolidated query loading,
    and L3 Async non-blocking audit logging.
    """

    def __init__(self, config: Optional[NomadRightConfig] = None):
        self.config = config or NomadRightConfig()
        self.db_path = self.config.db_path
        self.logger = logging.getLogger(self.__class__.__name__)

        # L1 In-Memory Cache
        self._portability_cache: Dict[str, PortabilityRecord] = {}
        self._faq_cache: Dict[str, List[Dict[str, str]]] = {}
        self._cache_lock = threading.Lock()

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
        
        # Setup Async Logger (L3)
        self.async_logger = AsyncAuditLogger(self.db_path)
        
        # Setup L2 DB Optimizations
        self._setup_db_optimizations()

    # ── Connection helper ──────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Opens a highly optimized WAL-mode connection."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA mmap_size=268435456;") # 256MB memory mapping
        conn.execute("PRAGMA cache_size=-64000;")   # 64MB page cache
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.row_factory = sqlite3.Row
        return conn

    def _setup_db_optimizations(self):
        """Creates compound indexes for blazing fast L2 lookups if needed."""
        conn = None
        try:
            conn = self._get_conn()
            conn.execute("CREATE INDEX IF NOT EXISTS idx_eligibility_scheme ON eligibility(scheme_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_scheme ON documents(scheme_id, is_mandatory);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_benefits_scheme ON benefits(scheme_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_app_steps_scheme ON application_steps(scheme_id, mode);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_state_rules_scheme ON state_rules(scheme_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exceptions_scheme ON exceptions_and_limitations(scheme_id, entry_type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_scheme ON official_contacts(scheme_id, contact_type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_faq_scheme ON faq(scheme_id);")
            conn.commit()
        except Exception as exc:
            self.logger.warning(f"Failed to setup DB index optimizations: {exc}")
        finally:
            if conn:
                conn.close()

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

    # ── L1 Cache Warmup ────────────────────────────────────────────────────

    def preload_cache(self) -> None:
        """
        L1 Cache Warmup: Loads all known scheme definitions into RAM at startup.
        Ensures microsecond latency for all query DB lookups.
        """
        self.logger.info("Preloading L1 Database Cache into RAM...")
        for scheme_code in constants.SCHEME_CODE_TO_DB_ID.keys():
            # This triggers an L2 fetch and stores it in L1 cache
            self.get_portability_record(scheme_code)
            
            # Preload FAQ cache
            scheme_id = self._resolve_scheme_id(scheme_code)
            if scheme_id:
                conn = None
                try:
                    conn = self._get_conn()
                    cur = conn.execute("SELECT question, answer, source FROM faq WHERE scheme_id = ? ORDER BY id", (scheme_id,))
                    with self._cache_lock:
                        self._faq_cache[scheme_id] = [dict(r) for r in cur.fetchall()]
                except Exception as exc:
                    self.logger.error(f"Failed to preload FAQ cache for {scheme_id}: {exc}")
                finally:
                    if conn:
                        conn.close()
        self.logger.info("L1 Database Cache Preload Complete. Ready for microsecond retrieval.")


    # ── Public query methods ───────────────────────────────────────────────

    def get_portability_record(self, scheme_code: str) -> Optional[PortabilityRecord]:
        """
        Fetches portability record. Uses L1 RAM cache (<0.05ms) if available.
        Otherwise falls back to L2 Single-Pass SQLite fetch.
        """
        scheme_id = self._resolve_scheme_id(scheme_code)
        if not scheme_id:
            self.logger.warning(f"Unknown scheme code: '{scheme_code}'")
            return None

        # Check L1 Cache
        with self._cache_lock:
            if scheme_id in self._portability_cache:
                self.logger.debug(f"L1 Cache Hit for {scheme_code} (<0.05ms)")
                return self._portability_cache[scheme_id]

        # L2 Cache Miss - Single Pass DB Fetch
        self.logger.info(f"L1 Cache Miss. Fetching L2 Consolidated DB Record for {scheme_code}")
        conn = None
        try:
            conn = self._get_conn()
            
            # Single consolidated query utilizing SQLite JSON aggregation to fetch 8 tables at once
            query = """
            SELECT
                (SELECT json_group_array(criterion) FROM (SELECT criterion FROM eligibility WHERE scheme_id = ? ORDER BY id)) AS eligibility_json,
                (SELECT json_group_array(document_name) FROM (SELECT document_name FROM documents WHERE scheme_id = ? AND is_mandatory = 1 ORDER BY id)) AS documents_json,
                (SELECT json_group_array(benefit_description) FROM (SELECT benefit_description FROM benefits WHERE scheme_id = ? ORDER BY id LIMIT 3)) AS benefits_json,
                (SELECT json_group_array(description) FROM (SELECT description FROM application_steps WHERE scheme_id = ? AND mode = 'offline' ORDER BY step_number)) AS steps_json,
                (SELECT json_group_array(rule_note) FROM (SELECT rule_note FROM state_rules WHERE scheme_id = ? ORDER BY id)) AS rules_json,
                (SELECT json_group_array(description) FROM (SELECT description FROM exceptions_and_limitations WHERE scheme_id = ? AND entry_type = 'exception' ORDER BY id)) AS exceptions_json,
                (SELECT number_or_url FROM official_contacts WHERE scheme_id = ? AND contact_type = 'Helpline' ORDER BY id LIMIT 1) AS helpline,
                (SELECT json_group_array(json_object('question', question, 'answer', answer, 'source', source)) FROM (SELECT question, answer, source FROM faq WHERE scheme_id = ? ORDER BY id LIMIT 5)) AS faq_json
            """
            
            # Run the single massive query
            cur = conn.execute(query, (scheme_id,) * 8)
            row = cur.fetchone()
            
            if not row:
                return None
            
            record = PortabilityRecord(
                scheme_id=scheme_id,
                scheme_code=scheme_code.upper(),
                eligibility_criteria=json.loads(row["eligibility_json"]) if row["eligibility_json"] else [],
                required_documents=json.loads(row["documents_json"]) if row["documents_json"] else [],
                benefits=json.loads(row["benefits_json"]) if row["benefits_json"] else [],
                application_steps_offline=json.loads(row["steps_json"]) if row["steps_json"] else [],
                state_rules=json.loads(row["rules_json"]) if row["rules_json"] else [],
                exceptions=json.loads(row["exceptions_json"]) if row["exceptions_json"] else [],
                faq_matches=json.loads(row["faq_json"]) if row["faq_json"] else [],
                helpline=row["helpline"]
            )

            # Add to L1 Cache
            with self._cache_lock:
                self._portability_cache[scheme_id] = record
                
            self.logger.info(
                f"L2 DB query OK: scheme_id={scheme_id}, "
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
        """
        results: List[Dict[str, str]] = []
        if not keywords:
            return results
            
        # Check L1 Cache
        with self._cache_lock:
            cached_faqs = self._faq_cache.get(scheme_id)
        
        if cached_faqs is not None:
            # Microsecond memory scan
            for row in cached_faqs:
                row_text = (row["question"] + " " + row["answer"]).lower()
                if any(kw in row_text for kw in keywords):
                    results.append(row)
            return results
            
        # L2 Fallback
        conn = None
        try:
            conn = self._get_conn()
            cur = conn.execute(
                "SELECT question, answer, source FROM faq "
                "WHERE scheme_id = ? ORDER BY id",
                (scheme_id,)
            )
            faqs = [dict(r) for r in cur.fetchall()]
            
            # Warm cache
            with self._cache_lock:
                self._faq_cache[scheme_id] = faqs
                
            for row in faqs:
                row_text = (row["question"] + " " + row["answer"]).lower()
                if any(kw in row_text for kw in keywords):
                    results.append(row)
        except Exception as exc:
            self.logger.error(f"FAQ query failed: {exc}")
        finally:
            if conn is not None:
                conn.close()
        return results

    def insert_query_log(self, log_dto: CitizenQueryLogDTO) -> bool:
        """Asynchronous non-blocking L3 queue write."""
        self.async_logger.log(log_dto)
        self.logger.debug(
            f"Audit log queued asynchronously: session={log_dto.session_id}, "
            f"intent={log_dto.intent}"
        )
        return True
