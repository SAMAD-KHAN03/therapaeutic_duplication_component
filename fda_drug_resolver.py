"""
fda_drug_resolver.py
--------------------
Resolves drug names to DrugProfile via the OpenFDA Drug Labels API,
with multi-tier parsing and PostgreSQL persistence (replaces disk/memory cache).

Resolution order
----------------
  1. PostgreSQL cache (drug_profiles table)
  2. Live OpenFDA API  (3-tier pharm-class parsing)
  3. Emergency fallback (drug_knowledge_base.py)
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pg_store

logger = logging.getLogger(__name__)


@dataclass
class DrugProfile:
    name: str
    brand_names: List[str]
    drug_class: str
    mechanism_of_action: str
    indications: Set[str]
    nice_guideline_codes: List[str]
    source: str = "fda"
    raw_pharm_class: List[str] = field(default_factory=list)
    raw_indications_text: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Tier 1: FDA structured pharm_class fields
# ──────────────────────────────────────────────────────────────────────────────

_EPC_MOA_TO_CLASS: List[Tuple[str, str]] = [
    ("angiotensin-converting enzyme inhibitor",             "ACE_INHIBITOR"),
    ("angiotensin converting enzyme inhibitor",             "ACE_INHIBITOR"),
    ("ace inhibitor",                                       "ACE_INHIBITOR"),
    ("angiotensin 2 receptor blocker",                      "ARB"),
    ("angiotensin ii receptor blocker",                     "ARB"),
    ("angiotensin receptor blocker",                        "ARB"),
    ("angiotensin-converting enzyme inhibitors [moa]",      "ACE_INHIBITOR"),
    ("angiotensin ii receptor antagonists [moa]",           "ARB"),
    ("angiotensin 2 receptor antagonists [moa]",            "ARB"),
    ("neprilysin inhibitor",                                "ARNI"),
    ("sacubitril",                                          "ARNI"),
    ("beta-adrenergic blocker [epc]",                       "BETA_BLOCKER"),
    ("beta-adrenergic blocker",                             "BETA_BLOCKER"),
    ("beta adrenergic blocker",                             "BETA_BLOCKER"),
    ("beta-adrenergic blocking agent",                      "BETA_BLOCKER"),
    ("beta adrenergic antagonists [moa]",                   "BETA_BLOCKER"),
    ("adrenergic beta-antagonists",                         "BETA_BLOCKER"),
    ("calcium channel blocker [epc]",                       "CALCIUM_CHANNEL_BLOCKER"),
    ("calcium channel antagonists [moa]",                   "CALCIUM_CHANNEL_BLOCKER"),
    ("calcium channel blocker",                             "CALCIUM_CHANNEL_BLOCKER"),
    ("calcium channel antagonist",                          "CALCIUM_CHANNEL_BLOCKER"),
    ("dihydropyridine calcium channel antagonist",          "CALCIUM_CHANNEL_BLOCKER"),
    ("hmg-coa reductase inhibitor [epc]",                   "STATIN"),
    ("hydroxymethylglutaryl-coa reductase inhibitor [epc]", "STATIN"),
    ("hydroxymethylglutaryl-coa reductase inhibitors [moa]","STATIN"),
    ("hmg coa reductase inhibitor",                         "STATIN"),
    ("statin",                                              "STATIN"),
    ("vitamin k antagonist",                                "VITAMIN_K_ANTAGONIST"),
    ("coumarin anticoagulant",                              "VITAMIN_K_ANTAGONIST"),
    ("factor xa inhibitor [epc]",                           "DOAC_FACTOR_Xa_INHIBITOR"),
    ("factor xa inhibitors [moa]",                          "DOAC_FACTOR_Xa_INHIBITOR"),
    ("direct factor xa inhibitor",                          "DOAC_FACTOR_Xa_INHIBITOR"),
    ("direct thrombin inhibitor [epc]",                     "DOAC_THROMBIN_INHIBITOR"),
    ("direct thrombin inhibitors [moa]",                    "DOAC_THROMBIN_INHIBITOR"),
    ("thrombin inhibitor",                                  "DOAC_THROMBIN_INHIBITOR"),
    ("sodium-glucose cotransporter 2 inhibitor [epc]",      "SGLT2_INHIBITOR"),
    ("sodium glucose cotransporter 2 inhibitors [moa]",     "SGLT2_INHIBITOR"),
    ("sglt2 inhibitor",                                     "SGLT2_INHIBITOR"),
    ("sodium-glucose co-transporter 2",                     "SGLT2_INHIBITOR"),
    ("glucagon-like peptide-1 receptor agonist [epc]",      "GLP1_AGONIST"),
    ("glucagon-like peptide 1 receptor agonists [moa]",     "GLP1_AGONIST"),
    ("glp-1 receptor agonist",                              "GLP1_AGONIST"),
    ("dipeptidyl peptidase-4 inhibitor [epc]",              "DPP4_INHIBITOR"),
    ("dipeptidyl peptidase 4 inhibitors [moa]",             "DPP4_INHIBITOR"),
    ("dpp-4 inhibitor",                                     "DPP4_INHIBITOR"),
    ("biguanide [epc]",                                     "BIGUANIDE"),
    ("biguanides [moa]",                                    "BIGUANIDE"),
    ("biguanide",                                           "BIGUANIDE"),
    ("selective serotonin reuptake inhibitor [epc]",        "SSRI"),
    ("serotonin uptake inhibitors [moa]",                   "SSRI"),
    ("serotonin reuptake inhibitors [moa]",                 "SSRI"),
    ("selective serotonin reuptake inhibitor",              "SSRI"),
    ("ssri",                                                "SSRI"),
    ("serotonin-norepinephrine reuptake inhibitor [epc]",   "SNRI"),
    ("serotonin and norepinephrine reuptake inhibitors [moa]", "SNRI"),
    ("serotonin norepinephrine reuptake inhibitor",         "SNRI"),
    ("snri",                                                "SNRI"),
    ("nonsteroidal anti-inflammatory drug [epc]",           "NSAID"),
    ("cyclooxygenase inhibitors [moa]",                     "NSAID"),
    ("nonsteroidal anti-inflammatory",                      "NSAID"),
    ("cox-2 selective [epc]",                               "COX2_INHIBITOR"),
    ("cyclooxygenase 2 inhibitors [moa]",                   "COX2_INHIBITOR"),
    ("cox-2 inhibitor",                                     "COX2_INHIBITOR"),
    ("selective cyclooxygenase-2 inhibitor",                "COX2_INHIBITOR"),
    ("proton pump inhibitor [epc]",                         "PPI"),
    ("h+/k+-atpase inhibitors [moa]",                       "PPI"),
    ("proton pump inhibitor",                               "PPI"),
    ("cholesterol absorption inhibitor",                    "EZETIMIBE"),
    ("ezetimibe",                                           "EZETIMIBE"),
    ("npc1l1 inhibitor",                                    "EZETIMIBE"),
    ("thiazide diuretic",                                   "THIAZIDE_DIURETIC"),
    ("thiazide-like diuretic",                              "THIAZIDE_DIURETIC"),
    ("sulfonamide diuretic",                                "THIAZIDE_DIURETIC"),
    ("mineralocorticoid receptor antagonist",               "MINERALOCORTICOID_RECEPTOR_ANTAGONIST"),
    ("aldosterone antagonist",                              "MINERALOCORTICOID_RECEPTOR_ANTAGONIST"),
    ("sulfonylurea [epc]",                                  "SULFONYLUREA"),
    ("sulfonylureas [moa]",                                 "SULFONYLUREA"),
    ("sulfonylurea",                                        "SULFONYLUREA"),
    ("long-acting insulin [epc]",                           "INSULIN_LONG_ACTING"),
    ("long acting insulin",                                 "INSULIN_LONG_ACTING"),
    ("insulin, long-acting",                                "INSULIN_LONG_ACTING"),
    ("basal insulin",                                       "INSULIN_LONG_ACTING"),
    ("antirheumatic agent",                                 "CONVENTIONAL_DMARD"),
    ("disease-modifying antirheumatic drug",                "CONVENTIONAL_DMARD"),
    ("dmard",                                               "CONVENTIONAL_DMARD"),
    ("folate antagonist",                                   "CONVENTIONAL_DMARD"),
    ("antimycobacterial [epc]",                             "ANTIMYCOBACTERIAL"),
    ("antimycobacterials [moa]",                            "ANTIMYCOBACTERIAL"),
    ("antimycobacterial",                                   "ANTIMYCOBACTERIAL"),
    ("antituberculosis",                                    "ANTIMYCOBACTERIAL"),
    ("anti-tuberculosis",                                   "ANTIMYCOBACTERIAL"),
]

_EPC_MOA_TO_MOA: List[Tuple[str, str]] = [
    ("angiotensin-converting enzyme inhibitor",             "RAAS_INHIBITION_ACEi"),
    ("ace inhibitor",                                       "RAAS_INHIBITION_ACEi"),
    ("angiotensin 2 receptor blocker",                      "RAAS_INHIBITION_ARB"),
    ("angiotensin ii receptor blocker",                     "RAAS_INHIBITION_ARB"),
    ("neprilysin inhibitor",                                "RAAS_INHIBITION_ARNI"),
    ("beta-adrenergic blocker",                             "BETA_ADRENERGIC_BLOCKADE"),
    ("beta adrenergic blocker",                             "BETA_ADRENERGIC_BLOCKADE"),
    ("calcium channel antagonists [moa]",                   "CALCIUM_CHANNEL_BLOCKADE"),
    ("calcium channel blocker",                             "CALCIUM_CHANNEL_BLOCKADE"),
    ("hydroxymethylglutaryl-coa reductase inhibitors [moa]","HMG_COA_REDUCTASE_INHIBITION"),
    ("hmg-coa reductase inhibitor",                         "HMG_COA_REDUCTASE_INHIBITION"),
    ("statin",                                              "HMG_COA_REDUCTASE_INHIBITION"),
    ("vitamin k antagonist",                                "VITAMIN_K_CYCLE_INHIBITION"),
    ("factor xa inhibitor",                                 "FACTOR_Xa_INHIBITION_DIRECT"),
    ("thrombin inhibitor",                                  "DIRECT_THROMBIN_INHIBITION"),
    ("sodium glucose cotransporter 2 inhibitors [moa]",     "SGLT2_INHIBITION_RENAL_GLUCOSE_EXCRETION"),
    ("sglt2 inhibitor",                                     "SGLT2_INHIBITION_RENAL_GLUCOSE_EXCRETION"),
    ("glucagon-like peptide 1 receptor agonists [moa]",     "GLP1_RECEPTOR_AGONISM"),
    ("glp-1 receptor agonist",                              "GLP1_RECEPTOR_AGONISM"),
    ("dipeptidyl peptidase 4 inhibitors [moa]",             "DPP4_INHIBITION_GLP1_AUGMENTATION"),
    ("biguanides [moa]",                                    "AMPK_ACTIVATION_HEPATIC_GLUCOSE_REDUCTION"),
    ("biguanide",                                           "AMPK_ACTIVATION_HEPATIC_GLUCOSE_REDUCTION"),
    ("serotonin uptake inhibitors [moa]",                   "SEROTONIN_REUPTAKE_INHIBITION"),
    ("selective serotonin reuptake inhibitor",              "SEROTONIN_REUPTAKE_INHIBITION"),
    ("serotonin and norepinephrine reuptake inhibitors [moa]", "SEROTONIN_NOREPINEPHRINE_REUPTAKE_INHIBITION"),
    ("cyclooxygenase inhibitors [moa]",                     "COX_INHIBITION_NONSELECTIVE"),
    ("nonsteroidal anti-inflammatory",                      "COX_INHIBITION_NONSELECTIVE"),
    ("cyclooxygenase 2 inhibitors [moa]",                   "COX2_INHIBITION_SELECTIVE"),
    ("proton pump inhibitor",                               "H_K_ATPase_INHIBITION"),
    ("cholesterol absorption inhibitor",                    "INTESTINAL_CHOLESTEROL_ABSORPTION_INHIBITION"),
    ("ezetimibe",                                           "INTESTINAL_CHOLESTEROL_ABSORPTION_INHIBITION"),
    ("thiazide diuretic",                                   "RENAL_SODIUM_CHLORIDE_REABSORPTION_INHIBITION"),
    ("sulfonamide diuretic",                                "RENAL_SODIUM_CHLORIDE_REABSORPTION_INHIBITION"),
    ("mineralocorticoid receptor antagonist",               "ALDOSTERONE_RECEPTOR_BLOCKADE"),
    ("aldosterone antagonist",                              "ALDOSTERONE_RECEPTOR_BLOCKADE"),
    ("sulfonylurea",                                        "PANCREATIC_INSULIN_SECRETION_ATP_K_CHANNEL"),
    ("long-acting insulin",                                 "INSULIN_RECEPTOR_ACTIVATION"),
    ("long acting insulin",                                 "INSULIN_RECEPTOR_ACTIVATION"),
    ("basal insulin",                                       "INSULIN_RECEPTOR_ACTIVATION"),
    ("antirheumatic",                                       "IMMUNOMODULATION"),
    ("folate antagonist",                                   "DIHYDROFOLATE_REDUCTASE_INHIBITION"),
    ("antimycobacterial",                                   "ANTIMYCOBACTERIAL_ACTIVITY"),
    ("antituberculosis",                                    "ANTIMYCOBACTERIAL_ACTIVITY"),
]

_FREETEXT_CLASS_PATTERNS: List[Tuple[str, str]] = [
    (r"angiotensin.converting enzyme\s+inhibit|ace\s+inhibit",              "ACE_INHIBITOR"),
    (r"angiotensin.ii.*receptor.*antagonist|angiotensin.*receptor.*blocker", "ARB"),
    (r"neprilysin.*inhibit",                                                 "ARNI"),
    (r"beta.?adrenergic.{0,15}block|beta.?blocker",                         "BETA_BLOCKER"),
    (r"calcium channel.{0,15}(block|antagonist)",                           "CALCIUM_CHANNEL_BLOCKER"),
    (r"hmg.?coa reductase inhibit|hydroxymethylglutaryl",                   "STATIN"),
    (r"\bstatin\b",                                                          "STATIN"),
    (r"cholesterol absorption inhibit|npc1l1|ezetimibe",                    "EZETIMIBE"),
    (r"vitamin k.{0,20}(cycle|antagonist|inhibit)|inhibit.{0,20}vitamin k", "VITAMIN_K_ANTAGONIST"),
    (r"factor xa.{0,15}inhibit",                                            "DOAC_FACTOR_Xa_INHIBITOR"),
    (r"thrombin.{0,15}inhibit",                                             "DOAC_THROMBIN_INHIBITOR"),
    (r"sglt.?2|sodium.glucose cotransporter",                               "SGLT2_INHIBITOR"),
    (r"glp.?1 receptor agonist|glucagon.like peptide.{0,5}receptor",       "GLP1_AGONIST"),
    (r"dpp.?4|dipeptidyl peptidase",                                        "DPP4_INHIBITOR"),
    (r"\bbiguanide\b|hepatic glucose.{0,20}(produc|output)",                "BIGUANIDE"),
    (r"selective serotonin reuptake inhibit|ssri",                          "SSRI"),
    (r"serotonin.*norepinephrine reuptake inhibit|snri",                    "SNRI"),
    (r"nonsteroidal anti.inflammatory|nsaid|cyclooxygenase.{0,15}inhibit",  "NSAID"),
    (r"cyclooxygenase.?2.{0,15}(select|specific)|cox.?2",                  "COX2_INHIBITOR"),
    (r"proton pump inhibit|h\+/k\+.atpase",                                "PPI"),
    (r"thiazide|sulfonamide.{0,15}diuretic|indapamide",                    "THIAZIDE_DIURETIC"),
    (r"mineralocorticoid.{0,15}receptor.{0,15}antag|aldosterone.{0,15}antag|spironolactone", "MINERALOCORTICOID_RECEPTOR_ANTAGONIST"),
    (r"\bsulfonylurea\b|atp.sensitive.{0,15}potassium.{0,15}channel|atp.k.channel", "SULFONYLUREA"),
    (r"long.acting insulin|basal insulin|insulin.{0,20}glargine|insulin.{0,20}detemir|insulin.{0,20}degludec", "INSULIN_LONG_ACTING"),
    (r"disease.modifying antirheumatic|dmard|dihydrofolate reductase|methotrexate|sulfasalazine|hydroxychloroquine", "CONVENTIONAL_DMARD"),
    (r"mycolic acid|antimycobacterial|antituberculosis|anti-tuberculosis|isoniazid|rifampin|rifampicin|pyrazinamide|ethambutol", "ANTIMYCOBACTERIAL"),
]

_FREETEXT_MOA_PATTERNS: List[Tuple[str, str]] = [
    (r"angiotensin.converting enzyme\s+inhibit|ace\s+inhibit",              "RAAS_INHIBITION_ACEi"),
    (r"angiotensin.ii.*receptor.*antagonist|angiotensin.*receptor.*blocker", "RAAS_INHIBITION_ARB"),
    (r"neprilysin.*inhibit",                                                 "RAAS_INHIBITION_ARNI"),
    (r"beta.?adrenergic.{0,15}block",                                       "BETA_ADRENERGIC_BLOCKADE"),
    (r"calcium channel.{0,15}(block|antagonist)",                           "CALCIUM_CHANNEL_BLOCKADE"),
    (r"hmg.?coa reductase inhibit|hydroxymethylglutaryl",                   "HMG_COA_REDUCTASE_INHIBITION"),
    (r"cholesterol absorption inhibit|npc1l1",                              "INTESTINAL_CHOLESTEROL_ABSORPTION_INHIBITION"),
    (r"vitamin k.{0,20}(cycle|antagonist|inhibit)",                         "VITAMIN_K_CYCLE_INHIBITION"),
    (r"factor xa.{0,15}inhibit",                                            "FACTOR_Xa_INHIBITION_DIRECT"),
    (r"thrombin.{0,15}inhibit",                                             "DIRECT_THROMBIN_INHIBITION"),
    (r"sglt.?2|sodium.glucose cotransporter",                               "SGLT2_INHIBITION_RENAL_GLUCOSE_EXCRETION"),
    (r"glp.?1 receptor agonist|glucagon.like peptide.{0,5}receptor",       "GLP1_RECEPTOR_AGONISM"),
    (r"dpp.?4|dipeptidyl peptidase",                                        "DPP4_INHIBITION_GLP1_AUGMENTATION"),
    (r"\bbiguanide\b|ampk|hepatic glucose.{0,20}(produc|output)",           "AMPK_ACTIVATION_HEPATIC_GLUCOSE_REDUCTION"),
    (r"serotonin reuptake inhibit",                                         "SEROTONIN_REUPTAKE_INHIBITION"),
    (r"serotonin.*norepinephrine reuptake inhibit",                         "SEROTONIN_NOREPINEPHRINE_REUPTAKE_INHIBITION"),
    (r"cyclooxygenase.?2.{0,15}(select|specific)|cox.?2.*inhibit",         "COX2_INHIBITION_SELECTIVE"),
    (r"cyclooxygen|nonsteroidal anti.inflammatory",                         "COX_INHIBITION_NONSELECTIVE"),
    (r"proton pump inhibit|h\+/k\+.atpase",                                "H_K_ATPase_INHIBITION"),
    (r"thiazide|sodium.{0,15}chloride.{0,15}reabsorption",                 "RENAL_SODIUM_CHLORIDE_REABSORPTION_INHIBITION"),
    (r"mineralocorticoid.{0,15}receptor|aldosterone.{0,15}antag",          "ALDOSTERONE_RECEPTOR_BLOCKADE"),
    (r"atp.sensitive.{0,15}potassium|sulfonylurea|insulin secretion",       "PANCREATIC_INSULIN_SECRETION_ATP_K_CHANNEL"),
    (r"long.acting insulin|basal insulin|insulin.receptor",                 "INSULIN_RECEPTOR_ACTIVATION"),
    (r"dihydrofolate reductase",                                            "DIHYDROFOLATE_REDUCTASE_INHIBITION"),
    (r"immunomodul|nf.?kb|cytokine.{0,15}suppres",                         "IMMUNOMODULATION_NFKB_CYTOKINE_SUPPRESSION"),
    (r"mycolic acid",                                                       "MYCOLIC_ACID_SYNTHESIS_INHIBITION"),
    (r"rna polymerase",                                                     "RNA_POLYMERASE_INHIBITION"),
    (r"arabinosyl transferase",                                             "ARABINOSYL_TRANSFERASE_INHIBITION"),
    (r"pyrazinamide|acidic.{0,15}(environment|condition)",                 "INTRACELLULAR_ACIDIC_ENVIRONMENT_ACTIVITY"),
]

_INDICATION_PATTERNS: List[Tuple[str, str]] = [
    (r"heart failure|cardiac failure|hfref|hfpef",         "heart_failure"),
    (r"hypertension|high blood pressure",                  "hypertension"),
    (r"type 2 diabetes|type ii diabetes|t2dm|diabetes mellitus.*type 2", "type2_diabetes"),
    (r"\bobesity\b|weight management",                     "obesity"),
    (r"major depressive|depression",                       "depression"),
    (r"\banxiety\b",                                       "anxiety"),
    (r"obsessive.compulsive|\bocd\b",                      "ocd"),
    (r"post.traumatic|ptsd",                               "ptsd"),
    (r"panic disorder",                                    "panic_disorder"),
    (r"atrial fibrillation|\baf\b",                        "atrial_fibrillation"),
    (r"deep vein thrombosis|\bdvt\b",                      "dvt"),
    (r"pulmonary embolism|\bpe\b",                         "pe"),
    (r"osteoarthritis",                                    "osteoarthritis"),
    (r"rheumatoid arthritis",                              "rheumatoid_arthritis"),
    (r"\bpain\b|\banalges",                                "pain"),
    (r"\binflammation\b|\binflammatory\b",                 "inflammation"),
    (r"hypercholesterol|hyperlipid|high.*cholesterol|dyslipid", "hypercholesterolaemia"),
    (r"gastroesophageal reflux|gord|gerd",                 "gord"),
    (r"peptic ulcer",                                      "peptic_ulcer"),
    (r"myocardial infarction|post.mi|post.myocardial",     "post_MI"),
    (r"\bangina\b",                                        "angina"),
    (r"diabetic nephropathy|chronic kidney disease",       "diabetic_nephropathy"),
    (r"diabetic neuropathy|peripheral neuropathy",         "diabetic_neuropathy"),
    (r"\bfibromyalgia\b",                                  "fibromyalgia"),
    (r"bulimia",                                           "bulimia_nervosa"),
    (r"polycystic ovary|pcos",                             "pcos"),
    (r"\bfever\b|\bpyrexia\b",                             "fever"),
    (r"\bgout\b",                                          "gout"),
    (r"prediabetes|impaired glucose",                      "prediabetes"),
    (r"tuberculosis|\btb\b",                               "tuberculosis"),
    (r"rheumatoid",                                        "rheumatoid_arthritis"),
    (r"cardiovascular.{0,30}(disease|risk|prevention)",   "hypercholesterolaemia"),
]


def _match_substring(text: str, patterns: List[Tuple[str, str]]) -> Optional[str]:
    t = text.lower()
    for pattern, canonical in patterns:
        if pattern in t:
            return canonical
    return None


def _match_regex(text: str, patterns: List[Tuple[str, str]]) -> Optional[str]:
    t = text.lower()
    for pattern, canonical in patterns:
        if re.search(pattern, t):
            return canonical
    return None


def _extract_indications(texts: List[str]) -> Set[str]:
    found: Set[str] = set()
    combined = " ".join(texts).lower()
    for pattern, canonical in _INDICATION_PATTERNS:
        if re.search(pattern, combined):
            found.add(canonical)
    return found


# ──────────────────────────────────────────────────────────────────────────────
# FDA API helpers
# ──────────────────────────────────────────────────────────────────────────────

FDA_LABEL_ENDPOINT = "https://api.fda.gov/drug/label.json"
_TIMEOUT = 10
_RATE_DELAY = 0.4


class FDAAPIError(Exception):
    pass


def _fda_get(params: Dict[str, Any]) -> Optional[Dict]:
    url = f"{FDA_LABEL_ENDPOINT}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "TherapeuticDuplicationChecker/2.0"})
    try:
        time.sleep(_RATE_DELAY)
        with urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise FDAAPIError(f"FDA API HTTP {exc.code}") from exc
    except URLError as exc:
        logger.warning("FDA API unreachable: %s", exc.reason)
        return None


def _search_fda_label(drug_name: str) -> Optional[Dict]:
    n = drug_name.strip()
    strategies = [
        {"search": f'openfda.generic_name:"{n}"',    "limit": 3},
        {"search": f'openfda.brand_name:"{n}"',      "limit": 3},
        {"search": f'openfda.substance_name:"{n}"',  "limit": 3},
        {"search": n,                                 "limit": 3},
    ]
    for params in strategies:
        data = _fda_get(params)
        if not data or not data.get("results"):
            continue
        best = _pick_best_result(data["results"], n)
        if best:
            return best
    return None


def _pick_best_result(results: List[Dict], drug_name: str) -> Optional[Dict]:
    n = drug_name.lower()
    def score(r: Dict) -> int:
        s = 0
        openfda = r.get("openfda", {})
        names = [x.lower() for x in openfda.get("generic_name", [])]
        if any(n in name or name in n for name in names):
            s += 2
        if openfda.get("pharm_class_epc") or openfda.get("pharm_class_moa"):
            s += 1
        return s
    ranked = sorted(results, key=score, reverse=True)
    return ranked[0] if ranked else None


def _parse_fda_result(drug_name: str, result: Dict) -> DrugProfile:
    openfda = result.get("openfda", {})
    generic_names = openfda.get("generic_name", [])
    generic = generic_names[0].lower().strip() if generic_names else drug_name.lower()
    brand_names = [b.title() for b in openfda.get("brand_name", [])]

    pharm_epc = openfda.get("pharm_class_epc", [])
    pharm_moa = openfda.get("pharm_class_moa", [])
    pharm_cs  = openfda.get("pharm_class_cs",  [])
    pharm_pe  = openfda.get("pharm_class_pe",  [])
    all_pharm = pharm_epc + pharm_moa + pharm_cs + pharm_pe
    tier1_text = " | ".join(all_pharm)

    drug_class = _match_substring(tier1_text, _EPC_MOA_TO_CLASS)
    moa        = _match_substring(tier1_text, _EPC_MOA_TO_MOA)

    if drug_class is None or moa is None:
        tier2_texts = (
            result.get("mechanism_of_action", [])
            + result.get("clinical_pharmacology", [])
            + result.get("pharmacodynamics_and_pharmacokinetics", [])
        )
        tier2_text = " ".join(tier2_texts)
        if drug_class is None and tier2_text:
            drug_class = _match_regex(tier2_text, _FREETEXT_CLASS_PATTERNS)
        if moa is None and tier2_text:
            moa = _match_regex(tier2_text, _FREETEXT_MOA_PATTERNS)

    if drug_class is None:
        tier3_text = " ".join(
            result.get("description", []) + result.get("clinical_pharmacology", [])
        )
        if tier3_text:
            drug_class = _match_regex(tier3_text, _FREETEXT_CLASS_PATTERNS)
            if moa is None:
                moa = _match_regex(tier3_text, _FREETEXT_MOA_PATTERNS)

    drug_class = drug_class or "UNKNOWN"
    moa        = moa or "UNKNOWN"

    indication_texts = (
        result.get("indications_and_usage", [])
        + result.get("indications", [])
        + result.get("purpose", [])
    )
    indications = _extract_indications(indication_texts)

    return DrugProfile(
        name=generic,
        brand_names=brand_names,
        drug_class=drug_class,
        mechanism_of_action=moa,
        indications=indications,
        nice_guideline_codes=[],
        source="fda",
        raw_pharm_class=all_pharm,
        raw_indications_text=" ".join(indication_texts)[:500],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ──────────────────────────────────────────────────────────────────────────────

def _profile_to_dict(p: DrugProfile) -> Dict:
    d = p.__dict__.copy()
    d["indications"] = list(d["indications"])
    return d


def _profile_from_dict(d: Dict) -> DrugProfile:
    d = d.copy()
    d["indications"] = set(d.get("indications", []))
    d.setdefault("raw_pharm_class", [])
    d.setdefault("raw_indications_text", "")
    return DrugProfile(**d)


# ──────────────────────────────────────────────────────────────────────────────
# Resolver
# ──────────────────────────────────────────────────────────────────────────────

class FDADrugResolver:
    """
    Resolves drug names to DrugProfile.

    Resolution order:
      1. PostgreSQL cache  (drug_profiles table)
      2. Live FDA API      (3-tier parsing)
      3. Emergency fallback (drug_knowledge_base.py)
    """

    def __init__(self, use_static_fallback: bool = True, api_key: Optional[str] = None):
        self._use_fallback = use_static_fallback
        self._api_key = api_key

    def _emergency_fallback(self, name: str) -> Optional[DrugProfile]:
        try:
            from drug_knowledge_base import get_profile as seed_get
            seed = seed_get(name)
            if seed:
                logger.warning(
                    "EMERGENCY FALLBACK used for '%s' — FDA API unavailable / drug not found.", name
                )
                return DrugProfile(
                    name=seed.name,
                    brand_names=list(seed.brand_names),
                    drug_class=seed.drug_class,
                    mechanism_of_action=seed.mechanism_of_action,
                    indications=set(seed.indications),
                    nice_guideline_codes=list(seed.nice_guideline_codes),
                    source="emergency_fallback",
                )
        except ImportError:
            pass
        return None

    def get_profile(self, drug_name: str) -> Optional[DrugProfile]:
        # 1 — PostgreSQL cache
        try:
            cached = pg_store.load_drug_profile(drug_name)
            if cached is not None:
                logger.debug("PG cache hit for '%s'", drug_name)
                return _profile_from_dict(cached)
        except Exception as exc:
            logger.warning("PG load failed for '%s': %s", drug_name, exc)

        # 2 — Live FDA API
        profile: Optional[DrugProfile] = None
        try:
            result = _search_fda_label(drug_name)
            if result:
                profile = _parse_fda_result(drug_name, result)
                logger.info(
                    "FDA resolved '%s' -> class=%s moa=%s",
                    drug_name, profile.drug_class, profile.mechanism_of_action,
                )
            else:
                logger.warning("'%s' not found in FDA label database.", drug_name)
        except Exception as exc:
            logger.error("FDA API error for '%s': %s", drug_name, exc)

        # 3 — Emergency fallback
        if profile is None and self._use_fallback:
            profile = self._emergency_fallback(drug_name)

        # Persist to PostgreSQL
        if profile is not None:
            try:
                pg_store.save_drug_profile(drug_name, _profile_to_dict(profile))
            except Exception as exc:
                logger.warning("PG save failed for '%s': %s", drug_name, exc)

        return profile

    def get_profiles_bulk(self, names: List[str]) -> Dict[str, Optional[DrugProfile]]:
        return {n: self.get_profile(n) for n in names}

    def debug_fda_raw(self, drug_name: str) -> Dict:
        result = _search_fda_label(drug_name)
        if not result:
            return {"error": f"'{drug_name}' not found in FDA label database"}
        openfda = result.get("openfda", {})
        return {
            "generic_name":    openfda.get("generic_name", []),
            "brand_name":      openfda.get("brand_name", []),
            "pharm_class_epc": openfda.get("pharm_class_epc", []),
            "pharm_class_moa": openfda.get("pharm_class_moa", []),
            "mechanism_of_action_text": result.get("mechanism_of_action", [])[:1],
        }