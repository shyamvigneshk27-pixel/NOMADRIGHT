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

# ── Voice styling (natural pitch, Alexa-like clarity) ────────────────────────
# There is only ONE Flite voice file installed per language NomadRight
# actually uses (e.g. cmu_indic_hin_ab.flitevox for Hindi, cmu_indic_tam_sdr
# for Tamil - see ~/bhashini_models/tts/infer.py's LANG_VOICE_MAP) and no
# alternate/neural voice available offline on this device, so a different
# *voice* isn't selectable - the only lever is this ffmpeg DSP post-process
# on the WAV bytes. An earlier version of this shifted pitch down a full
# octave (TTS_PITCH_FACTOR=0.50) to fake a male-leaning voice; on-device
# listening confirmed that made speech sound distorted/hard to follow, not
# clearer - reverted to natural pitch and natural pace (a real assistant
# voice like Alexa's is clear because it's natural-pitched and consistently
# leveled, not because it's pitch-shifted). The presence EQ / compressor /
# loudnorm stages below (bhashini_bridge.py's _apply_voice_style) are kept -
# those genuinely improve clarity and consistent volume. Purely a DSP
# post-process - never touches the BHASHINI service itself, and always
# falls back to the unmodified audio if ffmpeg is unavailable or fails, so
# this can never break playback.
TTS_VOICE_STYLE_ENABLED = True
TTS_PITCH_FACTOR = 1.0    # 1.0 = natural pitch, no artificial shift
TTS_ENERGY_BOOST = 1.0    # 1.0 = natural pace, no artificial speed-up

# ── Supported Welfare Scheme Identifiers (short codes) ───────────────────────
SCHEME_CODE_PDS = "PDS"
SCHEME_CODE_PMJAY = "PMJAY"
SCHEME_CODE_ESHRAM = "ESHRAM"
SCHEME_CODE_BOCW = "BOCW"
SCHEME_CODE_MGNREGS = "MGNREGS"

SCHEME_CODE_APY = "APY"
SCHEME_CODE_NSAP = "NSAP"
SCHEME_CODE_PM_KISAN = "PM_KISAN"
SCHEME_CODE_PM_SURYA_GHAR = "PM_SURYA_GHAR"
SCHEME_CODE_PM_SVANIDHI = "PM_SVANIDHI"
SCHEME_CODE_PM_SYM = "PM_SYM"
SCHEME_CODE_PM_VISHWAKARMA = "PM_VISHWAKARMA"
SCHEME_CODE_PMAY_G = "PMAY_G"
SCHEME_CODE_PMFBY = "PMFBY"
SCHEME_CODE_PMJDY = "PMJDY"
SCHEME_CODE_PMJJBY = "PMJJBY"
SCHEME_CODE_PMMY = "PMMY"
SCHEME_CODE_PMSBY = "PMSBY"
SCHEME_CODE_PMUY = "PMUY"
SCHEME_CODE_SUKANYA_SAMRIDDHI = "SUKANYA_SAMRIDDHI"

SUPPORTED_SCHEME_CODES = [
    SCHEME_CODE_PDS, SCHEME_CODE_PMJAY, SCHEME_CODE_ESHRAM, SCHEME_CODE_BOCW,
    SCHEME_CODE_MGNREGS, SCHEME_CODE_APY, SCHEME_CODE_NSAP, SCHEME_CODE_PM_KISAN,
    SCHEME_CODE_PM_SURYA_GHAR, SCHEME_CODE_PM_SVANIDHI, SCHEME_CODE_PM_SYM,
    SCHEME_CODE_PM_VISHWAKARMA, SCHEME_CODE_PMAY_G, SCHEME_CODE_PMFBY,
    SCHEME_CODE_PMJDY, SCHEME_CODE_PMJJBY, SCHEME_CODE_PMMY, SCHEME_CODE_PMSBY,
    SCHEME_CODE_PMUY, SCHEME_CODE_SUKANYA_SAMRIDDHI
]

# Scheme IDs as stored in nomadright_kb.db / scheme JSON files
DB_SCHEME_ID_PDS = "PDS_ONORC_001"
DB_SCHEME_ID_PMJAY = "PMJAY_001"
DB_SCHEME_ID_ESHRAM = "ESHRAM_OSH_001"
DB_SCHEME_ID_BOCW = "BOCW_001"
DB_SCHEME_ID_MGNREGS = "MGNREGS_001"
DB_SCHEME_ID_APY = "apy"
DB_SCHEME_ID_NSAP = "nsap"
DB_SCHEME_ID_PM_KISAN = "pm_kisan"
DB_SCHEME_ID_PM_SURYA_GHAR = "pm_surya_ghar"
DB_SCHEME_ID_PM_SVANIDHI = "pm_svanidhi"
DB_SCHEME_ID_PM_SYM = "pm_sym"
DB_SCHEME_ID_PM_VISHWAKARMA = "pm_vishwakarma"
DB_SCHEME_ID_PMAY_G = "pmay_g"
DB_SCHEME_ID_PMFBY = "pmfby"
DB_SCHEME_ID_PMJDY = "pmjdy"
DB_SCHEME_ID_PMJJBY = "pmjjby"
DB_SCHEME_ID_PMMY = "pmmy"
DB_SCHEME_ID_PMSBY = "pmsby"
DB_SCHEME_ID_PMUY = "pmuy"
DB_SCHEME_ID_SUKANYA_SAMRIDDHI = "sukanya_samriddhi"

# Scheme code -> DB scheme_id mapping
SCHEME_CODE_TO_DB_ID = {
    SCHEME_CODE_PDS: DB_SCHEME_ID_PDS,
    SCHEME_CODE_PMJAY: DB_SCHEME_ID_PMJAY,
    SCHEME_CODE_ESHRAM: DB_SCHEME_ID_ESHRAM,
    SCHEME_CODE_BOCW: DB_SCHEME_ID_BOCW,
    SCHEME_CODE_MGNREGS: DB_SCHEME_ID_MGNREGS,
    SCHEME_CODE_APY: DB_SCHEME_ID_APY,
    SCHEME_CODE_NSAP: DB_SCHEME_ID_NSAP,
    SCHEME_CODE_PM_KISAN: DB_SCHEME_ID_PM_KISAN,
    SCHEME_CODE_PM_SURYA_GHAR: DB_SCHEME_ID_PM_SURYA_GHAR,
    SCHEME_CODE_PM_SVANIDHI: DB_SCHEME_ID_PM_SVANIDHI,
    SCHEME_CODE_PM_SYM: DB_SCHEME_ID_PM_SYM,
    SCHEME_CODE_PM_VISHWAKARMA: DB_SCHEME_ID_PM_VISHWAKARMA,
    SCHEME_CODE_PMAY_G: DB_SCHEME_ID_PMAY_G,
    SCHEME_CODE_PMFBY: DB_SCHEME_ID_PMFBY,
    SCHEME_CODE_PMJDY: DB_SCHEME_ID_PMJDY,
    SCHEME_CODE_PMJJBY: DB_SCHEME_ID_PMJJBY,
    SCHEME_CODE_PMMY: DB_SCHEME_ID_PMMY,
    SCHEME_CODE_PMSBY: DB_SCHEME_ID_PMSBY,
    SCHEME_CODE_PMUY: DB_SCHEME_ID_PMUY,
    SCHEME_CODE_SUKANYA_SAMRIDDHI: DB_SCHEME_ID_SUKANYA_SAMRIDDHI,
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
    SCHEME_CODE_APY: "UNKNOWN",
    SCHEME_CODE_NSAP: "UNKNOWN",
    SCHEME_CODE_PM_KISAN: "UNKNOWN",
    SCHEME_CODE_PM_SURYA_GHAR: "UNKNOWN",
    SCHEME_CODE_PM_SVANIDHI: "UNKNOWN",
    SCHEME_CODE_PM_SYM: "UNKNOWN",
    SCHEME_CODE_PM_VISHWAKARMA: "UNKNOWN",
    SCHEME_CODE_PMAY_G: "UNKNOWN",
    SCHEME_CODE_PMFBY: "UNKNOWN",
    SCHEME_CODE_PMJDY: "UNKNOWN",
    SCHEME_CODE_PMJJBY: "UNKNOWN",
    SCHEME_CODE_PMMY: "UNKNOWN",
    SCHEME_CODE_PMSBY: "UNKNOWN",
    SCHEME_CODE_PMUY: "UNKNOWN",
    SCHEME_CODE_SUKANYA_SAMRIDDHI: "UNKNOWN",
}

# Scheme JSON source files (repo-root nomadright/ directory). Used by the
# RAG pipeline's --build-cache indexer and by build_sqlite_db.py.
SCHEME_JSON_FILES = [
    "pds.json", "pmjay.json", "eshram_osh.json", "bocw.json", "mgnregs.json",
    "apy.json", "nsap.json", "pm_kisan.json", "pm_surya_ghar.json",
    "pm_svanidhi.json", "pm_sym.json", "pm_vishwakarma.json", "pmay_g.json",
    "pmfby.json", "pmjdy.json", "pmjjby.json", "pmmy.json", "pmsby.json",
    "pmuy.json", "sukanya_samriddhi.json"
]

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

# Of SOURCE_LANGUAGES above, only these have an actual ASR checkpoint on the
# BHASHINI side (~/bhashini_models/asr/checkpoints/{hi,ta}-conformer.onnx -
# see infer.py's `self.sessions` dict). The rest are UI/roadmap entries the
# touchscreen still renders buttons for; selecting one used to be accepted
# silently and made every subsequent turn's /asr call 500 forever with no
# on-screen explanation. app.py's ui_cb() gates on this set before honouring
# a selection - add a code here only once its .onnx checkpoint actually
# exists on disk.
ASR_SUPPORTED_LANGUAGES = {"hi", "ta"}

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
LLM_FALLBACK_MODEL = "hf.co/Qwen/Qwen3-VL-2B-Instruct-GGUF:Q4_K_M"
LLM_FALLBACK_ENABLED = True
# How long the model stays resident after answering before Ollama evicts it,
# freeing RAM back to BHASHINI - user-chosen: covers one worker's back-and-
# forth at the kiosk without holding ~4.9GB hostage between different
# workers' sessions.
LLM_KEEP_ALIVE = "15m"
LLM_NUM_GPU = 99
LLM_NUM_THREAD = 6
# The GGUF model natively supports up to 262144 tokens, but Ollama was
# silently running every call at its own runtime default of 4096 (never
# explicitly requested here before) - measured on-device: a single
# photographed form alone consumes ~1096 of that (api/generate's
# prompt_eval_count), before the system prompt, question, and answer
# tokens are even added, and a higher-resolution real camera photo (this
# device's webcam defaults to 1280x720, vs. the smaller image used for
# that measurement) would consume more still. 8192 (2x the previous
# ceiling) gives real headroom without the KV-cache memory cost of a much
# larger window on this RAM-constrained Jetson. Changing this value forces
# a one-time model reload the next time it's requested (measured ~43s,
# similar in nature to a normal cold start) - NOT a recurring per-query
# cost: confirmed on-device that repeated calls at a fixed num_ctx stay
# resident and fast (~1-3s) exactly like before this was added.
LLM_NUM_CTX = 8192
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
