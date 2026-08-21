"""
Curated scenario cache - an exact-answer fast path in front of the Decision
Layer.

Why this exists
---------------
For a fixed set of known questions we want the *exact* curated wording every
time, delivered fast. The normal path can't give either guarantee: intent
recognition is regex-based and drops perfectly ordinary questions to
UNKNOWN_QUERY, and an unmatched query ends up at Qwen, which rephrases its
answer on every run and costs ~2.6s warm - or ~53s if Ollama has evicted the
model (measured on-device: load_duration 53195ms).

What this does NOT do
---------------------
It does not change the pipeline. On any miss - which includes every question
not in CACHE_ENTRIES - lookup() returns None and app.py proceeds through the
exact same intent -> entity -> rules/RAG -> response path as before. Nothing
downstream of here knows this module exists.

Only the *routing* is short-circuited on a hit. ASR, NMT and TTS all still
run live, so a cached turn is still genuinely multilingual and still speaks
through the real BHASHINI stack - the cache supplies the answer *content*,
not a pre-recorded clip.

How matching works
------------------
Queries are matched by embedding similarity against curated question
phrasings, in the worker's own language, using the SentenceTransformer the
RAG retriever has already loaded (no second model, no extra RAM, no new
dependency).

Matching native-to-native matters. Measured with this exact embedder:

    same question, Hindi                       1.000
    same question, ASR-corrupted (मुे/मुझे)     0.961   <- ASR noise is cheap
    same question, English translation         0.922
    DIFFERENT Hindi question (portability)     0.896
    unrelated ("what is the weather today")    0.761

So ASR garbling costs almost nothing, but crossing languages costs more than
the gap to a genuinely different question - which is why each entry carries
phrasings in every language it should match, rather than relying on the
embedder to bridge from English. It is also why this compares questions to
*questions*: the RAG index compares a question to document chunks, where
everything lands in the same "government scheme talk" neighbourhood (see
RAG_MIN_SCORE's note - legitimate 0.83-0.88 vs garbage 0.79-0.84, an overlap
band with no safe threshold).

MATCH_THRESHOLD sits at 0.93: above the 0.896 scored by a different question
in the same language, below the 0.961 an ASR-mangled real utterance scores.
A miss is not a failure here - it just falls through to the full pipeline.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pocketinfer.applications.nomad_right import constants
from pocketinfer.applications.nomad_right.response import (
    SeverityLevel,
    StructuredResponsePackage,
)

logger = logging.getLogger(__name__)

# Accept a cached answer at or above this cosine similarity. See the module
# docstring for the measurements this sits between.
MATCH_THRESHOLD = 0.93


@dataclass
class ScenarioEntry:
    """One curated question -> exact answer mapping.

    `questions` maps a language code to the phrasings a worker might
    actually say in that language. Include clumsy and partial forms: they
    cost nothing and they are what ASR really produces.

    `answer_en` is the single source of truth for the wording. It is
    translated to the worker's language at runtime by the same BHASHINI NMT
    the rest of the pipeline uses, so a cached answer is never a
    pre-recorded clip and the demo still exercises the multilingual path.

    `requires_context_scheme` gates follow-up questions that only make sense
    after a particular scheme has been discussed ("what documents do I
    need?" means nothing on its own). When set, the entry only matches if
    that scheme was the subject of the previous turn.
    """
    entry_id: str
    scheme_code: str
    display_top: str
    display_bottom: str
    answer_en: str
    questions: Dict[str, List[str]] = field(default_factory=dict)
    requires_context_scheme: Optional[str] = None
    severity: SeverityLevel = SeverityLevel.INFO


# ── The curated scenario ────────────────────────────────────────────────────
# Answer content is taken from this repo's own knowledge base
# (nomadright/pds.json - description, application_process, required_documents,
# eligibility, official_contacts), not invented here, so the spoken answer
# agrees with what the RAG path would have grounded on.
#
# Kept near ~40 words each: measured TTS runs about 0.23s of audio per word,
# so ~40 words is ~9s of speech - long enough to be a real answer, short
# enough to stay listenable. constants.MAX_VOICE_WORDS (60) is the ceiling.
CACHE_ENTRIES: List[ScenarioEntry] = [
    ScenarioEntry(
        entry_id="PDS_ONORC_PORTABILITY",
        scheme_code=constants.SCHEME_CODE_PDS,
        display_top="PDS / ONORC",
        display_bottom="Ration is portable across all 36 States and UTs",
        answer_en=(
            "Yes. Under One Nation One Ration Card, part of the National Food "
            "Security Act, your ration card works in Tamil Nadu just as it does "
            "in Uttar Pradesh. Collect your subsidised grain from any ePoS "
            "enabled Fair Price Shop, in any of India's thirty six states and "
            "union territories."
        ),
        questions={
            "en": [
                "I am a migrant worker from Uttar Pradesh can I get my ration goods in Tamil Nadu",
                "I am a migrant worker from Maharashtra can I get ration goods in Tamil Nadu",
                "can I get my ration in another state",
                "my ration card is from Uttar Pradesh can I use it in Tamil Nadu",
                "I moved to Tamil Nadu for work can I still get ration",
                "can I use my ration card outside my home state",
                "will my ration card work in a different state",
                "I am a migrant worker can I get ration here",
            ],
            "hi": [
                "मैं उत्तर प्रदेश से प्रवासी मजदूर हूं क्या मुझे तमिलनाडु में राशन मिलेगा",
                "क्या मैं दूसरे राज्य में अपना राशन ले सकता हूं",
                "मेरा राशन कार्ड उत्तर प्रदेश का है क्या तमिलनाडु में चलेगा",
                "मैं काम के लिए तमिलनाडु आया हूं क्या मुझे राशन मिलेगा",
                "क्या मेरा राशन कार्ड दूसरे राज्य में काम करेगा",
                "मैं प्रवासी मजदूर हूं क्या यहां राशन मिल सकता है",
            ],
            "ta": [
                "நான் உத்தரப் பிரதேசத்தில் இருந்து வந்த புலம்பெயர் தொழிலாளி தமிழ்நாட்டில் ரேஷன் கிடைக்குமா",
                "என் ரேஷன் கார்டு வேறு மாநிலத்தில் வேலை செய்யுமா",
                "நான் வேலைக்காக தமிழ்நாடு வந்தேன் எனக்கு ரேஷன் கிடைக்குமா",
            ],
        },
    ),
    ScenarioEntry(
        entry_id="PDS_HOW_TO_APPLY",
        scheme_code=constants.SCHEME_CODE_PDS,
        display_top="PDS / ONORC - How to apply",
        display_bottom="No separate application. Link Aadhaar, then use any ePoS shop",
        answer_en=(
            "There is no separate application. If you already hold a National "
            "Food Security Act ration card, just make sure your Aadhaar number "
            "is linked to it at your Food and Civil Supplies office. Then visit "
            "any ePoS enabled Fair Price Shop, give your ration card number, and "
            "verify by fingerprint to collect your grain."
        ),
        questions={
            "en": [
                "how to apply for PDS scheme",
                "how do I apply for the PDS scheme",
                "how can I apply for one nation one ration card",
                "what is the process to apply",
                "how do I register for this scheme",
                "tell me the steps to apply",
                "what are the steps to apply for ration card portability",
                "how to get this scheme",
            ],
            "hi": [
                "पीडीएस योजना के लिए आवेदन कैसे करें",
                "इस योजना के लिए आवेदन कैसे करूं",
                "वन नेशन वन राशन कार्ड के लिए कैसे आवेदन करें",
                "आवेदन करने की प्रक्रिया क्या है",
                "मुझे इसके लिए क्या करना होगा",
                "आवेदन के चरण बताइए",
            ],
            "ta": [
                "பிடிஎஸ் திட்டத்திற்கு எப்படி விண்ணப்பிப்பது",
                "இந்த திட்டத்திற்கு விண்ணப்பிக்கும் நடைமுறை என்ன",
                "விண்ணப்பிக்க என்ன செய்ய வேண்டும்",
            ],
        },
    ),
    ScenarioEntry(
        entry_id="PDS_DOCUMENTS_ELIGIBILITY",
        scheme_code=constants.SCHEME_CODE_PDS,
        display_top="PDS / ONORC - Documents",
        display_bottom="Ration card + Aadhaar, seeded. AAY or Priority Household",
        # Gated on the previous turn having been about PDS: on its own,
        # "what documents do I need?" is not a PDS question, and answering
        # it as one would be a confident wrong answer.
        requires_context_scheme=constants.SCHEME_CODE_PDS,
        answer_en=(
            "You need two documents, both compulsory: your existing ration card "
            "issued under the National Food Security Act, and your Aadhaar card, "
            "which must be linked to that ration card. To be eligible you must "
            "already be a Food Security Act beneficiary under either the Antyodaya "
            "Anna Yojana or the Priority Household category. Helpline fourteen "
            "four four five."
        ),
        questions={
            "en": [
                "what are the documents required",
                "what documents do I need",
                "which documents are required for this",
                "what papers do I need to bring",
                "what documents and eligibility are needed",
                "who is eligible for this scheme",
                "am I eligible for this",
                "what is the eligibility",
            ],
            "hi": [
                "कौन से दस्तावेज चाहिए",
                "इसके लिए क्या दस्तावेज लगेंगे",
                "मुझे कौन कौन से कागजात लाने होंगे",
                "दस्तावेज और पात्रता क्या है",
                "इस योजना के लिए कौन पात्र है",
                "क्या मैं इसके लिए पात्र हूं",
            ],
            "ta": [
                "என்ன ஆவணங்கள் தேவை",
                "இதற்கு தேவையான ஆவணங்கள் என்ன",
                "யார் இந்த திட்டத்திற்கு தகுதியானவர்",
            ],
        },
    ),
]


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace.

    ASR output has inconsistent punctuation and spacing between runs; this
    keeps those differences from showing up as embedding differences.
    """
    text = re.sub(r"[^\w\sऀ-ॿ஀-௿]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class ScenarioHit:
    entry: ScenarioEntry
    score: float
    matched_language: str


class ScenarioCache:
    """Embedding lookup over CACHE_ENTRIES.

    Constructed with a zero-argument callable returning the shared
    SentenceTransformer (WorkflowController's RAG retriever owns it) so this
    never loads a model of its own, and so a retriever that failed to
    initialise simply disables the cache instead of breaking startup.
    """

    def __init__(self, embedder_provider, entries: Optional[List[ScenarioEntry]] = None):
        self._embedder_provider = embedder_provider
        self.entries = entries if entries is not None else CACHE_ENTRIES
        self._matrix = None          # (N, dim) normalised question vectors
        self._index: List[tuple] = []  # row -> (entry, language)
        self._ready = False
        self._failed = False
        self.logger = logging.getLogger(__name__)

    def _ensure_ready(self) -> bool:
        """Embed every curated phrasing once, on first use."""
        if self._ready:
            return True
        if self._failed:
            return False
        try:
            embedder = self._embedder_provider()
            if embedder is None:
                self._failed = True
                return False
            import numpy as np

            texts, index = [], []
            for entry in self.entries:
                for lang, phrasings in entry.questions.items():
                    for phrasing in phrasings:
                        texts.append(constants.RAG_QUERY_PREFIX + _normalise(phrasing))
                        index.append((entry, lang))
            if not texts:
                self._failed = True
                return False
            # Same "query: " prefix on both sides - this compares questions to
            # questions, not questions to passages.
            self._matrix = np.asarray(
                embedder.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            )
            self._index = index
            self._ready = True
            self.logger.info(
                "Scenario cache ready: %d phrasings across %d entries",
                len(texts), len(self.entries),
            )
            return True
        except Exception:
            # A cache that can't build is not an error worth failing startup
            # for - every query simply takes the normal path.
            self.logger.warning("Scenario cache unavailable, using full pipeline", exc_info=True)
            self._failed = True
            return False

    def warm(self) -> bool:
        """Build the embedding index up front.

        Without this the whole index is built lazily inside the first
        lookup, which measured 4.94s on-device against 0.19-0.30s for every
        lookup afterwards - a cost that would otherwise land entirely on the
        first worker of the session. Returns True if the cache is usable.
        """
        return self._ensure_ready()

    def match(
        self,
        native_query: str,
        context_scheme_code: Optional[str] = None,
    ) -> Optional[ScenarioHit]:
        """Best curated entry for this query, or None to use the full pipeline."""
        if not native_query or not native_query.strip():
            return None
        if not self._ensure_ready():
            return None
        try:
            import numpy as np

            embedder = self._embedder_provider()
            query_vec = np.asarray(
                embedder.encode(
                    [constants.RAG_QUERY_PREFIX + _normalise(native_query)],
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            )[0]
            scores = self._matrix @ query_vec

            best: Optional[ScenarioHit] = None
            for row, score in enumerate(scores):
                entry, lang = self._index[row]
                # A context-gated entry is only a candidate when the previous
                # turn was actually about its scheme.
                if entry.requires_context_scheme and \
                        context_scheme_code != entry.requires_context_scheme:
                    continue
                if score >= MATCH_THRESHOLD and (best is None or score > best.score):
                    best = ScenarioHit(entry=entry, score=float(score), matched_language=lang)
            return best
        except Exception:
            self.logger.warning("Scenario cache lookup failed, using full pipeline", exc_info=True)
            return None

    def lookup(
        self,
        native_query: str,
        context_scheme_code: Optional[str] = None,
    ) -> Optional[StructuredResponsePackage]:
        """Curated answer as the same StructuredResponsePackage the Decision
        Layer produces, so callers need no special handling for a cache hit.

        voice_text is English - the caller translates it to the worker's
        language through the normal NMT stage, exactly as it would a
        pipeline-generated answer.
        """
        hit = self.match(native_query, context_scheme_code)
        if hit is None:
            return None
        self.logger.info(
            "Scenario cache HIT %s (score=%.3f, matched %s phrasing)",
            hit.entry.entry_id, hit.score, hit.matched_language,
        )
        return StructuredResponsePackage(
            voice_text=hit.entry.answer_en,
            display_top_text=hit.entry.display_top,
            display_bottom_text=hit.entry.display_bottom,
            severity=hit.entry.severity,
            scheme_code=hit.entry.scheme_code,
        )
