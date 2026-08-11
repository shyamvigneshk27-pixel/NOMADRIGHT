# Suno Sutra — AI Model Analysis
**Author:** Senior AI Systems Engineer
**Date:** August 4, 2026
**Document Version:** 1.0.0
**Scope:** Complete analysis of every AI model used by the Suno Sutra platform

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Model Inventory](#2-model-inventory)
3. [Complete Inference Pipeline](#3-complete-inference-pipeline)
4. [Audio Flow Diagram](#4-audio-flow-diagram)
5. [Camera Flow Diagram](#5-camera-flow-diagram)
6. [Text Flow Diagram](#6-text-flow-diagram)
7. [Service Dependency Map](#7-service-dependency-map)
8. [NomadRight Reuse Summary](#8-nomadright-reuse-summary)
9. [Model Comparison Table](#9-model-comparison-table)

---

## 1. Executive Summary

Suno Sutra is an **offline, edge-native AI inference platform** running on an NVIDIA Jetson Orin Nano 8GB (JetPack 6.2). It orchestrates a **cascaded multimodal AI pipeline** that takes real-time audio (microphone) and visual (camera) inputs, routes them through a sequence of AI models, and delivers voice and display responses — all without internet connectivity at runtime.

The platform uses **7 distinct AI models** across **3 inference subsystems** (ASR, NMT/VLM, TTS), served by **3 runtime daemons**:
- `pocketinfer.service` — the main Python application host
- `ollama.service` — the GPU-accelerated LLM/VLM runtime (port 11434)
- `bhashini_models.service` — the Indic language model server (port 11400)

Models span **3 formats**: GGUF (via Ollama), ONNX (via Piper), and Kaldi/CTranslate2 (Vosk + Bhashini).

---

## 2. Model Inventory

---

### Model 1 — Vosk (English ASR)

| Attribute | Detail |
|:---|:---|
| **Model Name** | vosk-model-small-en-us-0.15 |
| **Purpose** | Offline English Automatic Speech Recognition (ASR). Converts user spoken English audio into a text query string. |
| **File Location** | ~/.cache/pocketinfer/vosk_model/vosk-model-small-en-us-0.15/ (downloaded at runtime; not in repo) |
| **Model Format** | **Kaldi** — compiled acoustic + language model directory (am/, graph/, ivector/ subdirs). |
| **Model Size** | ~40 MB (small variant zip archive). Source: https://alphacephei.com/vosk/models/ |
| **How It Is Loaded** | KaldiRecognizer(Model(self.model_path), SAMPLE_RATE) instantiated per inference call. No persistent preloading — model loaded fresh on each button-press event. |
| **Which Python File Loads It** | python/pocketinfer/models/vosk.py — Vosk.recognize() method |
| **Which Application Uses It** | hear_the_world_en.py (always); hear_the_world.py (only when input_language == 'en') |
| **Input Format** | speech_recognition.AudioData -> downsampled to 16kHz 16-bit signed integer mono PCM via audio_data.get_raw_data(convert_rate=16000, convert_width=2) |
| **Output Format** | dict with key "text" -> plain-text English transcription string e.g. {"text": "what is this"} |
| **Offline Capability** | YES — Fully Offline. Model files on local disk. No internet at runtime. |
| **GPU / CPU Usage** | CPU only — Kaldi/Vosk does not use CUDA. Runs on Jetson ARM CPU cores. |
| **Memory Usage** | ~80-120 MB RAM estimated during inference. Not instrumented in source code. |
| **Can It Be Replaced?** | Yes. Drop-in replacements (Whisper.cpp, faster-whisper, Silero) need to accept AudioData and return {"text": "..."}. |
| **Should NomadRight Reuse It?** | YES — Reuse As-Is. Per INTEGRATION_PLAN.md Section 1: Vosk is fully offline, zero-modification required. Pre-cache the zip during deployment. |

---

### Model 2 — Bhashini ASR (Indic ASR)

| Attribute | Detail |
|:---|:---|
| **Model Name** | Bhashini Indic ASR — archive ASR-Hindi-CPUquantized.zip |
| **Purpose** | Multilingual Automatic Speech Recognition for Indic languages (Hindi hi, Tamil ta). Converts spoken Indic audio into source-language text. |
| **File Location** | rootfs/roles/indic/files/ASR-Hindi-CPUquantized.zip (Git LFS pointer); deployed to ~/bhashini_models/ on device via Ansible. |
| **Model Format** | **CTranslate2** quantized format (CPU-quantized). Likely Wav2Vec2-based encoder ASR converted for ARM CPU via Intel CTranslate2 with OpenBLAS. |
| **Model Size** | Unknown (LFS pointer only). CPU-quantized Indic ASR typically 200-600 MB. |
| **How It Is Loaded** | NOT loaded directly by pocketinfer. The Asr class in models/asr.py is a REST client only. Model is loaded and kept resident by bhashini_models.service (separate Python virtualenv at ~/bhashini_models/). |
| **Which Python File Loads It** | python/pocketinfer/models/asr.py — Asr.infer() sends POST http://localhost:11400/asr. Actual loading inside bhashini_models.service. |
| **Which Application Uses It** | hear_the_world.py — only when settings['input_language'] != 'en' |
| **Input Format** | JSON: {"language": "hi", "audio_base64": "<base64_wav>"} via POST to localhost:11400/asr |
| **Output Format** | JSON: {"text": "<transcribed_indic_text>"} |
| **Offline Capability** | YES — Fully Offline. Weights local. HTTP is loopback only (localhost:11400). |
| **GPU / CPU Usage** | CPU only — archive name ASR-Hindi-CPUquantized explicitly indicates CPU-quantized weights. No CUDA. |
| **Memory Usage** | Held in RAM by bhashini_models.service. Estimated 400-800 MB RAM. Not instrumented in pocketinfer. |
| **Can It Be Replaced?** | Yes. Any HTTP service at localhost:11400/asr with same JSON schema can replace it. |
| **Should NomadRight Reuse It?** | OPTIONAL — Only if multilingual input required. Skip for English-native NomadRight to save ~400 MB RAM and latency. |

---

### Model 3 — Bhashini NMT (Neural Machine Translation)

| Attribute | Detail |
|:---|:---|
| **Model Name** | Bhashini NMT — archive nmt_trans.zip (CTranslate2-based) |
| **Purpose** | Bidirectional offline Neural Machine Translation between English and Indic languages. Used twice per inference: once translating user query to English (for VLM), once translating English VLM response back to target language (for TTS). |
| **File Location** | rootfs/roles/indic/files/nmt_trans.zip (Git LFS pointer); deployed to ~/bhashini_models/nmt/ on device. |
| **Model Format** | **CTranslate2** — Intel-optimized CPU inference format from a seq2seq transformer (Helsinki-NLP or IndicTrans architecture). Custom .deb (ctranslate2-0.1.1-Linux.deb) and .whl (ctranslate2-4.6.3-cp310-cp310-linux_aarch64.whl) built for Jetson aarch64. |
| **Model Size** | Typically 150-500 MB per language pair for CTranslate2 quantized NMT. |
| **How It Is Loaded** | Same as Bhashini ASR: loaded and kept resident by bhashini_models.service. Nmt class in models/nmt.py is REST client only. |
| **Which Python File Loads It** | python/pocketinfer/models/nmt.py — Nmt.infer() sends POST http://localhost:11400/nmt |
| **Which Application Uses It** | hear_the_world.py — for input translation (line 137) and output translation (line 154), ONLY when language != 'en'. |
| **Input Format** | JSON: {"text": "<source_text>", "src_lang": "HI", "tgt_lang": "EN"} via POST to localhost:11400/nmt |
| **Output Format** | JSON: {"translated_text": "<translated_string>"} |
| **Offline Capability** | YES — Fully Offline. All weights local. HTTP is loopback only. |
| **GPU / CPU Usage** | CPU only — CTranslate2 with OpenBLAS on ARM. Models deployed in CPU-quantized mode. |
| **Memory Usage** | Shared with bhashini_models.service. Full Bhashini service (ASR+NMT+TTS) likely 1-2 GB RAM total. |
| **Can It Be Replaced?** | Yes. Any HTTP endpoint at localhost:11400/nmt with same schema works. Alternatives: OPUS-MT, mBART-50. |
| **Should NomadRight Reuse It?** | DO NOT USE for English-native (saves latency + ~500 MB RAM). REUSE AS-IS if multilingual field operation required. |

---

### Model 4 — Qwen3-VL 2B (Primary VLM)

| Attribute | Detail |
|:---|:---|
| **Model Name** | qwen3-vl:2b (Ollama tag, digest 0635d9d857d4) |
| **Purpose** | Primary Vision-Language Model (VLM). Processes a JPEG image of the user environment together with a natural language text prompt to generate a concise natural language answer about the scene. |
| **File Location** | Stored by Ollama at /usr/share/ollama/.ollama/models/ or ~/.ollama/models/ (not in Git). Pulled via 'ollama pull qwen3-vl:2b' in rootfs/roles/vllm/tasks/main.yml line 17. |
| **Model Format** | **GGUF** — quantized model file served through Ollama runtime. Qwen3-VL supports simultaneous vision and text understanding. |
| **Model Size** | Approximately 1.5-2.0 GB on disk (2B parameter model at 4-bit or 8-bit GGUF quantization). |
| **How It Is Loaded** | Loaded into Jetson GPU VRAM by ollama daemon. On verification, pocketinfer sends warm-up POST http://localhost:11434/api/generate with "keep_alive": -1 to pin model in VRAM permanently. The Ollama adapter calls ollama.generate() which submits to daemon via localhost:11434. |
| **Which Python File Loads It** | python/pocketinfer/models/ollama.py — Ollama.generate(images, prompt). The ollama Python package communicates to the Ollama daemon. |
| **Which Application Uses It** | hear_the_world.py — primary default model (line 34: "model_name": "qwen3-vl:2b") |
| **Input Format** | ollama.generate(model="qwen3-vl:2b", images=[bytearray_jpg], prompt="text. Limit response to one short sentence") |
| **Output Format** | ollama.GenerateResponse object — resp.response is a plain-text natural language answer string |
| **Offline Capability** | YES — Fully Offline. Model weights cached locally. Inference via localhost HTTP only. |
| **GPU / CPU Usage** | GPU (CUDA VRAM) — Ollama loads GGUF weights into Jetson integrated GPU VRAM. keep_alive: -1 keeps model resident to avoid cold-start latency. |
| **Memory Usage** | Approximately 2.0-3.5 GB GPU VRAM for 2B model at 4-bit quantization. Jetson Orin Nano uses unified CPU+GPU memory (8 GB total). |
| **Can It Be Replaced?** | Yes. Ollama class accepts any model_name string. Any Ollama-compatible GGUF model (moondream:1.8B, llava-phi3, custom fine-tunes) can substitute. |
| **Should NomadRight Reuse It?** | YES — Extend. Specify target model tag in @RegisterApplication metadata. Ollama adapter class reused without modification. |

---

### Model 5 — Ministral-3 3B (Alternate VLM/LLM)

| Attribute | Detail |
|:---|:---|
| **Model Name** | ministral-3:3B (Ollama tag, digest f04aa1c738f6) |
| **Purpose** | Alternate Vision-Language / Language Model. Listed as primary model for HearTheWorldEn. Referenced as recommended NomadRight default in architecture documents. |
| **File Location** | Same as Qwen3-VL: stored by Ollama at ~/.ollama/models/. Pulled via 'ollama pull ministral-3:3B' in rootfs/roles/vllm/tasks/main.yml line 13. |
| **Model Format** | **GGUF** via Ollama runtime. Ministral is a Mistral-family model. |
| **Model Size** | Approximately 2.0-3.0 GB on disk (3B parameter model at 4-bit quantization). |
| **How It Is Loaded** | Identical to Qwen3-VL — loaded by ollama daemon into GPU VRAM. Same Ollama wrapper class; only model_name argument differs. |
| **Which Python File Loads It** | python/pocketinfer/models/ollama.py — same Ollama.generate() method |
| **Which Application Uses It** | hear_the_world_en.py — active default (line 24). Commented out in hear_the_world.py (line 36). Recommended in INTEGRATION_PLAN.md and NOMADRIGHT_ARCHITECTURE.md as NomadRight default. |
| **Input Format** | Same as Qwen3-VL: ollama.generate(model="ministral-3:3B", images=[bytearray_jpg], prompt="...") |
| **Output Format** | Same as Qwen3-VL: resp.response — plain-text natural language answer string |
| **Offline Capability** | YES — Fully Offline. Same as Qwen3-VL. |
| **GPU / CPU Usage** | GPU (CUDA VRAM) — same as Qwen3-VL. |
| **Memory Usage** | Approximately 2.5-4.0 GB GPU VRAM for 3B model. Only one VLM resident in VRAM at once. |
| **Can It Be Replaced?** | Yes — same substitution mechanism as Qwen3-VL. |
| **Should NomadRight Reuse It?** | YES — Recommended Default. NOMADRIGHT_ARCHITECTURE.md Section 7 and INTEGRATION_PLAN.md Section 9 cite ministral-3:3B as the NomadRight default. More conservative in VRAM than Qwen3-VL. |

> **Note on moondream:1.8B**: A third model (moondream:1.8B) appears in commented-out lines in both application files. NOT actively provisioned in Ansible but architecturally supported via the same Ollama wrapper. Estimated ~1.0-1.5 GB VRAM.

---

### Model 6 — Piper TTS (en_US-lessac-medium)

| Attribute | Detail |
|:---|:---|
| **Model Name** | en_US-lessac-medium |
| **Purpose** | Offline English Text-to-Speech synthesis. Converts the VLM natural language response into real-time spoken PCM audio for speaker playback. |
| **File Location** | ~/.cache/pocketinfer/piper_voice/en_US-lessac-medium.onnx and .onnx.json (downloaded via piper.download_voices.download_voice(); not tracked in repo) |
| **Model Format** | **ONNX** — Open Neural Network Exchange format. .onnx is the acoustic VITS architecture model. .onnx.json is the synthesis configuration (phoneme set, sample rate, speaker IDs). |
| **Model Size** | ~60-90 MB for the .onnx file (medium quality variant). JSON config is a few KB. |
| **How It Is Loaded** | PiperVoice.load(model_path=..., config_path=...) called ONCE at application startup in Piper.__init__(). Model kept PERSISTENTLY IN MEMORY for the application lifetime. Synthesis runs in a dedicated background thread via threading.Thread(target=self._synthesize_and_play). |
| **Which Python File Loads It** | python/pocketinfer/models/piper.py — Piper.__init__() loads the ONNX model; Piper.start_playback() triggers synthesis. |
| **Which Application Uses It** | hear_the_world_en.py — always used for TTS output. hear_the_world.py — Piper call is commented out (line 166); multilingual app routes all TTS through Bhashini TTS. |
| **Input Format** | Python string — the English text to synthesize e.g. "This is a computer mouse" |
| **Output Format** | Streaming raw 16-bit signed integer PCM audio chunks (audio_chunk.audio_int16_bytes) written to AudioPlayer stdin for ffplay playout. Sample rate from voice.config.sample_rate. |
| **Offline Capability** | YES — Fully Offline. ONNX model runs locally via piper-tts Python library. No network calls. |
| **GPU / CPU Usage** | CPU — Piper VITS ONNX uses ONNX Runtime on CPU. No CUDA utilized on Jetson. |
| **Memory Usage** | ~100-200 MB RAM (ONNX Runtime + model weights). Stays resident for application lifetime. |
| **Can It Be Replaced?** | Yes. Any TTS backend accepting a Python string and writing PCM to AudioPlayer can replace Piper. Alternatives: Kokoro TTS, StyleTTS2, Coqui TTS. |
| **Should NomadRight Reuse It?** | YES — Reuse As-Is. Per INTEGRATION_PLAN.md Section 3: Piper is the recommended offline English TTS. Pre-cache en_US-lessac-medium.onnx during deployment. |

---

### Model 7 — Bhashini TTS (Indic TTS via Flite)

| Attribute | Detail |
|:---|:---|
| **Model Name** | Bhashini Indic TTS — voice files from flite_voices.zip archive |
| **Purpose** | Offline Text-to-Speech synthesis for Indic languages. Converts translated Indic-language response text into spoken audio for playback. |
| **File Location** | rootfs/roles/indic/files/flite_voices.zip (Git LFS pointer); voices deployed to ~/bhashini_models/tts/flite/voices/. Flite binary compiled from source (github.com/festvox/flite) at ~/bhashini_models/tts/flite/. |
| **Model Format** | **Flite voice files** — compiled CMU Flite TTS voice archives (.flitevox format). Flite is a lightweight TTS engine from Carnegie Mellon University. Bhashini wraps Flite for Indic phoneme sets. |
| **Model Size** | Flite voice files typically 1-10 MB each. Total archive size unknown (LFS pointer only). |
| **How It Is Loaded** | Same as Bhashini ASR: loaded and served by bhashini_models.service. The Tts class in models/tts.py is a pure REST client — does NOT load any model weights itself. |
| **Which Python File Loads It** | python/pocketinfer/models/tts.py — Tts.infer() sends POST http://localhost:11400/tts. Bhashini service process handles synthesis. |
| **Which Application Uses It** | hear_the_world.py — always in the multilingual pipeline (line 164). Multilingual app routes ALL TTS through Bhashini (Piper call commented out on line 166). |
| **Input Format** | JSON: {"text": "<indic_or_english_text>", "language": "hi"} via POST to localhost:11400/tts |
| **Output Format** | JSON: {"audio_base64": "<base64_encoded_wav_bytes>"}. Caller decodes with base64.b64decode() and plays via AudioPlayer. |
| **Offline Capability** | YES — Fully Offline. Flite compiled locally. HTTP is loopback only. |
| **GPU / CPU Usage** | CPU only — Flite is a lightweight rule-based synthesis engine. No GPU utilization. |
| **Memory Usage** | Minimal — Flite synthesizers ~10-50 MB RAM per voice. Shared with bhashini_models.service process. |
| **Can It Be Replaced?** | Yes. Any HTTP endpoint returning base64 WAV at localhost:11400/tts works. Could be upgraded to Piper Indic voices or MMS-TTS. |
| **Should NomadRight Reuse It?** | SKIP for English-only NomadRight. REUSE if Indic voice output is required. Lower quality than Piper but very lightweight on CPU. |


---

## 3. Complete Inference Pipeline

### Pipeline A — English-Only (HearTheWorldEn)

**Application file:** python/pocketinfer/applications/hear_the_world_en.py
**Models used:** Vosk ASR (Model 1) -> Ministral-3 3B via Ollama (Model 5) -> Piper TTS (Model 6)

```
+-----------------------------------------------------------------------------------+
|                        PIPELINE A -- ENGLISH ONLY                                 |
|                                                                                   |
|  [AUDIO INPUT]              [CAMERA INPUT]                                        |
|  USB Microphone             Arducam 8MP (V4L2)                                    |
|        |                          |                                               |
|        v                          v                                               |
|   AudioRecorder              CameraReader                                         |
|   (audio.py)                 (boards/base.py)                                     |
|   PyAudio PCM                OpenCV frame                                         |
|   normalized to                   |                                               |
|   16-bit mono                 cv2.imencode()                                      |
|        |                          |                                               |
|        v                          v                                               |
|   AudioData object           JPEG bytes buffer                                    |
|        |                          |                                               |
|        v                          |                                               |
|   +-------------------+           |                                               |
|   |  MODEL 1: VOSK    |           |                                               |
|   |  Kaldi ASR Engine |           |                                               |
|   |  16kHz mono, CPU  |           |                                               |
|   |  ~40 MB on disk   |           |                                               |
|   +-------------------+           |                                               |
|        |                          |                                               |
|        v                          v                                               |
|        text query ----------> [PROMPT CONSTRUCTION]                              |
|                               query + ". Limit response to one short sentence"   |
|                               + JPEG image bytes                                  |
|                                         |                                         |
|                                         v                                         |
|                           +------------------------------+                        |
|                           |  MODEL 5: MINISTRAL-3 3B     |                        |
|                           |  GGUF via Ollama daemon       |                        |
|                           |  GPU VRAM ~3 GB               |                        |
|                           |  http://localhost:11434       |                        |
|                           +------------------------------+                        |
|                                         |                                         |
|                                         v                                         |
|                              English response text                                |
|                                         |                                         |
|                                         v                                         |
|                           +------------------------------+                        |
|                           |  MODEL 6: PIPER TTS          |                        |
|                           |  ONNX (en_US-lessac-medium)  |                        |
|                           |  CPU, ~100-200 MB RAM         |                        |
|                           +------------------------------+                        |
|                                         |                                         |
|                                         v                                         |
|                              PCM Int16 audio chunks (streaming)                  |
|                                         |                                         |
|                                         v                                         |
|                           AudioPlayer -> ffplay -> ALSA -> Speaker               |
+-----------------------------------------------------------------------------------+
```

---

### Pipeline B — Multilingual (HearTheWorld)

**Application file:** python/pocketinfer/applications/hear_the_world.py
**Models used:** Vosk / Bhashini ASR -> Bhashini NMT -> Qwen3-VL 2B -> Bhashini NMT -> Bhashini TTS

```
+-----------------------------------------------------------------------------------+
|                   PIPELINE B -- MULTILINGUAL (HearTheWorld)                       |
|                                                                                   |
|  [AUDIO INPUT]           [CAMERA INPUT]       settings.input_language             |
|        |                       |               (en / hi / ta)                    |
|        v                       v                       |                          |
|  AudioRecorder           CameraReader                  |                          |
|        |                       |                       v                          |
|        |                       |            +------------------------+            |
|        v                       |            | IF input == 'en':      |            |
|  AudioData object              |            | MODEL 1: VOSK ASR      |            |
|        |                       |            | (Kaldi, CPU, ~40 MB)   |            |
|        v                       |            +------------------------+            |
|  WAV bytes (base64)            |            | ELSE:                  |            |
|        |                       |            | MODEL 2: BHASHINI ASR  |            |
|        +───────────────────────+            | (CTranslate2, CPU)     |            |
|                                             | localhost:11400/asr    |            |
|                                             +------------------------+            |
|                                                        |                          |
|                                             raw_query (source language text)      |
|                                                        |                          |
|                                             +------------------------+            |
|                                             | IF input != 'en':      |            |
|                                             | MODEL 3: BHASHINI NMT  |            |
|                                             | (CTranslate2, CPU)     |            |
|                                             | src_lang -> EN         |            |
|                                             | localhost:11400/nmt    |            |
|                                             +------------------------+            |
|                                                        |                          |
|                                              English query text                   |
|                                                        |                          |
|  JPEG bytes -----------------------------> [PROMPT CONSTRUCTION]                  |
|                                            query + JPEG image bytes               |
|                                                        |                          |
|                                                        v                          |
|                                        +--------------------------+               |
|                                        |  MODEL 4: QWEN3-VL 2B   |               |
|                                        |  GGUF via Ollama daemon  |               |
|                                        |  GPU VRAM ~2.5 GB        |               |
|                                        |  http://localhost:11434  |               |
|                                        +--------------------------+               |
|                                                        |                          |
|                                              English response text                |
|                                                        |                          |
|                                             +------------------------+            |
|                                             | IF output != 'en':     |            |
|                                             | MODEL 3: BHASHINI NMT  |            |
|                                             | (CTranslate2, CPU)     |            |
|                                             | EN -> target_lang      |            |
|                                             | localhost:11400/nmt    |            |
|                                             +------------------------+            |
|                                                        |                          |
|                                              target language text                 |
|                                                        |                          |
|                                        +--------------------------+               |
|                                        |  MODEL 7: BHASHINI TTS   |               |
|                                        |  Flite voices (CPU)      |               |
|                                        |  localhost:11400/tts     |               |
|                                        +--------------------------+               |
|                                                        |                          |
|                                              base64 WAV bytes decoded             |
|                                                        |                          |
|                              AudioPlayer -> ffplay -> ALSA -> Speaker            |
+-----------------------------------------------------------------------------------+
```

---

## 4. Audio Flow Diagram

Tracks audio transformation from raw microphone PCM to final speaker output.

```
Microphone Hardware (USB PnP Sound Device via ALSA)
          |
          |  ALSA raw PCM stream
          v
AudioRecorder.__init__()          [audio.py]
  * Tests sample rates: [16k, 22.05k, 32k, 44.1k, 48k, 88.2k, 96k, 192k Hz]
  * Selects lowest supported rate (e.g. 44.1 kHz on most USB mics)
  * PyAudio: frames_per_buffer=4096
  * Background thread _record() reads chunks into self.frames list
          |
          |  Raw PCM bytes accumulated in self.frames
          v
AudioRecorder.stop() + to_audio_data()   [audio.py]
  * Concatenates self.frames into NumPy int16 array
  * Peak normalization: gain = 32768.0 / peak_amplitude * 1.2
  * np.clip(audio_array, -32768, 32767)
  * Returns speech_recognition.AudioData wrapper object
          |
          +------- [English ASR path] ----------------------------------------+
          |                                                                    |
          |  audio_data.get_raw_data(convert_rate=16000, convert_width=2)     |
          |  Downsample to 16kHz 16-bit mono PCM bytes                        |
          v                                                                    |
 MODEL 1: Vosk KaldiRecognizer.AcceptWaveform()                               |
 KaldiRecognizer.FinalResult() -> JSON {"text": "transcribed words"}          |
          |                                                                    |
          +------- [Indic ASR path] -------------------------------------------+
                                                                               |
          audio_data.get_wav_data() -> WAV format bytes                       |
          base64.b64encode(wav_bytes)                                          |
          POST http://localhost:11400/asr                                      |
          {"language": "hi", "audio_base64": "<base64>"}                      |
          v                                                                    |
 MODEL 2: Bhashini ASR (CTranslate2)                                          |
 Response: {"text": "user question in hindi"}                                 |
          |                                                                    |
          +---------- text query (source language string) ---------------------+
                                    |
                     [VLM + NMT Pipeline -- see Text Flow]
                                    |
                           response text output
                                    |
          +------- [English TTS path] -----------------------------------------+
          |                                                                     |
          |  MODEL 6: Piper.start_playback(text)                               |
          |    -> background thread: PiperVoice.synthesize(text, syn_config)   |
          |    -> yields audio_chunk.audio_int16_bytes (streaming PCM)         |
          |                                                                     |
          +------- [Indic TTS path] -------------------------------------------+
                                                                               |
          POST http://localhost:11400/tts                                      |
          {"text": "...", "language": "hi"}                                    |
          Response: {"audio_base64": "<base64 WAV bytes>"}                    |
          base64.b64decode() -> WAV bytes                                      |
          wave.open(BytesIO(tts_bytes)) -> getframerate() + readframes()       |
          |                                                                     |
          +--------------------------------------------------------------------+
                                    |
                                    v
              AudioPlayer(sample_rate, hw:1,0)   [audio.py]
                * Sets SDL_AUDIODRIVER=alsa, AUDIODEV=hw:1,0
                * Spawns: ffplay -nodisp -autoexit -f s16le -ar <rate> -ac 1 -
                * player.play(pcm_bytes) writes to ffplay stdin
                                    |
                            ALSA hardware driver
                                    |
                               Speaker output
```

---

## 5. Camera Flow Diagram

Tracks the camera image from hardware sensor to VLM model input.

```
Arducam 8MP Camera (USB V4L2 device)
          |
          |  V4L2 kernel video device: /dev/v4l/by-id/*
          |  Matched by name pattern "Arducam_8mp" via regex in CameraReader
          v
CameraReader._run() background thread    [boards/base.py]
  * cv2.VideoCapture(camera_idx)
  * cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
  * cap.set(cv2.CAP_PROP_FRAME_HEIGHT,  720)
  * Continuous loop: ret, frame = cap.read()
  * Stores latest BGR frame in self.frame (numpy.ndarray)
  * Sets threading.Event self.frame_available
          |
          |  Latest BGR numpy ndarray (1280 x 720 x 3, uint8)
          v
Board.camera_frame_jpg()   [boards/base.py]
  * ret, buffer = cv2.imencode(".jpg", frame)
  * Returns bytearray(buffer)   [JPEG-compressed image bytes]
          |
          |  JPEG bytes (bytearray, ~30-150 KB depending on scene)
          v
Application run loop (hear_the_world_en.py or hear_the_world.py)
  * img = self.board.camera_frame_jpg()
  * Captured simultaneously with audio during button-hold window
          |
          |  img passed as argument to VLM inference call
          v
Ollama.generate(images=[img], prompt=query + "...")   [models/ollama.py]
  * Ollama Python client serializes image bytes in HTTP request body
  * HTTP POST -> http://localhost:11434/api/generate
          |
          v
MODEL 4 or 5: Qwen3-VL 2B / Ministral-3 3B (GGUF, GPU VRAM)
  * VLM processes visual tokens from JPEG plus text tokens from prompt
  * Generates natural language description/answer about the scene
  * Returns GenerateResponse with resp.response as plain string
```

---

## 6. Text Flow Diagram

Tracks the text prompt and response through every model stage.

```
AUDIO -> ASR (Model 1 or Model 2)
          |
          |  raw_query (source language string)
          |
          +------ IF input_language == 'en' ----------------------------------------+
          |       raw_query is already English                                        |
          |       query = raw_query (no translation step)                             |
          |                                                                           |
          +------ IF input_language != 'en' -----------------------------------------+
                                                                                     |
               MODEL 3: Bhashini NMT (CTranslate2)                                 |
               POST /nmt {"text": raw_query, "src_lang": "HI", "tgt_lang": "EN"}   |
               Response: {"translated_text": "English equivalent query"}            |
               query = translated_text                                               |
               |                                                                     |
               +----------------------------English query---------------------------+
                                                    |
                          prompt = query + ". Limit response to one short sentence"
                          images = [JPEG bytes from camera]
                                                    |
                                                    v
               CAMERA JPEG ------> MODEL 4/5: Ollama VLM (GGUF, GPU VRAM)
                                                    |
                                                    v
                                          result (English response text)
                                          e.g. "This is a computer mouse."
                                                    |
               +------ IF output_language == 'en' --------------------------------+
               |       nmt_result = result (pass-through, no translation)         |
               |                                                                   |
               +------ IF output_language != 'en' --------------------------------+
                                                                                   |
                    MODEL 3: Bhashini NMT (CTranslate2) [second invocation]      |
                    POST /nmt {"text": result, "src_lang": "EN", "tgt_lang": "HI"}|
                    Response: {"translated_text": "Indic language response"}      |
                    nmt_result = translated_text                                   |
                    |                                                              |
                    +------------------target language text-----------------------+
                                                    |
               +--- English output path -------- Indic output path ---------------+
               |                                                                   |
               |  MODEL 6: Piper TTS                MODEL 7: Bhashini TTS         |
               |  piper.start_playback(result)       tts.infer(nmt_result, lang)  |
               |  ONNX, en_US-lessac-medium          Flite voices, CPU            |
               |  -> PCM Int16 audio chunks          -> {"audio_base64": "..."}   |
               |                                        base64.b64decode()         |
               |                                                                   |
               +-------- PCM audio bytes -------------------------------------------+
                                     |
                             AudioPlayer -> ffplay -> ALSA -> Speaker
```

---

## 7. Service Dependency Map

```
+---------------------------------------------------------------------------------+
|                        pocketinfer.service                                      |
|                                                                                 |
|   python/pocketinfer/service.py (main entry point)                              |
|                                                                                 |
|   In-process models (loaded directly into service RAM):                         |
|   +-------------------------------------------------------------------+         |
|   |  Model 1: Vosk (Kaldi, CPU)          ~/.cache/pocketinfer/vosk/  |         |
|   |  Model 6: Piper ONNX (CPU)           ~/.cache/pocketinfer/piper/ |         |
|   +-------------------------------------------------------------------+         |
|                                                                                 |
|   REST client wrappers (HTTP loopback only):                                    |
|   Asr client (models/asr.py)  ----+                                            |
|   Nmt client (models/nmt.py)  ----|---> HTTP localhost:11400                   |
|   Tts client (models/tts.py)  ----+                                            |
|   Ollama client (models/ollama.py) -----> HTTP localhost:11434                 |
|                                                                                 |
+---------------------------------------------------------------------------------+
                |                                    |
                v                                    v
+----------------------------------+   +---------------------------------+
|    bhashini_models.service       |   |        ollama.service           |
|    ~/bhashini_models/ (venv)     |   |        Ollama daemon            |
|                                  |   |                                 |
|  Model 2: Bhashini ASR           |   |  Model 4: qwen3-vl:2b          |
|    (CTranslate2, CPU-quantized)  |   |    (GGUF, GPU VRAM ~2.5 GB)    |
|  Model 3: Bhashini NMT           |   |  Model 5: ministral-3:3B       |
|    (CTranslate2, CPU-quantized)  |   |    (GGUF, GPU VRAM ~3 GB)      |
|  Model 7: Bhashini TTS           |   |                                 |
|    (Flite voices, CPU)           |   |  Endpoints:                     |
|                                  |   |  GET  /api/tags                 |
|  Endpoints:                      |   |  POST /api/generate             |
|  GET  /health                    |   |       {model, images, prompt,   |
|  POST /asr  {language, audio}    |   |        keep_alive}              |
|  POST /nmt  {text, src, tgt}     |   |  POST /api/chat                 |
|  POST /tts  {text, language}     |   |       {model, messages}         |
+----------------------------------+   +---------------------------------+
```

---

## 8. NomadRight Reuse Summary

Based on analysis in INTEGRATION_PLAN.md and NOMADRIGHT_ARCHITECTURE.md:

| Model | NomadRight Decision | Rationale |
|:---|:---:|:---|
| Model 1 — Vosk ASR | **Reuse As-Is** | 100% offline, zero modification, pre-cache zip to ~/.cache/pocketinfer/vosk_model/ |
| Model 2 — Bhashini ASR | **Optional** | Skip for English-native NomadRight; reuse only if Indic input is required |
| Model 3 — Bhashini NMT | **Do Not Use (EN)** | Adds 200-500ms latency and ~500 MB RAM; unnecessary for English-only operation |
| Model 4 — Qwen3-VL 2B | **Extend** | Specify in @RegisterApplication metadata; pre-pull with 'ollama pull qwen3-vl:2b' |
| Model 5 — Ministral-3 3B | **Recommended Default** | Specified as NomadRight default in arch docs; more memory-conservative |
| Model 6 — Piper TTS | **Reuse As-Is** | Offline ONNX TTS; pre-cache en_US-lessac-medium.onnx during deployment |
| Model 7 — Bhashini TTS | **Do Not Use (EN)** | Lower quality than Piper; skip for English; reuse only if Indic voice output needed |

### Recommended NomadRight Model Configuration (English-Only, Fully Offline)

```python
@RegisterApplication({
    "name": "NomadRight",
    "models": {
        "ollama": {"model_name": "ministral-3:3B"},       # VLM on GPU VRAM ~3 GB
        "piper":  {"voice_name": "en_US-lessac-medium"},  # TTS via ONNX ~100 MB RAM
        "vosk":   {"model_name": "vosk-model-small-en-us-0.15"},  # ASR Kaldi ~80 MB RAM
    },
    "service_dependencies": ["ollama"],
})
```

**Estimated total resource footprint (English-only NomadRight):**
- GPU VRAM:   ~3.0-4.0 GB  (Ministral-3 3B GGUF)
- System RAM: ~200-320 MB  (Vosk Kaldi + Piper ONNX Runtime)
- Disk:       ~2.5 GB      (Ollama model cache)
             + ~100 MB     (Piper ONNX voice file)
             + ~40 MB      (Vosk model directory)

---

## 9. Model Comparison Table

| # | Model Name | Task | Format | Runtime | Compute | Offline | Approx Size | Used By |
|:--|:---|:---|:---|:---|:---|:---:|:---|:---|
| 1 | vosk-model-small-en-us-0.15 | ASR (English) | Kaldi | In-process | CPU | YES | ~40 MB | HearTheWorldEn, HearTheWorld (EN mode) |
| 2 | Bhashini ASR (Hindi/Indic) | ASR (Indic) | CTranslate2 | bhashini daemon | CPU | YES | ~200-600 MB | HearTheWorld (non-EN input) |
| 3 | Bhashini NMT (Indic-EN) | Translation | CTranslate2 | bhashini daemon | CPU | YES | ~150-500 MB | HearTheWorld (non-EN language) |
| 4 | qwen3-vl:2b | Vision-Language | GGUF | Ollama daemon | GPU VRAM | YES | ~1.5-2.0 GB | HearTheWorld (primary) |
| 5 | ministral-3:3B | Vision-Language | GGUF | Ollama daemon | GPU VRAM | YES | ~2.0-3.0 GB | HearTheWorldEn, NomadRight |
| 6 | en_US-lessac-medium | TTS (English) | ONNX | In-process | CPU | YES | ~60-90 MB | HearTheWorldEn |
| 7 | Bhashini TTS / Flite voices | TTS (Indic) | Flite | bhashini daemon | CPU | YES | ~1-10 MB | HearTheWorld (all TTS) |

---

*End of MODEL_ANALYSIS.md*
*Analyzed by: Senior AI Systems Engineer | Repository: suno-sutra-sw-main | Date: August 4, 2026*
