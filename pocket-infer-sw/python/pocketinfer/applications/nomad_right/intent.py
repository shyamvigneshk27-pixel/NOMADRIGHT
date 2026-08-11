"""
NomadRight Intent Recognition Module
"""

import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple

from pocketinfer.applications.nomad_right.config import NomadRightConfig
from pocketinfer.applications.nomad_right.knowledge_loader import (
    load_knowledge, phrase_in_text, variant_match_score,
)

# Minimum word-overlap ratio (see knowledge_loader.variant_overlap_score)
# and minimum shared-word count for a question_variants paraphrase match to
# count as evidence in Phase 3 below - both required, so two short phrases
# sharing one generic word (e.g. both containing "hai") can't match alone.
_VARIANT_OVERLAP_MIN_SCORE = 0.6
_VARIANT_OVERLAP_MIN_SHARED_WORDS = 2

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """Supported citizen welfare inquiry intents."""
    PDS_ELIGIBILITY = "PDS_ELIGIBILITY"
    PDS_PORTABILITY = "PDS_PORTABILITY"
    PMJAY_ELIGIBILITY = "PMJAY_ELIGIBILITY"
    PMJAY_BENEFITS = "PMJAY_BENEFITS"
    PMJAY_DOCUMENTS = "PMJAY_DOCUMENTS"
    PMJAY_PORTABILITY = "PMJAY_PORTABILITY"
    ESHRAM_REGISTRATION = "ESHRAM_REGISTRATION"
    ESHRAM_BENEFITS = "ESHRAM_BENEFITS"
    ESHRAM_DOCUMENTS = "ESHRAM_DOCUMENTS"
    ESHRAM_WAGE_RIGHTS = "ESHRAM_WAGE_RIGHTS"
    BOCW_ELIGIBILITY = "BOCW_ELIGIBILITY"
    BOCW_REGISTRATION = "BOCW_REGISTRATION"
    BOCW_BENEFITS = "BOCW_BENEFITS"
    BOCW_DOCUMENTS = "BOCW_DOCUMENTS"
    REQUIRED_DOCUMENTS = "REQUIRED_DOCUMENTS"
    APPLICATION_PROCESS = "APPLICATION_PROCESS"
    WELFARE_OVERVIEW = "WELFARE_OVERVIEW"
    COST_INQUIRY = "COST_INQUIRY"
    TRANSLATION_REQUEST = "TRANSLATION_REQUEST"
    GENERAL_EXPLANATION = "GENERAL_EXPLANATION"
    UNKNOWN_QUERY = "UNKNOWN_QUERY"


# Maps nomadright_full_db.json faq[].intent_tag values onto IntentType
# members that already have a rules.py handler - see IntentRecognizer's
# Phase 3 (knowledge-base matching) below. Tags with no entry here (all
# mgnregs_* tags, pds_aadhaar_link, pds_amount, pds_family_split,
# pmjay_diseases, accident_claim, labour_rights, nearest_csc, ...) are
# deliberately left unmapped: rather than writing a new rules.py branch for
# every one of them this round, they fall through to UNKNOWN_QUERY, which
# routes to the (now similarity-thresholded) RAG pipeline instead - safe,
# since the RAG index already covers all 5 schemes including MGNREGS.
INTENT_TAG_MAP: Dict[str, IntentType] = {
    "pds_portability": IntentType.PDS_PORTABILITY,
    "pds_documents": IntentType.REQUIRED_DOCUMENTS,
    "pmjay_portability": IntentType.PMJAY_PORTABILITY,
    "pmjay_cost": IntentType.COST_INQUIRY,
    "pmjay_how_to_get": IntentType.PMJAY_ELIGIBILITY,
    "eshram_what_is": IntentType.GENERAL_EXPLANATION,
    "eshram_register": IntentType.ESHRAM_REGISTRATION,
    "wage_theft": IntentType.ESHRAM_WAGE_RIGHTS,
    "bocw_what_is": IntentType.GENERAL_EXPLANATION,
    "bocw_register": IntentType.BOCW_REGISTRATION,
    "bocw_certificate": IntentType.BOCW_DOCUMENTS,
    "bocw_benefits_detail": IntentType.BOCW_BENEFITS,
    "all_schemes_overview": IntentType.WELFARE_OVERVIEW,
}


@dataclass
class IntentResult:
    """Dataclass storing the output of Intent Recognition."""
    intent_type: IntentType
    confidence: float
    raw_intent_key: str
    metadata: Optional[Dict[str, Any]] = None


class IIntentRecognizer(ABC):
    """Abstract interface for Intent Recognition engines."""

    @abstractmethod
    def recognize(
        self, transcribed_text: str, context_state: Optional[Dict[str, Any]] = None
    ) -> IntentResult:
        """Parses speech transcript and returns classified IntentResult."""
        pass


class IntentRecognizer(IIntentRecognizer):
    """
    Offline Intent Recognition Engine combining pattern matching rules
    and keyword taxonomy for welfare and operational inquiries.

    Operates on the English-language text produced after BHASHINI NMT
    translates the worker's spoken query (Hindi/Tamil/Odia/Bhojpuri/
    Maithili/Santali/Chhattisgarhi) into English — see bhashini_bridge.py
    and workflow.py.
    """

    def __init__(self, config: Optional[NomadRightConfig] = None):
        self.config = config or NomadRightConfig()
        self.logger = logging.getLogger(self.__class__.__name__)
        self._rules: List[Tuple[re.Pattern, IntentType]] = []
        self._init_rules()

    def _init_rules(self) -> None:
        """Compiles regex patterns for supported intent triggers."""
        rule_definitions = [
            # PDS Portability — high specificity patterns first to avoid false translation match
            # Covers: "use my ration card in X", "ration valid in X", "get ration in X",
            # "will my ration card work in this new place", "moved to a new city, ration card"
            (r"\b(use|work|valid|collect|get)\b.{0,25}\b(ration|pds)\b.{0,25}\b(in|at|from)\b", IntentType.PDS_PORTABILITY),
            (r"\b(ration|pds)\b.{0,25}\b(use|work|valid|collect|get)\b.{0,25}\b(in|at|from)\b", IntentType.PDS_PORTABILITY),
            (r"\b(will|does|can)\b.{0,15}\b(ration|pds)\b.{0,20}\b(work|valid|function)\b", IntentType.PDS_PORTABILITY),
            (r"\b(one nation|onorc|portab|other state|migrant)\b.*\b(ration|card|grain)\b", IntentType.PDS_PORTABILITY),
            (r"\b(moved|shifted|relocated|migrated|arrived|new city|new place|new state|different city|different state|another city|another state)\b.{0,40}\b(ration|pds|food grain)\b", IntentType.PDS_PORTABILITY),
            (r"\b(ration|pds|food grain)\b.{0,40}\b(moved|shifted|relocated|migrated|arrived|new city|new place|new state|different city|different state|another city|another state)\b", IntentType.PDS_PORTABILITY),
            (r"\b(ration|pds|bpl|aay|food grain|free rice|wheat quota)\b.*\b(eligible|qualification|criteria|criterion|get|apply)\b", IntentType.PDS_ELIGIBILITY),

            # PMJAY (Ayushman Bharat) — Specific intent patterns
            (r"\b(ayushman|pmjay|pm-jay|golden card)\b.{0,35}\b(use|work|valid|cover|hospital|treatment)\b.{0,35}\b(in|at|from|other state|across|mumbai|delhi|bangalore|bengaluru|chennai|outside)\b", IntentType.PMJAY_PORTABILITY),
            (r"\b(use|work|valid|accept)\b.{0,35}\b(ayushman|pmjay|pm-jay|golden card)\b.{0,35}\b(in|at|from|other state|across|outside)\b", IntentType.PMJAY_PORTABILITY),
            (r"\b(is|will|does)\b.{0,15}\b(my\s+)?(ayushman|pmjay|pm-jay|golden card)\b.{0,25}\b(valid|work|cover)\b", IntentType.PMJAY_PORTABILITY),
            (r"\b(ayushman|pmjay|pm-jay|golden card)\b.{0,35}\b(portab|other state|migrant|any state|national|across india)\b", IntentType.PMJAY_PORTABILITY),
            (r"\b(ayushman|pmjay|pm-jay|golden card)\b.{0,35}\b(documents?|papers?|proofs?|aadhaar|card|required|needed?|list)\b", IntentType.PMJAY_DOCUMENTS),
            (r"\b(documents?|papers?|proofs?)\b.{0,35}\b(ayushman|pmjay|pm-jay|golden card)\b", IntentType.PMJAY_DOCUMENTS),
            (r"\b(ayushman|pmjay|pm-jay|golden card)\b.{0,35}\b(benefits?|amount|limit|cover|cashless|5 lakh|fifty thousand|free|surgery|treatment|pay|cost|charges?)\b", IntentType.PMJAY_BENEFITS),
            (r"\b(ayushman|pmjay|pm-jay|golden card)\b.{0,35}\b(eligible|qualification|who|list|secc|criteria|qualify)\b", IntentType.PMJAY_ELIGIBILITY),

            # e-Shram + OSH Code 2020 — Specific intent patterns
            (r"\b(eshram|e-shram|e shram)\b.{0,35}\b(register|apply|new|enroll|how|csc)\b", IntentType.ESHRAM_REGISTRATION),
            (r"\b(register|apply|enroll)\b.{0,35}\b(eshram|e-shram|e shram|uan)\b", IntentType.ESHRAM_REGISTRATION),
            (r"\b(eshram|e-shram|e shram|uan|universal account number)\b.{0,35}\b(documents?|papers?|proofs?|aadhaar|mobile|required|needed?|list)\b", IntentType.ESHRAM_DOCUMENTS),
            (r"\b(documents?|papers?|proofs?)\b.{0,35}\b(eshram|e-shram|uan)\b", IntentType.ESHRAM_DOCUMENTS),
            # Wage theft — "contractor hasn't paid me for 45 days", "not paid for X days", "what do I do"
            (r"\b(contractor|employer)\b.{0,35}\b(not paying|refus\w*|denied|wage theft|not pay|less than minimum)\b", IntentType.ESHRAM_WAGE_RIGHTS),
            (r"\b(wage|payment|salary|pay)\b.{0,25}\b(not|haven.t|hasn.t|not been|less)\b.{0,20}\b(paid|received|minimum|given)\b", IntentType.ESHRAM_WAGE_RIGHTS),
            (r"\b(not|haven.t|hasn.t)\b.{0,15}\b(paid|been paid)\b.{0,25}\b(\d+\s*(days?|weeks?|months?)|contractor)\b", IntentType.ESHRAM_WAGE_RIGHTS),
            (r"\b(contractor)\b.{0,40}\b(\d+\s*(days?|weeks?|months?))\b.{0,25}\b(pay|paid|money|wage|salary)\b", IntentType.ESHRAM_WAGE_RIGHTS),
            (r"\b(equal wage|minimum wage|wage discrimination|shram suvidha|labour office|labour inspector|form ?11)\b", IntentType.ESHRAM_WAGE_RIGHTS),
            (r"\b(eshram|e-shram|e shram|uan|universal account number)\b.{0,35}\b(benefits?|insurance|2 lakh|scheme|what is|card)\b", IntentType.ESHRAM_BENEFITS),

            # BOCW (Building & Other Construction Workers) — Specific intent patterns
            # Covers: "how do I make a construction worker card", "nirman shramik card kaise banaye"
            (r"\b(bocw|building and other construction|construction worker board|construction board|nirman shramik|labour card)\b.{0,35}\b(register|apply|new|enroll|how|which board|which state|make|get|create|banaye|banai)\b", IntentType.BOCW_REGISTRATION),
            (r"\b(how|kaise)\b.{0,25}\b(make|get|create|apply for|banaye|banai)\b.{0,25}\b(bocw|construction worker|labour card|nirman shramik)\b", IntentType.BOCW_REGISTRATION),
            (r"\b(register|apply|enroll)\b.{0,35}\b(bocw|construction worker|labour card|nirman shramik)\b", IntentType.BOCW_REGISTRATION),
            (r"\b(bocw|construction worker|labour card|building worker)\b.{0,35}\b(documents?|papers?|proofs?|certificates?|required|needed?|90 day|90-day)\b", IntentType.BOCW_DOCUMENTS),
            (r"\b(documents?|papers?|proofs?)\b.{0,35}\b(bocw|construction worker|labour card)\b", IntentType.BOCW_DOCUMENTS),
            (r"\b(90 days|ninety days|90-day)\b.{0,35}\b(work|construction|certificate|proof)\b", IntentType.BOCW_ELIGIBILITY),
            (r"\b(bocw|construction worker|labour card|building worker)\b.{0,35}\b(eligible|qualification|who can|criteria|qualify)\b", IntentType.BOCW_ELIGIBILITY),
            (r"\b(bocw|construction worker|labour card|building worker|nirman shramik)\b.{0,35}\b(benefits?|insurance|pension|scholarships?|marriage|accident|education)\b", IntentType.BOCW_BENEFITS),

            # Cost / "is it free" — scheme-agnostic; only fires when no scheme name is
            # present above (a scheme-specific phrasing like "is ayushman free" already
            # matched PMJAY_BENEFITS earlier). Resolves against conversation context
            # (the scheme discussed last turn) - see EntityExtractor._CONTEXT_INHERITABLE_INTENTS.
            (r"\b(is it free|will it be free|free hai|free of cost)\b", IntentType.COST_INQUIRY),
            (r"\b(do i|will i|have to)\b.{0,20}\b(pay|payment)\b", IntentType.COST_INQUIRY),
            (r"\b(how much|what)\b.{0,15}\b(does|will)\b.{0,10}\b(it|this)\b.{0,10}\bcost\b", IntentType.COST_INQUIRY),
            (r"\b(is there|any)\b.{0,10}\b(a )?(fee|charge|cost)\b", IntentType.COST_INQUIRY),

            # Broad "what can I get" overview — scenario: a first-time migrant asking
            # what's available at all, with no scheme named yet. Deliberately requires
            # distinctive phrasing ("workers like me", "government give/provide",
            # "eligible for") so it doesn't shadow scheme-specific benefit questions.
            (r"\b(what)\b.{0,20}\b(can|do|does)\b.{0,15}\bi\b.{0,10}\bget\b.{0,25}\b(migrant|worker)\b", IntentType.WELFARE_OVERVIEW),
            (r"\b(government|sarkar)\b.{0,20}\b(give|provide|gives|provides)\b.{0,25}\b(worker|migrant|me)\b", IntentType.WELFARE_OVERVIEW),
            (r"\bwhat\b.{0,15}\b(schemes?|benefits?|help|support)\b.{0,20}\b(am i|are we|is there)\b.{0,15}\beligible\b", IntentType.WELFARE_OVERVIEW),
            (r"\bwhat\b.{0,15}(all\s+)?\b(schemes?|benefits?|help|support)\b.{0,20}\bavailable\b.{0,20}\b(for me|migrant|worker)\b", IntentType.WELFARE_OVERVIEW),
            (r"\bi.?m\s+new\b.{0,30}\b(what|which)\b.{0,20}\b(scheme|help|register)\b", IntentType.WELFARE_OVERVIEW),

            # Documents & process
            (r"\b(documents?|papers?|proofs?|aadhaar|passbook|certificates?)\b.*\b(needed|required|list|need|require)\b", IntentType.REQUIRED_DOCUMENTS),
            (r"\b(process|apply|step|where|office|panchayat|form)\b", IntentType.APPLICATION_PROCESS),

            # Translation / voice bridge — after all scheme patterns (state names like 'Tamil Nadu' should not trigger this)
            (r"\b(translate|convert|meaning|voice bridge|for the officer|for the official|speak to)\b", IntentType.TRANSLATION_REQUEST),

            # General explanation — lowest priority (routes to RAG pipeline)
            (r"\b(explain|what is|tell me|overview|summary)\b", IntentType.GENERAL_EXPLANATION),
        ]

        for pattern_str, intent in rule_definitions:
            # re.DOTALL ensures `.` matches newlines in multi-line transcripts
            self._rules.append((re.compile(pattern_str, re.IGNORECASE | re.DOTALL), intent))

    def recognize(
        self, transcribed_text: str, context_state: Optional[Dict[str, Any]] = None
    ) -> IntentResult:
        """
        Detects citizen intent from ASR transcribed (and NMT-translated) text.

        Args:
            transcribed_text: English text after ASR + NMT-to-English.
            context_state: Optional dictionary containing session metadata.

        Returns:
            IntentResult containing detected IntentType and confidence score.
        """
        if not transcribed_text or not transcribed_text.strip():
            self.logger.warning("Empty transcribed text provided to IntentRecognizer.")
            return IntentResult(IntentType.UNKNOWN_QUERY, 0.0, "empty_input")

        text_cleaned = transcribed_text.strip()
        self.logger.debug(f"Recognizing intent for text: '{text_cleaned}'")

        # Phase 1: Regex Pattern Matching
        for pattern, intent in self._rules:
            if pattern.search(text_cleaned):
                self.logger.info(f"Intent matched: {intent.value} via pattern '{pattern.pattern}'")
                return IntentResult(intent_type=intent, confidence=0.90, raw_intent_key=pattern.pattern)

        # Phase 2: Keyword Fallback Matching
        text_lower = text_cleaned.lower()
        # Use word-boundary checks to avoid 'ration' matching inside 'registration'
        _wm = lambda kw: bool(re.search(r'\b' + re.escape(kw) + r'\b', text_lower))
        # Prefix variant for genuine word stems (e.g. "portab" -> portability/
        # portable, "eligib" -> eligible/eligibility) - a trailing \b would
        # never match here since letters continue past the stem, so only the
        # leading boundary is required. NOTE: "portab" below was already
        # using _wm (whole-word) before this fix and therefore never
        # actually matched "portability"/"portable" in practice.
        _wmp = lambda kw: bool(re.search(r'\b' + re.escape(kw), text_lower))

        portab_kw  = any(_wmp(kw) for kw in ("portab",)) or any(_wm(kw) for kw in ("other state", "another state", "migrate", "migrant", "onorc", "one nation", "outside"))
        pmjay_kw   = any(_wm(kw) for kw in ("ayushman", "pmjay", "pm-jay", "golden card"))
        eshram_kw  = any(_wm(kw) for kw in ("eshram", "uan", "e-shram"))
        bocw_kw    = any(_wm(kw) for kw in ("bocw", "construction worker", "labour card", "building worker"))
        pds_kw     = _wm("ration") or _wm("pds")

        # A bare scheme-name mention is not, by itself, a real question - a
        # garbled ASR sentence that merely contains "pds" or "ayushman"
        # (e.g. "PDS Scheme it's back") would otherwise confidently default
        # to a made-up ELIGIBLE answer via the catch-all branches below.
        # Require an actual inquiry cue to co-occur before defaulting to
        # the scheme's generic eligibility intent (the more specific
        # document/benefit/register/portability branches already require
        # their own cue words, so they're unaffected by this).
        eligibility_cue_kw = (
            any(_wmp(kw) for kw in ("eligib", "qualif"))
            or any(_wm(kw) for kw in (
                "criteria", "criterion", "get", "apply", "milega", "layak",
                "chahiye", "kya hai", "what is", "can i", "how do i", "how to",
            ))
        )

        if portab_kw and pds_kw:
            return IntentResult(IntentType.PDS_PORTABILITY, 0.65, "kw_pds_portab")
        elif pds_kw and eligibility_cue_kw:
            return IntentResult(IntentType.PDS_ELIGIBILITY, 0.65, "kw_pds")
        elif pmjay_kw:
            if portab_kw:
                return IntentResult(IntentType.PMJAY_PORTABILITY, 0.65, "kw_pmjay_portab")
            elif any(_wm(kw) for kw in ("document", "paper", "proof", "required", "needed")):
                return IntentResult(IntentType.PMJAY_DOCUMENTS, 0.65, "kw_pmjay_doc")
            elif any(_wm(kw) for kw in ("benefit", "benefits", "cover", "amount", "5 lakh", "cashless", "surgery", "hospital", "treatment")):
                return IntentResult(IntentType.PMJAY_BENEFITS, 0.65, "kw_pmjay_benefit")
            elif eligibility_cue_kw:
                return IntentResult(IntentType.PMJAY_ELIGIBILITY, 0.65, "kw_pmjay_elig")
        elif eshram_kw:
            if any(_wm(kw) for kw in ("document", "paper", "proof", "required", "needed")):
                return IntentResult(IntentType.ESHRAM_DOCUMENTS, 0.65, "kw_eshram_doc")
            elif any(_wm(kw) for kw in ("register", "apply", "new", "enroll")):
                return IntentResult(IntentType.ESHRAM_REGISTRATION, 0.65, "kw_eshram_reg")
            elif any(_wm(kw) for kw in ("wage", "salary", "payment", "contractor")):
                return IntentResult(IntentType.ESHRAM_WAGE_RIGHTS, 0.65, "kw_eshram_wage")
            elif eligibility_cue_kw:
                return IntentResult(IntentType.ESHRAM_BENEFITS, 0.65, "kw_eshram_benefit")
        elif bocw_kw:
            if any(_wm(kw) for kw in ("document", "paper", "proof", "required", "needed", "certificate")):
                return IntentResult(IntentType.BOCW_DOCUMENTS, 0.65, "kw_bocw_doc")
            elif any(_wm(kw) for kw in ("register", "apply", "new", "enroll")):
                return IntentResult(IntentType.BOCW_REGISTRATION, 0.65, "kw_bocw_reg")
            elif any(_wm(kw) for kw in ("benefit", "benefits", "insurance", "pension", "scholarship", "marriage")):
                return IntentResult(IntentType.BOCW_BENEFITS, 0.65, "kw_bocw_benefit")
            elif eligibility_cue_kw:
                return IntentResult(IntentType.BOCW_ELIGIBILITY, 0.65, "kw_bocw_elig")

        # Phase 3: knowledge-base (nomadright_full_db.json) matching - the
        # live data source for anything Phase 1/2 above don't recognize.
        # Only runs as a safety-net fallback *after* the hand-tuned regex
        # and keyword ladder above, so nothing that already worked can
        # change behaviour; it exists to cover schemes/questions that only
        # exist in the JSON, like MGNREGS, without needing a Python change.
        # Picks the longest matching question_keywords phrase (a longer,
        # more specific phrase is stronger evidence than a short one).
        try:
            kb = load_knowledge()
        except Exception as exc:
            kb = None
            self.logger.warning(f"Knowledge base unavailable, skipping Phase 3 matching: {exc}")

        if kb:
            best_tag, best_score = None, 0.0
            for faq in kb.faqs:
                for kw in faq.question_keywords:
                    if phrase_in_text(kw, text_lower):
                        # Score on a comparable scale to the variant-overlap
                        # score below - longer/more specific phrase wins.
                        score = len(kw)
                        if score > best_score:
                            best_tag, best_score = faq.intent_tag, score
                for variant in faq.question_variants:
                    ratio, shared = variant_match_score(text_lower, variant)
                    if (
                        ratio >= _VARIANT_OVERLAP_MIN_SCORE
                        and shared >= _VARIANT_OVERLAP_MIN_SHARED_WORDS
                        and ratio * 50 > best_score
                    ):
                        best_tag, best_score = faq.intent_tag, ratio * 50
            if best_tag:
                mapped = INTENT_TAG_MAP.get(best_tag)
                if mapped:
                    self.logger.info(
                        f"Intent matched via knowledge base: {mapped.value} "
                        f"(faq intent_tag='{best_tag}')"
                    )
                    return IntentResult(mapped, 0.75, f"kb_{best_tag}")
                self.logger.info(
                    f"Knowledge base matched intent_tag='{best_tag}' but it has "
                    f"no rules.py handler yet - falling back to UNKNOWN_QUERY "
                    f"(routes to RAG, which does cover this)."
                )

        self.logger.info("No matching intent pattern found. Falling back to UNKNOWN_QUERY.")
        return IntentResult(IntentType.UNKNOWN_QUERY, 0.40, "fallback_unknown")
