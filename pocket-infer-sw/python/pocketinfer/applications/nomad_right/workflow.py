"""
NomadRight Workflow Controller Module

Orchestrates the complete post-ASR / pre-TTS Decision Layer pipeline:

  English query text (post BHASHINI ASR + NMT-to-English)
    │
    ├─ 1. IntentRecognizer      → IntentResult
    ├─ 2. EntityExtractor       → EntityMap
    ├─ 3. QueryClassifier       → ClassificationResult (route decision)
    ├─ 4. SQLiteAccessLayer     → PortabilityRecord (live KB data, optional)
    ├─ 5. RulesEngine           → RuleEvaluationResult (deterministic, optional)
    ├─ 6. RAGRetriever          → List[RetrievedChunk] (retrieve-then-template, optional)
    ├─ 7. ResponseGenerator     → StructuredResponsePackage
    └─ 8. Audit log             → citizen_query_log row

All steps are 100% offline on the Suno Sutra platform, and this module has
no hardware or BHASHINI-model dependency — it is pure text-in/text-out and
importable on any dev machine. There is no generative LLM anywhere in the
answer path: eligibility/registration/benefit answers come from the
deterministic RulesEngine, and open-ended follow-ups come from the
ChromaDB RAG pipeline via retrieve-then-TEMPLATE, never retrieve-then-generate.

Voice-bridge translation (TRANSLATION_REQUEST intent) is handled by
app.py directly via BhashiniBridge, since it needs the previous answer
text and the BHASHINI NMT model — both outside this controller's scope.
"""

import uuid
import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from pocketinfer.applications.nomad_right.config import NomadRightConfig
from pocketinfer.applications.nomad_right.intent import IntentRecognizer, IntentResult
from pocketinfer.applications.nomad_right.entities import EntityExtractor, EntityMap
from pocketinfer.applications.nomad_right.classifier import QueryClassifier, ClassificationResult
from pocketinfer.applications.nomad_right.rules import RulesEngine, RuleEvaluationResult
from pocketinfer.applications.nomad_right.database import SQLiteAccessLayer, CitizenQueryLogDTO, PortabilityRecord
from pocketinfer.applications.nomad_right.response import ResponseGenerator, StructuredResponsePackage
from pocketinfer.applications.nomad_right.rag_pipeline import RAGRetriever, RetrievedChunk

logger = logging.getLogger(__name__)


class IWorkflowController(ABC):
    """Abstract interface for the NomadRight pipeline orchestrator."""

    @abstractmethod
    def process(
        self, transcribed_text: str, context_scheme_code: Optional[str] = None
    ) -> StructuredResponsePackage:
        """Processes an English-language query through the Decision Layer."""


class WorkflowController(IWorkflowController):
    """
    Central pipeline orchestrator wiring Intent Recognition, Entity Extraction,
    Query Routing, Rules Evaluation, SQLite/RAG lookup, and Response Generation.
    """

    def __init__(self, config: Optional[NomadRightConfig] = None):
        self.config = config or NomadRightConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

        self.intent_recognizer = IntentRecognizer(config=self.config)
        self.db_access = SQLiteAccessLayer(config=self.config)
        self.entity_extractor = EntityExtractor(db_access=self.db_access, config=self.config)
        self.query_classifier = QueryClassifier(config=self.config)
        self.rules_engine = RulesEngine(config=self.config)
        self.response_generator = ResponseGenerator(config=self.config)
        self.rag_retriever = RAGRetriever(config=self.config)

    # ──────────────────────────────────────────────────────────────────────
    # Main pipeline
    # ──────────────────────────────────────────────────────────────────────

    def process(
        self, transcribed_text: str, context_scheme_code: Optional[str] = None
    ) -> StructuredResponsePackage:
        """
        Runs the full Decision Layer pipeline for one citizen query.

        Args:
            transcribed_text: English query text, after BHASHINI ASR in the
                               worker's language and NMT translation to English.
            context_scheme_code: Scheme discussed in the immediately prior
                               turn of this session (e.g. "PDS"), if any -
                               lets generic follow-ups ("what documents do I
                               need?") resolve without repeating the scheme
                               name. See EntityExtractor.extract().

        Returns:
            StructuredResponsePackage ready for BHASHINI TTS + LCD display.
        """
        session_id = str(uuid.uuid4())[:8]
        self.logger.info(f"[{session_id}] Pipeline start — text='{transcribed_text}'")

        # ── Step 1: Intent Recognition ─────────────────────────────────────
        intent_res: IntentResult = self.intent_recognizer.recognize(transcribed_text)
        self.logger.info(
            f"[{session_id}] INTENT → {intent_res.intent_type.value}  "
            f"(confidence={intent_res.confidence:.2f})"
        )

        # ── Step 2: Entity Extraction ──────────────────────────────────────
        entities: EntityMap = self.entity_extractor.extract(
            transcribed_text, intent_res, context_scheme_code=context_scheme_code
        )
        self.logger.info(
            f"[{session_id}] ENTITIES → scheme={entities.scheme_code}  "
            f"state={entities.state_name}  doc={entities.document_type}  "
            f"lang={entities.language_code}"
        )

        # ── Step 3: Query Routing ──────────────────────────────────────────
        classification: ClassificationResult = self.query_classifier.classify(intent_res, entities)
        self.logger.info(f"[{session_id}] ROUTE → {classification.route_type.value}")

        # ── Step 4: Knowledge Base Lookup ──────────────────────────────────
        kb_record: Optional[PortabilityRecord] = None
        if classification.requires_db and entities.scheme_code:
            kb_record = self.db_access.get_portability_record(entities.scheme_code)
            if kb_record:
                self.logger.info(
                    f"[{session_id}] DB HIT → scheme_id={kb_record.scheme_id}  "
                    f"eligibility rows={len(kb_record.eligibility_criteria)}"
                )
            else:
                self.logger.warning(f"[{session_id}] DB MISS for scheme={entities.scheme_code}")

        # ── Step 5: Rules Engine Evaluation ────────────────────────────────
        rule_res: Optional[RuleEvaluationResult] = None
        if classification.requires_rules:
            rule_res = self.rules_engine.evaluate(intent_res, entities, kb_record)
            self.logger.info(
                f"[{session_id}] RULE → {rule_res.triggered_rule_id}  "
                f"status={rule_res.status_code.value}  passed={rule_res.passed}"
            )

        # ── Step 6: RAG retrieval (retrieve-then-template, no LLM) ─────────
        rag_chunks: List[RetrievedChunk] = []
        if classification.requires_rag:
            rag_chunks = self.rag_retriever.retrieve(transcribed_text)
            self.logger.info(f"[{session_id}] RAG → {len(rag_chunks)} chunks retrieved")

        # ── Step 7: Response Synthesis ──────────────────────────────────────
        response_pkg: StructuredResponsePackage = self.response_generator.generate(
            intent_result=intent_res,
            classification=classification,
            rule_result=rule_res,
            kb_record=kb_record,
            rag_chunks=rag_chunks,
            entities=entities,
        )
        self.logger.info(
            f"[{session_id}] RESPONSE → severity={response_pkg.severity.value}  "
            f"voice='{response_pkg.voice_text[:60]}...'"
        )

        # ── Step 8: Audit Logging ───────────────────────────────────────────
        log_dto = CitizenQueryLogDTO(
            session_id=session_id,
            intent=intent_res.intent_type.value,
            scheme_code=entities.scheme_code or "GENERAL",
            transcribed_text=transcribed_text,
            response_summary=response_pkg.voice_text[:120],
            language=entities.language_code or "en",
            status=response_pkg.severity.value,
        )
        self.db_access.insert_query_log(log_dto)

        return response_pkg
