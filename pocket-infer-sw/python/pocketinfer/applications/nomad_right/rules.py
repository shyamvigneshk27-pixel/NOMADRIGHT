"""
NomadRight Rules Engine Module

Evaluates statutory welfare eligibility and portability rules for PDS, PM-JAY,
e-Shram+OSH Code, and BOCW schemes. All rule logic is 100% offline and data-driven
from the SQLite KB.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List

from pocketinfer.applications.nomad_right.config import NomadRightConfig
from pocketinfer.applications.nomad_right.intent import IntentResult, IntentType
from pocketinfer.applications.nomad_right.entities import EntityMap
from pocketinfer.applications.nomad_right.database import PortabilityRecord

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Result types
# ──────────────────────────────────────────────────────────────────────────────

class RuleStatusCode(Enum):
    """Status codes emitted by the Rules Engine."""
    OK = "OK"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    PORTABILITY_ALLOWED = "PORTABILITY_ALLOWED"
    MISSING_PREREQ = "MISSING_PREREQ"
    UNKNOWN = "UNKNOWN"


@dataclass
class RuleEvaluationResult:
    """Dataclass storing the output of one rule evaluation pass."""
    passed: bool
    status_code: RuleStatusCode
    summary_message: str                                      # Short (≤ 2 sentences) for TTS
    detail_message: str = ""                                  # Longer text for LCD / logging
    triggered_rule_id: Optional[str] = None
    required_documents: List[str] = field(default_factory=list)
    next_steps: str = ""
    helpline: Optional[str] = None
    scheme_code: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Abstract interface
# ──────────────────────────────────────────────────────────────────────────────

class IRulesEngine(ABC):
    """Abstract interface for offline welfare Rules Evaluation engines."""

    @abstractmethod
    def evaluate(
        self,
        intent_result: IntentResult,
        entity_map: EntityMap,
        kb_record: Optional[PortabilityRecord] = None,
    ) -> RuleEvaluationResult:
        """Evaluates rules given intent, entities, and knowledge base record."""
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Concrete implementation
# ──────────────────────────────────────────────────────────────────────────────

class RulesEngine(IRulesEngine):
    """
    Offline, declarative Rules Engine for PDS, PM-JAY, e-Shram, and BOCW schemes.

    Rule evaluation is data-driven: the engine reads eligibility criteria,
    documents, and next-steps from the PortabilityRecord fetched by the
    SQLiteAccessLayer, rather than encoding them as hardcoded strings.

    Full rule support implemented for PDS (ONORC), PM-JAY (Ayushman Bharat),
    e-Shram + OSH Code 2020, and BOCW (construction workers) schemes.
    """

    def __init__(self, config: Optional[NomadRightConfig] = None):
        self.config = config or NomadRightConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    # ── Multi-scheme overview (first-time / unsure migrant workers) ────────

    def _evaluate_welfare_overview(
        self,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """
        Broad "what all can I get as a migrant worker?" walkthrough for a
        first-time or unsure worker who hasn't named a specific scheme.
        Deliberately scheme_code="" (not a real scheme) so this answer is
        never inherited as conversation context by a later follow-up.
        """
        summary = (
            "First register on e-Shram — you get a UAN card valid across "
            "India, with 2 lakh rupees accident insurance right away. That "
            "also makes you eligible for ration card portability, an "
            "Ayushman health card, and BOCW welfare if you do construction work."
        )
        detail = (
            "e-Shram registration is free and takes a few minutes at any "
            "Common Service Centre with your Aadhaar card. Once registered, "
            "ask about ration card portability for food grains, Ayushman "
            "Bharat for free hospital treatment, or BOCW registration if "
            "you work in construction."
        )
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.OK,
            summary_message=summary,
            detail_message=detail,
            triggered_rule_id="WELFARE-OVERVIEW-001",
            required_documents=["Aadhaar Card"],
            next_steps="Do you have an Aadhaar card? Visit the nearest Common Service Centre to register on e-Shram first.",
            helpline="14434",
            scheme_code="",
        )

    # ── PDS / ONORC ───────────────────────────────────────────────────────

    def _evaluate_pds(
        self,
        intent_type: IntentType,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """
        Evaluates PDS (ONORC) portability and eligibility rules.

        Key rules (sourced from pds.json / nomadright_kb.db):
          PDS-PORT-001  Portability allowed under ONORC across all 36 States/UTs.
          PDS-PORT-002  Aadhaar must be seeded with ration card (prerequisite).
          PDS-ELIG-001  Applicant must be NFSA beneficiary (AAY or PHH).
        """
        state_mention = entity_map.state_name or "any state"

        # Pull live data from KB record when available
        docs: List[str] = kb.required_documents if kb else [
            "Ration Card", "Aadhaar Card"
        ]
        steps: List[str] = kb.application_steps_offline if kb else [
            "Ensure Aadhaar is linked with ration card.",
            "Visit any ePoS-enabled Fair Price Shop.",
            "Authenticate with Aadhaar biometrics.",
            "Collect entitled food grains.",
        ]
        helpline = kb.helpline if kb else "14445"

        # ── Rule: PDS portability (ONORC inter-state) ──────────────────────
        if intent_type == IntentType.PDS_PORTABILITY:
            # Prerequisite check: Aadhaar must be seeded
            prereq_note = (
                "Important: Your Aadhaar number must be linked (seeded) with "
                "your ration card to use ONORC portability."
            )
            summary = (
                f"Yes. Under One Nation One Ration Card (ONORC), you can "
                f"collect your entitled food grains from any ePoS-enabled "
                f"Fair Price Shop in {state_mention} or anywhere in India. "
                f"Your Aadhaar must be linked to your ration card."
            )
            detail = (
                f"ONORC is implemented across all 36 States/UTs. "
                f"Since January 2024, food grains are provided FREE under PMGKAY. "
                f"{prereq_note}"
            )
            next_step = steps[0] if steps else "Visit the nearest Fair Price Shop."
            return RuleEvaluationResult(
                passed=True,
                status_code=RuleStatusCode.PORTABILITY_ALLOWED,
                summary_message=summary,
                detail_message=detail,
                triggered_rule_id="PDS-PORT-001",
                required_documents=docs,
                next_steps=next_step,
                helpline=helpline,
                scheme_code="PDS",
            )

        # ── Rule: PDS documents ─────────────────────────────────────────────
        # secneraio.txt Scenario 1 follow-up: "Document kana lagiba?" -
        # answer is just Aadhaar, no new card needed - not eligibility text.
        if intent_type == IntentType.REQUIRED_DOCUMENTS:
            return RuleEvaluationResult(
                passed=True,
                status_code=RuleStatusCode.OK,
                summary_message=(
                    "You only need your Aadhaar card. There is no need to make "
                    "a new ration card — just make sure your Aadhaar is linked "
                    "to your existing one."
                ),
                detail_message=(
                    "Your existing ration card works anywhere in India under "
                    "ONORC as long as your Aadhaar number is seeded to it. No "
                    "new registration or card is required in the new state."
                ),
                triggered_rule_id="PDS-DOC-001",
                required_documents=docs,
                next_steps="Visit any ePoS-enabled Fair Price Shop with your Aadhaar card.",
                helpline=helpline,
                scheme_code="PDS",
            )

        # ── Rule: PDS eligibility (general) ────────────────────────────────
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.ELIGIBLE,
            summary_message=(
                "BPL and AAY ration cardholders are eligible for subsidised "
                "food grains. Since January 2024, all NFSA beneficiaries receive "
                "food grains free of cost under PM Garib Kalyan Ann Yojana."
            ),
            detail_message=(
                "AAY households: 35 kg/month. PHH individuals: 5 kg/person/month. "
                "NFSA 2013 governs eligibility."
            ),
            triggered_rule_id="PDS-ELIG-001",
            required_documents=docs,
            next_steps="Contact your local Fair Price Shop dealer.",
            helpline=helpline,
            scheme_code="PDS",
        )

    # ── PM-JAY (Ayushman Bharat) ───────────────────────────────────────────

    def _evaluate_pmjay(
        self,
        intent_type: IntentType,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """
        Evaluates PM-JAY (Ayushman Bharat) rules.

        Supports:
          PMJAY_PORTABILITY : Inter-state cashless hospitalization portability across empanelled hospitals.
          PMJAY_DOCUMENTS   : Required documents for Ayushman card generation & hospital admission.
          PMJAY_BENEFITS    : Coverage limit (5 Lakhs/family/year), 1900+ procedures, pre-existing diseases.
          PMJAY_ELIGIBILITY : SECC 2011 criteria & entitlement status.
        """
        location = entity_map.state_name or "any location"

        docs: List[str] = kb.required_documents if kb else [
            "Aadhaar Card", "Ration Card", "Ayushman Golden Card"
        ]
        helpline = kb.helpline if kb else "14555"

        # ── Rule: PM-JAY Portability ───────────────────────────────────────
        if intent_type == IntentType.PMJAY_PORTABILITY:
            summary = (
                f"Yes. Ayushman Bharat PM-JAY is nationwide portable. You can receive "
                f"cashless treatment at any empanelled public or private hospital in {location} "
                f"or anywhere in India. All states, including West Bengal since July 2026, "
                f"are now covered."
            )
            detail = (
                f"PM-JAY nationwide portability enables eligible beneficiaries to access "
                f"cashless secondary and tertiary care hospitalization across all empanelled hospitals. "
                f"Approach the Ayushman Mitra desk at the hospital with your Aadhaar Card."
            )
            return RuleEvaluationResult(
                passed=True,
                status_code=RuleStatusCode.PORTABILITY_ALLOWED,
                summary_message=summary,
                detail_message=detail,
                triggered_rule_id="PMJAY-PORT-001",
                required_documents=docs,
                next_steps="Approach the Pradhan Mantri Arogya Mitra (PMAM) desk at the empanelled hospital.",
                helpline=helpline,
                scheme_code="PMJAY",
            )

        # ── Rule: PM-JAY Documents ─────────────────────────────────────────
        if intent_type == IntentType.PMJAY_DOCUMENTS or intent_type == IntentType.REQUIRED_DOCUMENTS:
            summary = (
                "To avail PM-JAY benefits, you need an Aadhaar Card for identity verification "
                "and an Ayushman Golden Card or Ration Card linked with your family record."
            )
            detail = (
                "Required documents: Aadhaar Card for biometric authentication, Ration Card or "
                "SECC family proof, and Ayushman e-Card."
            )
            return RuleEvaluationResult(
                passed=True,
                status_code=RuleStatusCode.OK,
                summary_message=summary,
                detail_message=detail,
                triggered_rule_id="PMJAY-DOC-001",
                required_documents=docs,
                next_steps="Carry your Aadhaar and Ration Card to the nearest empanelled hospital or Common Service Centre (CSC).",
                helpline=helpline,
                scheme_code="PMJAY",
            )

        # ── Rule: PM-JAY Benefits ──────────────────────────────────────────
        if intent_type in (IntentType.PMJAY_BENEFITS, IntentType.COST_INQUIRY):
            summary = (
                "Ayushman Bharat PM-JAY provides free cashless health cover up to 5 lakh rupees "
                "per family per year for hospitalization covering over 1,900 procedures."
            )
            detail = (
                "Key benefits: 5 Lakh rupees annual cashless cover per family. Covers secondary and "
                "tertiary care hospitalization, pre-existing conditions from day one, and 3 days pre "
                "and 15 days post-hospitalization."
            )
            return RuleEvaluationResult(
                passed=True,
                status_code=RuleStatusCode.OK,
                summary_message=summary,
                detail_message=detail,
                triggered_rule_id="PMJAY-BENEFIT-001",
                required_documents=docs,
                next_steps="Show your Ayushman Golden Card at any empanelled hospital for cashless admission.",
                helpline=helpline,
                scheme_code="PMJAY",
            )

        # ── Rule: PM-JAY Eligibility ───────────────────────────────────────
        summary = (
            "Families identified under Socio-Economic Caste Census (SECC 2011) and active BPL "
            "cardholders are eligible for 5 lakh rupees annual health cover under PM-JAY."
        )
        detail = (
            "Eligibility is determined by SECC 2011 rural deprivation criteria and urban occupational "
            "categories. No enrolment fee or premium is required."
        )
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.ELIGIBLE,
            summary_message=summary,
            detail_message=detail,
            triggered_rule_id="PMJAY-ELIG-001",
            required_documents=docs,
            next_steps="Check your name on the PM-JAY portal (pmjay.gov.in) or call toll-free helpline 14555.",
            helpline=helpline,
            scheme_code="PMJAY",
        )

    # ── e-Shram + OSH Code 2020 rules ────────────────────────────────────────

    def _evaluate_eshram(
        self,
        intent_type: IntentType,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """Fan-out dispatcher for all e-Shram / OSH Code intents."""
        dispatch = {
            IntentType.ESHRAM_REGISTRATION: self._eshram_registration,
            IntentType.ESHRAM_DOCUMENTS:    self._eshram_documents,
            IntentType.REQUIRED_DOCUMENTS:  self._eshram_documents,
            IntentType.ESHRAM_WAGE_RIGHTS:  self._eshram_wage_rights,
            IntentType.ESHRAM_BENEFITS:     self._eshram_benefits,
        }
        handler = dispatch.get(intent_type)
        if handler:
            return handler(entity_map, kb)
        return self._eshram_benefits(entity_map, kb)

    # -- KB FAQ Helper -------------------------------------------------------

    def _kb_faq_text(self, kb: Optional[PortabilityRecord]) -> Optional[str]:
        """Returns the first FAQ answer from the KB record, or None."""
        if kb and kb.faq_matches:
            return kb.faq_matches[0].get("answer") or kb.faq_matches[0].get("a")
        return None

    def _eshram_registration(
        self,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """How to register on the e-Shram portal."""
        docs: List[str] = kb.required_documents if kb else [
            "Aadhaar Card", "Aadhaar-linked Mobile Number", "Bank Account Details",
        ]
        helpline = kb.helpline if kb else "14434"
        detail = (
            self._kb_faq_text(kb)
            or (
                "Visit eshram.gov.in and enter your Aadhaar-linked mobile number, "
                "verify the OTP, and fill in your name, occupation, and bank "
                "details. A 12-digit UAN and e-Shram card are generated instantly. "
                "If you don't have internet, any Common Service Centre (CSC) will "
                "register you free of cost."
            )
        )
        summary = (
            "e-Shram registration is completely free. Visit eshram.gov.in with "
            "your Aadhaar-linked mobile number, or visit any Common Service "
            "Centre with your Aadhaar card and bank passbook."
        )
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.OK,
            summary_message=summary,
            detail_message=detail,
            triggered_rule_id="ESHRAM-REG-001",
            required_documents=docs,
            next_steps="Visit eshram.gov.in or your nearest Common Service Centre (CSC) with your Aadhaar card.",
            helpline=helpline,
            scheme_code="ESHRAM",
        )

    def _eshram_documents(
        self,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """Documents required for e-Shram registration."""
        docs: List[str] = kb.required_documents if kb else [
            "Aadhaar Card", "Aadhaar-linked Mobile Number", "Bank Account Details (IFSC + Account Number)",
        ]
        helpline = kb.helpline if kb else "14434"
        summary = (
            "You need your Aadhaar card, an Aadhaar-linked mobile number for "
            "OTP verification, and your bank account details. No fee is charged."
        )
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.OK,
            summary_message=summary,
            detail_message=summary,
            triggered_rule_id="ESHRAM-DOC-001",
            required_documents=docs,
            next_steps="Carry your Aadhaar card and bank passbook to any Common Service Centre if registering offline.",
            helpline=helpline,
            scheme_code="ESHRAM",
        )

    def _eshram_wage_rights(
        self,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """
        OSH Code 2020 interstate migrant worker rights (wages, medical, transport).

        NOTE: deliberately does NOT fall back to _kb_faq_text(kb) here - the KB
        FAQ table for e-Shram is ordered by id, not relevance, so "the first
        FAQ" is "What is e-Shram?", not the wage-theft answer. The specific
        facts below (14-day payment window, Form 11, licence suspension) are
        sourced from eshram_osh.json's worker_rights_under_osh_code section.
        """
        state = entity_map.state_name or "your destination state's"
        summary = (
            "Interstate migrant workers must be paid within 14 days of the "
            f"wage period ending, under OSH Code 2020. If your contractor "
            f"hasn't paid you, you can complain at the {state} Labour "
            "Department. Do you have your e-Shram UAN?"
        )
        detail = (
            "Take your e-Shram UAN card to the nearest District Labour Office "
            "(Shram Suvidha Kendra) and file a wage-theft complaint using "
            "Form 11. The contractor's licence can be suspended for "
            "non-payment. You're also entitled to equal wages as local "
            "workers, free basic medical care at the worksite, and — if "
            "recruited by a contractor — a displacement allowance and free "
            "return travel."
        )
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.OK,
            summary_message=summary,
            detail_message=detail,
            triggered_rule_id="ESHRAM-WAGE-001",
            next_steps="Take your e-Shram UAN card to the nearest Shram Suvidha Kendra and file Form 11.",
            helpline="1800-891-8888",
            scheme_code="ESHRAM",
        )

    def _eshram_benefits(
        self,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """e-Shram UAN card benefits and linked insurance."""
        benefit_txt = kb.benefits[0] if (kb and kb.benefits) else None
        helpline = kb.helpline if kb else "14434"
        summary = (
            benefit_txt or (
                "e-Shram gives you a 12-digit UAN card valid across all of "
                "India, and automatically links you to Rs. 2 lakh accident "
                "insurance under PMSBY, free for your first year."
            )
        )
        detail = (
            "The e-Shram UAN is a single national identity for unorganised "
            "workers, giving access to over 50 linked government welfare "
            "schemes and pan-India portability of benefits."
        )
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.OK,
            summary_message=summary,
            detail_message=detail,
            triggered_rule_id="ESHRAM-BENEFIT-001",
            next_steps="Show your e-Shram UAN card to access any of the linked welfare schemes.",
            helpline=helpline,
            scheme_code="ESHRAM",
        )

    # ── BOCW (Building & Other Construction Workers) rules ──────────────────

    def _evaluate_bocw(
        self,
        intent_type: IntentType,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """Fan-out dispatcher for all BOCW intents."""
        dispatch = {
            IntentType.BOCW_ELIGIBILITY:  self._bocw_eligibility,
            IntentType.BOCW_REGISTRATION: self._bocw_registration,
            IntentType.BOCW_DOCUMENTS:    self._bocw_documents,
            IntentType.REQUIRED_DOCUMENTS:self._bocw_documents,
            IntentType.BOCW_BENEFITS:     self._bocw_benefits,
        }
        handler = dispatch.get(intent_type)
        if handler:
            return handler(entity_map, kb)
        return self._bocw_eligibility(entity_map, kb)

    def _bocw_eligibility(
        self,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """BOCW eligibility: 90-day construction work requirement, age 18-60."""
        docs: List[str] = kb.required_documents if kb else [
            "Aadhaar Card", "90-Day Work Certificate", "Bank Passbook", "Passport-size Photographs",
        ]
        helpline = kb.helpline if kb else "1800-891-8888"
        summary = (
            "You are eligible if you are aged 18 to 60 and have worked at "
            "least 90 days in construction in the last 12 months. Migrant "
            "construction workers are explicitly covered under a 2018 "
            "Supreme Court order."
        )
        detail = (
            "You must register with the State Welfare Board of the state "
            "where you are CURRENTLY working, not your home state. Workers "
            "already covered under EPFO or ESIC are not eligible."
        )
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.ELIGIBLE,
            summary_message=summary,
            detail_message=detail,
            triggered_rule_id="BOCW-ELIG-001",
            required_documents=docs,
            next_steps="Get a 90-day work certificate from your contractor, then register with your destination state's BOCW Board.",
            helpline=helpline,
            scheme_code="BOCW",
        )

    def _bocw_registration(
        self,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """BOCW registration must happen with the destination state's board."""
        state = entity_map.state_name or "the state you are currently working in"
        helpline = kb.helpline if kb else "1800-891-8888"
        summary = (
            f"Register with the BOCW Welfare Board of {state} — the state "
            "where you are CURRENTLY working, not your home state. You need "
            "90 days of construction work proof. Benefits include accident "
            "insurance, daughter's marriage assistance, children's education "
            "money, and pension."
        )
        detail = (
            "Visit the nearest Common Service Centre, District Labour "
            "Office, or your destination state's BOCW Board portal (for "
            "example mahabocw.in in Maharashtra) with your Aadhaar, 90-day "
            "work certificate, bank passbook, and photographs. A one-time "
            "registration fee of Rs. 25 to 50 applies in most states; some "
            "states register for free."
        )
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.OK,
            summary_message=summary,
            detail_message=detail,
            triggered_rule_id="BOCW-REG-001",
            next_steps="Visit the nearest CSC or your destination state's BOCW Board office with Aadhaar, work certificate, bank passbook, and photos.",
            helpline=helpline,
            scheme_code="BOCW",
        )

    def _bocw_documents(
        self,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """Documents required for BOCW registration."""
        docs: List[str] = kb.required_documents if kb else [
            "Aadhaar Card", "90-Day Work Certificate", "Bank Passbook", "Passport-size Photographs",
        ]
        helpline = kb.helpline if kb else "1800-891-8888"
        summary = (
            "You need your Aadhaar card, a 90-day work certificate from your "
            "contractor, a bank passbook, and passport-size photographs."
        )
        detail = (
            "If your contractor refuses a work certificate, a self-declaration "
            "witnessed by two people, or a certificate from a labour union or "
            "NGO, is accepted by many state boards."
        )
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.OK,
            summary_message=summary,
            detail_message=detail,
            triggered_rule_id="BOCW-DOC-001",
            required_documents=docs,
            next_steps="Carry originals and photocopies of all documents to your destination state's BOCW Board office or CSC.",
            helpline=helpline,
            scheme_code="BOCW",
        )

    def _bocw_benefits(
        self,
        entity_map: EntityMap,
        kb: Optional[PortabilityRecord],
    ) -> RuleEvaluationResult:
        """BOCW welfare benefits: accident insurance, pension, education, marriage."""
        helpline = kb.helpline if kb else "1800-891-8888"
        summary = (
            "BOCW registration gives you accident insurance, medical "
            "assistance, a monthly pension after age 60, education "
            "scholarships for your children, and marriage assistance "
            "for daughters."
        )
        detail = (
            "Accident death compensation ranges from Rs. 1 to 5 lakh "
            "depending on your state. Education scholarships range from "
            "Rs. 1,000 to 25,000 per year. Amounts vary by state — check "
            "your destination state's BOCW Board portal."
        )
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.OK,
            summary_message=summary,
            detail_message=detail,
            triggered_rule_id="BOCW-BENEFIT-001",
            next_steps="Once registered, apply for individual benefits through your state BOCW Board portal or office.",
            helpline=helpline,
            scheme_code="BOCW",
        )

    # ── Main evaluate dispatcher ───────────────────────────────────────────

    def evaluate(
        self,
        intent_result: IntentResult,
        entity_map: EntityMap,
        kb_record: Optional[PortabilityRecord] = None,
    ) -> RuleEvaluationResult:
        """
        Dispatches rule evaluation based on detected intent and scheme code.

        Args:
            intent_result: Output of IntentRecognizer.
            entity_map:    Output of EntityExtractor.
            kb_record:     Live PortabilityRecord from SQLiteAccessLayer (may be None).

        Returns:
            RuleEvaluationResult with TTS-ready summary and structured details.
        """
        intent = intent_result.intent_type
        scheme = entity_map.scheme_code

        self.logger.info(
            f"Evaluating rules: intent={intent.value}, scheme={scheme}, "
            f"state={entity_map.state_name}, kb_loaded={kb_record is not None}"
        )

        # ── Multi-scheme overview (no single scheme - always deterministic) ─
        if intent == IntentType.WELFARE_OVERVIEW:
            return self._evaluate_welfare_overview(entity_map, kb_record)

        # ── PDS / ONORC ────────────────────────────────────────────────────
        if scheme == "PDS" or intent in (
            IntentType.PDS_ELIGIBILITY, IntentType.PDS_PORTABILITY
        ):
            return self._evaluate_pds(intent, entity_map, kb_record)

        # ── PM-JAY ─────────────────────────────────────────────────────────
        if scheme == "PMJAY" or intent in (
            IntentType.PMJAY_ELIGIBILITY, IntentType.PMJAY_BENEFITS,
            IntentType.PMJAY_DOCUMENTS, IntentType.PMJAY_PORTABILITY
        ):
            return self._evaluate_pmjay(intent, entity_map, kb_record)

        # ── e-Shram + OSH Code 2020 ────────────────────────────────────────
        if scheme == "ESHRAM" or intent in (
            IntentType.ESHRAM_REGISTRATION, IntentType.ESHRAM_BENEFITS,
            IntentType.ESHRAM_DOCUMENTS, IntentType.ESHRAM_WAGE_RIGHTS,
        ):
            return self._evaluate_eshram(intent, entity_map, kb_record)

        # ── BOCW (Building & Other Construction Workers) ───────────────────
        if scheme == "BOCW" or intent in (
            IntentType.BOCW_ELIGIBILITY, IntentType.BOCW_REGISTRATION,
            IntentType.BOCW_BENEFITS, IntentType.BOCW_DOCUMENTS,
        ):
            return self._evaluate_bocw(intent, entity_map, kb_record)

        # ── General / Unknown fallback ─────────────────────────────────────
        self.logger.info("No specific rule matched. Returning general guidance.")
        return RuleEvaluationResult(
            passed=True,
            status_code=RuleStatusCode.UNKNOWN,
            summary_message=(
                "I can help with PDS ration card, Ayushman Bharat health cover, "
                "e-Shram registration, or BOCW construction worker queries. "
                "Please mention the scheme name."
            ),
            triggered_rule_id="GENERIC-001",
            next_steps="Please re-state your question with the scheme name.",
            scheme_code=scheme or "GENERAL",
        )
