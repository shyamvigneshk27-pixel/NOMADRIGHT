"""
NomadRight RAG Pipeline Module

ChromaDB + multilingual-e5-small retrieve-then-TEMPLATE pipeline for
open-ended / follow-up welfare questions that the deterministic RulesEngine
doesn't directly cover. There is deliberately no generative LLM in the
answer path — hallucination risk is unacceptable for legal welfare
entitlements. Retrieved chunks are slot-filled into templates by
ResponseGenerator (response.py), never paraphrased by a model.

Static cache (built once, offline, read-only at runtime):
    A ChromaDB PersistentClient index of scheme JSON chunks, embedded with
    intfloat/multilingual-e5-small (~118MB, ARM-optimised, supports
    Hindi/Odia/Tamil query embedding as well as English).

Build (or rebuild) the index once on-device with:
    python -m pocketinfer.applications.nomad_right.rag_pipeline --build-cache

chromadb and sentence-transformers are lazy-imported so this module stays
importable — and the rest of NomadRight keeps working via the RulesEngine
fast path — even before those two pip packages are installed on-device.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from pocketinfer.applications.nomad_right import constants
from pocketinfer.applications.nomad_right.config import NomadRightConfig

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """One retrieved scheme passage, ready for template slot-filling."""
    text: str
    scheme_id: str
    scheme_code: str
    section: str
    score: float


class RAGRetrieverNotAvailableError(RuntimeError):
    """Raised when chromadb/sentence-transformers aren't installed, or the index is empty."""


class RAGRetriever:
    """
    Retrieve-then-template RAG pipeline over the four NomadRight scheme JSONs
    (PDS, PM-JAY, e-Shram+OSH Code, BOCW).

    Chunking strategy: each scheme JSON is split into short, self-contained
    passages — one per eligibility criterion, benefit, FAQ answer, application
    step, exception, and definition — tagged with scheme_id + section, so a
    retrieved chunk is always directly answerable rather than a fragment of a
    longer paragraph.
    """

    def __init__(self, config: Optional[NomadRightConfig] = None):
        self.config = config or NomadRightConfig()
        self.logger = logging.getLogger(self.__class__.__name__)
        self._client = None
        self._collection = None
        self._embedder = None

    # ── Lazy engine bring-up ────────────────────────────────────────────────

    def _ensure_ready(self) -> None:
        if self._collection is not None and self._embedder is not None:
            return
        # NomadRight's entire premise is 100% offline operation. The model
        # weights are already cached locally from --build-cache, but
        # sentence-transformers/huggingface_hub still phone home on every
        # load by default to check for updates (etag/redirect HEAD+GET
        # calls) - harmless-looking on a dev machine with internet, but on
        # the actual field device this adds ~10-15s of startup latency and,
        # with no connectivity, would either hang or fail outright. These
        # must be set before SentenceTransformer touches the hub client.
        import os
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            import chromadb
        except ImportError as exc:
            raise RAGRetrieverNotAvailableError(
                "chromadb is not installed. Install with: "
                "pip install chromadb sentence-transformers --break-system-packages"
            ) from exc
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RAGRetrieverNotAvailableError(
                "sentence-transformers is not installed. Install with: "
                "pip install chromadb sentence-transformers --break-system-packages"
            ) from exc

        persist_dir = Path(self.config.chroma_persist_dir)
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=self.config.chroma_collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        # Explicit CPU placement: left to auto-select, sentence-transformers
        # puts this on cuda:0 - but Qwen (qwen_client.py, LLM_NUM_GPU=99) is
        # forced fully onto the GPU precisely because Jetson's unified
        # memory has no separate VRAM pool, and the two now contend for the
        # same physical RAM on every RAG-routed query (Step 6.5a in
        # workflow.py runs the embedder, then Qwen, back to back). Confirmed
        # on-device: with Qwen resident, embedder cuda:0 init raised
        # "NVML_SUCCESS == r INTERNAL ASSERT FAILED" (CUDA allocator OOM)
        # under real memory pressure. multilingual-e5-small is a ~118M-param
        # model - CPU embedding of one short query is a few hundred ms, a
        # cost worth paying to keep the GPU free for Qwen and avoid this
        # crash entirely.
        self._embedder = SentenceTransformer(self.config.embedding_model_name, device="cpu")
        self.logger.info(
            f"RAG engine ready: collection='{self.config.chroma_collection_name}' "
            f"({self._collection.count()} chunks), model='{self.config.embedding_model_name}'"
        )

    def is_available(self) -> bool:
        """Returns True if the RAG engine is installed and the index has chunks."""
        try:
            self._ensure_ready()
            return self._collection.count() > 0
        except Exception:
            return False

    # ── Chunking ─────────────────────────────────────────────────────────────

    @staticmethod
    def _chunk_scheme(scheme_json: Dict[str, Any]) -> List[Dict[str, str]]:
        """Splits one scheme JSON into short (id, scheme_id, section, text) passages."""
        scheme_id = scheme_json.get("scheme_id", "UNKNOWN")
        scheme_name = scheme_json.get("scheme_name", scheme_id)
        chunks: List[Dict[str, str]] = []

        def add(section: str, text: str, idx: int) -> None:
            if text and text.strip():
                chunks.append({
                    "id": f"{scheme_id}::{section}::{idx}",
                    "scheme_id": scheme_id,
                    "section": section,
                    "text": f"{scheme_name}. {text.strip()}",
                })

        if scheme_json.get("description"):
            add("description", scheme_json["description"], 0)
        for i, item in enumerate(scheme_json.get("eligibility", [])):
            add("eligibility", item.get("criterion", ""), i)
        for i, item in enumerate(scheme_json.get("benefits", [])):
            add("benefits", item.get("benefit", ""), i)
        for i, item in enumerate(scheme_json.get("financial_benefits", [])):
            details = item.get("details") or item.get("amount") or ""
            text = f"{item.get('benefit_type', '')}: {details}. {item.get('description', '')}"
            add("financial_benefits", text, i)
        for i, item in enumerate(scheme_json.get("required_documents", [])):
            add("documents", f"{item.get('document', '')}: {item.get('description', '')}", i)
        for mode in ("online", "offline"):
            for i, step in enumerate(scheme_json.get("application_process", {}).get(mode, [])):
                add(f"application_{mode}", f"Step {step.get('step')}: {step.get('description', '')}", i)
        for i, item in enumerate(scheme_json.get("exceptions", [])):
            add("exceptions", item.get("exception", ""), i)
        for i, item in enumerate(scheme_json.get("limitations", [])):
            add("limitations", item.get("limitation", ""), i)
        for i, item in enumerate(scheme_json.get("faq", [])):
            q, a = item.get("question", ""), item.get("answer", "")
            add("faq", f"Q: {q} A: {a}", i)
        for i, item in enumerate(scheme_json.get("important_definitions", [])):
            add("definitions", f"{item.get('term', '')}: {item.get('definition', '')}", i)
        for i, item in enumerate(scheme_json.get("worker_rights_under_osh_code", [])):
            add("rights", f"{item.get('right', '')} {item.get('action_if_violated', '')}", i)

        port = scheme_json.get("portability", {})
        for i, (key, val) in enumerate(port.items()):
            if isinstance(val, str):
                add("portability", val, i)

        return chunks

    # ── Index build (offline, run once via --build-cache) ──────────────────

    def build_index(self, scheme_dir: Optional[Path] = None) -> int:
        """
        Builds (or rebuilds) the ChromaDB index from the four scheme JSON files.

        Args:
            scheme_dir: Directory containing pds.json/pmjay.json/eshram_osh.json/
                        bocw.json. Defaults to config.rules_dir.

        Returns:
            Total number of chunks indexed.
        """
        self._ensure_ready()
        scheme_dir = scheme_dir or Path(self.config.rules_dir)

        # Wipe and rebuild for a clean, reproducible offline cache.
        try:
            self._client.delete_collection(self.config.chroma_collection_name)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=self.config.chroma_collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        all_chunks: List[Dict[str, str]] = []
        for filename in constants.SCHEME_JSON_FILES:
            path = scheme_dir / filename
            if not path.exists():
                self.logger.warning(f"Scheme JSON not found, skipping: {path}")
                continue
            with open(path, "r", encoding="utf-8") as f:
                scheme_json = json.load(f)
            chunks = self._chunk_scheme(scheme_json)
            all_chunks.extend(chunks)
            self.logger.info(f"Chunked {filename}: {len(chunks)} passages")

        if not all_chunks:
            self.logger.error("No scheme chunks produced — RAG index will be empty.")
            return 0

        texts = [constants.RAG_PASSAGE_PREFIX + c["text"] for c in all_chunks]
        embeddings = self._embedder.encode(texts, normalize_embeddings=True).tolist()
        self._collection.add(
            ids=[c["id"] for c in all_chunks],
            embeddings=embeddings,
            documents=[c["text"] for c in all_chunks],
            metadatas=[{"scheme_id": c["scheme_id"], "section": c["section"]} for c in all_chunks],
        )
        self.logger.info(
            f"RAG index built: {len(all_chunks)} chunks -> {self.config.chroma_persist_dir}"
        )
        return len(all_chunks)

    # ── Query-time retrieval ─────────────────────────────────────────────────

    def retrieve(
        self, query_text: str, top_k: Optional[int] = None, min_score: Optional[float] = None
    ) -> List[RetrievedChunk]:
        """
        Retrieves the top-k most relevant scheme passages for a query.

        Args:
            query_text: English query text (after BHASHINI ASR + NMT-to-English).
            top_k:      Overrides config.rag_top_k if provided.
            min_score:  Overrides constants.RAG_MIN_SCORE if provided. The
                        qwen fallback (qwen_client.py, via workflow.py) calls
                        this with constants.LLM_CONTEXT_MIN_SCORE - a looser
                        floor - to gather grounding material for the LLM to
                        read, as distinct from this default's stricter floor
                        for accepting a chunk as a direct template answer.

        Returns:
            List of RetrievedChunk, best match first. Empty list if the RAG
            engine isn't installed or the index hasn't been built yet — the
            caller (ResponseGenerator) falls back to a generic "please
            contact the helpline / nearest CSC" answer rather than crashing.
        """
        if not query_text or not query_text.strip():
            return []
        try:
            self._ensure_ready()
        except RAGRetrieverNotAvailableError as exc:
            self.logger.warning(f"RAG retrieval unavailable: {exc}")
            return []

        k = top_k or self.config.rag_top_k
        score_floor = constants.RAG_MIN_SCORE if min_score is None else min_score
        try:
            query_embedding = self._embedder.encode(
                [constants.RAG_QUERY_PREFIX + query_text], normalize_embeddings=True
            ).tolist()
            results = self._collection.query(query_embeddings=query_embedding, n_results=k)
        except Exception as exc:
            self.logger.error(f"RAG query failed: {exc}")
            return []

        chunks: List[RetrievedChunk] = []
        docs = (results.get("documents") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        dists = (results.get("distances") or [[]])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            # Cosine distance -> similarity score (1.0 = identical)
            score = max(0.0, 1.0 - dist)
            scheme_id = meta.get("scheme_id", "")
            scheme_code = next(
                (code for code, sid in constants.SCHEME_CODE_TO_DB_ID.items() if sid == scheme_id),
                "",
            )
            if score < score_floor:
                self.logger.info(
                    f"RAG chunk below score floor ({score:.3f} < "
                    f"{score_floor}) - dropping to avoid a "
                    f"confident-but-irrelevant answer: '{doc[:60]}'"
                )
                continue
            chunks.append(RetrievedChunk(
                text=doc, scheme_id=scheme_id, scheme_code=scheme_code,
                section=meta.get("section", ""), score=score,
            ))
        self.logger.info(f"RAG retrieved {len(chunks)} chunks for query='{query_text[:60]}'")
        return chunks


def _cli_build_cache() -> None:
    """CLI entrypoint: python -m pocketinfer.applications.nomad_right.rag_pipeline --build-cache"""
    logging.basicConfig(level=logging.INFO)
    retriever = RAGRetriever()
    count = retriever.build_index()
    print(
        f"RAG index built: {count} chunks indexed into "
        f"'{retriever.config.chroma_collection_name}' at {retriever.config.chroma_persist_dir}"
    )


if __name__ == "__main__":
    import sys
    if "--build-cache" in sys.argv:
        _cli_build_cache()
    else:
        print("Usage: python -m pocketinfer.applications.nomad_right.rag_pipeline --build-cache")
