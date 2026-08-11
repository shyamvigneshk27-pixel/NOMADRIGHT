# NomadRight — Intent Recognition Module Architecture & Design Specification

**Role:** Principal AI Engineer  
**Date:** August 4, 2026  
**Target Platform:** Suno Sutra Edge AI Platform (NVIDIA Jetson Orin Nano 8GB)  
**Deployment Context:** 100% Offline Multilingual Citizen Welfare Assistant (VYOMA Challenge)  
**Document Version:** 1.0.0

---

## Executive Summary

This document defines the complete engineering design for the **Intent Recognition Module** (intent_recognizer.py / intent.py) within the NomadRight offline AI assistant. 

Operating entirely at the edge without internet access, this module sits directly downstream of the offline ASR pipeline (Vosk/Bhashini ASR). It receives text transcriptions, normalizes speech artifacts, and categorizes citizen queries across welfare schemes (PDS, PM-JAY, MGNREGS), administrative workflows, and multimodal camera/translation capabilities.

---

## 1. System Position & Architectural Contract

`
+-----------------------------------------------------------------------------------+
|                            NOMADRIGHT CORE PIPELINE                               |
|                                                                                   |
|  [Microphone] -> [AudioRecorder] -> [Vosk / Bhashini ASR]                         |
|                                            |                                      |
|                                            v                                      |
|                                   transcribed_text (str)                          |
|                                            |                                      |
|                                            v                                      |
|                  +-----------------------------------+                            |
|                  |     INTENT RECOGNITION MODULE     |  <-- DESIGNED IN THIS DOC  |
|                  |     (pocketinfer.applications.    |                            |
|                  |      nomad_right.intent)          |                            |
|                  +-----------------------------------+                            |
|                                            |                                      |
|                                            v                                      |
|                                 IntentResult (dataclass)                          |
|                                            |                                      |
|                                            v                                      |
|                  [EntityExtractor] -> [QueryClassifier] -> ... -> [Piper TTS]     |
+-----------------------------------------------------------------------------------+
`

---

## 2. Intent Taxonomy & Classification Hierarchy

The intent taxonomy is structured as a two-tier hierarchy separating domain schemes from operational capabilities:

`
Intent Taxonomy
├── 1. Welfare Schemes
│   ├── PDS (Public Distribution System / Ration)
│   │   ├── PDS_ELIGIBILITY
│   │   └── PDS_PORTABILITY (ONORC)
│   ├── PM-JAY (Ayushman Bharat Health Insurance)
│   │   ├── PMJAY_ELIGIBILITY
│   │   └── PMJAY_BENEFITS
│   └── MGNREGS (Rural Employment Guarantee / NREGA)
│       ├── MGNREGS_REGISTRATION (Job Card)
│       └── MGNREGS_WAGE_PAYMENT
│
├── 2. Administrative Workflows
│   ├── REQUIRED_DOCUMENTS
│   └── APPLICATION_PROCESS
│
├── 3. Multimodal Field Services
│   ├── TRANSLATION_REQUEST
│   └── OCR_DOCUMENT_ANALYSIS
│
└── 4. Assistance & Fallback
    ├── GENERAL_EXPLANATION
    └── UNKNOWN_QUERY
`

---

## 3. Supported Intent Detailed Specifications

---

### 3.1 PDS_ELIGIBILITY

* **Intent Name**: PDS_ELIGIBILITY
* **Description**: User inquiring if they or their family qualify for subsidized or free food grains under the Public Distribution System (National Food Security Act / Ration Card categories: AAY, BPL, PHH).
* **Trigger Examples (ASR Transcriptions)**:
  - *"Am I eligible for free ration card?"*
  - *"Who qualifies for BPL yellow ration card in village?"*
  - *"Can I get free rice under PDS scheme?"*
  - *"What is income limit for ration card eligibility?"*
* **Required Entities**: scheme_name ("PDS"), income_category (optional), 
ation_card_type (optional).
* **Expected Next Module**: EntityExtractor -> RulesEngine (
ules.py evaluating pds.json).

---

### 3.2 PDS_PORTABILITY

* **Intent Name**: PDS_PORTABILITY
* **Description**: User inquiring how to collect monthly ration grains in another state, district, or non-home ration shop under One Nation One Ration Card (ONORC).
* **Trigger Examples (ASR Transcriptions)**:
  - *"Can I take ration in Gujarat with Bihar ration card?"*
  - *"How to use One Nation One Ration Card in another state?"*
  - *"Is my ration card valid in city for migrant worker?"*
  - *"Portability procedure for taking food grains anywhere"*
* **Required Entities**: scheme_name ("PDS"), source_state (optional), 	arget_state (optional).
* **Expected Next Module**: EntityExtractor -> RulesEngine (pds.json portability clause) -> ResponseGenerator.

---

### 3.3 PMJAY_ELIGIBILITY

* **Intent Name**: PMJAY_ELIGIBILITY
* **Description**: User asking whether they qualify for the 5 Lakh rupees annual cashless health insurance cover under Ayushman Bharat PM-JAY.
* **Trigger Examples (ASR Transcriptions)**:
  - *"Am I eligible for Ayushman Bharat golden card?"*
  - *"Who gets 5 lakh hospital card in my family?"*
  - *"How to check if my name is in PM-JAY beneficiary list?"*
  - *"Qualifying criteria for Ayushman health card"*
* **Required Entities**: scheme_name ("PMJAY"), secc_category (optional), amily_id (optional).
* **Expected Next Module**: EntityExtractor -> RulesEngine (pmjay.json eligibility limits) -> ResponseGenerator.

---

### 3.4 PMJAY_BENEFITS

* **Intent Name**: PMJAY_BENEFITS
* **Description**: User asking what medical treatments, surgeries, hospitalizations, or illness costs are covered under the PM-JAY Ayushman card.
* **Trigger Examples (ASR Transcriptions)**:
  - *"What surgeries are free under Ayushman card?"*
  - *"Does PMJAY cover heart surgery and cancer treatment?"*
  - *"What are the benefits of 5 lakh health insurance?"*
  - *"Is hospital admission covered cashless in Ayushman?"*
* **Required Entities**: scheme_name ("PMJAY"), medical_condition (optional), 	reatment_type (optional).
* **Expected Next Module**: EntityExtractor -> SQLiteAccessLayer (search covered packages) -> ResponseGenerator.

---

### 3.5 MGNREGS_REGISTRATION

* **Intent Name**: MGNREGS_REGISTRATION
* **Description**: User asking how to register for a MGNREGA Job Card or demand guaranteed 100 days of rural manual employment.
* **Trigger Examples (ASR Transcriptions)**:
  - *"How to make NREGA job card in Gram Panchayat?"*
  - *"Where to register for 100 days guaranteed work?"*
  - *"Process to get new MGNREGA job card for family"*
  - *"Who can apply for rural work job card?"*
* **Required Entities**: scheme_name ("MGNREGS"), gram_panchayat (optional), pplicant_age (optional).
* **Expected Next Module**: EntityExtractor -> RulesEngine (mgnregs.json) -> ResponseGenerator.

---

### 3.6 MGNREGS_WAGE_PAYMENT

* **Intent Name**: MGNREGS_WAGE_PAYMENT
* **Description**: User inquiring about daily wage rates, 15-day wage payment timelines, delayed payment compensation, or bank transfer issues under MGNREGA.
* **Trigger Examples (ASR Transcriptions)**:
  - *"What is daily NREGA wage rate in Madhya Pradesh?"*
  - *"Why is my job card payment delayed for two weeks?"*
  - *"When will NREGA work money come in bank account?"*
  - *"What is delay allowance if wage is not paid in 15 days?"*
* **Required Entities**: scheme_name ("MGNREGS"), state_name (optional), job_card_id (optional).
* **Expected Next Module**: EntityExtractor -> RulesEngine (mgnregs.json wage rules) -> ResponseGenerator.

---

### 3.7 REQUIRED_DOCUMENTS

* **Intent Name**: REQUIRED_DOCUMENTS
* **Description**: User asking what supporting documents (Aadhaar, ration card, bank passbook, income certificate) are required to apply for a specific scheme.
* **Trigger Examples (ASR Transcriptions)**:
  - *"What documents are needed to apply for Ayushman card?"*
  - *"Which papers required for making new ration card?"*
  - *"List of documents needed for NREGA job card registration"*
  - *"Do I need bank passbook and Aadhaar card?"*
* **Required Entities**: 	arget_scheme (PDS / PMJAY / MGNREGS / General).
* **Expected Next Module**: EntityExtractor -> SQLiteAccessLayer / Scheme Data Store -> ResponseGenerator.

---

### 3.8 APPLICATION_PROCESS

* **Intent Name**: APPLICATION_PROCESS
* **Description**: User asking for step-by-step instructions on where to submit forms, which office to visit (CSC, Gram Panchayat, Ration Shop), or how to track application status.
* **Trigger Examples (ASR Transcriptions)**:
  - *"Where should I submit ration card application form?"*
  - *"Step by step process to get Ayushman golden card"*
  - *"How to submit application in Gram Panchayat office?"*
  - *"Where to go for job card registration in village?"*
* **Required Entities**: 	arget_scheme, submission_channel (optional).
* **Expected Next Module**: EntityExtractor -> RulesEngine / Database -> ResponseGenerator.

---

### 3.9 TRANSLATION_REQUEST

* **Intent Name**: TRANSLATION_REQUEST
* **Description**: User explicitly requesting translation of spoken phrases or text between English and local languages.
* **Trigger Examples (ASR Transcriptions)**:
  - *"Translate this sentence into Hindi"*
  - *"What does this form line mean in Tamil?"*
  - *"Convert this English text to my local language"*
  - *"Translate speech to English"*
* **Required Entities**: source_language (optional), 	arget_language (optional), 	ext_content.
* **Expected Next Module**: QueryClassifier -> Offline Bhashini NMT Service (localhost:11400/nmt).

---

### 3.10 OCR_DOCUMENT_ANALYSIS

* **Intent Name**: OCR_DOCUMENT_ANALYSIS
* **Description**: User pointing the device camera at a printed paper, scheme pamphlet, notice board, or official certificate and asking the assistant to analyze it.
* **Trigger Examples (ASR Transcriptions)**:
  - *"Read this scheme notice paper for me"*
  - *"What is written on this ration card document?"*
  - *"Analyze this hospital bill paper using camera"*
  - *"Explain what this government notice says"*
* **Required Entities**: document_type (optional), camera_frame (JPEG bytes from camera).
* **Expected Next Module**: QueryClassifier -> Ollama VLM (ministral-3:3B / qwen3-vl:2b GPU inference).

---

### 3.11 GENERAL_EXPLANATION

* **Intent Name**: GENERAL_EXPLANATION
* **Description**: User asking for a high-level overview or summary of what a specific government welfare scheme is and how it helps citizens.
* **Trigger Examples (ASR Transcriptions)**:
  - *"What is PM-JAY scheme in simple words?"*
  - *"Explain MGNREGA scheme and its purpose"*
  - *"Tell me about Public Distribution System food scheme"*
  - *"What are main welfare schemes for poor families?"*
* **Required Entities**: 	arget_scheme.
* **Expected Next Module**: QueryClassifier -> SQLiteAccessLayer / Ollama LLM -> ResponseGenerator.

---

### 3.12 UNKNOWN_QUERY

* **Intent Name**: UNKNOWN_QUERY
* **Description**: Transcribed input cannot be reliably matched to any supported welfare scheme, capability, or system command.
* **Trigger Examples (ASR Transcriptions)**:
  - *"What is the score of today's cricket match?"*
  - *"Sing a song for me"*
  - *"Abcd123 random noise"*
  - *"Unintelligible speech artifact"*
* **Required Entities**: None.
* **Expected Next Module**: ResponseGenerator (Triggers graceful voice clarification & options menu).

---

## 4. Engineering Architecture & Mechanisms

### 4.1 Hybrid Deterministic + Statistical Recognition Strategy

To achieve **100% offline operational guarantee** on Jetson Orin Nano without relying on cloud NLU services, IntentRecognizer uses a **two-phase hybrid inference pipeline**:

`
Transcribed ASR Text
        |
        v
[Phase 1: Pre-Processor & Normalizer]
  • Lowercase conversion
  • Strip speech stutters ("um", "ah")
  • Phonetic number normalization ("one oh four" -> "104")
        |
        v
[Phase 2: Compiled Regex & Keyword Pattern Engine]
  • Evaluates pattern rules in intents.json
  • Fast exact match (< 2 ms latency)
        |
        +---> If Match (Confidence >= 0.85) ----> Return IntentResult
        |
        +---> If No Deterministic Match
                    |
                    v
          [Phase 3: Offline TF-IDF Cosine Similarity Engine]
            • Computes sparse TF-IDF vector over local intent seed corpus
            • Evaluates cosine similarity against reference embeddings
                    |
                    v
          [Confidence Threshold Evaluator]
            • Score >= 0.60 -> Return Closest Intent (Medium Confidence)
            • Score <  0.60 -> Return UNKNOWN_QUERY (Low Confidence)
`

---

### 4.2 Confidence Handling & Scoring Framework

Confidence calculation is governed by the following scoring formula:

Confidence = 0.60 * S_match + 0.30 * S_entity + 0.10 * S_asr

Where:
- S_match: Match score (1.0 for Regex pattern match, 0.60-0.90 for TF-IDF cosine score, 0.0 for fallback).
- S_entity: Entity indicator score (1.0 if scheme keywords like "PDS", "Ayushman", "NREGA" are present).
- S_asr: ASR transcript confidence score passed from Vosk/Bhashini.

#### Decision Thresholding Matrix:

| Confidence Range | Level | System Behavior |
|:---|:---:|:---|
| **0.85 – 1.00** | **HIGH** | Direct Pipeline Execution (Fast Path < 15ms or VLM Path). |
| **0.60 – 0.84** | **MEDIUM** | Proceed with execution; append confirming context to TTS output (e.g. *"Checking Ayushman eligibility..."*). |
| **0.00 – 0.59** | **LOW** | Route to UNKNOWN_QUERY. Trigger voice options menu ("Did you mean Ration, Ayushman, or NREGA?"). |

---

### 4.3 Unknown Intent Handling & Recovery Strategy

When confidence < 0.60 or intent is UNKNOWN_QUERY, the system executes a **Graceful Degradation & Recovery Loop**:

1. **Camera Fallback Check**:
   - If a camera snapshot was captured during trigger press, automatically route query to OCR_DOCUMENT_ANALYSIS via Ollama VLM rather than failing.
2. **Clarification Speech Response**:
   - ResponseGenerator produces a targeted voice prompt:
     > *"I didn't quite understand. You can ask me about Ration Card, Ayushman Health Cover, or NREGA Job Card."*
3. **Display Options Rendering**:
   - Renders 3 quick selectable options on the 320x240 LCD display:
     - Top: 1: RATION (PDS)
     - Body: 2: AYUSHMAN  3: NREGA
4. **Diagnostic Logging**:
   - Appends unrecognized query text to /tmp/nomad_right_logs/unmatched_intents.jsonl for offline developer analysis and rule tuning.

---

### 4.4 Declarative Extensible Architecture for Adding New Schemes

To allow adding future welfare schemes (e.g., **PM-Kisan**, **PM Awas Yojana**, **Labor Welfare Card**) without modifying Python source code or recompiling binaries, the Intent Module uses a **Declarative Schema Contract**:

#### Schema Definition File (data/nomadright/rules/intents.json):

`json
{
  "version": "1.0.0",
  "schemes": [
    {
      "scheme_code": "PDS",
      "intents": [
        {
          "intent_name": "PDS_ELIGIBILITY",
          "patterns": [
            "\\b(ration|pds|bpl|aay|food grain|free rice|wheat quota)\\b.*\\b(eligible|qualification|get|apply)\\b",
            "\\bwho gets free ration\\b"
          ],
          "keywords": ["ration", "pds", "bpl", "aay", "food grain", "rice", "wheat"],
          "required_entities": ["scheme_name"],
          "next_module": "RulesEngine"
        },
        {
          "intent_name": "PDS_PORTABILITY",
          "patterns": [
            "\\b(one nation|onorc|portability|other state|different state|migrant)\\b.*\\b(ration|card|grain)\\b"
          ],
          "keywords": ["portability", "onorc", "other state", "migrant", "bihar card", "gujarat"],
          "required_entities": ["scheme_name"],
          "next_module": "RulesEngine"
        }
      ]
    },
    {
      "scheme_code": "PM-KISAN",
      "intents": [
        {
          "intent_name": "PM_KISAN_INSTALLMENT",
          "patterns": [
            "\\b(kisan|farmer|installment|6000|2000)\\b.*\\b(status|eligible|payment)\\b"
          ],
          "keywords": ["pm kisan", "kisan Samman", "farmer 2000", "installment"],
          "required_entities": ["scheme_name"],
          "next_module": "RulesEngine"
        }
      ]
    }
  ]
}
`

#### Zero-Code Extension Workflow for New Schemes:
1. Edit data/nomadright/rules/intents.json.
2. Add new scheme object (e.g., PM-KISAN) with pattern rules and keyword dictionaries.
3. Add scheme JSON rules file (e.g., data/nomadright/pmkisan.json).
4. On next boot, IntentRecognizer automatically ingests the updated JSON and exposes the new intent to the workflow pipeline — **zero python code modification required**.

---

*Engineering Specification Complete — Approved for Intent Recognition Module Implementation*
