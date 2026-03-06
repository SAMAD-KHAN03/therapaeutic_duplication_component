"""
therapeutic_duplication_checker.py
------------------------------------
Core engine for detecting and evaluating therapeutic duplication.

All caching is handled by PostgreSQL via pg_store.py — no cache_dir arguments.

Key behaviours:
  1. CONVENTIONAL_DMARD same-class pair -> different MOA allowed (not a duplicate)
  2. ANTIMYCOBACTERIAL same-class pair  -> TB combination therapy is mandatory
  3. Ezetimibe + Statin: different class, different MOA -> shared indication match only
  4. Duplicate detection only fires on SAME class AND/OR SAME MOA
  5. Report includes NICE guideline, section reference, and URL for every finding
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class DuplicateReason(str, Enum):
    SAME_CLASS       = "Same pharmacological class"
    SAME_MOA         = "Same mechanism of action"
    SAME_INDICATION  = "Overlapping indication(s)"
    CLASS_AND_MOA    = "Same class and mechanism of action"
    ALL_THREE        = "Same class, mechanism of action, and indication"


class PairOutcome(str, Enum):
    UNIQUE                    = "UNIQUE - No therapeutic duplication identified"
    DUPLICATE_NO_RATIONALE    = "REDUNDANT - No supporting NICE guideline found"
    DUPLICATE_NOT_RECOMMENDED = "REDUNDANT - Specifically NOT recommended by NICE"
    DUPLICATE_CONTRAINDICATED = "REDUNDANT - CONTRAINDICATED per NICE guideline"
    DUPLICATE_SUPPORTED       = "OVERLAP WITH RATIONALE - Combination SUPPORTED by NICE guideline"
    DUPLICATE_CONDITIONAL     = "OVERLAP WITH RATIONALE - Combination CONDITIONALLY SUPPORTED by NICE"


_SAME_CLASS_DUPLICATE_CLASSES = {
    "NSAID", "COX2_INHIBITOR", "SSRI", "SNRI",
    "ACE_INHIBITOR", "ARB", "STATIN",
    "VITAMIN_K_ANTAGONIST", "DOAC_FACTOR_Xa_INHIBITOR", "DOAC_THROMBIN_INHIBITOR",
    "PPI", "BETA_BLOCKER", "CALCIUM_CHANNEL_BLOCKER", "THIAZIDE_DIURETIC",
    "BIGUANIDE", "DPP4_INHIBITOR", "GLP1_AGONIST", "SGLT2_INHIBITOR",
    "SULFONYLUREA", "INSULIN_LONG_ACTING",
    "MINERALOCORTICOID_RECEPTOR_ANTAGONIST",
}

_SAME_CLASS_REQUIRES_LOOKUP = {
    "CONVENTIONAL_DMARD",
    "ANTIMYCOBACTERIAL",
    "FOLATE_SUPPLEMENT",
}

_ALWAYS_UNIQUE_CLASS_PAIRS = frozenset([
    frozenset({"STATIN", "BETA_BLOCKER"}),
    frozenset({"STATIN", "PPI"}),
    frozenset({"PPI", "NSAID"}),
    frozenset({"SSRI", "PPI"}),
    frozenset({"BETA_BLOCKER", "PPI"}),
])

_KNOWN_COMBINATION_PAIRS = frozenset([
    # Hypertension multi-drug therapy
    frozenset({"ACE_INHIBITOR", "BETA_BLOCKER"}),
    frozenset({"ACE_INHIBITOR", "CALCIUM_CHANNEL_BLOCKER"}),
    frozenset({"ACE_INHIBITOR", "THIAZIDE_DIURETIC"}),
    frozenset({"ACE_INHIBITOR", "MINERALOCORTICOID_RECEPTOR_ANTAGONIST"}),
    frozenset({"ACE_INHIBITOR", "SGLT2_INHIBITOR"}),
    frozenset({"ARB", "BETA_BLOCKER"}),
    frozenset({"ARB", "CALCIUM_CHANNEL_BLOCKER"}),
    frozenset({"ARB", "THIAZIDE_DIURETIC"}),
    frozenset({"ARB", "MINERALOCORTICOID_RECEPTOR_ANTAGONIST"}),
    frozenset({"ARB", "SGLT2_INHIBITOR"}),
    frozenset({"BETA_BLOCKER", "CALCIUM_CHANNEL_BLOCKER"}),
    frozenset({"BETA_BLOCKER", "THIAZIDE_DIURETIC"}),
    frozenset({"BETA_BLOCKER", "MINERALOCORTICOID_RECEPTOR_ANTAGONIST"}),
    frozenset({"BETA_BLOCKER", "SGLT2_INHIBITOR"}),
    frozenset({"CALCIUM_CHANNEL_BLOCKER", "THIAZIDE_DIURETIC"}),
    frozenset({"MINERALOCORTICOID_RECEPTOR_ANTAGONIST", "SGLT2_INHIBITOR"}),
    # Lipid lowering
    frozenset({"STATIN", "EZETIMIBE"}),
    # T2DM combinations
    frozenset({"BIGUANIDE", "SGLT2_INHIBITOR"}),
    frozenset({"BIGUANIDE", "SULFONYLUREA"}),
    frozenset({"BIGUANIDE", "GLP1_AGONIST"}),
    frozenset({"BIGUANIDE", "DPP4_INHIBITOR"}),
    frozenset({"SGLT2_INHIBITOR", "SULFONYLUREA"}),
    frozenset({"SGLT2_INHIBITOR", "GLP1_AGONIST"}),
    frozenset({"SULFONYLUREA", "GLP1_AGONIST"}),
    # RA DMARDs
    frozenset({"CONVENTIONAL_DMARD", "FOLATE_SUPPLEMENT"}),
])


@dataclass
class DrugPairResult:
    drug_a: str
    drug_b: str
    profile_a: Any
    profile_b: Any
    is_duplicate: bool = False
    duplicate_reasons: List[DuplicateReason] = field(default_factory=list)
    shared_classes: List[str] = field(default_factory=list)
    shared_moas: List[str] = field(default_factory=list)
    shared_indications: Set[str] = field(default_factory=set)
    nice_rules_found: List[Tuple[str, Any]] = field(default_factory=list)
    outcome: PairOutcome = PairOutcome.UNIQUE
    outcome_detail: str = ""


@dataclass
class PrescriptionAnalysisReport:
    medications: List[str]
    resolved_profiles: Dict[str, Any] = field(default_factory=dict)
    unresolved_drugs: List[str] = field(default_factory=list)
    pair_results: List[DrugPairResult] = field(default_factory=list)

    @property
    def unique_pairs(self):
        return [r for r in self.pair_results if r.outcome == PairOutcome.UNIQUE]

    @property
    def duplicate_pairs(self):
        return [r for r in self.pair_results if r.outcome != PairOutcome.UNIQUE]

    @property
    def supported_combinations(self):
        return [r for r in self.pair_results if r.outcome in (
            PairOutcome.DUPLICATE_SUPPORTED, PairOutcome.DUPLICATE_CONDITIONAL,
        )]

    @property
    def unsupported_duplicates(self):
        return [r for r in self.pair_results if r.outcome in (
            PairOutcome.DUPLICATE_NO_RATIONALE,
            PairOutcome.DUPLICATE_NOT_RECOMMENDED,
            PairOutcome.DUPLICATE_CONTRAINDICATED,
        )]


# ──────────────────────────────────────────────────────────────────────────────
# Duplicate detection
# ──────────────────────────────────────────────────────────────────────────────

def _check_duplicate(profile_a, profile_b) -> Tuple[
    bool, List[DuplicateReason], List[str], List[str], Set[str],
]:
    ca = profile_a.drug_class
    cb = profile_b.drug_class
    ma = profile_a.mechanism_of_action
    mb = profile_b.mechanism_of_action
    shared_ind = set(profile_a.indications) & set(profile_b.indications)
    class_pair = frozenset({ca, cb})
    same_class = ca == cb
    same_moa   = (ma == mb) and ma not in ("UNKNOWN", "")

    if class_pair in _KNOWN_COMBINATION_PAIRS and not same_class:
        return True, [DuplicateReason.SAME_INDICATION], [], [], shared_ind

    if same_class and ca in _SAME_CLASS_REQUIRES_LOOKUP:
        return True, [DuplicateReason.SAME_CLASS], [ca], [], shared_ind

    if class_pair in _ALWAYS_UNIQUE_CLASS_PAIRS and not same_class:
        return False, [], [], [], shared_ind

    reasons: List[DuplicateReason] = []
    if same_class and same_moa and shared_ind:
        reasons.append(DuplicateReason.ALL_THREE)
    elif same_class and same_moa:
        reasons.append(DuplicateReason.CLASS_AND_MOA)
    else:
        if same_class:
            reasons.append(DuplicateReason.SAME_CLASS)
        if same_moa:
            reasons.append(DuplicateReason.SAME_MOA)
        if shared_ind and (same_class or same_moa):
            reasons.append(DuplicateReason.SAME_INDICATION)

    shared_classes = [ca] if same_class else []
    shared_moas    = [ma]  if same_moa   else []
    return bool(reasons), reasons, shared_classes, shared_moas, shared_ind


# ──────────────────────────────────────────────────────────────────────────────
# Outcome classification
# ──────────────────────────────────────────────────────────────────────────────

def _classify_outcome(rules, shared_indications: Set[str]) -> Tuple[PairOutcome, str]:
    if not rules:
        return (
            PairOutcome.DUPLICATE_NO_RATIONALE,
            (
                "No specific NICE guideline recommendation was found to support or "
                "prohibit this combination. This does not mean the combination is "
                "acceptable — clinical judgement and BNF/SPC review are required."
            ),
        )

    rec_types = {rule.recommendation for _, rule in rules}
    priority_order = ["CONTRAINDICATED", "NOT_RECOMMENDED", "CONDITIONAL", "SUPPORTED"]

    for priority in priority_order:
        if priority not in rec_types:
            continue
        applicable = [(code, r) for code, r in rules if r.recommendation == priority]
        code, rule = applicable[0]
        cond_text = "; ".join(rule.conditions) if rule.conditions else ""

        if priority == "CONTRAINDICATED":
            return (
                PairOutcome.DUPLICATE_CONTRAINDICATED,
                (
                    f"CONTRAINDICATED per NICE {code} ({rule.section_ref}).\n"
                    f"   Recommendation: {rule.recommendation_text}\n"
                    f"   Rationale: {rule.rationale}"
                    + (f"\n   Conditions: {cond_text}" if cond_text else "")
                    + f"\n   Guideline: {rule.url}"
                ),
            )
        elif priority == "NOT_RECOMMENDED":
            return (
                PairOutcome.DUPLICATE_NOT_RECOMMENDED,
                (
                    f"NOT RECOMMENDED per NICE {code} ({rule.section_ref}).\n"
                    f"   Recommendation: {rule.recommendation_text}\n"
                    f"   Rationale: {rule.rationale}"
                    + (f"\n   Conditions: {cond_text}" if cond_text else "")
                    + f"\n   Guideline: {rule.url}"
                ),
            )
        elif priority == "CONDITIONAL":
            return (
                PairOutcome.DUPLICATE_CONDITIONAL,
                (
                    f"CONDITIONALLY SUPPORTED per NICE {code} ({rule.section_ref}).\n"
                    f"   Recommendation: {rule.recommendation_text}"
                    + (f"\n   Conditions: {cond_text}" if cond_text else "")
                    + f"\n   Rationale: {rule.rationale}"
                    + f"\n   Guideline: {rule.url}"
                ),
            )
        elif priority == "SUPPORTED":
            return (
                PairOutcome.DUPLICATE_SUPPORTED,
                (
                    f"SUPPORTED per NICE {code} ({rule.section_ref}).\n"
                    f"   Recommendation: {rule.recommendation_text}\n"
                    f"   Rationale: {rule.rationale}"
                    + (f"\n   Conditions: {cond_text}" if cond_text else "")
                    + f"\n   Guideline: {rule.url}"
                ),
            )

    return (
        PairOutcome.DUPLICATE_NO_RATIONALE,
        "Rules found but none matched a known recommendation type.",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main checker — no cache_dir; all persistence via PostgreSQL
# ──────────────────────────────────────────────────────────────────────────────

class TherapeuticDuplicationChecker:

    def __init__(self, drug_resolver=None, nice_client=None):
        if drug_resolver is None:
            from fda_drug_resolver import FDADrugResolver
            self._resolver = FDADrugResolver(use_static_fallback=True)
        else:
            self._resolver = drug_resolver

        if nice_client is None:
            from nice_api_client import NICEAPIClient
            self._nice = NICEAPIClient(use_static_fallback=True)
        else:
            self._nice = nice_client

    def resolve_prescription(self, medications: List[str]) -> Dict[str, Any]:
        return {med: self._resolver.get_profile(med) for med in medications}

    def analyse(self, medications: List[str]) -> PrescriptionAnalysisReport:
        report = PrescriptionAnalysisReport(medications=medications)
        report.resolved_profiles = self.resolve_prescription(medications)
        report.unresolved_drugs  = [
            med for med, p in report.resolved_profiles.items() if p is None
        ]

        resolvable = [
            (med, profile)
            for med, profile in report.resolved_profiles.items()
            if profile is not None
        ]

        for (name_a, pa), (name_b, pb) in itertools.combinations(resolvable, 2):
            result = DrugPairResult(drug_a=name_a, drug_b=name_b, profile_a=pa, profile_b=pb)

            (
                result.is_duplicate,
                result.duplicate_reasons,
                result.shared_classes,
                result.shared_moas,
                result.shared_indications,
            ) = _check_duplicate(pa, pb)

            if not result.is_duplicate:
                result.outcome = PairOutcome.UNIQUE
                result.outcome_detail = (
                    f"No therapeutic overlap: {name_a} ({pa.drug_class}) and "
                    f"{name_b} ({pb.drug_class}) have different classes and mechanisms."
                )
            else:
                result.nice_rules_found = self._nice.find_combination_rules(
                    drug_a_class=pa.drug_class,
                    drug_b_class=pb.drug_class,
                    drug_a_name=pa.name,
                    drug_b_name=pb.name,
                    shared_indications=result.shared_indications,
                )
                result.outcome, result.outcome_detail = _classify_outcome(
                    result.nice_rules_found, result.shared_indications
                )

            report.pair_results.append(result)

        return report

    def format_report(self, report: PrescriptionAnalysisReport) -> str:
        lines = [
            "=" * 90,
            "                 THERAPEUTIC DUPLICATION CHECK REPORT",
            "=" * 90,
            "",
            f"Prescription ({len(report.medications)} medications):",
        ]

        for i, med in enumerate(report.medications, 1):
            profile = report.resolved_profiles.get(med)
            if profile:
                src = f"[{profile.source.upper()}]" if hasattr(profile, "source") else ""
                lines.append(
                    f"  {i:2}. {med.upper():<30} "
                    f"Class: {profile.drug_class:<40} "
                    f"MOA: {profile.mechanism_of_action} {src}"
                )
            else:
                lines.append(f"  {i:2}. {med.upper():<30} [UNRESOLVED]")

        if report.unresolved_drugs:
            lines += ["", "WARNING: UNRESOLVED DRUGS (manual review required):"]
            for d in report.unresolved_drugs:
                lines.append(f"   - {d}")

        lines += ["", "-" * 90, "  PAIR-BY-PAIR ANALYSIS", "-" * 90]

        icon_map = {
            PairOutcome.UNIQUE:                    "OK",
            PairOutcome.DUPLICATE_SUPPORTED:       "WARN [OVERLAP w/ RATIONALE]",
            PairOutcome.DUPLICATE_CONDITIONAL:     "WARN [OVERLAP w/ RATIONALE - CONDITIONAL]",
            PairOutcome.DUPLICATE_NO_RATIONALE:    "ALERT [REDUNDANT - NO GUIDELINE SUPPORT]",
            PairOutcome.DUPLICATE_NOT_RECOMMENDED: "ALERT [REDUNDANT - NOT RECOMMENDED]",
            PairOutcome.DUPLICATE_CONTRAINDICATED: "BLOCK [REDUNDANT - CONTRAINDICATED]",
        }

        for result in report.pair_results:
            icon = icon_map.get(result.outcome, "?")
            lines += [
                "",
                f"  {icon}",
                f"  Drug Pair : {result.drug_a.upper()}  <->  {result.drug_b.upper()}",
                f"  Outcome   : {result.outcome.value}",
            ]
            if result.is_duplicate:
                lines.append(
                    f"  Overlap   : {', '.join(r.value for r in result.duplicate_reasons)}"
                )
                if result.shared_classes:
                    lines.append(f"  Shared Class : {', '.join(result.shared_classes)}")
                if result.shared_moas:
                    lines.append(f"  Shared MOA   : {', '.join(result.shared_moas)}")
                if result.shared_indications:
                    lines.append(
                        f"  Shared Indication(s): {', '.join(sorted(result.shared_indications))}"
                    )
            for detail_line in result.outcome_detail.split("\n"):
                lines.append(f"  {detail_line}")

        lines += [
            "", "-" * 90, "  SUMMARY", "-" * 90,
            f"  Total drug pairs analysed    : {len(report.pair_results)}",
            f"  Unique (no overlap)          : {len(report.unique_pairs)}",
            f"  Duplicates/Overlaps detected : {len(report.duplicate_pairs)}",
            f"    Overlap w/ rationale       : {len(report.supported_combinations)}",
            f"    Redundant / contra         : {len(report.unsupported_duplicates)}",
            "", "-" * 90, "  DATA SOURCES", "-" * 90,
            "  Drug profiles : OpenFDA Drug Labels API (https://api.fda.gov/drug/label.json)",
            "  NICE rules    : Curated static library + NICE Evidence Search API",
            "  Persistence   : PostgreSQL (drug_profiles, combination_rules, analysis_results)",
            "  Fallback      : Local static knowledge base (drug_knowledge_base.py)",
            "",
            "  NOTE: Always supplement with current BNF, SPC, and clinical pharmacist review.",
            "=" * 90,
        ]

        return "\n".join(lines)


# Legacy shims
_default_checker: Optional[TherapeuticDuplicationChecker] = None

def _get_default_checker() -> TherapeuticDuplicationChecker:
    global _default_checker
    if _default_checker is None:
        _default_checker = TherapeuticDuplicationChecker()
    return _default_checker

def analyse_prescription(medications: List[str]) -> PrescriptionAnalysisReport:
    return _get_default_checker().analyse(medications)

def format_report(report: PrescriptionAnalysisReport) -> str:
    return _get_default_checker().format_report(report)