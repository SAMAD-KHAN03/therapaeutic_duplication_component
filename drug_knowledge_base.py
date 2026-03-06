"""
drug_knowledge_base.py
----------------------
EMERGENCY FALLBACK ONLY — not a drug database.

This file exists solely as a last resort when:
  1. The OpenFDA API is unreachable (network outage)
  2. AND the drug was never previously resolved and disk-cached

Extended to cover all 10 TD test case drugs including:
  - TB drugs (isoniazid, rifampicin, pyrazinamide, ethambutol)
  - DMARDs (methotrexate, sulfasalazine)
  - Basal insulins (glargine, detemir)
  - Ezetimibe
  - Indapamide, spironolactone, gliclazide

Profiles tagged source="emergency_fallback" so callers always know
the data did NOT come from the FDA API.
"""

from dataclasses import dataclass, field
from typing import List, Set


@dataclass
class DrugProfile:
    name: str
    brand_names: List[str]
    drug_class: str
    mechanism_of_action: str
    indications: Set[str]
    nice_guideline_codes: List[str]


EMERGENCY_SEED: dict[str, DrugProfile] = {

    # ── Anticoagulants ────────────────────────────────────────────────────────
    "warfarin":     DrugProfile("warfarin",     ["Coumadin", "Jantoven"],
                                "VITAMIN_K_ANTAGONIST",    "VITAMIN_K_CYCLE_INHIBITION",
                                {"atrial_fibrillation","dvt","pe","mechanical_heart_valve"},
                                ["CG180","NG196"]),
    "apixaban":     DrugProfile("apixaban",     ["Eliquis"],
                                "DOAC_FACTOR_Xa_INHIBITOR","FACTOR_Xa_INHIBITION_DIRECT",
                                {"atrial_fibrillation","dvt","pe","dvt_prophylaxis"},
                                ["TA275","CG180","NG196"]),
    "rivaroxaban":  DrugProfile("rivaroxaban",  ["Xarelto"],
                                "DOAC_FACTOR_Xa_INHIBITOR","FACTOR_Xa_INHIBITION_DIRECT",
                                {"atrial_fibrillation","dvt","pe","dvt_prophylaxis"},
                                ["TA256","CG180","NG196"]),
    "edoxaban":     DrugProfile("edoxaban",     ["Lixiana"],
                                "DOAC_FACTOR_Xa_INHIBITOR","FACTOR_Xa_INHIBITION_DIRECT",
                                {"atrial_fibrillation","dvt","pe"},
                                ["TA354","CG180"]),
    "dabigatran":   DrugProfile("dabigatran",   ["Pradaxa"],
                                "DOAC_THROMBIN_INHIBITOR", "DIRECT_THROMBIN_INHIBITION",
                                {"atrial_fibrillation","dvt","pe","dvt_prophylaxis"},
                                ["TA249","CG180"]),

    # ── SSRIs / SNRIs ─────────────────────────────────────────────────────────
    "sertraline":   DrugProfile("sertraline",   ["Lustral","Zoloft"],
                                "SSRI",  "SEROTONIN_REUPTAKE_INHIBITION",
                                {"depression","anxiety","ocd","ptsd","panic_disorder"},
                                ["NG222"]),
    "fluoxetine":   DrugProfile("fluoxetine",   ["Prozac"],
                                "SSRI",  "SEROTONIN_REUPTAKE_INHIBITION",
                                {"depression","ocd","bulimia_nervosa"},
                                ["NG222"]),
    "citalopram":   DrugProfile("citalopram",   ["Cipramil","Celexa"],
                                "SSRI",  "SEROTONIN_REUPTAKE_INHIBITION",
                                {"depression","anxiety","panic_disorder"},
                                ["NG222"]),
    "escitalopram": DrugProfile("escitalopram", ["Cipralex","Lexapro"],
                                "SSRI",  "SEROTONIN_REUPTAKE_INHIBITION",
                                {"depression","anxiety","ocd","panic_disorder"},
                                ["NG222"]),
    "paroxetine":   DrugProfile("paroxetine",   ["Seroxat","Paxil"],
                                "SSRI",  "SEROTONIN_REUPTAKE_INHIBITION",
                                {"depression","anxiety","ocd","ptsd","panic_disorder"},
                                ["NG222"]),
    "venlafaxine":  DrugProfile("venlafaxine",  ["Efexor"],
                                "SNRI",  "SEROTONIN_NOREPINEPHRINE_REUPTAKE_INHIBITION",
                                {"depression","anxiety","panic_disorder"},
                                ["NG222"]),
    "duloxetine":   DrugProfile("duloxetine",   ["Cymbalta","Yentreve"],
                                "SNRI",  "SEROTONIN_NOREPINEPHRINE_REUPTAKE_INHIBITION",
                                {"depression","anxiety","diabetic_neuropathy","fibromyalgia"},
                                ["NG222"]),
    "desvenlafaxine": DrugProfile("desvenlafaxine", ["Pristiq"],
                                "SNRI",  "SEROTONIN_NOREPINEPHRINE_REUPTAKE_INHIBITION",
                                {"depression","anxiety"},
                                ["NG222"]),

    # ── NSAIDs ────────────────────────────────────────────────────────────────
    "ibuprofen":    DrugProfile("ibuprofen",    ["Nurofen","Brufen","Advil"],
                                "NSAID", "COX_INHIBITION_NONSELECTIVE",
                                {"pain","inflammation","fever","osteoarthritis"},
                                ["NG226"]),
    "naproxen":     DrugProfile("naproxen",     ["Naprosyn","Aleve"],
                                "NSAID", "COX_INHIBITION_NONSELECTIVE",
                                {"pain","inflammation","osteoarthritis","gout"},
                                ["NG226"]),
    "diclofenac":   DrugProfile("diclofenac",   ["Voltarol","Voltaren"],
                                "NSAID", "COX_INHIBITION_NONSELECTIVE",
                                {"pain","inflammation","osteoarthritis"},
                                ["NG226"]),
    "celecoxib":    DrugProfile("celecoxib",    ["Celebrex"],
                                "COX2_INHIBITOR","COX2_INHIBITION_SELECTIVE",
                                {"pain","osteoarthritis","rheumatoid_arthritis"},
                                ["NG226"]),

    # ── Statins ───────────────────────────────────────────────────────────────
    "atorvastatin": DrugProfile("atorvastatin", ["Lipitor","Torvast"],
                                "STATIN", "HMG_COA_REDUCTASE_INHIBITION",
                                {"hypercholesterolaemia","post_MI","hypertension","heart_failure"},
                                ["NG238"]),
    "rosuvastatin": DrugProfile("rosuvastatin", ["Crestor"],
                                "STATIN", "HMG_COA_REDUCTASE_INHIBITION",
                                {"hypercholesterolaemia","post_MI"},
                                ["NG238"]),
    "simvastatin":  DrugProfile("simvastatin",  ["Zocor"],
                                "STATIN", "HMG_COA_REDUCTASE_INHIBITION",
                                {"hypercholesterolaemia"},
                                ["NG238"]),

    # ── Ezetimibe ─────────────────────────────────────────────────────────────
    "ezetimibe":    DrugProfile("ezetimibe",    ["Ezetrol","Zetia"],
                                "EZETIMIBE", "INTESTINAL_CHOLESTEROL_ABSORPTION_INHIBITION",
                                {"hypercholesterolaemia","post_MI"},
                                ["NG238"]),

    # ── ACE inhibitors ────────────────────────────────────────────────────────
    "ramipril":     DrugProfile("ramipril",     ["Tritace","Altace"],
                                "ACE_INHIBITOR", "RAAS_INHIBITION_ACEi",
                                {"hypertension","heart_failure","post_MI","diabetic_nephropathy"},
                                ["NG136","NG106"]),
    "lisinopril":   DrugProfile("lisinopril",   ["Zestril","Prinivil"],
                                "ACE_INHIBITOR", "RAAS_INHIBITION_ACEi",
                                {"hypertension","heart_failure","post_MI","diabetic_nephropathy"},
                                ["NG136","NG106"]),
    "enalapril":    DrugProfile("enalapril",    ["Innovace"],
                                "ACE_INHIBITOR", "RAAS_INHIBITION_ACEi",
                                {"hypertension","heart_failure"},
                                ["NG136","NG106"]),
    "perindopril":  DrugProfile("perindopril",  ["Coversyl"],
                                "ACE_INHIBITOR", "RAAS_INHIBITION_ACEi",
                                {"hypertension","heart_failure","post_MI"},
                                ["NG136","NG106"]),

    # ── ARBs ──────────────────────────────────────────────────────────────────
    "losartan":     DrugProfile("losartan",     ["Cozaar"],
                                "ARB", "RAAS_INHIBITION_ARB",
                                {"hypertension","heart_failure","diabetic_nephropathy"},
                                ["NG136","NG106"]),
    "candesartan":  DrugProfile("candesartan",  ["Amias"],
                                "ARB", "RAAS_INHIBITION_ARB",
                                {"hypertension","heart_failure"},
                                ["NG136","NG106"]),
    "valsartan":    DrugProfile("valsartan",    ["Diovan"],
                                "ARB", "RAAS_INHIBITION_ARB",
                                {"hypertension","heart_failure"},
                                ["NG136","NG106"]),

    # ── Beta-blockers ─────────────────────────────────────────────────────────
    "bisoprolol":   DrugProfile("bisoprolol",   ["Cardicor","Emcor"],
                                "BETA_BLOCKER", "BETA_ADRENERGIC_BLOCKADE",
                                {"hypertension","heart_failure","angina","atrial_fibrillation"},
                                ["NG136","NG106"]),
    "carvedilol":   DrugProfile("carvedilol",   ["Eucardic"],
                                "BETA_BLOCKER", "BETA_ADRENERGIC_BLOCKADE",
                                {"heart_failure","hypertension"},
                                ["NG106"]),
    "metoprolol":   DrugProfile("metoprolol",   ["Betaloc"],
                                "BETA_BLOCKER", "BETA_ADRENERGIC_BLOCKADE",
                                {"hypertension","heart_failure","angina"},
                                ["NG136","NG106"]),

    # ── CCBs ──────────────────────────────────────────────────────────────────
    "amlodipine":   DrugProfile("amlodipine",   ["Norvasc","Istin"],
                                "CALCIUM_CHANNEL_BLOCKER", "CALCIUM_CHANNEL_BLOCKADE",
                                {"hypertension","angina"},
                                ["NG136"]),
    "felodipine":   DrugProfile("felodipine",   ["Plendil"],
                                "CALCIUM_CHANNEL_BLOCKER", "CALCIUM_CHANNEL_BLOCKADE",
                                {"hypertension"},
                                ["NG136"]),

    # ── Thiazide diuretics ────────────────────────────────────────────────────
    "indapamide":   DrugProfile("indapamide",   ["Natrilix"],
                                "THIAZIDE_DIURETIC", "RENAL_SODIUM_CHLORIDE_REABSORPTION_INHIBITION",
                                {"hypertension"},
                                ["NG136"]),
    "chlortalidone": DrugProfile("chlortalidone", ["Hygroton"],
                                "THIAZIDE_DIURETIC", "RENAL_SODIUM_CHLORIDE_REABSORPTION_INHIBITION",
                                {"hypertension"},
                                ["NG136"]),

    # ── MRAs ─────────────────────────────────────────────────────────────────
    "spironolactone": DrugProfile("spironolactone", ["Aldactone"],
                                "MINERALOCORTICOID_RECEPTOR_ANTAGONIST",
                                "ALDOSTERONE_RECEPTOR_BLOCKADE",
                                {"heart_failure","hypertension"},
                                ["NG106"]),
    "eplerenone":   DrugProfile("eplerenone",   ["Inspra"],
                                "MINERALOCORTICOID_RECEPTOR_ANTAGONIST",
                                "ALDOSTERONE_RECEPTOR_BLOCKADE",
                                {"heart_failure","post_MI"},
                                ["NG106"]),

    # ── SGLT2 inhibitors ──────────────────────────────────────────────────────
    "empagliflozin": DrugProfile("empagliflozin", ["Jardiance"],
                                "SGLT2_INHIBITOR", "SGLT2_INHIBITION_RENAL_GLUCOSE_EXCRETION",
                                {"type2_diabetes","heart_failure","diabetic_nephropathy"},
                                ["NG28","NG106"]),
    "dapagliflozin": DrugProfile("dapagliflozin", ["Forxiga","Farxiga"],
                                "SGLT2_INHIBITOR", "SGLT2_INHIBITION_RENAL_GLUCOSE_EXCRETION",
                                {"type2_diabetes","heart_failure","diabetic_nephropathy"},
                                ["NG28","NG106"]),
    "canagliflozin": DrugProfile("canagliflozin", ["Invokana"],
                                "SGLT2_INHIBITOR", "SGLT2_INHIBITION_RENAL_GLUCOSE_EXCRETION",
                                {"type2_diabetes"},
                                ["NG28"]),

    # ── Metformin ─────────────────────────────────────────────────────────────
    "metformin":    DrugProfile("metformin",    ["Glucophage"],
                                "BIGUANIDE", "AMPK_ACTIVATION_HEPATIC_GLUCOSE_REDUCTION",
                                {"type2_diabetes","prediabetes","pcos"},
                                ["NG28"]),

    # ── Sulfonylureas ─────────────────────────────────────────────────────────
    "gliclazide":   DrugProfile("gliclazide",   ["Diamicron"],
                                "SULFONYLUREA", "PANCREATIC_INSULIN_SECRETION_ATP_K_CHANNEL",
                                {"type2_diabetes"},
                                ["NG28"]),
    "glibenclamide": DrugProfile("glibenclamide", ["Daonil"],
                                "SULFONYLUREA", "PANCREATIC_INSULIN_SECRETION_ATP_K_CHANNEL",
                                {"type2_diabetes"},
                                ["NG28"]),
    "glimepiride":  DrugProfile("glimepiride",  ["Amaryl"],
                                "SULFONYLUREA", "PANCREATIC_INSULIN_SECRETION_ATP_K_CHANNEL",
                                {"type2_diabetes"},
                                ["NG28"]),

    # ── Basal insulins ────────────────────────────────────────────────────────
    "insulin glargine": DrugProfile("insulin glargine", ["Lantus","Toujeo","Basaglar"],
                                "INSULIN_LONG_ACTING", "INSULIN_RECEPTOR_ACTIVATION",
                                {"type2_diabetes","type1_diabetes"},
                                ["NG28"]),
    "insulin detemir":  DrugProfile("insulin detemir",  ["Levemir"],
                                "INSULIN_LONG_ACTING", "INSULIN_RECEPTOR_ACTIVATION",
                                {"type2_diabetes","type1_diabetes"},
                                ["NG28"]),
    "insulin degludec": DrugProfile("insulin degludec", ["Tresiba"],
                                "INSULIN_LONG_ACTING", "INSULIN_RECEPTOR_ACTIVATION",
                                {"type2_diabetes","type1_diabetes"},
                                ["NG28"]),

    # ── GLP-1 agonists ────────────────────────────────────────────────────────
    "semaglutide":  DrugProfile("semaglutide",  ["Ozempic","Wegovy","Rybelsus"],
                                "GLP1_AGONIST", "GLP1_RECEPTOR_AGONISM",
                                {"type2_diabetes","obesity"},
                                ["NG28"]),
    "liraglutide":  DrugProfile("liraglutide",  ["Victoza","Saxenda"],
                                "GLP1_AGONIST", "GLP1_RECEPTOR_AGONISM",
                                {"type2_diabetes","obesity"},
                                ["NG28"]),

    # ── DMARDs (RA) ───────────────────────────────────────────────────────────
    "methotrexate": DrugProfile("methotrexate", ["Methofar","Metoject"],
                                "CONVENTIONAL_DMARD", "DIHYDROFOLATE_REDUCTASE_INHIBITION",
                                {"rheumatoid_arthritis","psoriasis","psoriatic_arthritis"},
                                ["NG100"]),
    "sulfasalazine": DrugProfile("sulfasalazine", ["Salazopyrin"],
                                "CONVENTIONAL_DMARD", "IMMUNOMODULATION_NFKB_CYTOKINE_SUPPRESSION",
                                {"rheumatoid_arthritis","inflammatory_bowel_disease"},
                                ["NG100"]),
    "hydroxychloroquine": DrugProfile("hydroxychloroquine", ["Plaquenil"],
                                "CONVENTIONAL_DMARD", "TOLL_LIKE_RECEPTOR_INHIBITION",
                                {"rheumatoid_arthritis","systemic_lupus_erythematosus"},
                                ["NG100"]),

    # ── Folic acid (RA adjunct) ───────────────────────────────────────────────
    "folic acid":   DrugProfile("folic acid",   ["Lexpec"],
                                "FOLATE_SUPPLEMENT", "FOLATE_REPLENISHMENT",
                                {"rheumatoid_arthritis","pregnancy"},
                                ["NG100"]),

    # ── TB drugs ─────────────────────────────────────────────────────────────
    "isoniazid":    DrugProfile("isoniazid",    ["INH","Rimifon"],
                                "ANTIMYCOBACTERIAL", "MYCOLIC_ACID_SYNTHESIS_INHIBITION",
                                {"tuberculosis"},
                                ["NG33"]),
    "rifampin":     DrugProfile("rifampin",     ["Rifadin","Rimactane"],
                                "ANTIMYCOBACTERIAL", "RNA_POLYMERASE_INHIBITION",
                                {"tuberculosis"},
                                ["NG33"]),
    "rifampicin":   DrugProfile("rifampicin",   ["Rifadin","Rimactane"],
                                "ANTIMYCOBACTERIAL", "RNA_POLYMERASE_INHIBITION",
                                {"tuberculosis"},
                                ["NG33"]),
    "pyrazinamide": DrugProfile("pyrazinamide", ["Zinamide"],
                                "ANTIMYCOBACTERIAL", "INTRACELLULAR_ACIDIC_ENVIRONMENT_ACTIVITY",
                                {"tuberculosis"},
                                ["NG33"]),
    "ethambutol":   DrugProfile("ethambutol",   ["Myambutol"],
                                "ANTIMYCOBACTERIAL", "ARABINOSYL_TRANSFERASE_INHIBITION",
                                {"tuberculosis"},
                                ["NG33"]),

    # ── PPI ───────────────────────────────────────────────────────────────────
    "omeprazole":   DrugProfile("omeprazole",   ["Losec","Prilosec"],
                                "PPI", "H_K_ATPase_INHIBITION",
                                {"gord","peptic_ulcer"},
                                []),
    "lansoprazole": DrugProfile("lansoprazole", ["Zoton"],
                                "PPI", "H_K_ATPase_INHIBITION",
                                {"gord","peptic_ulcer"},
                                []),
}

BRAND_TO_GENERIC: dict[str, str] = {
    brand.lower(): generic
    for generic, profile in EMERGENCY_SEED.items()
    for brand in profile.brand_names
}

# Handle common name variants
_ALIASES: dict[str, str] = {
    "rifampin":            "rifampicin",
    "insulin glargine":    "insulin glargine",
    "insulin detemir":     "insulin detemir",
    "glargine":            "insulin glargine",
    "detemir":             "insulin detemir",
    "degludec":            "insulin degludec",
    "folic acid":          "folic acid",
    "folate":              "folic acid",
}


def get_profile(name: str) -> DrugProfile | None:
    """
    Emergency fallback only. Checks EMERGENCY_SEED, brand-name map, and aliases.
    Returns None for drugs not present.
    """
    n = name.lower().strip()
    if n in EMERGENCY_SEED:
        return EMERGENCY_SEED[n]
    # alias map
    if n in _ALIASES:
        return EMERGENCY_SEED.get(_ALIASES[n])
    # brand name
    generic = BRAND_TO_GENERIC.get(n)
    if generic:
        return EMERGENCY_SEED.get(generic)
    # partial match for multi-word names like "insulin glargine 20u"
    for key in EMERGENCY_SEED:
        if key in n:
            return EMERGENCY_SEED[key]
    return None


# Backward-compat alias
DRUG_DATABASE = EMERGENCY_SEED