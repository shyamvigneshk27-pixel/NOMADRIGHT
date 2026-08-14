"""
NomadRight Application Constants
"""

import os

APP_NAME = "NomadRight"
APP_VERSION = "2.0.0"
APP_DESCRIPTION = "Offline, voice-first, multilingual rights navigator for interstate migrant workers."
APP_AUTHOR = "STARK-X"

# ── BHASHINI Model Service ───────────────────────────────────────────────────
BHASHINI_HOST = "localhost"
BHASHINI_PORT = 11400

# ── Storage & Path Constants ─────────────────────────────────────────────────
# Anchored to this file's own on-disk location (repo_root/python/pocketinfer/
# applications/nomad_right/constants.py -> repo_root), NOT the process's
# current working directory. Previously these were bare relative strings
# ("nomadright/nomadright_kb.db") resolved via os.getcwd() in database.py,
# which meant `pocketinfer-service --app NomadRight` silently read a
# different, empty NomadRight data folder depending on which directory the
# user happened to be standing in when they typed the command.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))

DEFAULT_LOG_DIR = "/tmp/nomad_right_logs"
DEFAULT_DB_PATH = os.path.join(_REPO_ROOT, "nomadright", "nomadright_kb.db")
DEFAULT_RULES_DIR = os.path.join(_REPO_ROOT, "nomadright")
DEFAULT_CHROMA_PERSIST_DIR = os.path.join(_REPO_ROOT, "nomadright", "chroma_db")

# ── UI & Display Limits (320x240 LCD Screen) ─────────────────────────────────
DISPLAY_HEADER_MAX_LEN = 30
DISPLAY_BODY_MAX_LEN = 60

# ── Audio & Hardware Thresholds ──────────────────────────────────────────────
MAX_AUDIO_RECORD_SECONDS = 15
DEFAULT_SAMPLE_RATE = 16000

# TTS answers must stay short for a comfortable listening experience.
MAX_VOICE_WORDS = 60

# ── Voice styling (male-leaning, energetic delivery) ─────────────────────────
# The only installed Flite voices for Hindi (cmu_indic_hin_ab) and Tamil
# (cmu_indic_tam_sdr) are both tagged "female" in their model metadata, and
# no alternate male Indic voice file is installed on this device - there is
# no different-voice-actor option available offline. As a software-only
# approximation, TTS output is pitch-shifted down (more masculine-leaning)
# and sped up slightly (more energetic/"active" delivery) via ffmpeg before
# playback. Purely a DSP post-process on the WAV bytes - never touches the
# BHASHINI service itself, and always falls back to the unmodified audio if
# ffmpeg is unavailable or fails, so this can never break playback.
TTS_VOICE_STYLE_ENABLED = True
TTS_PITCH_FACTOR = 0.85   # <1.0 = lower pitch (more male-leaning)
# asetrate-based pitch shifting stretches duration by 1/TTS_PITCH_FACTOR as a
# side effect (lowering pitch this way inherently slows playback down) - the
# tempo factor must first cancel that out, then add extra on top for a
# genuinely brisker/more "active" delivery rather than just a normal-speed one.
TTS_ENERGY_BOOST = 1.05   # extra >1.0 speed-up beyond canceling the pitch-shift slowdown

# ── Supported Welfare Scheme Identifiers (short codes) ───────────────────────
SCHEME_CODE_PDS = "PDS"
SCHEME_CODE_PMJAY = "PMJAY"
SCHEME_CODE_ESHRAM = "ESHRAM"
SCHEME_CODE_BOCW = "BOCW"
SCHEME_CODE_MGNREGS = "MGNREGS"

SUPPORTED_SCHEME_CODES = [
    SCHEME_CODE_PDS, SCHEME_CODE_PMJAY, SCHEME_CODE_ESHRAM, SCHEME_CODE_BOCW,
    SCHEME_CODE_MGNREGS,
]

# Scheme IDs as stored in nomadright_kb.db / scheme JSON files
DB_SCHEME_ID_PDS = "PDS_ONORC_001"
DB_SCHEME_ID_PMJAY = "PMJAY_001"
DB_SCHEME_ID_ESHRAM = "ESHRAM_OSH_001"
DB_SCHEME_ID_BOCW = "BOCW_001"
DB_SCHEME_ID_MGNREGS = "MGNREGS_001"

# Scheme code -> DB scheme_id mapping
SCHEME_CODE_TO_DB_ID = {
    SCHEME_CODE_PDS: DB_SCHEME_ID_PDS,
    SCHEME_CODE_PMJAY: DB_SCHEME_ID_PMJAY,
    SCHEME_CODE_ESHRAM: DB_SCHEME_ID_ESHRAM,
    SCHEME_CODE_BOCW: DB_SCHEME_ID_BOCW,
    SCHEME_CODE_MGNREGS: DB_SCHEME_ID_MGNREGS,
}

# Scheme code -> helpline. Used as the rules-engine fallback when a live KB
# record isn't available; a KB/JSON-sourced helpline always takes priority.
# MGNREGS has no single national helpline - state-specific numbers only
# (nrega.nic.in) - "UNKNOWN" here is real data, not a placeholder bug.
SCHEME_HELPLINES = {
    SCHEME_CODE_PDS: "14445",
    SCHEME_CODE_PMJAY: "14555",
    SCHEME_CODE_ESHRAM: "14434",
    SCHEME_CODE_BOCW: "1800-891-8888",
    SCHEME_CODE_MGNREGS: "UNKNOWN",
}

# Scheme JSON source files (repo-root nomadright/ directory). Used by the
# RAG pipeline's --build-cache indexer and by build_sqlite_db.py.
SCHEME_JSON_FILES = ["pds.json", "pmjay.json", "eshram_osh.json", "bocw.json", "mgnregs.json"]

# ── Language Configuration ───────────────────────────────────────────────────
# Source languages (ASR input - worker's own language).
SOURCE_LANGUAGES = {
    "hi": "Hindi",
    "ta": "Tamil",
    "or": "Odia",
    "bho": "Bhojpuri",
    "mai": "Maithili",
    "sat": "Santali",
    "hne": "Chhattisgarhi",
}
DEFAULT_SOURCE_LANGUAGE = "hi"

# Voice bridge target languages (destination-state official's language).
BRIDGE_LANGUAGES = {
    "ta": "Tamil",
    "gu": "Gujarati",
    "mr": "Marathi",
    "kn": "Kannada",
}
DEFAULT_BRIDGE_LANGUAGE = "ta"

# The Decision Layer (intent/entity/rules/RAG) always operates in English;
# BHASHINI NMT brackets it on the way in and out.
PIPELINE_LANGUAGE = "EN"

# ── RAG Pipeline (ChromaDB + multilingual-e5-small) ──────────────────────────
CHROMA_COLLECTION_NAME = "nomadright_schemes"
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"
RAG_TOP_K = 3
# multilingual-e5-small expects a "query: " / "passage: " instruction prefix
# on every embedded string - see https://huggingface.co/intfloat/multilingual-e5-small
RAG_QUERY_PREFIX = "query: "
RAG_PASSAGE_PREFIX = "passage: "
# ChromaDB always returns its k nearest neighbours even when nothing in the
# index is actually relevant (there is no "no match" result in embedding
# search) - without a floor, garbled ASR / off-topic queries get answered
# with a confident but unrelated scheme passage instead of the fallback
# message. Empirically measured (not guessed) against this app's own index:
# multilingual-e5-small embeds everything into a tight "government scheme
# talk" neighbourhood, so scores don't spread out as much as you'd hope -
# genuine off-pattern-but-legitimate queries scored 0.83-0.88, while
# garbled ASR / totally unrelated text scored 0.79-0.84. The threshold sits
# in that narrow overlap, biased toward rejecting borderline cases (a
# missed legitimate query gets an honest "I don't know" fallback; the
# alternative is a confidently wrong scheme answer, which is worse).
RAG_MIN_SCORE = 0.83

# ── LLM Fallback / Vision (qwen2.5vl:3b via Ollama) ─────────────────────────
# Deliberately NOT in the primary answer path for routed (rules/RAG) queries
# - only used when those find nothing (text fallback) or when a worker
# explicitly photographs a form (vision path). See qwen_client.py.
#
# num_gpu is forced high (not left to Ollama's auto-fit) because on this
# Jetson's *unified* memory (GPU and CPU share one physical RAM pool - no
# separate VRAM), Ollama's auto-fit heuristic sees little "free GPU memory"
# once BHASHINI's ASR/NMT/TTS service is already resident and defensively
# offloads 0 layers to GPU, running everything on CPU. Empirically measured
# on this device: forcing full GPU offload cut warm prompt-eval from 7.16s
# to 1.07s and generation from 4.61s to 3.25s (~4.3s total, inside the 5s
# budget) - see the "wire qwen2.5vl" plan for the full measurement.
LLM_FALLBACK_MODEL = "qwen3-vl:2b"
LLM_FALLBACK_ENABLED = True
# How long the model stays resident after answering before Ollama evicts it,
# freeing RAM back to BHASHINI - user-chosen: covers one worker's back-and-
# forth at the kiosk without holding ~4.9GB hostage between different
# workers' sessions.
LLM_KEEP_ALIVE = "15m"
LLM_NUM_GPU = 99
LLM_NUM_THREAD = 6
LLM_NUM_PREDICT_TEXT = 60
LLM_NUM_PREDICT_VISION = 80
LLM_TEMPERATURE = 0.1
# Generous enough to allow a legitimate cold load rather than aborting a
# real answer right before it would have landed - callers must show a "may
# take a moment" status during the wait instead of leaving the screen
# looking hung. See qwen_client.py / app.py. Measured cold loads on this
# device ranged 108-242s depending on memory/swap pressure from BHASHINI +
# whatever else is resident (RAG embedder, chromadb, UI process); a real
# on-device run hit >150s and got cut off right as it would have answered,
# wasting the whole wait for nothing - 220s gives more margin for that
# worst case while still eventually giving up rather than hanging forever.
LLM_REQUEST_TIMEOUT_S = 220.0
# Looser than RAG_MIN_SCORE (0.83) on purpose: this floor only decides
# whether a chunk is worth handing to the LLM as *grounding material*, not
# whether to accept it as a direct template answer - the LLM's own strict
# "answer only from context" instruction (see LLM_SENTINEL_NOT_FOUND) is the
# real backstop against a loosely-related chunk causing a wrong answer.
LLM_CONTEXT_MIN_SCORE = 0.55
# Sentinel the LLM is instructed to return verbatim when the provided
# context/image doesn't actually answer the question - callers treat this
# exactly like "no answer" and fall through to the existing constant
# fallback message, preserving the no-confident-hallucination guarantee.
LLM_SENTINEL_NOT_FOUND = "NOT_IN_CONTEXT"
# How long a Camera-button photo stays "pending" waiting for the worker's
# follow-up question before app.py silently drops it and treats the next
# utterance as a normal voice query - stops a stale photo from an earlier
# worker (who walked away without asking) getting attached to someone
# else's unrelated question later. See app.py's ui_cb/run().
LLM_VISION_PENDING_TTL_S = 120.0
