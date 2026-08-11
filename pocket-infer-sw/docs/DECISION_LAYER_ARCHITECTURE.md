# NomadRight — Decision Layer Architecture Specification

**Role:** Principal AI Systems Architect & Senior Software Engineer  
**Date:** August 4, 2026  
**Target Platform:** Suno Sutra Edge AI Platform (NVIDIA Jetson Orin Nano 8GB)  
**Deployment Context:** 100% Offline Multilingual Citizen Welfare Assistant (VYOMA Challenge)  
**Document Version:** 1.0.0

---

## Executive Summary

This document defines the complete engineering architecture for the **Decision Layer** within the NomadRight offline AI assistant. 

Operating 100% offline at the edge on the NVIDIA Jetson Orin Nano, the Decision Layer sits directly between **Intent Recognition** (intent_recognizer.py) and **Speech Synthesis** (Bhashini/Piper TTS). It evaluates citizen intent, extracts structured entities, selects execution routes, queries local database knowledge bases, evaluates welfare rules, and formats multi-modal responses for voice, screen, and QR codes.

The Decision Layer consists strictly of **5 decoupled modules**:
1. **Entity Extraction** (entities.py)
2. **Query Router** (classifier.py)
3. **Rules Engine** (
ules.py)
4. **SQLite Access Layer** (database.py)
5. **Response Generator** (
esponse.py)

---

## 1. System Position & Architectural Boundaries

`
+----------------------------------------------------------------------------------------------------+
|                                    NOMADRIGHT CORE PIPELINE                                        |
|                                                                                                    |
|  [Microphone] -> [AudioRecorder] -> [Bhashini / Vosk ASR]                                          |
|                                            |                                                       |
|                                            v                                                       |
|                                   transcribed_text (str)                                           |
|                                            |                                                       |
|                                            v                                                       |
|                                 [Intent Recognition Module]                                        |
|                                            |                                                       |
|                                            v                                                       |
|                                 IntentResult (dataclass)                                           |
|                                            |                                                       |
|  ==========================================v====================================================   |
|  |                             DECISION LAYER BOUNDARY                                         |   |
|  |                                                                                             |   |
|  |   1. Entity Extraction -------> Extracts parameters (Scheme, Asset ID, Location)            |   |
|  |   2. Query Router -----------> Decides subsystem route (RULES, TRANSLATION, OCR, LLM)       |   |
|  |   3. SQLite Access Layer -----> Performs thread-safe local DB & FTS5 searches               |   |
|  |   4. Rules Engine ------------> Evaluates PDS, PM-JAY, MGNREGS statutory rules               |   |
|  |   5. Response Generator ------> Produces structured Voice, Display & QR outputs            |   |
|  |                                                                                             |   |
|  ==========================================v====================================================   |
|                                            |                                                       |
|                                            v                                                       |
|                              StructuredResponsePackage                                             |
|                                            |                                                       |
|                     +----------------------+----------------------+                                |
|                     |                                             |                                |
|                     v                                             v                                |
|        [Bhashini / Piper TTS Adapter]                    [Board HAL Display]                       |
|        PCM Audio Stream -> Speaker                       320x240 LCD Screen                        |
+----------------------------------------------------------------------------------------------------+
`

---

## 2. Comprehensive Module Specifications

---

### 2.1 Entity Extraction Module (entities.py)

* **Purpose**: Parses, normalizes, and extracts domain-specific structured parameters (e.g., Asset IDs, Scheme Codes, Document Types, Income/Age numbers, Location/States) from transcribed text.
* **Inputs**:
  - 	ranscribed_text: str — Speech transcript from ASR.
  - intent_result: IntentResult — Intent output from Intent Recognition module.
* **Outputs**:
  - EntityMap: dataclass
    - scheme_code: Optional[str] (e.g., "PDS", "PMJAY", "MGNREGS")
    - sset_id: Optional[str] (e.g., "PUMP-104")
    - state_name: Optional[str] (e.g., "BIHAR", "GUJARAT")
    - document_type: Optional[str] (e.g., "RATION_CARD", "AADHAAR")
    - 
umeric_values: Dict[str, float] (e.g., {"income": 120000.0})
    - is_complete: bool
    - 
aw_entities: Dict[str, str]
* **Internal Logic**:
  1. **Spoken Number Normalizer**: Converts verbal number phrases ("one zero four" -> "104", "fifty thousand" -> "50000") to numeric digits.
  2. **Regex Pattern Engine**: Matches hardware tags (PUMP-\d+, GEN-\d+), document keywords, and state names.
  3. **Gazetteer Dictionary Lookup**: Validates extracted terms against in-memory dictionary tables pre-loaded from SQLite on boot.
  4. **Fuzzy String Matching**: Uses Levenshtein distance (difflib) to recover from noisy ASR transcriptions.
* **Public Interfaces**:
  `python
  class IEntityExtractor(ABC):
      @abstractmethod
      def extract(self, transcribed_text: str, intent_result: IntentResult) -> EntityMap: pass
  `
* **Data Structures**: EntityMap, EntityType (Enum), EntityValue.
* **Error Handling**: Missing entities set to None; partial extraction populated with is_complete = False.
* **Offline Considerations**: 100% offline. Pre-loads gazetteers into memory at system startup.
* **Performance Considerations**: Sub-3 ms execution time on Jetson ARM CPU cores.
* **Future Extensibility**: Extensible to ingest OCR tokens from camera frames as additional entity inputs.

---

### 2.2 Query Router Module (classifier.py)

* **Purpose**: Evaluates Intent, Extracted Entities, Camera frame presence, and System State to select the lowest-latency, most resource-efficient processing subsystem.
* **Inputs**:
  - intent_result: IntentResult
  - entity_map: EntityMap
  - has_camera_frame: bool
  - system_state: SystemState (VRAM availability, thermal throttling status)
* **Outputs**:
  - RoutingDecision: dataclass
    - subsystem: SubsystemType (Enum: RULES_ENGINE, TRANSLATION, OCR_PIPELINE, LOCAL_LLM)
    - 
equires_db: bool
    - 
equires_vlm: bool
    - priority: int (1 = Fast Path < 15ms, 2 = Generative Path ~1-3s)
    - execution_plan: Dict[str, Any]
* **Internal Logic**:
  - Multi-Criteria Decision Matrix:
    1. **RULES_ENGINE Path**: Intent is a welfare scheme query (PDS_*, PMJAY_*, MGNREGS_*) + Scheme Entity present -> Direct SQLite & Rules evaluation (< 15 ms).
    2. **TRANSLATION Path**: Intent is TRANSLATION_REQUEST -> Route to offline Bhashini NMT service (localhost:11400/nmt).
    3. **OCR_PIPELINE Path**: Intent is OCR_DOCUMENT_ANALYSIS OR (has_camera_frame == True and no scheme entity) -> Route camera frame to Ollama VLM (qwen3-vl:2b / ministral-3:3B).
    4. **LOCAL_LLM Path**: Intent is GENERAL_EXPLANATION or complex query -> Route text to Ollama LLM.
* **Public Interfaces**:
  `python
  class IQueryRouter(ABC):
      @abstractmethod
      def route(self, intent_result: IntentResult, entity_map: EntityMap, has_camera_frame: bool, system_state: Optional[SystemState] = None) -> RoutingDecision: pass
  `
* **Data Structures**: RoutingDecision, SubsystemType (Enum), SystemState.
* **Error Handling**: Defaults to RULES_ENGINE generic guidance or LOCAL_LLM fallback on ambiguous inputs.
* **Offline Considerations**: Monitors local GPU VRAM pressure to prevent OOM kernel kills.
* **Performance Considerations**: Routing decision matrix evaluates in < 1 ms.
* **Future Extensibility**: Supports dynamic battery / thermal throttling route overrides.

---

### 2.3 Rules Engine Module (
ules.py)

* **Purpose**: Evaluates offline business logic, statutory eligibility rules, entitlement calculations, and procedural requirements for **PDS**, **PM-JAY**, and **MGNREGS** schemes.
* **Inputs**:
  - intent_result: IntentResult
  - entity_map: EntityMap
  - db_context: Optional[Dict[str, Any]] — Data fetched from SQLite Layer.
* **Outputs**:
  - RuleEvaluationResult: dataclass
    - passed: bool
    - status_code: RuleStatusCode (Enum: OK, ELIGIBLE, INELIGIBLE, PORTABILITY_ALLOWED, WARNING_THRESHOLD_EXCEEDED, PROCEDURE_BLOCKED)
    - 	riggered_rule_id: str
    - summary_message: str
    - entitlement_details: Dict[str, Any]
    - 
equired_documents: List[str]
    - 
ext_steps: str
* **Internal Logic**:
  - Declarative Rule Evaluation Engine loading JSON rule sets (pds.json, pmjay.json, mgnregs.json):
    - **PDS Rules**: Evaluates NFSA grain quotas (35 kg/month for BPL/AAY), prices (Rice ₹3/kg, Wheat ₹2/kg), and ONORC inter-state portability clauses.
    - **PM-JAY Rules**: Evaluates ₹5,00,000 annual family floater health cover, cashless hospitalization eligibility, and pre-existing condition day-one coverage.
    - **MGNREGS Rules**: Evaluates 100 days guaranteed rural manual labor, 15-day application-to-work allotment limit, and delayed wage payment compensation clauses.
* **Public Interfaces**:
  `python
  class IRulesEngine(ABC):
      @abstractmethod
      def evaluate(self, intent_result: IntentResult, entity_map: EntityMap, db_context: Optional[Dict[str, Any]] = None) -> RuleEvaluationResult: pass
  `
* **Data Structures**: RuleEvaluationResult, RuleStatusCode (Enum), SchemeRuleSet.
* **Error Handling**: Fails safe (passed = False, status_code = PROCEDURE_BLOCKED) if rule definitions are missing.
* **Offline Considerations**: Loads rule sets from pre-baked local files in data/nomadright/.
* **Performance Considerations**: Evaluates complex rule trees in < 4 ms on ARM CPU.
* **Future Extensibility**: Declarative JSON rule files allow adding new schemes (PM-Kisan, PM Awas) without modifying Python code.

---

### 2.4 SQLite Access Layer Module (database.py)

* **Purpose**: Provides thread-safe, high-performance, WAL-mode embedded SQLite access to asset registries, inspection logs, scheme rule tables, and offline technical documentation.
* **Inputs**: Query parameters, asset IDs, scheme codes, FTS search keywords.
* **Outputs**: Strongly-typed Data Transfer Objects (AssetDTO, SchemeRuleDTO, InspectionLogDTO).
* **Internal Logic & Query Strategy**:
  1. **WAL-Mode Thread Safety**: Connects to data/nomadright/nomadright.db using Write-Ahead Logging (PRAGMA journal_mode=WAL;) for concurrent read/write access.
  2. **Connection Pooling**: Uses thread-local connection pooling with 5-second timeout guards.
  3. **Direct Primary Key Queries**: Fast indexed queries for exact Asset ID or Scheme Code lookups (SELECT * FROM assets WHERE id = ?).
  4. **FTS5 Full-Text Search**: Full-text indexed search queries over legal citations (citations.md) and technical manuals.
  5. **Audit Logging**: Inserts structured decision audit records into inspection_logs.
* **Public Interfaces**:
  `python
  class IDatabaseAccess(ABC):
      @abstractmethod
      def get_asset_by_id(self, asset_id: str) -> Optional[AssetDTO]: pass
      
      @abstractmethod
      def get_scheme_data(self, scheme_code: str) -> Optional[SchemeRuleDTO]: pass
      
      @abstractmethod
      def search_knowledge_base(self, query_text: str) -> List[Dict[str, Any]]: pass
      
      @abstractmethod
      def insert_inspection_log(self, log_dto: InspectionLogDTO) -> bool: pass
  `
* **Data Structures**: AssetDTO, SchemeRuleDTO, InspectionLogDTO.
* **Error Handling**: Handles database lock contention with exponential backoff retries; auto-executes schema DDL if missing.
* **Offline Considerations**: 100% embedded SQLite storage; zero network database calls.
* **Performance Considerations**: Single-row PK queries < 1 ms; FTS5 text search < 8 ms.
* **Future Extensibility**: Schema version tracking table (schema_version) enables dynamic migrations.

---

### 2.5 Response Generator Module (
esponse.py)

* **Purpose**: Formats and synthesizes multi-modal response packages tailored for **Voice output** (Bhashini/Piper TTS), **LCD Display output** (320x240 screen), and **QR Payload generation** (offline verification).
* **Inputs**:
  - 
outing_decision: RoutingDecision
  - 
ule_result: Optional[RuleEvaluationResult]
  - db_context: Optional[Dict[str, Any]]
  - lm_response: Optional[str]
* **Outputs**:
  - StructuredResponsePackage: dataclass
    - oice_text: str — Clear speech string optimized for TTS pronunciation.
    - display_top: str — Header string (max 30 chars).
    - display_bottom: str — Body string (max 60 chars).
    - qr_payload: Optional[Dict[str, Any]] — Compact JSON payload for QR code generation.
    - severity: SeverityLevel (Enum: INFO, WARNING, CRITICAL)
* **Internal Logic**:
  1. **Voice Output Synthesis**: Formats clear, natural spoken sentences. Strips markdown tags, expands abbreviations ("PDS" -> "Public Distribution System", "INR" -> "rupees", "BPL" -> "Below Poverty Line") for smooth TTS rendering.
  2. **Display Output Formatting**: Truncates strings to 320x240 LCD screen limits (Header: 30 chars, Body: 60 chars).
  3. **QR Payload Synthesis**: Generates a compact JSON object containing log_id, 	imestamp, intent, scheme_code, status_code, and SHA-256 integrity hash for scanning via mobile devices.
* **Public Interfaces**:
  `python
  class IResponseGenerator(ABC):
      @abstractmethod
      def generate(self, routing_decision: RoutingDecision, rule_result: Optional[RuleEvaluationResult] = None, db_context: Optional[Dict[str, Any]] = None, vlm_response: Optional[str] = None) -> StructuredResponsePackage: pass
  `
* **Data Structures**: StructuredResponsePackage, QRPayload, SeverityLevel (Enum).
* **Error Handling**: Generates clear fallback speech prompts if all input contexts are empty.
* **Offline Considerations**: Local template formatting; zero external API dependencies.
* **Performance Considerations**: String synthesis and formatting completes in < 2 ms.
* **Future Extensibility**: Multi-locale language template rendering (Hindi, Tamil, Kannada, Telugu).

---

## 3. System Diagrams

### 3.1 System Architecture Diagram

`
+--------------------------------------------------------------------------------------------------+
|                                  SYSTEM ARCHITECTURE DIAGRAM                                     |
|                                                                                                  |
|  [Vosk / Bhashini ASR]                                                                           |
|          |                                                                                       |
|          v                                                                                       |
|  [IntentRecognizer] ----> IntentResult                                                           |
|                               |                                                                  |
|  =============================v================================================================  |
|  |                            DECISION LAYER (nomad_right package)                            |  |
|  |                                                                                            |  |
|  |   +-------------------+        +-------------------+        +--------------------------+   |  |
|  |   |  EntityExtractor  | ---->  |   QueryRouter     | ---->  |    SQLiteAccessLayer     |   |  |
|  |   |   (entities.py)   |        |  (classifier.py)  |        |      (database.py)        |   |  |
|  |   +-------------------+        +-------------------+        +--------------------------+   |  |
|  |                                          |                               |                 |  |
|  |                                          v                               v                 |  |
|  |                                +-------------------+        +--------------------------+   |  |
|  |                                |   RulesEngine     | <----> |  data/nomadright/*.json  |   |  |
|  |                                |    (rules.py)     |        |  (PDS, PMJAY, MGNREGS)   |   |  |
|  |                                +-------------------+        +--------------------------+   |  |
|  |                                          |                                                 |  |
|  |                                          v                                                 |  |
|  |                                +-------------------+                                       |  |
|  |                                | ResponseGenerator |                                       |  |
|  |                                |   (response.py)   |                                       |  |
|  |                                +-------------------+                                       |  |
|  ===========================================|==================================================  |
|                                             v                                                    |
|                                 StructuredResponsePackage                                        |
|                                             |                                                    |
|                    +------------------------+------------------------+                           |
|                    |                        |                        |                           |
|                    v                        v                        v                           |
|         [Bhashini/Piper TTS]        [Board LCD Display]       [QR Code Generator]                    |
|          PCM Speech Output           320x240 Screen Output       Future Verification                 |
+--------------------------------------------------------------------------------------------------+
`

---

### 3.2 Sequence Diagram

`mermaid
sequenceDiagram
    autonumber
    participant ASR as Vosk/Bhashini ASR
    participant App as NomadRightApplication
    participant EE as EntityExtractor
    participant QR as QueryRouter
    participant DB as SQLiteAccessLayer
    participant RE as RulesEngine
    participant RG as ResponseGenerator
    participant TTS as Bhashini/Piper TTS
    participant Board as Board Display

    ASR->>App: transcribed_text: "Am I eligible for PDS ration card?"
    App->>EE: extract("Am I eligible for PDS ration card?", IntentResult(PDS_ELIGIBILITY))
    EE-->>App: EntityMap(scheme_code="PDS", is_complete=True)
    
    App->>QR: route(IntentResult, EntityMap, has_camera=False)
    QR-->>App: RoutingDecision(Subsystem=RULES_ENGINE, requires_db=True)
    
    App->>DB: get_scheme_data("PDS")
    DB-->>App: SchemeRuleDTO(code="PDS", rules_file="pds.json")
    
    App->>RE: evaluate(IntentResult, EntityMap, DB_context)
    RE-->>App: RuleEvaluationResult(passed=True, status="ELIGIBLE", msg="35 kg free grain quota under NFSA")
    
    App->>RG: generate(RoutingDecision, RuleResult, DB_context)
    RG-->>App: StructuredResponsePackage(voice_text="You are eligible for 35 kg food grains monthly under PDS.", top="PDS: ELIGIBLE", bottom="35 kg Grain Quota (Free)", qr_data={...})
    
    par Multi-Modal Output Playout
        App->>Board: top_text("PDS: ELIGIBLE")
        App->>Board: bottom_text("35 kg Grain Quota (Free)")
        App->>TTS: start_playback("You are eligible for 35 kg food grains monthly under PDS.")
    end
`

---

### 3.3 Class Diagram

`mermaid
classDiagram
    class IEntityExtractor {
        <<Interface>>
        +extract(transcribed_text, intent_result) EntityMap
    }
    class EntityExtractor {
        -db_access: IDatabaseAccess
        -number_normalizer: Any
        +extract(transcribed_text, intent_result) EntityMap
    }

    class IQueryRouter {
        <<Interface>>
        +route(intent_result, entity_map, has_camera_frame, system_state) RoutingDecision
    }
    class QueryRouter {
        +route(intent_result, entity_map, has_camera_frame, system_state) RoutingDecision
    }

    class IRulesEngine {
        <<Interface>>
        +evaluate(intent_result, entity_map, db_context) RuleEvaluationResult
    }
    class RulesEngine {
        -rule_sets: Dict
        +evaluate(intent_result, entity_map, db_context) RuleEvaluationResult
    }

    class IDatabaseAccess {
        <<Interface>>
        +get_asset_by_id(asset_id) AssetDTO
        +get_scheme_data(scheme_code) SchemeRuleDTO
        +search_knowledge_base(query_text) List
        +insert_inspection_log(log_dto) bool
    }
    class SQLiteAccessLayer {
        -db_path: str
        +get_asset_by_id(asset_id) AssetDTO
        +get_scheme_data(scheme_code) SchemeRuleDTO
        +search_knowledge_base(query_text) List
        +insert_inspection_log(log_dto) bool
    }

    class IResponseGenerator {
        <<Interface>>
        +generate(routing_decision, rule_result, db_context, vlm_response) StructuredResponsePackage
    }
    class ResponseGenerator {
        +generate(routing_decision, rule_result, db_context, vlm_response) StructuredResponsePackage
    }

    class WorkflowController {
        -entity_extractor: IEntityExtractor
        -query_router: IQueryRouter
        -rules_engine: IRulesEngine
        -db_access: IDatabaseAccess
        -response_generator: IResponseGenerator
        +process(transcribed_text, camera_image) StructuredResponsePackage
    }

    IEntityExtractor <|.. EntityExtractor
    IQueryRouter <|.. QueryRouter
    IRulesEngine <|.. RulesEngine
    IDatabaseAccess <|.. SQLiteAccessLayer
    IResponseGenerator <|.. ResponseGenerator

    WorkflowController --> IEntityExtractor
    WorkflowController --> IQueryRouter
    WorkflowController --> IRulesEngine
    WorkflowController --> IDatabaseAccess
    WorkflowController --> IResponseGenerator
    EntityExtractor --> IDatabaseAccess
`

---

### 3.4 Data Flow Diagram

`
+---------------------------------------------------------------------------------------------------+
|                                      DATA FLOW DIAGRAM                                            |
|                                                                                                   |
|  IntentResult + ASR Text                                                                          |
|       |                                                                                           |
|       v                                                                                           |
|  [EntityExtractor] ------------------> EntityMap                                                  |
|       |                                   |                                                       |
|       |                                   v                                                       |
|       +-------------------------> [QueryRouter]                                                   |
|                                           |                                                       |
|                                           v                                                       |
|                                    RoutingDecision                                                |
|                                           |                                                       |
|                  +------------------------+------------------------+                              |
|                  | DB / RULES                              | VLM / OCR                            |
|                  v                                         v                                      |
|       [SQLiteAccessLayer]                          [Ollama VLM Adapter]                           |
|       Fetches DTO Context                          Generates Scene Text                           |
|                  |                                         |                                      |
|                  v                                         |                                      |
|          [RulesEngine]                                     |                                      |
|       Evaluates PDS/PMJAY/MGNREGS                          |                                      |
|                  |                                         |                                      |
|                  +------------------------+----------------+                                      |
|                                           |                                                       |
|                                           v                                                       |
|                                  [ResponseGenerator]                                              |
|                                           |                                                       |
|                                           v                                                       |
|                               StructuredResponsePackage                                           |
|                                           |                                                       |
|                 +-------------------------+-------------------------+                             |
|                 | voice_text              | display_top/bottom      | qr_payload                  |
|                 v                         v                         v                             |
|        [Bhashini/Piper TTS]      [Board LCD Display]       [QR Generator]                         |
+---------------------------------------------------------------------------------------------------+
`

---

### 3.5 State Machine Diagram

`mermaid
stateDiagram-v2
    [*] --> IdleReady : System Boot / Ready State
    
    IdleReady --> ReceivingIntent : ASR Transcription & Intent Recognition Complete
    
    state DecisionLayerExecution {
        [*] --> ExtractingEntities : EntityExtractor.extract()
        ExtractingEntities --> RoutingQuery : QueryRouter.route()
        
        RoutingQuery --> EvaluatingRules : Subsystem == RULES_ENGINE
        RoutingQuery --> QueryingLLM : Subsystem == LOCAL_LLM
        RoutingQuery --> ProcessingOCR : Subsystem == OCR_PIPELINE
        RoutingQuery --> RunningNMT : Subsystem == TRANSLATION
        
        EvaluatingRules --> QueryingDB : Fetch Scheme Specs & DTOs
        QueryingDB --> EvaluatingRules : Rule Logic Execution
        
        EvaluatingRules --> FormattingResponse : RuleEvaluationResult Produced
        QueryingLLM --> FormattingResponse : VLM Text Produced
        ProcessingOCR --> FormattingResponse : OCR Text Produced
        RunningNMT --> FormattingResponse : NMT Text Produced
        
        FormattingResponse --> GeneratingOutputs : Synthesize Voice, Screen & QR Package
    }
    
    DecisionLayerExecution --> OutputPlayout : ResponsePackage Ready
    
    state OutputPlayout {
        [*] --> RenderScreen : Board.top_text() & bottom_text()
        RenderScreen --> PlayVoice : TTS.start_playback()
        PlayVoice --> LogAudit : SQLite.insert_inspection_log()
    }
    
    OutputPlayout --> IdleReady : Interaction Complete
`

---

### 3.6 Repository Package Layout

The Decision Layer code lives inside python/pocketinfer/applications/nomad_right/ and accesses pre-baked rules in data/nomadright/:

`	ext
suno-sutra-sw-main/
├── docs/
│   ├── DECISION_LAYER_ARCHITECTURE.md     <-- THIS SPECIFICATION DOCUMENT
│   ├── INTENT_RECOGNITION_DESIGN.md       <-- Intent Recognition Spec
│   ├── PROJECT_HEALTH_CHECK.md            <-- Technical Audit Report
│   └── NOMADRIGHT_ARCHITECTURE.md         <-- System Architecture Spec
│
├── data/
│   └── nomadright/
│       ├── nomadright.db                  <-- WAL-Mode SQLite Database
│       ├── pds.json                       <-- PDS statutory rules
│       ├── pmjay.json                     <-- PM-JAY health cover rules
│       └── mgnregs.json                   <-- MGNREGS wage & work rules
│
├── python/
│   └── pocketinfer/
│       └── applications/
│           └── nomad_right/
│               ├── __init__.py            <-- Exports NomadRightApplication
│               ├── app.py                 <-- Application entry point wrapper
│               ├── workflow.py            <-- WorkflowController orchestrator
│               ├── intent.py              <-- Intent Recognition module
│               ├── entities.py            <-- MODULE 1: Entity Extraction
│               ├── classifier.py          <-- MODULE 2: Query Router
│               ├── rules.py               <-- MODULE 3: Rules Engine (PDS/PMJAY/MGNREGS)
│               ├── database.py            <-- MODULE 4: SQLite Access Layer
│               └── response.py            <-- MODULE 5: Response Generator (Voice/Display/QR)
`

---

*Decision Layer Architectural Specification Complete — Approved for NomadRight System Implementation*
