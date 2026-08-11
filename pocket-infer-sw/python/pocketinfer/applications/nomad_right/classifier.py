"""
NomadRight Query Classifier & Router Module
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional

from pocketinfer.applications.nomad_right.config import NomadRightConfig
from pocketinfer.applications.nomad_right.intent import IntentResult, IntentType
from pocketinfer.applications.nomad_right.entities import EntityMap

logger = logging.getLogger(__name__)


class RouteType(Enum):
    """Subsystem routes supported by Query Router."""
    RULES_ENGINE = "RULES_ENGINE"      # Deterministic eligibility/portability/benefits logic
    RAG_PIPELINE = "RAG_PIPELINE"      # ChromaDB retrieve-then-template for open-ended questions
    TRANSLATION = "TRANSLATION"        # Voice bridge: translate last answer for a local official
    DB_ONLY = "DB_ONLY"


@dataclass
class ClassificationResult:
    """Dataclass storing the routing decision."""
    route_type: RouteType
    requires_db: bool
    requires_rules: bool
    requires_rag: bool
    priority: int
    execution_plan: Dict[str, Any] = field(default_factory=dict)


class IQueryClassifier(ABC):
    """Abstract interface for Query Routing decisions."""

    @abstractmethod
    def classify(
        self,
        intent_result: IntentResult,
        entity_map: EntityMap,
        system_state: Optional[Dict[str, Any]] = None
    ) -> ClassificationResult:
        """Determines execution route based on Intent and Entities."""
        pass


class QueryClassifier(IQueryClassifier):
    """
    Offline Query Classifier decision engine directing execution flow to the
    deterministic RulesEngine, the ChromaDB RAG pipeline, or the voice-bridge
    NMT/TTS path. There is no generative LLM in the answer path — hallucination
    risk is unacceptable for legal welfare entitlements (see prompt.txt).
    """

    # Scheme codes that have a hand-written dispatch branch in
    # RulesEngine.evaluate() (see rules.py). A scheme detected in the query
    # that ISN'T in this set (e.g. MGNREGS, which is in the KB/RAG index
    # but has no rules.py branch yet) must not force the RULES_ENGINE
    # route below - rules.py would just fall through to its generic
    # "please mention the scheme name" answer, even though the scheme WAS
    # named. Routing those to RAG_PIPELINE instead lets the (now
    # similarity-thresholded) RAG index answer them properly.
    _SCHEMES_WITH_RULES = ("PDS", "PMJAY", "ESHRAM", "BOCW")

    # Intents with hand-written, deterministic rules in RulesEngine
    _RULES_ENGINE_INTENTS = (
        IntentType.PDS_ELIGIBILITY, IntentType.PDS_PORTABILITY,
        IntentType.PMJAY_ELIGIBILITY, IntentType.PMJAY_BENEFITS,
        IntentType.PMJAY_DOCUMENTS, IntentType.PMJAY_PORTABILITY,
        IntentType.ESHRAM_REGISTRATION, IntentType.ESHRAM_BENEFITS,
        IntentType.ESHRAM_DOCUMENTS, IntentType.ESHRAM_WAGE_RIGHTS,
        IntentType.BOCW_ELIGIBILITY, IntentType.BOCW_REGISTRATION,
        IntentType.BOCW_BENEFITS, IntentType.BOCW_DOCUMENTS,
        # Always deterministic, never RAG - WELFARE_OVERVIEW has one fixed
        # walkthrough answer, and COST_INQUIRY resolves via conversation
        # context onto whichever scheme was last discussed (or a graceful
        # "please mention the scheme" fallback if there is none).
        IntentType.WELFARE_OVERVIEW, IntentType.COST_INQUIRY,
    )

    def __init__(self, config: Optional[NomadRightConfig] = None):
        self.config = config or NomadRightConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def classify(
        self,
        intent_result: IntentResult,
        entity_map: EntityMap,
        system_state: Optional[Dict[str, Any]] = None
    ) -> ClassificationResult:
        """
        Selects optimal execution subsystem route.

        Args:
            intent_result: Classified IntentResult.
            entity_map: Extracted EntityMap.
            system_state: Optional system health dictionary.

        Returns:
            ClassificationResult containing Subsystem RouteType and requirement flags.
        """
        intent = intent_result.intent_type
        has_scheme = entity_map.scheme_code is not None
        # A scheme name merely being *present in the text* is not enough on
        # its own - rules.py's per-scheme dispatch (e.g. _evaluate_pds)
        # ends with an unconditional "default to ELIGIBLE" branch for any
        # intent it doesn't specifically recognize, so routing here on
        # has_scheme alone meant a garbled sentence that happened to
        # contain a scheme name (e.g. "PDS Scheme it's back") got a
        # confident PDS-ELIG-001 answer instead of the fallback - even
        # though IntentRecognizer correctly returned UNKNOWN_QUERY for it.
        # Only trust the scheme-name signal when SOME real intent was also
        # recognized (Phase 1/2/3 in intent.py all require an actual
        # inquiry cue, not just a bare scheme mention - see intent.py).
        has_rules_scheme = (
            entity_map.scheme_code in self._SCHEMES_WITH_RULES
            and intent != IntentType.UNKNOWN_QUERY
        )

        self.logger.debug(f"Classifying query: intent={intent.value}, has_scheme={has_scheme}")

        # 1. Voice bridge translation request
        if intent == IntentType.TRANSLATION_REQUEST:
            self.logger.info("Routing to TRANSLATION (voice bridge)")
            return ClassificationResult(
                route_type=RouteType.TRANSLATION,
                requires_db=False,
                requires_rules=False,
                requires_rag=False,
                priority=1,
                execution_plan={"target": "BHASHINI NMT voice bridge"}
            )

        # 2. Rules Engine fast path — deterministic, zero-hallucination answers
        if has_rules_scheme or intent in self._RULES_ENGINE_INTENTS:
            self.logger.info("Routing to RULES_ENGINE (fast path)")
            return ClassificationResult(
                route_type=RouteType.RULES_ENGINE,
                requires_db=True,
                requires_rules=True,
                requires_rag=False,
                priority=1,
                execution_plan={"target": "Rules Engine"}
            )

        # 3. RAG pipeline fallback — open-ended / follow-up questions with no
        #    directly-matched rule (GENERAL_EXPLANATION, REQUIRED_DOCUMENTS
        #    without a scheme mention, UNKNOWN_QUERY, etc.)
        self.logger.info("Routing to RAG_PIPELINE (retrieve-then-template)")
        return ClassificationResult(
            route_type=RouteType.RAG_PIPELINE,
            requires_db=False,
            requires_rules=False,
            requires_rag=True,
            priority=2,
            execution_plan={"target": "ChromaDB RAG Pipeline"}
        )
