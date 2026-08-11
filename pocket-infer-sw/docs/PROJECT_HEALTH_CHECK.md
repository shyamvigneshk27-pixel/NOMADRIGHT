# NomadRight Project Health Check & Technical Audit Report

**Author:** Principal Software Architect & Technical Auditor  
**Date:** August 4, 2026  
**Target Platform:** Suno Sutra Edge AI Platform (NVIDIA Jetson Orin Nano 8GB)  
**Target Event:** VYOMA Innovation Challenge (100% Offline Multilingual AI Assistant)  
**Document Version:** 1.0.0

---

## Executive Audit Summary

A complete technical audit and health check was performed on the **NomadRight** project within the suno-sutra-sw-main repository. 

The project has achieved solid foundational milestones:
- Hardware abstraction (Jetson Orin Nano HAL, USB camera, ALSA audio, serial display drivers) is operational.
- The 7 core internal application modules (intent, entities, classifier, 
ules, database, 
esponse, workflow) are implemented and registered into the Suno Sutra ApplicationRegistry.
- Architecture and model analysis specifications are comprehensive.

However, the audit identified **critical architectural risks**, **legacy directory duplication**, **hidden runtime network fallback risks in model wrappers**, and **ASR phonetic matching vulnerabilities** that must be remediated prior to final submission.

---

## Scorecard Overview

| Category | Score | Status |
|:---|:---:|:---:|
| **Overall Readiness** | **74 / 100** | ⚠️ Needs Remediation |
| Architecture Score | **88 / 100** | ✅ Excellent |
| Repository Score | **78 / 100** | ⚠️ Minor Debt |
| Offline Readiness | **75 / 100** | ⚠️ Critical Risk in Fallbacks |
| Model Readiness | **85 / 100** | ✅ Solid |
| Database Readiness | **70 / 100** | ⚠️ Duplication Debt |
| Production Readiness | **55 / 100** | ❌ Needs Hardening |
| Hackathon Readiness | **80 / 100** | 🟡 Demo Ready with Caveats |

---

## Detailed Audit Checklist

---

### 1. Repository Structure

* **Folder Cleanliness**: **Good (Post-Reorganization)**. The core application logic resides in python/pocketinfer/applications/nomad_right/, documentation is grouped in docs/, and datasets live in data/nomadright/.
* **Misplaced & Redundant Files**:
  - ❌ **Legacy Root Directory Debt**: The root-level directory 
omadright/ contains duplicate files (uild_sqlite_db.py, citations.md, mgnregs.json, 
omadright_kb.db, pds.json, pmjay.json, alidate.py, alidation_report.md) from earlier standalone experiments. This creates confusion and data drift against data/nomadright/.
* **Missing Folders**:
  - ❌ 	ests/ directory is missing. There are zero automated unit or integration tests covering the 7 NomadRight software modules.

---

### 2. Database Audit

* **Organization & Location**:
  - Current operational database: data/nomadright/nomadright.db (28 KB).
  - Legacy standalone database: 
omadright/nomadright_kb.db (131 KB).
  - **Audit Finding**: Two database files exist simultaneously. data/nomadright/nomadright.db is initialized with WAL mode and assets/logs tables, but lacks the rich scheme rule datasets contained in 
omadright_kb.db.
* **Schema Analysis**:
  - Table ssets: Clean DDL (id, 
ame, 	ype, location, max_operating_psi, status).
  - Table inspection_logs: Stores historical audit events.
* **Scalability & Indexing**:
  - ⚠️ inspection_logs lacks explicit indices on sset_id and 	imestamp.
  - ⚠️ SQLite Full-Text Search (FTS5) is not yet configured for searching legal citations (citations.md) and scheme rule JSONs (pds.json, pmjay.json, mgnregs.json).

---

### 3. AI Model Audit

| Model | Task | Format | Deployment State | Audit Notes |
|:---|:---|:---|:---|:---|
| **Vosk** | English ASR | Kaldi | In-process | Active in pp.py. Uses ~40MB RAM on CPU. |
| **Ministral-3 3B** | VLM / LLM | GGUF | Ollama Daemon | Active default. Uses ~3.0 GB GPU VRAM. |
| **Qwen3-VL 2B** | Primary VLM | GGUF | Ollama Daemon | Provisioned via Ansible. Primary visual model. |
| **Piper** | English TTS | ONNX | In-process | Active in pp.py. en_US-lessac-medium voice. |
| **Bhashini ASR/NMT/TTS** | Indic Multilingual | CTranslate2 / Flite | hashini_models.service | Provisioned in 
ootfs/roles/indic, but disabled in English app wrapper. |

* **Unused Models**: Bhashini Indic stack (ASR, NMT, Flite TTS) is present on disk via Ansible but unintegrated into 
omad_right/app.py.
* **Missing Model Layer**: Lack of a lightweight ONNX Intent/NER Classifier (currently relying on regex in intent.py and entities.py).

---

### 4. Offline Capability Verification

* **Runtime Autonomy**: **100% Offline Capable** when assets are pre-cached.
* **HIDDEN INTERNET DEPENDENCY RISKS**:
  1. 🚨 **Vosk Auto-Download Risk**: In python/pocketinfer/models/vosk.py, if the model directory does not exist at ~/.cache/pocketinfer/vosk_model/, the code calls urllib.request to download the zip from https://alphacephei.com/vosk/models/. In an offline competition setting without internet, this will raise a socket error and crash the application.
  2. 🚨 **Piper Auto-Download Risk**: In python/pocketinfer/models/piper.py, if the .onnx voice file is missing, it invokes piper.download_voices.download_voice(), attempting an external HTTP fetch to HuggingFace/GitHub.
* **Remediation Required**: Wrap model initialization in strict offline_mode=True assertions that raise clear configuration errors if cached files are missing, rather than attempting runtime network fetches.

---

### 5. Software Architecture Review

* **Module Separation**: **88/100 (Excellent)**. Decouples ASR and TTS via 7 distinct modules:
  IntentRecognizer -> EntityExtractor -> QueryClassifier -> RulesEngine -> SQLiteAccessLayer -> ResponseGenerator -> WorkflowController.
* **Dependency Flow**: Strictly unidirectional.
* **Coupling**: Low. Hardware HAL is injected via BaseApplication and Board.
* **Maintainability**: High. Each module adheres to the Single Responsibility Principle (SRP).

---

### 6. Integration Points with Suno Sutra

NomadRight integrates cleanly into Suno Sutra via 6 well-defined touchpoints:

1. ApplicationRegistry (python/pocketinfer/applications/registry.py): Decorator @RegisterApplication exposes NomadRight to CLI and UI launchers.
2. pocketinfer-service CLI (python/pocketinfer/service.py): Invoked via pocketinfer-service --app NomadRight.
3. Board HAL (python/pocketinfer/boards/base.py & jetson.py): Trigger button events (wait_for_trigger_button_down), camera frames (camera_frame_jpg), statusbar rendering (statusbar), and display text (	op_text, ottom_text).
4. Vosk Model Adapter (python/pocketinfer/models/vosk.py): osk.recognize(audio_data).
5. Ollama Model Adapter (python/pocketinfer/models/ollama.py): ollama.generate(images, prompt).
6. Piper Model Adapter (python/pocketinfer/models/piper.py): piper.start_playback(tts_text).

---

## 7. Risk Analysis

### Critical Risks (Must Fix Before Submission)
1. **Model Fallback Network Fetches**: Unguarded network download code in Vosk and Piper wrappers will crash/hang during offline evaluation if cache directories are missing or corrupted.
2. **ASR Transcription Fragility**: Speech recognition errors (e.g. ASR transcribing "pump one oh four" or "pump 104") cause regex matches in entities.py to fail if strict string formatting is assumed.

### High Risks
1. **Legacy Directory Duplication Debt**: Root directory 
omadright/ duplicates data/nomadright/, risking stale rule definitions being queried during execution.
2. **Ollama GPU Memory Spike**: Running ministral-3:3B alongside camera buffer encoding and UI rendering pushes Jetson Orin Nano memory usage close to the 8GB unified limit.

### Medium Risks
1. **Lack of Automated Test Coverage**: Zero test files under 	ests/.
2. **Single-Sentence VLM Truncation**: Crude string splitting (
esult.split('.')[0]) can truncate critical safety warnings in TTS output.

### Low Risks
1. Unindexed SQLite log queries on large datasets.

---

## 8. Missing Components Before Implementation Complete

1. **Strict Offline Guard Module** (erify_offline_assets.py): Pre-flight check script ensuring all Vosk, Ollama, and Piper weights exist on disk prior to boot.
2. **Phonetic & Spoken-Number Normalizer**: Normalizes spoken number strings ("one zero four" -> "104") before regex entity extraction.
3. **Scheme Data Consolidation Engine**: Unifies PDS, PM-JAY, and MGNREGS JSON datasets into 
omadright.db tables.
4. **Automated Unit Test Suite** (	ests/test_nomadright_pipeline.py).

---

## 9. Readiness Assessment

`
[  MVP Readiness: 74%  ]
██████████████████████████████░░░░░░░░░░
`

### What is Still Missing?
- Cleanup of duplicate legacy root 
omadright/ directory.
- Inclusion of scheme JSON rules (PDS, PM-JAY, MGNREGS) inside SQLiteAccessLayer queries.
- Strict offline download guards in osk.py and piper.py.
- Spoken number normalization in entities.py.
- Automated test coverage.

---

## 10. Top 5 Recommended Engineering Tasks (Priority Order)

1. **Task 1: Delete Legacy Root Directory Debt**  
   Remove redundant 
omadright/ directory at repository root and migrate all scheme JSONs/DB tables into data/nomadright/nomadright.db.

2. **Task 2: Harden Model Adapters Against Network Downloads**  
   Add offline_mode=True assertions in models/vosk.py and models/piper.py to block urllib / HTTP downloads and throw explicit local path errors if weights are absent.

3. **Task 3: Implement Spoken Number & Phonetic Normalizer**  
   Enhance entities.py with number word conversion ("one oh four" -> "104") to ensure ASR transcriptions reliably resolve asset IDs.

4. **Task 4: Integrate Scheme Datasets into SQLite & Rules Engine**  
   Update database.py and 
ules.py to query pds.json, pmjay.json, and mgnregs.json for offline citizen scheme guidance.

5. **Task 5: Create Unit & Integration Test Suite**  
   Build 	ests/test_nomadright_pipeline.py to validate WorkflowController across sample audio queries and camera frames.

---

## Key Jury Question

> **"If this project were submitted today, what would prevent it from winning?"**

### Auditor's Direct Answer:

1. **ASR Speech Fragility**: In a live judge demonstration, if the speaker says *"Check pump one zero four"* and Vosk transcribes "check pump 1 0 4", the regex in entities.py will fail to extract PUMP-104, causing the system to fall back to generic VLM inference or return a "No data found" error.
2. **Missing Scheme Intelligence in Live App**: The current workflow.py queries ssets tables but does not yet evaluate the newly created PDS, PM-JAY, and MGNREGS social entitlement rules during the voice pipeline.
3. **Repository Debt**: A technical judge reviewing the Git repository will immediately notice the duplicate legacy 
omadright/ directory at the root alongside data/nomadright/, signaling incomplete refactoring.
4. **Offline Vulnerability**: If the Jetson is booted in a clean environment where Vosk/Piper paths are misconfigured, the adapters will attempt internet downloads, failing silently or crashing live on stage.

---

*Report Complete — Technical Audit Approved by Principal Software Architect*
