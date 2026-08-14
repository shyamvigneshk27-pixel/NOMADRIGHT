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
importable on any dev machine. Eligibility/registration/benefit answers
come from the deterministic RulesEngine, and open-ended follow-ups come
from the ChromaDB RAG pipeline via retrieve-then-TEMPLATE, never
retrieve-then-generate. A generative LLM (qwen2.5vl:3b, see qwen_client.py)
only enters the answer path in two narrow, explicitly-gated cases: Step 6.5
below (RulesEngine and thresholded RAG both found nothing) and
process_vision_query() (a worker explicitly photographed a form via the
touchscreen Camera button) - both are grounded in retrieved context and
sentinel-gated against confident hallucination, never free generation.

Voice-bridge translation (TRANSLATION_REQUEST intent) is handled by
app.py directly via BhashiniBridge, since it needs the previous answer
text and the BHASHINI NMT model — both outside this controller's scope.
"""

import uuid
import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from pocketinfer.applications.nomad_right import constants
from pocketinfer.applications.nomad_right.config import NomadRightConfig
from pocketinfer.applications.nomad_right.intent import IntentRecognizer, IntentResult
from pocketinfer.applications.nomad_right.entities import EntityExtractor, EntityMap
from pocketinfer.applications.nomad_right.classifier import QueryClassifier, ClassificationResult
from pocketinfer.applications.nomad_right.rules import RulesEngine, RuleEvaluationResult
from pocketinfer.applications.nomad_right.database import SQLiteAccessLayer, CitizenQueryLogDTO, PortabilityRecord
from pocketinfer.applications.nomad_right.response import ResponseGenerator, StructuredResponsePackage
from pocketinfer.applications.nomad_right.rag_pipeline import RAGRetriever, RetrievedChunk
from pocketinfer.applications.nomad_right.qwen_client import QwenClient

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
        # Constructing QwenClient touches no RAM/model weights - it's just an
        # HTTP client. Ollama only loads qwen2.5vl:3b into memory on the
        # first actual answer_text()/answer_vision() call. See qwen_client.py.
        self.qwen_client = QwenClient()
        
        # Preload High-Performance L1 DB Cache
        self.db_access.preload_cache()

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

        # ── Step 6.5: LLM fallback (qwen2.5vl:3b, grounded) ─────────────────
        # Only reached when every higher-priority path in response.py's
        # chain (rule_result / rag_chunks / kb_record) found nothing -
        # mirrors that priority order exactly so a query response.py would
        # answer from kb_record never pays the qwen latency cost.
        llm_answer: Optional[str] = None
        if constants.LLM_FALLBACK_ENABLED and not rule_res and not rag_chunks and not kb_record:
            llm_answer = self._llm_fallback_answer(transcribed_text, entities, session_id)

        # ── Step 7: Response Synthesis ──────────────────────────────────────
        response_pkg: StructuredResponsePackage = self.response_generator.generate(
            intent_result=intent_res,
            classification=classification,
            rule_result=rule_res,
            kb_record=kb_record,
            rag_chunks=rag_chunks,
            entities=entities,
            llm_answer=llm_answer,
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

    # ──────────────────────────────────────────────────────────────────────
    # LLM fallback context gathering (shared by Step 6.5 and vision queries)
    # ──────────────────────────────────────────────────────────────────────

    def _gather_llm_context(self, query_text: str, scheme_code: Optional[str]) -> List[str]:
        """
        Collects grounding snippets for a qwen call: loosely-thresholded RAG
        chunks (constants.LLM_CONTEXT_MIN_SCORE - looser than the strict
        RAG_MIN_SCORE used for direct template answers, since here the
        snippets are just reading material for the LLM, not the answer
        itself) plus a KB record's key facts if a scheme was detected.
        """
        snippets: List[str] = []
        try:
            loose_chunks = self.rag_retriever.retrieve(
                query_text, min_score=constants.LLM_CONTEXT_MIN_SCORE
            )
            snippets.extend(c.text for c in loose_chunks)
        except Exception as exc:
            self.logger.warning(f"LLM context RAG lookup failed: {exc}")

        if scheme_code:
            kb_record = self.db_access.get_portability_record(scheme_code)
            if kb_record:
                snippets.extend(kb_record.eligibility_criteria[:3])
                snippets.extend(kb_record.benefits[:3])
                snippets.extend(kb_record.required_documents[:3])

        return snippets

    def _llm_fallback_answer(
        self, query_text: str, entities: EntityMap, session_id: str
    ) -> Optional[str]:
        """Step 6.5 helper: gathers context and calls qwen's text path."""
        context = self._gather_llm_context(query_text, entities.scheme_code)
        answer = self.qwen_client.answer_text(query_text, context)
        self.logger.info(
            f"[{session_id}] LLM_FALLBACK → "
            f"{'answered' if answer else 'no answer (sentinel/error)'}"
        )
        return answer

    # ──────────────────────────────────────────────────────────────────────
    # Vision form-reading (Camera button flow - see app.py)
    # ──────────────────────────────────────────────────────────────────────

    def process_vision_query(
        self, query_text: str, image_jpg: bytes, context_scheme_code: Optional[str] = None
    ) -> StructuredResponsePackage:
        """
        Answers a question about a photographed government form. Triggered
        only when a worker explicitly presses the touchscreen Camera button
        and asks a follow-up question (see app.py) - never part of the
        normal voice-query routing in process() above.

        Eligibility RULE logic doesn't apply to "what does this field mean"
        questions, so this deliberately skips RulesEngine entirely and goes
        straight to qwen, grounded with whatever scheme context is available
        (same _gather_llm_context() helper as the text fallback) plus the
        image itself.

        Args:
            query_text:          English query text (after ASR + NMT).
            image_jpg:            JPEG bytes from board.camera_frame_jpg().
            context_scheme_code:  Scheme discussed in the prior turn, if any.

        Returns:
            StructuredResponsePackage ready for BHASHINI TTS + LCD display.
        """
        session_id = str(uuid.uuid4())[:8]
        self.logger.info(f"[{session_id}] Vision pipeline start — text='{query_text}'")

        intent_res: IntentResult = self.intent_recognizer.recognize(query_text)
        entities: EntityMap = self.entity_extractor.extract(
            query_text, intent_res, context_scheme_code=context_scheme_code
        )

        context = self._gather_llm_context(query_text, entities.scheme_code)
        answer = self.qwen_client.answer_vision(query_text, image_jpg, context)
        self.logger.info(
            f"[{session_id}] VISION_FORM_QUERY → "
            f"{'answered' if answer else 'no answer (sentinel/error)'}"
        )

        if answer:
            response_pkg = self.response_generator.generate_vision_response(
                answer, scheme_code=entities.scheme_code
            )
        else:
            response_pkg = self.response_generator.generate(
                intent_result=intent_res,
                classification=self.query_classifier.classify(intent_res, entities),
                entities=entities,
            )

        log_dto = CitizenQueryLogDTO(
            session_id=session_id,
            intent="VISION_FORM_QUERY",
            scheme_code=entities.scheme_code or "GENERAL",
            transcribed_text=query_text,
            response_summary=response_pkg.voice_text[:120],
            language=entities.language_code or "en",
            status=response_pkg.severity.value,
        )
        self.db_access.insert_query_log(log_dto)

        return response_pkg
