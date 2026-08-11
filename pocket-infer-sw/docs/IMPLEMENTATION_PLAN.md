# NomadRight — Engineering Implementation Plan

**Role:** Lead Software Engineer  
**Date:** August 4, 2026  
**Target Platform:** Suno Sutra Edge AI Platform (NVIDIA Jetson Orin Nano 8GB)  
**Deployment Context:** 100% Offline Multilingual Citizen Welfare Assistant (VYOMA Challenge)  
**Document Version:** 2.0.0

---

## Executive Summary

This document establishes the step-by-step engineering implementation plan for the **NomadRight** application on the Suno Sutra platform. 

Based on the approved architectural specifications (NOMADRIGHT_ARCHITECTURE.md, MODEL_ANALYSIS.md, PROJECT_HEALTH_CHECK.md, INTENT_RECOGNITION_DESIGN.md, and DECISION_LAYER_ARCHITECTURE.md), the implementation is broken into **5 incremental milestones**.

The strategy prioritizes building **one complete vertical slice in Milestone 1** (Trigger Button -> ASR -> Intent -> Entity -> Rules -> SQLite -> Response Generator -> TTS) before expanding to multi-scheme data, visual OCR, multilingual translation, and pre-flight offline hardening.

---

## Roadmap Overview

`
[ Milestone 1: Vertical Slice ] ──► [ Milestone 2: Multi-Scheme ] ──► [ Milestone 3: Multimodal Vision ]
        (PDS Scheme End-to-End)           (PM-JAY & MGNREGS Rules)              (Ollama VLM OCR)
                                                                                       │
                                                                                       ▼
[ Milestone 5: Production Hardening ] ◄──────────────────────────────── [ Milestone 4: Multilingual ]
     (Offline Guards & Verification)                                         (Bhashini Indic Stack)
`

---

## Milestone Specifications

---

### Milestone 1: Complete End-to-End Vertical Slice (PDS Scheme)

* **Objective**: Build and validate a complete, functional vertical slice of the voice pipeline for a single welfare scheme (**Public Distribution System / PDS Eligibility**). Prove the end-to-end execution loop from trigger button press to TTS audio playout.
* **Pipeline Sequence**:
  `
  Press Button -> Speak Question -> Vosk ASR -> Intent Recognition (PDS_ELIGIBILITY)
  -> Entity Extraction (scheme_code="PDS") -> Rules Engine (pds.json) -> SQLite DB
  -> Response Generator -> Piper TTS Playout -> LCD Display Render
  `

#### Files to Implement & Harden:
1. python/pocketinfer/applications/nomad_right/app.py — NomadRightApplication main execution loop.
2. python/pocketinfer/applications/nomad_right/workflow.py — WorkflowController pipeline orchestrator.
3. python/pocketinfer/applications/nomad_right/intent.py — IntentRecognizer pattern matcher.
4. python/pocketinfer/applications/nomad_right/entities.py — EntityExtractor parameter parser.
5. python/pocketinfer/applications/nomad_right/rules.py — RulesEngine loading pds.json.
6. python/pocketinfer/applications/nomad_right/database.py — SQLiteAccessLayer WAL-mode reader/writer.
7. python/pocketinfer/applications/nomad_right/response.py — ResponseGenerator voice & display formatter.
8. data/nomadright/pds.json — PDS NFSA entitlement rules data file.
9. data/nomadright/nomadright.db — Initialized SQLite database file.

#### System Dependencies:
- Cached Vosk English model (~/.cache/pocketinfer/vosk_model/vosk-model-small-en-us-0.15/).
- Cached Piper ONNX voice (~/.cache/pocketinfer/piper_voice/en_US-lessac-medium.onnx).
- ALSA sound driver & OpenCV V4L2 camera framework.
- PocketInfer Board HAL (PocketInferDemo / DummyBoard).

#### Testing Strategy:
- **Unit Tests (	ests/test_m1_vertical_slice.py)**:
  - 	est_intent_pds_eligibility(): Asserts "Am I eligible for free ration?" maps to IntentType.PDS_ELIGIBILITY with confidence >= 0.85.
  - 	est_entity_pds(): Asserts scheme code "PDS" is extracted.
  - 	est_rules_pds(): Asserts pds.json rule check returns passed=True with 35 kg grain quota.
  - 	est_response_pds(): Asserts voice text contains "35 kg food grains" and display top text is "PDS: ELIGIBLE".
- **Integration Tests (	ests/test_m1_integration.py)**:
  - 	est_full_pipeline_dummy_board(): Executes NomadRightApplication using DummyBoard and a pre-recorded 16kHz WAV audio file ("Am I eligible for ration card?").

#### Expected Output:
- **Voice Output (Speaker)**: *"You are eligible for 35 kg food grains monthly under PDS."*
- **Display Output (320x240 LCD)**:
  - Top Text: PDS: ELIGIBLE
  - Bottom Text: 35 kg Grain Quota (Free)
- **Database Entry**: Row inserted into inspection_logs table in 
omadright.db.

#### Success Criteria:
- End-to-end execution completes in < 500 ms (excluding TTS audio playout time).
- 100% execution without network calls or external sockets.
- Zero exceptions raised on DummyBoard and physical Jetson hardware.

---

### Milestone 2: Multi-Scheme Data & Statutory Rules Integration (PM-JAY & MGNREGS)

* **Objective**: Expand the Decision Layer and local database layer to support statutory welfare rules for **PM-JAY (Ayushman Bharat)** and **MGNREGS (Rural Employment)** schemes.

#### Files to Implement & Harden:
1. data/nomadright/pmjay.json — Ayushman Bharat ₹5,00,000 health cover rule definitions.
2. data/nomadright/mgnregs.json — MGNREGA 100 days work & 15-day wage payment rules.
3. python/pocketinfer/applications/nomad_right/rules.py — Multi-scheme rule evaluation dispatcher.
4. python/pocketinfer/applications/nomad_right/database.py — Scheme dataset query methods.

#### System Dependencies:
- Completion of Milestone 1.
- data/nomadright/nomadright.db containing scheme_rules seed table.

#### Testing Strategy:
- **Unit Tests (	ests/test_m2_scheme_rules.py)**:
  - 	est_pmjay_eligibility(): Validates ₹5,00,000 family floater health cover rules.
  - 	est_pmjay_benefits(): Validates cashless hospital surgery coverage rules.
  - 	est_mgnregs_work(): Validates 100 days guaranteed work allotment rules.
  - 	est_mgnregs_wage(): Validates 15-day wage payment timeline & delay allowance rules.
- **Integration Tests (	ests/test_m2_multi_scheme.py)**:
  - Simulates sequential queries across PDS, PM-JAY, and MGNREGS, verifying state consistency in SQLite log tables.

#### Expected Output:
- **PM-JAY Query Voice Output**: *"PM-JAY provides 5 Lakh rupees annual cashless health cover per family for empaneled hospitals."*
- **MGNREGS Query Voice Output**: *"MGNREGS guarantees 100 days of rural manual work per household per year."*

#### Success Criteria:
- 100% test pass rate across 20+ synthetic welfare test cases.
- Rule evaluation latency remains < 5 ms per query.

---

### Milestone 3: Multimodal Vision & OCR Subsystem Integration

* **Objective**: Integrate camera snapshot processing with the local Ollama VLM (ministral-3:3B / qwen3-vl:2b) for document analysis, ration card scanning, and notice board OCR.

#### Files to Implement & Harden:
1. python/pocketinfer/applications/nomad_right/classifier.py — QueryClassifier decision matrix routing for OCR_DOCUMENT_ANALYSIS and HYBRID_RULES_VLM paths.
2. python/pocketinfer/applications/nomad_right/workflow.py — VLM prompt builder and image byte pass-through.
3. python/pocketinfer/applications/nomad_right/app.py — Camera snapshot capture trigger logic.

#### System Dependencies:
- Local ollama.service running on port 11434.
- ministral-3:3B or qwen3-vl:2b model tag pulled and pinned in GPU VRAM (keep_alive: -1).
- OpenCV V4L2 camera capture stream (CameraReader).

#### Testing Strategy:
- **Unit Tests (	ests/test_m3_vlm_routing.py)**:
  - 	est_classifier_with_camera(): Verifies RouteType.HYBRID_RULES_VLM selection when camera frame is attached.
  - 	est_vlm_prompt_formatting(): Verifies DB context is injected into VLM prompt string.
- **Integration Tests (	ests/test_m3_ocr_integration.py)**:
  - Sends a sample JPEG image byte array of a scheme notice paper to Ollama.generate() adapter and validates natural text response formatting.

#### Expected Output:
- **Visual Query Voice Output**: *"The notice states that ration distribution is open until 5 PM today."*
- **Display Output**: Top: NOTICE AUDIT, Bottom: Distribution Open Until 5 PM.

#### Success Criteria:
- VLM visual inference completes in < 2.5 seconds on Jetson Orin Nano GPU VRAM.
- Zero Out-Of-Memory (OOM) kernel crashes under repeated camera snapshot triggers.

---

### Milestone 4: Multilingual Translation & Bhashini Integration

* **Objective**: Enable non-English citizen interactions by integrating the offline Bhashini Indic model stack (ASR, NMT translation, Flite TTS) for Hindi, Tamil, Telugu, and Kannada.

#### Files to Implement & Harden:
1. python/pocketinfer/models/asr.py — Bhashini REST ASR client (localhost:11400/asr).
2. python/pocketinfer/models/nmt.py — Bhashini REST NMT client (localhost:11400/nmt).
3. python/pocketinfer/models/tts.py — Bhashini REST TTS client (localhost:11400/tts).
4. python/pocketinfer/applications/nomad_right/app.py — Multilingual settings switch and Bhashini pipeline routing.

#### System Dependencies:
- Local hashini_models.service active on port 11400 (provisioned via Ansible 
ootfs/roles/indic).
- CPU-quantized CTranslate2 ASR/NMT model archives deployed to ~/bhashini_models/.

#### Testing Strategy:
- **Unit Tests (	ests/test_m4_bhashini_clients.py)**:
  - 	est_asr_payload(): Tests base64 WAV serialization for /asr.
  - 	est_nmt_payload(): Tests text translation request formatting for /nmt.
  - 	est_tts_decoding(): Tests base64 WAV decoding from /tts.
- **Integration Tests (	ests/test_m4_indic_pipeline.py)**:
  - Simulates a Hindi spoken query ("क्या मुझे मुफ्त राशन मिलेगा?") through ASR -> NMT -> Rules Engine -> NMT -> Bhashini TTS.

#### Expected Output:
- **Hindi Voice Output**: *"आपको प्रति माह 35 किलोग्राम मुफ़्त खाद्यान्न मिलेगा।"*
- **Display Output**: Top: PDS: पात्र, Bottom: 35 किग्रा खाद्यान्न कोटा.

#### Success Criteria:
- Seamless bidirectional translation between English VLM/Rules and Indic user speech.
- Zero network socket requests outside localhost:11400.

---

### Milestone 5: Offline Hardening, Safety Guards & Pre-flight Verification

* **Objective**: Eliminate all runtime network download fallback risks, add pre-flight offline weight assertions, spoken number normalizer, and QR payload synthesis.

#### Files to Implement & Harden:
1. python/pocketinfer/models/vosk.py — Add strict offline_mode=True checks blocking urllib calls.
2. python/pocketinfer/models/piper.py — Add strict offline_mode=True checks blocking piper.download_voices fetches.
3. python/pocketinfer/applications/nomad_right/entities.py — Add spoken number normalizer ("one oh four" -> "104").
4. python/pocketinfer/applications/nomad_right/response.py — Add QR code payload JSON generator.
5. erify_offline_assets.py — Pre-flight audit script verifying all local weights prior to field deployment.

#### System Dependencies:
- Milestones 1–4 complete.

#### Testing Strategy:
- **Unit Tests (	ests/test_m5_offline_hardening.py)**:
  - 	est_vosk_missing_model_raises_error(): Asserts that missing model directory raises FileNotFoundError without attempting HTTP connection.
  - 	est_piper_missing_voice_raises_error(): Asserts missing ONNX voice raises FileNotFoundError without network access.
  - 	est_spoken_number_normalizer(): Tests "pump one oh four" -> "PUMP-104".
- **Integration Tests (	ests/test_m5_preflight.py)**:
  - Runs erify_offline_assets.py against filesystem and asserts 100% offline compliance.

#### Expected Output:
- **Pre-flight Console Output**:
  `	ext
  [PASS] Vosk Model: ~/.cache/pocketinfer/vosk_model/vosk-model-small-en-us-0.15/
  [PASS] Piper ONNX: ~/.cache/pocketinfer/piper_voice/en_US-lessac-medium.onnx
  [PASS] Ollama VLM: ministral-3:3B (VRAM Pinned)
  [PASS] Bhashini Service: localhost:11400 (Active)
  [PASS] SQLite Database: data/nomadright/nomadright.db (WAL Mode)
  SUCCESS: 100% OFFLINE READY FOR FIELD DEPLOYMENT
  `

#### Success Criteria:
- 0 socket connections opened to internet IP addresses under simulated network disconnect.
- Pre-flight audit completes in < 2.0 seconds.

---

## Summary Milestone Schedule & Verification Matrix

| Milestone | Key Deliverable | Primary Modules | Success Verification |
|:---:|:---|:---|:---|
| **M1** | Complete PDS Vertical Slice | pp, workflow, intent, entities, 
ules, database, 
esponse | End-to-end voice query playout on DummyBoard in < 500ms |
| **M2** | PM-JAY & MGNREGS Rules | 
ules.py, pmjay.json, mgnregs.json | 100% pass on 20+ statutory rule test scenarios |
| **M3** | Vision & Camera OCR | classifier.py, workflow.py, Ollama VLM | Camera snapshot visual answer in < 2.5s GPU VRAM |
| **M4** | Multilingual Bhashini | sr.py, 
mt.py, 	ts.py | Hindi/Indic voice interaction loop via localhost:11400 |
| **M5** | Offline Pre-flight Guard | osk.py, piper.py, erify_offline_assets.py | 100% offline verification; 0 network downloads attempted |

---

*Implementation Plan Complete — Ready for Engineering Execution*
