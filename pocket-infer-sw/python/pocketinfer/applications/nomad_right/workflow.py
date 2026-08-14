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

Qwen (constants.LLM_FALLBACK_MODEL) enters the answer path in three
explicitly-gated cases, always grounded and sentinel-gated against
confident hallucination (see qwen_client.py):
  1. Step 6.5a - RAG_PIPELINE retrieve-then-GENERATE: once RAGRetriever
     has found chunks above RAG_MIN_SCORE, Qwen synthesizes the final
     answer from exactly those chunks (never free generation). If Qwen
     errors or returns the not-found sentinel, response.py falls back to
     the raw top chunk (retrieve-then-TEMPLATE) so an answer is never
     silently dropped.
  2. Step 6.5b - text fallback: when RulesEngine, RAG, and the KB all find
     nothing.
  3. process_vision_query() - a worker photographs a form via the
     touchscreen Camera button.
RULES_ENGINE-routed queries (statutory eligibility/registration/benefit
determinations) never touch Qwen - those stay 100% deterministic.
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

        # Warm the RAG embedder (sentence-transformers) + ChromaDB
        # collection now, at app startup, instead of leaving it lazy until
        # the first live RAG-routed query. Measured on-device: this cold
        # load is highly variable (10-140s depending on system memory
        # pressure at the moment) - lazy-loading it meant whichever worker
        # happened to ask the first RAG-routed question of a session could
        # wait well over a minute for an answer, blowing the <7s latency
        # budget. is_available() triggers the same _ensure_ready() load
        # path and never raises (swallows errors, logs a warning) - a slow
        # or failed warm-up here degrades gracefully to the existing
        # empty-chunks-on-failure behavior in rag_pipeline.py, it never
        # blocks startup from completing.
        if self.rag_retriever.is_available():
            self.logger.info("RAG engine pre-warmed at startup.")
        else:
            self.logger.warning("RAG engine unavailable after startup warm-up attempt.")

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

        # ── Step 6: RAG retrieval (ChromaDB, no LLM here) ───────────────────
        rag_chunks: List[RetrievedChunk] = []
        if classification.requires_rag:
            rag_chunks = self.rag_retriever.retrieve(transcribed_text)
            self.logger.info(f"[RAG] [{session_id}] {len(rag_chunks)} chunks retrieved")

        # ── Step 6.5a: RAG retrieve-then-GENERATE (qwen, grounded) ─────────
        # Every RAG_PIPELINE hit gets its final answer synthesized by Qwen
        # from exactly the chunks retrieved above (LLM_FALLBACK_MODEL) -
        # never free generation. response.py falls back to the raw top
        # chunk if this comes back empty (error or not-found sentinel).
        rag_llm_answer: Optional[str] = None
        if constants.LLM_FALLBACK_ENABLED and rag_chunks:
            rag_llm_answer = self.qwen_client.answer_text(
                transcribed_text, [c.text for c in rag_chunks]
            )
            self.logger.info(
                f"[QWEN] [{session_id}] RAG-grounded generation → "
                f"{'answered' if rag_llm_answer else 'no answer (sentinel/error) - template fallback'}"
            )

        # ── Step 6.5b: LLM text fallback (qwen) ─────────────────────────────
        # Reached whenever rule_result, kb_record, AND a Qwen-grounded RAG
        # answer (Step 6.5a) all came up empty - deliberately NOT gated on
        # "rag_chunks empty", only on "rag_llm_answer empty". Some of the
        # newer, terser scheme chunks (e.g. "PM Vishwakarma. Marketing
        # support" - a 3-word fragment) can spuriously cross RAG_MIN_SCORE
        # against completely unrelated/garbled text (short passages carry
        # little specific semantic content, so embedding similarity against
        # them is noisier) - reproduced on-device with a garbled-ASR query
        # that matched 3 PM_VISHWAKARMA chunks at >0.83 even though it was
        # meaningless. Qwen (Step 6.5a) correctly declined to answer from
        # those chunks (sentinel), which is a stronger relevance signal
        # than the raw cosine score that let them through RAG_MIN_SCORE in
        # the first place - so a Qwen decline here now gets a second real
        # chance via this smarter fallback instead of falling straight to
        # response.py's blind "echo the raw top chunk" tier. Two cases:
        #   - A scheme WAS named - ground qwen in that scheme's own
        #     deterministic KB record (a direct DB lookup, not another
        #     vector search) so the answer still centers on the right
        #     scheme's real facts.
        #   - No scheme was named at all - a genuinely general/off-topic
        #     question - let qwen answer directly as a general assistant.
        # Previously both cases ran a second, LOOSELY-thresholded RAG
        # search as "reading material," which was both redundant latency
        # (Step 6 already searched once) and a real hallucination bug: an
        # unrelated query ("Updating the app") pulled in an unrelated
        # e-Shram chunk as fake context and qwen fabricated an answer from
        # it. Removed entirely.
        llm_answer: Optional[str] = None
        if constants.LLM_FALLBACK_ENABLED and not rule_res and not rag_llm_answer and not kb_record:
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
            rag_llm_answer=rag_llm_answer,
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
        self._clear_gpu_cache()

        return response_pkg

    # ──────────────────────────────────────────────────────────────────────
    # GPU memory hygiene
    # ──────────────────────────────────────────────────────────────────────

    def _clear_gpu_cache(self) -> None:
        """
        Releases any GPU memory this Python process is still holding after
        finishing one complete pipeline iteration, so a long-running kiosk
        session doesn't accumulate a growing CUDA allocator cache turn
        after turn on the Jetson's unified memory pool. Only affects
        allocations made INSIDE this process (currently none by default -
        the RAG embedder is pinned to CPU, see rag_pipeline.py). Qwen's own
        GPU memory is managed separately by Ollama (a different OS process
        running its own llama.cpp allocator) and is deliberately NOT
        touched here - see constants.LLM_KEEP_ALIVE for why it's kept
        warm between turns rather than unloaded (unloading it every
        iteration would reintroduce the ~30-60s cold-load penalty this
        app's <7s latency budget can't afford). Safe no-op if torch/CUDA
        aren't available - never allowed to break a pipeline turn.
        """
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as exc:
            self.logger.debug(f"GPU cache clear skipped: {exc}")

    # ──────────────────────────────────────────────────────────────────────
    # LLM fallback for queries strict RAG and RulesEngine both missed
    # ──────────────────────────────────────────────────────────────────────

    def _gather_kb_context(self, scheme_code: str) -> List[str]:
        """
        Deterministic grounding snippets for a named scheme's own KB record
        (direct DB lookup - not a vector search, so it can't attach the
        wrong scheme's facts to the question). Used only when a scheme was
        actually named but strict RAG (Step 6) didn't match a chunk for
        this exact phrasing.
        """
        snippets: List[str] = []
        kb_record = self.db_access.get_portability_record(scheme_code)
        if kb_record:
            snippets.extend(kb_record.eligibility_criteria[:3])
            snippets.extend(kb_record.benefits[:3])
            snippets.extend(kb_record.required_documents[:3])
        return snippets

    def _llm_fallback_answer(
        self, query_text: str, entities: EntityMap, session_id: str
    ) -> Optional[str]:
        """
        Step 6.5b helper. A scheme was named -> ground qwen in that
        scheme's own KB record. No scheme was named -> a genuinely
        general/off-topic question, let qwen answer directly with no forced
        scheme context (see qwen_client._GENERAL_SYSTEM_PROMPT).
        """
        if entities.scheme_code:
            context = self._gather_kb_context(entities.scheme_code)
            answer = self.qwen_client.answer_text(query_text, context)
            kind = "scheme-grounded (KB)"
        else:
            answer = self.qwen_client.answer_general(query_text)
            kind = "general"
        self.logger.info(
            f"[QWEN] [{session_id}] LLM_FALLBACK ({kind}) → "
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
        straight to qwen, grounded only in the photographed image itself
        (no RAG/KB context - see the CAMERA_FORM note below).

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

        # CAMERA_FORM never touches RAG/ChromaDB/the scheme database - the
        # image itself is the only source of truth Qwen is grounded against
        # here (see qwen_client.answer_vision's system prompt).
        answer = self.qwen_client.answer_vision(query_text, image_jpg, context_snippets=None)
        self.logger.info(
            f"[QWEN_VISION] [{session_id}] VISION_FORM_QUERY → "
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
        self._clear_gpu_cache()

        return response_pkg
