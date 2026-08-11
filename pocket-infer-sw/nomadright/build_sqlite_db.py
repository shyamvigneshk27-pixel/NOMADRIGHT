"""
NomadRight SQLite Database Converter & Ingestion Script
VYOMA Innovation Challenge - Offline AI Assistant
Converts pds.json, pmjay.json, eshram_osh.json, bocw.json, and mgnregs.json
into a normalized SQLite database.
"""

import json
import os
import sqlite3

DATASET_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATASET_DIR, "nomadright_kb.db")
JSON_FILES = ["pds.json", "pmjay.json", "eshram_osh.json", "bocw.json", "mgnregs.json"]


def create_schema(cursor: sqlite3.Cursor) -> None:
    """Creates the normalized database tables with primary and foreign keys."""
    cursor.executescript("""
    PRAGMA foreign_keys = ON;

    -- Master Scheme Table
    CREATE TABLE IF NOT EXISTS schemes (
        scheme_id TEXT PRIMARY KEY,
        scheme_name TEXT NOT NULL,
        description TEXT NOT NULL,
        objective TEXT NOT NULL,
        portability_inter_state TEXT,
        portability_intra_state TEXT,
        portability_coverage TEXT,
        portability_partial_collection TEXT,
        portability_authentication_method TEXT,
        portability_description TEXT,
        last_updated TEXT NOT NULL,
        data_extraction_note TEXT
    );

    -- Eligibility Criteria Table
    CREATE TABLE IF NOT EXISTS eligibility (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        criterion TEXT NOT NULL,
        source TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- Beneficiary Categories Table
    CREATE TABLE IF NOT EXISTS beneficiary_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        source TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- Documents Table
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        document_name TEXT NOT NULL,
        description TEXT,
        is_mandatory INTEGER NOT NULL DEFAULT 0,
        source TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- Benefits Table (General & Financial)
    CREATE TABLE IF NOT EXISTS benefits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        benefit_type TEXT NOT NULL DEFAULT 'General',
        benefit_description TEXT NOT NULL,
        details TEXT,
        source TEXT,
        note TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- Application Process Steps Table
    CREATE TABLE IF NOT EXISTS application_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        mode TEXT NOT NULL, -- 'online' or 'offline'
        step_number INTEGER NOT NULL,
        description TEXT NOT NULL,
        source TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- State Specific Rules Table
    CREATE TABLE IF NOT EXISTS state_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        rule_note TEXT NOT NULL,
        source TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- Exceptions and Limitations Table
    CREATE TABLE IF NOT EXISTS exceptions_and_limitations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        entry_type TEXT NOT NULL, -- 'exception' or 'limitation'
        description TEXT NOT NULL,
        source TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- FAQ Table
    CREATE TABLE IF NOT EXISTS faq (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        source TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- Important Definitions Table
    CREATE TABLE IF NOT EXISTS important_definitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        term TEXT NOT NULL,
        definition TEXT NOT NULL,
        source TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- Official Contacts Table
    CREATE TABLE IF NOT EXISTS official_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        contact_type TEXT,
        number_or_url TEXT,
        description TEXT,
        source TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- Official Sources / Citations Table
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id TEXT NOT NULL,
        website TEXT,
        document TEXT,
        url TEXT,
        page TEXT,
        section TEXT,
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
    );

    -- Indexes for Offline Query Performance Optimization
    CREATE INDEX IF NOT EXISTS idx_eligibility_scheme ON eligibility(scheme_id);
    CREATE INDEX IF NOT EXISTS idx_documents_scheme ON documents(scheme_id);
    CREATE INDEX IF NOT EXISTS idx_benefits_scheme ON benefits(scheme_id);
    CREATE INDEX IF NOT EXISTS idx_app_steps_scheme ON application_steps(scheme_id, mode);
    CREATE INDEX IF NOT EXISTS idx_faq_scheme ON faq(scheme_id);
    CREATE INDEX IF NOT EXISTS idx_state_rules_scheme ON state_rules(scheme_id);
    CREATE INDEX IF NOT EXISTS idx_sources_scheme ON sources(scheme_id);
    """)


def ingest_scheme_data(cursor: sqlite3.Cursor, data: dict) -> None:
    """Ingests a single scheme JSON dictionary into the normalized database."""
    scheme_id = data["scheme_id"]
    port = data.get("portability", {})

    # 1. Ingest Master Scheme record
    cursor.execute("""
        INSERT INTO schemes (
            scheme_id, scheme_name, description, objective,
            portability_inter_state, portability_intra_state,
            portability_coverage, portability_partial_collection,
            portability_authentication_method, portability_description,
            last_updated, data_extraction_note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        scheme_id,
        data.get("scheme_name"),
        data.get("description"),
        data.get("objective"),
        port.get("inter_state"),
        port.get("intra_state"),
        port.get("coverage"),
        port.get("partial_collection"),
        port.get("authentication_method"),
        port.get("description"),
        data.get("last_updated"),
        data.get("data_extraction_note")
    ))

    # 2. Ingest Eligibility
    for item in data.get("eligibility", []):
        cursor.execute("""
            INSERT INTO eligibility (scheme_id, criterion, source)
            VALUES (?, ?, ?)
        """, (scheme_id, item.get("criterion"), item.get("source")))

    # 3. Ingest Beneficiary Categories
    for item in data.get("beneficiary_categories", []):
        cursor.execute("""
            INSERT INTO beneficiary_categories (scheme_id, category, description, source)
            VALUES (?, ?, ?, ?)
        """, (scheme_id, item.get("category"), item.get("description"), item.get("source")))

    # 4. Ingest Documents
    for item in data.get("required_documents", []):
        is_mand = 1 if item.get("mandatory") else 0
        cursor.execute("""
            INSERT INTO documents (scheme_id, document_name, description, is_mandatory, source)
            VALUES (?, ?, ?, ?, ?)
        """, (scheme_id, item.get("document"), item.get("description"), is_mand, item.get("source")))

    # 5. Ingest General Benefits
    for item in data.get("benefits", []):
        cursor.execute("""
            INSERT INTO benefits (scheme_id, benefit_type, benefit_description, source)
            VALUES (?, 'General', ?, ?)
        """, (scheme_id, item.get("benefit"), item.get("source")))

    # 6. Ingest Financial Benefits
    for item in data.get("financial_benefits", []):
        details_val = item.get("details")
        if isinstance(details_val, (dict, list)):
            details_str = json.dumps(details_val)
        else:
            details_str = str(details_val) if details_val is not None else None

        cursor.execute("""
            INSERT INTO benefits (scheme_id, benefit_type, benefit_description, details, source, note)
            VALUES (?, 'Financial', ?, ?, ?, ?)
        """, (
            scheme_id,
            item.get("benefit_type", "Financial Benefit"),
            details_str,
            item.get("source"),
            item.get("note")
        ))

    # 7. Ingest Application Process Steps
    app_proc = data.get("application_process", {})
    for mode in ["online", "offline"]:
        for step in app_proc.get(mode, []):
            cursor.execute("""
                INSERT INTO application_steps (scheme_id, mode, step_number, description, source)
                VALUES (?, ?, ?, ?, ?)
            """, (scheme_id, mode, step.get("step"), step.get("description"), step.get("source")))

    # 8. Ingest State Rules
    for item in data.get("state_specific_rules", []):
        cursor.execute("""
            INSERT INTO state_rules (scheme_id, rule_note, source)
            VALUES (?, ?, ?)
        """, (scheme_id, item.get("note"), item.get("source")))

    # 9. Ingest Exceptions
    for item in data.get("exceptions", []):
        cursor.execute("""
            INSERT INTO exceptions_and_limitations (scheme_id, entry_type, description, source)
            VALUES (?, 'exception', ?, ?)
        """, (scheme_id, item.get("exception"), item.get("source")))

    # 10. Ingest Limitations
    for item in data.get("limitations", []):
        cursor.execute("""
            INSERT INTO exceptions_and_limitations (scheme_id, entry_type, description, source)
            VALUES (?, 'limitation', ?, ?)
        """, (scheme_id, item.get("limitation"), item.get("source")))

    # 11. Ingest FAQ
    for item in data.get("faq", []):
        cursor.execute("""
            INSERT INTO faq (scheme_id, question, answer, source)
            VALUES (?, ?, ?, ?)
        """, (scheme_id, item.get("question"), item.get("answer"), item.get("source")))

    # 12. Ingest Important Definitions
    for item in data.get("important_definitions", []):
        cursor.execute("""
            INSERT INTO important_definitions (scheme_id, term, definition, source)
            VALUES (?, ?, ?, ?)
        """, (scheme_id, item.get("term"), item.get("definition"), item.get("source")))

    # 13. Ingest Official Contacts
    for item in data.get("official_contacts", []):
        num_or_url = item.get("number") or item.get("url")
        cursor.execute("""
            INSERT INTO official_contacts (scheme_id, contact_type, number_or_url, description, source)
            VALUES (?, ?, ?, ?, ?)
        """, (scheme_id, item.get("type"), num_or_url, item.get("description"), item.get("source")))

    # 14. Ingest Sources
    for item in data.get("official_sources", []):
        cursor.execute("""
            INSERT INTO sources (scheme_id, website, document, url, page, section)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            scheme_id,
            item.get("website"),
            item.get("document"),
            item.get("url"),
            item.get("page"),
            item.get("section")
        ))


def build_database() -> None:
    """Builds and verifies the SQLite database from JSON files."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    create_schema(cursor)

    for json_file in JSON_FILES:
        full_path = os.path.join(DATASET_DIR, json_file)
        print(f"Ingesting: {json_file}...")
        with open(full_path, "r", encoding="utf-8") as f:
            scheme_data = json.load(f)
            ingest_scheme_data(cursor, scheme_data)

    conn.commit()

    print("\n" + "=" * 60)
    print("SQLITE DATABASE BUILDING COMPLETE")
    print("=" * 60)
    print(f"Database Location: {DB_PATH}")

    # Summary Audit Query
    tables = [
        "schemes", "eligibility", "beneficiary_categories", "documents",
        "benefits", "application_steps", "state_rules",
        "exceptions_and_limitations", "faq", "important_definitions",
        "official_contacts", "sources"
    ]

    print("\nTable Row Counts:")
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  - {table:30s}: {count:4d} rows")

    # Sample query test
    print("\nVerification Test Query (FAQ count per scheme):")
    cursor.execute("""
        SELECT s.scheme_id, s.scheme_name, COUNT(f.id) as faq_count
        FROM schemes s
        LEFT JOIN faq f ON s.scheme_id = f.scheme_id
        GROUP BY s.scheme_id;
    """)
    for row in cursor.fetchall():
        print(f"  * [{row[0]}] {row[1][:45]}... -> {row[2]} FAQs")

    conn.close()


if __name__ == "__main__":
    build_database()
