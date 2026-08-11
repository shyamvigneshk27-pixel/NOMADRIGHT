"""
NomadRight Entity Extraction Module

Extracts structured welfare-domain entities (scheme codes, state names,
document types, Aadhaar partial IDs, and numeric values) from ASR text.
Operates fully offline using regex patterns and a gazetteer approach.
"""

import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple

from pocketinfer.applications.nomad_right.config import NomadRightConfig
from pocketinfer.applications.nomad_right.intent import IntentResult, IntentType
from pocketinfer.applications.nomad_right.knowledge_loader import load_knowledge, phrase_in_text

logger = logging.getLogger(__name__)


class EntityType(Enum):
    """Supported entity categories for NomadRight welfare queries."""
    SCHEME_CODE = "SCHEME_CODE"
    STATE_NAME = "STATE_NAME"
    DOCUMENT_TYPE = "DOCUMENT_TYPE"
    AADHAAR_LAST4 = "AADHAAR_LAST4"
    NUMERIC_VALUE = "NUMERIC_VALUE"
    LANGUAGE_CODE = "LANGUAGE_CODE"


@dataclass
class EntityMap:
    """Dataclass storing extracted query parameters from a citizen's utterance."""
    scheme_code: Optional[str] = None           # e.g. "PDS", "PMJAY", "ESHRAM", "BOCW"
    state_name: Optional[str] = None            # e.g. "Rajasthan", "Maharashtra"
    document_type: Optional[str] = None         # e.g. "ration_card", "aadhaar"
    aadhaar_last4: Optional[str] = None         # Last 4 digits spoken by citizen
    language_code: Optional[str] = None         # Target language for translation
    numeric_values: Dict[str, float] = field(default_factory=dict)
    is_complete: bool = False
    raw_entities: Dict[str, str] = field(default_factory=dict)


class IEntityExtractor(ABC):
    """Abstract interface for Entity Extraction engines."""

    @abstractmethod
    def extract(
        self, transcribed_text: str, intent_result: Optional[IntentResult] = None
    ) -> EntityMap:
        """Extracts structured parameters from ASR speech text."""
        pass


class EntityExtractor(IEntityExtractor):
    """
    Offline Entity Extraction Engine using regex patterns and a keyword
    gazetteer for Indian state names, document types, and welfare schemes.
    All extraction is deterministic and requires no network access.
    """

    # Indian state names gazetteer
    _STATE_NAMES: List[str] = [
        "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
        "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
        "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya",
        "mizoram", "nagaland", "odisha", "punjab", "rajasthan", "sikkim",
        "tamil nadu", "telangana", "tripura", "uttar pradesh", "uttarakhand",
        "west bengal", "delhi", "jammu and kashmir", "ladakh",
    ]

    # Document type keyword map
    _DOCUMENT_KEYWORDS: Dict[str, str] = {
        "aadhaar": "aadhaar_card",
        "aadhar": "aadhaar_card",
        "ration card": "ration_card",
        "ration": "ration_card",
        "passbook": "bank_passbook",
        "bank passbook": "bank_passbook",
        "birth certificate": "birth_certificate",
        "caste certificate": "caste_certificate",
        "income certificate": "income_certificate",
        "golden card": "ayushman_golden_card",
        "ayushman card": "ayushman_golden_card",
        "work certificate": "work_certificate_90_day",
        "90 day certificate": "work_certificate_90_day",
        "uan card": "eshram_uan_card",
        "uan": "eshram_uan_card",
        "labour card": "bocw_labour_card",
        "bocw card": "bocw_labour_card",
    }

    # Language code keyword map (for TRANSLATION_REQUEST intent)
    _LANGUAGE_KEYWORDS: Dict[str, str] = {
        "hindi": "hi",
        "tamil": "ta",
        "telugu": "te",
        "kannada": "kn",
        "malayalam": "ml",
        "marathi": "mr",
        "bengali": "bn",
        "gujarati": "gu",
        "punjabi": "pa",
        "odia": "or",
        "assamese": "as",
        "urdu": "ur",
        "english": "en",
    }

    def __init__(self, db_access: Optional[Any] = None, config: Optional[NomadRightConfig] = None):
        self.db_access = db_access
        self.config = config or NomadRightConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

        # Aadhaar last-4 pattern: "my aadhaar ends with 1234" or "last four 5678"
        self._aadhaar_last4_pattern = re.compile(
            r"(?:aadhaar|aadhar).*?(\d{4})|last\s*(?:four|4)\s*(?:digits?)?.*?(\d{4})",
            re.IGNORECASE
        )
        # Generic number extraction
        self._numeric_pattern = re.compile(r"\b(\d+(?:\.\d+)?)\b")

        # Pre-compile word-boundary state patterns (longest names first to avoid
        # shorter alternatives stealing matches in ambiguous phrases)
        sorted_states = sorted(self._STATE_NAMES, key=len, reverse=True)
        self._state_patterns: List[tuple] = [
            (state, re.compile(r"\b" + re.escape(state) + r"\b", re.IGNORECASE))
            for state in sorted_states
        ]

    def normalize_spoken_numbers(self, text: str) -> str:
        """
        Normalizes spoken verbal digit words to numeric digits.
        Example: 'one two three four' -> '1234' (for Aadhaar last-4 extraction).
        """
        if not text:
            return ""

        word_to_digit = {
            "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
            "four": "4", "five": "5", "six": "6", "seven": "7",
            "eight": "8", "nine": "9",
        }
        normalized = text
        for word, digit in word_to_digit.items():
            normalized = re.sub(r"\b" + word + r"\b", digit, normalized, flags=re.IGNORECASE)
        return normalized

    # Word-boundary keyword sets per scheme. Using \b-bounded regex (not bare
    # substring `in` checks) matters here: "ration" is a substring of
    # "registration", so a naive `"ration" in text` check would misclassify
    # every e-Shram/BOCW *registration* query as PDS.
    _SCHEME_KEYWORDS: List[Tuple[str, List[str]]] = [
        ("PDS",    ["ration", "pds", "bpl", "aay", "free food", "food grain"]),
        ("PMJAY",  ["ayushman", "pmjay", "pm-jay", "golden card", "5 lakh"]),
        ("ESHRAM", ["eshram", "e-shram", "e shram", "uan", "universal account number"]),
        ("BOCW",   ["bocw", "construction worker", "labour card", "building worker", "building and other construction"]),
    ]

    def _extract_scheme_code(self, text_lower: str) -> Optional[str]:
        """Returns scheme code based on word-boundary keyword presence.

        Checks the original hardcoded table first (unchanged behaviour for
        the four originally-verified schemes), then the live
        nomadright_full_db.json-sourced index as a second pass - this is
        what makes a scheme added only to that JSON (e.g. MGNREGS) newly
        detectable without a Python code change. If the JSON is ever
        missing/malformed, this second pass is skipped and the hardcoded
        table alone still works exactly as before.
        """
        for scheme_code, keywords in self._SCHEME_KEYWORDS:
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                    return scheme_code

        try:
            kb = load_knowledge()
        except Exception as exc:
            self.logger.warning(f"Knowledge base unavailable for scheme lookup: {exc}")
            return None

        for scheme in kb.schemes:
            for kw in scheme.keywords:
                if phrase_in_text(kw, text_lower):
                    return scheme.short_code
        return None

    def _extract_state_name(self, text_lower: str) -> Optional[str]:
        """Matches Indian state names from the gazetteer using word-boundary regex.

        Uses pre-compiled \\b-bounded patterns sorted longest-first to prevent
        false positives (e.g. 'goa' matching 'goals', 'or' matching 'border').
        """
        for state, pattern in self._state_patterns:
            if pattern.search(text_lower):
                return state.title()
        return None

    def _extract_document_type(self, text_lower: str) -> Optional[str]:
        """Matches document type keywords (word-boundary; 'ration' must not match inside 'registration')."""
        for keyword, doc_type in self._DOCUMENT_KEYWORDS.items():
            if re.search(r"\b" + re.escape(keyword) + r"\b", text_lower):
                return doc_type
        return None

    def _extract_language_code(self, text_lower: str) -> Optional[str]:
        """Matches target language keywords for TRANSLATION_REQUEST."""
        for lang_name, lang_code in self._LANGUAGE_KEYWORDS.items():
            if lang_name in text_lower:
                return lang_code
        return None

    def _extract_aadhaar_last4(self, normalized_text: str) -> Optional[str]:
        """Extracts last 4 Aadhaar digits if spoken in the utterance."""
        match = self._aadhaar_last4_pattern.search(normalized_text)
        if match:
            return match.group(1) or match.group(2)
        return None

    # Intents that are clearly scheme-dependent follow-ups ("what documents
    # do I need?", "where do I apply?") but carry no scheme name of their
    # own - safe to inherit the previous turn's scheme from conversation
    # context. Deliberately excludes GENERAL_EXPLANATION/UNKNOWN_QUERY: a
    # vague or off-topic follow-up should still fall back honestly rather
    # than silently answering about whatever scheme was last discussed.
    _CONTEXT_INHERITABLE_INTENTS = (
        IntentType.REQUIRED_DOCUMENTS,
        IntentType.APPLICATION_PROCESS,
        IntentType.COST_INQUIRY,
    )

    def extract(
        self,
        transcribed_text: str,
        intent_result: Optional[IntentResult] = None,
        context_scheme_code: Optional[str] = None,
    ) -> EntityMap:
        """
        Extracts welfare-domain entities from ASR transcribed text.

        Args:
            transcribed_text: English text after BHASHINI ASR + NMT-to-English.
            intent_result: IntentResult from Intent Recognition module (optional).
            context_scheme_code: The scheme discussed in the immediately prior
                turn of this session (e.g. "PDS"), if any. Used only as a
                last-resort fallback for a narrow set of generic follow-up
                intents (see _CONTEXT_INHERITABLE_INTENTS) so a worker can
                say "will my ration card work here?" and then just "what
                documents do I need?" without repeating the scheme name -
                matching real conversational flow. Never overrides a scheme
                actually named in this turn's own text.

        Returns:
            EntityMap containing extracted welfare parameters.
        """
        if not transcribed_text:
            return EntityMap(is_complete=False)

        normalized_text = self.normalize_spoken_numbers(transcribed_text)
        text_lower = normalized_text.lower()
        self.logger.debug(f"Extracting entities from: '{text_lower}'")

        scheme_code = self._extract_scheme_code(text_lower)

        # Infer scheme from intent if not found in text
        if not scheme_code and intent_result:
            intent_to_scheme = {
                IntentType.PDS_ELIGIBILITY: "PDS",
                IntentType.PDS_PORTABILITY: "PDS",
                IntentType.PMJAY_ELIGIBILITY: "PMJAY",
                IntentType.PMJAY_BENEFITS: "PMJAY",
                IntentType.PMJAY_DOCUMENTS: "PMJAY",
                IntentType.PMJAY_PORTABILITY: "PMJAY",
                IntentType.ESHRAM_REGISTRATION: "ESHRAM",
                IntentType.ESHRAM_BENEFITS: "ESHRAM",
                IntentType.ESHRAM_DOCUMENTS: "ESHRAM",
                IntentType.ESHRAM_WAGE_RIGHTS: "ESHRAM",
                IntentType.BOCW_ELIGIBILITY: "BOCW",
                IntentType.BOCW_REGISTRATION: "BOCW",
                IntentType.BOCW_BENEFITS: "BOCW",
                IntentType.BOCW_DOCUMENTS: "BOCW",
            }
            scheme_code = intent_to_scheme.get(intent_result.intent_type)

        # Last resort: inherit the previous turn's scheme for a narrow set
        # of generic follow-up intents (see _CONTEXT_INHERITABLE_INTENTS).
        if (
            not scheme_code
            and context_scheme_code
            and intent_result
            and intent_result.intent_type in self._CONTEXT_INHERITABLE_INTENTS
        ):
            scheme_code = context_scheme_code
            self.logger.info(f"Inherited scheme_code='{scheme_code}' from conversation context")

        state_name = self._extract_state_name(text_lower)
        document_type = self._extract_document_type(text_lower)
        language_code = self._extract_language_code(text_lower)
        aadhaar_last4 = self._extract_aadhaar_last4(normalized_text)

        # Extract generic numeric values
        numeric_values: Dict[str, float] = {}
        for i, match in enumerate(self._numeric_pattern.finditer(normalized_text)):
            numeric_values[f"num_{i}"] = float(match.group(1))

        is_complete = bool(scheme_code or document_type)

        self.logger.info(
            f"Extracted entities: scheme={scheme_code}, state={state_name}, "
            f"doc_type={document_type}, lang={language_code}"
        )

        return EntityMap(
            scheme_code=scheme_code,
            state_name=state_name,
            document_type=document_type,
            aadhaar_last4=aadhaar_last4,
            language_code=language_code,
            numeric_values=numeric_values,
            is_complete=is_complete,
            raw_entities={
                "raw_text": transcribed_text,
                "normalized_text": normalized_text
            }
        )
