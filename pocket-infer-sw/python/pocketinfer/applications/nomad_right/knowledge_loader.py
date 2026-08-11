"""
NomadRight Knowledge Base Loader

Loads nomadright_full_db.json once and exposes it as an in-memory index for
query matching. This is the *live* data source for intent/entity matching
(see intent.py's Phase 3 / entities.py's scheme lookup) - adding a new
scheme or question phrasing to that JSON takes effect immediately, with no
Python code change, for anything routed through this loader.

Deliberately NOT the source of any spoken/displayed answer content: the
JSON's faq[].answer field is pre-written Hindi/Hinglish text, while the
Decision Layer must always produce English voice_text (translated to the
worker's language by BHASHINI NMT afterward) - mixing pre-translated
regional text into that step would produce broken/double-translated
output. Answer content continues to come from rules.py and the RAG
pipeline, unchanged.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
DEFAULT_KNOWLEDGE_PATH = os.path.join(_REPO_ROOT, "nomadright_full_db.json")


@dataclass
class SchemeKeywords:
    short_code: str
    keywords: List[str] = field(default_factory=list)


@dataclass
class FaqEntry:
    intent_tag: str
    scheme_short_code: Optional[str]
    question_keywords: List[str] = field(default_factory=list)
    question_variants: List[str] = field(default_factory=list)


@dataclass
class KnowledgeBase:
    schemes: List[SchemeKeywords] = field(default_factory=list)
    faqs: List[FaqEntry] = field(default_factory=list)


def phrase_in_text(phrase: str, text_lower: str) -> bool:
    """Word-boundary-safe substring check for a (possibly multi-word)
    keyword phrase against already-lowercased text. Mirrors the \\b-bounded
    approach used throughout intent.py/entities.py (e.g. 'ration' must not
    match inside 'registration')."""
    phrase = phrase.strip().lower()
    if not phrase:
        return False
    return bool(re.search(r"\b" + re.escape(phrase) + r"\b", text_lower))


_WORD_RE = re.compile(r"[a-z']+")


def variant_match_score(text_lower: str, variant: str) -> Tuple[float, int]:
    """
    Returns (word-overlap ratio 0.0-1.0, shared word count) between
    already-lowercased text and one of a FAQ's question_variants examples.
    Many genuine paraphrases (e.g. a Hinglish follow-up like "Kaun kaun sa
    kagaz lana hai?") don't literally contain any of that FAQ's curated
    question_keywords substrings, so exact/substring matching alone misses
    them - this catches a query that's a close rewording of a known
    example instead. Both the ratio AND the shared count matter: two short
    phrases sharing one generic word would score a deceptively high ratio.
    """
    a = set(_WORD_RE.findall(text_lower))
    b = set(_WORD_RE.findall(variant.lower()))
    if not a or not b:
        return 0.0, 0
    shared = a & b
    return len(shared) / min(len(a), len(b)), len(shared)


@lru_cache(maxsize=1)
def load_knowledge(path: Optional[str] = None) -> KnowledgeBase:
    """Loads and indexes nomadright_full_db.json. Cached after first call -
    the file is read once per process, matching how IntentRecognizer/
    EntityExtractor are each constructed once per app session."""
    load_path = path or DEFAULT_KNOWLEDGE_PATH
    with open(load_path, encoding="utf-8") as f:
        raw = json.load(f)

    scheme_id_to_short = {
        s["scheme_id"]: s.get("short_code") for s in raw.get("schemes", [])
    }

    schemes = [
        SchemeKeywords(
            short_code=s["short_code"],
            keywords=list(s.get("keywords", [])),
        )
        for s in raw.get("schemes", [])
        if s.get("short_code")
    ]

    faqs = [
        FaqEntry(
            intent_tag=f["intent_tag"],
            scheme_short_code=scheme_id_to_short.get(f.get("scheme_id")),
            question_keywords=list(f.get("question_keywords", [])),
            question_variants=list(f.get("question_variants", [])),
        )
        for f in raw.get("faq", [])
        if f.get("intent_tag")
    ]

    logger.info(
        f"Loaded NomadRight knowledge base from {load_path}: "
        f"{len(schemes)} schemes, {len(faqs)} FAQ intents"
    )
    return KnowledgeBase(schemes=schemes, faqs=faqs)
