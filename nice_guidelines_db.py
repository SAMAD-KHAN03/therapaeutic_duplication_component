"""
nice_guidelines_db.py
---------------------
Curated static NICE combination-rule library.

Covers all 10 TD test cases from the validated case scenario spreadsheet:

  TD_1  Dual antihypertensive (ACEi + CCB + Thiazide)  → NG136  SUPPORTED
  TD_2  Statin + Ezetimibe                              → NG238  SUPPORTED
  TD_3  HFrEF quad therapy (ACEi + BB + MRA + SGLT2)   → NG106  SUPPORTED
  TD_4  T2DM triple therapy (Metformin + SGLT2 + SU)   → NG28   SUPPORTED
  TD_5  RA csDMARD combo (MTX + SSZ)                   → NG100  SUPPORTED
  TD_6  TB quad therapy (HRZE)                         → NG33   SUPPORTED
  TD_7  Dual NSAID                                     → NG226  NOT_RECOMMENDED
  TA_8  Dual ACE inhibitor                             → NG136  NOT_RECOMMENDED
  TA_9  Dual SSRI                                      → NG222  NOT_RECOMMENDED
  TA_10 Dual basal insulin                             → NG28   NOT_RECOMMENDED

All drug_a / drug_b values are the canonical drug_class strings produced by
FDADrugResolver so matching is class-level (bidirectional).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class CombinationRule:
    drug_a: str           # canonical drug_class or drug name
    drug_b: str
    indication: str
    recommendation: str   # SUPPORTED | CONDITIONAL | NOT_RECOMMENDED | CONTRAINDICATED
    recommendation_text: str
    strength: str         # Strong | Conditional
    section_ref: str
    url: str
    rationale: str
    conditions: List[str] = field(default_factory=list)


@dataclass
class NICEGuideline:
    code: str
    title: str
    url: str
    combination_rules: List[CombinationRule]


# ──────────────────────────────────────────────────────────────────────────────
# NG136 – Hypertension in adults (2019, updated 2023)
# ──────────────────────────────────────────────────────────────────────────────
NG136_RULES = [

    # TD_1: ACEi + CCB → SUPPORTED (step 2)
    CombinationRule(
        drug_a="ACE_INHIBITOR",
        drug_b="CALCIUM_CHANNEL_BLOCKER",
        indication="hypertension",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG136 recommends offering a combination of an ACE inhibitor (or ARB) "
            "AND a calcium-channel blocker as step-2 antihypertensive therapy when "
            "blood pressure is not controlled on monotherapy."
        ),
        strength="Strong",
        section_ref="NG136 §1.4 – Step 2",
        url="https://www.nice.org.uk/guidance/ng136",
        rationale=(
            "Each agent targets a distinct BP-regulating mechanism: ACEi reduces "
            "angiotensin II–mediated vasoconstriction; CCBs vasodilate peripheral "
            "arterioles via L-type calcium channel blockade. Combination provides "
            "additive antihypertensive effect with complementary tolerability."
        ),
        conditions=["Blood pressure above target on monotherapy"],
    ),

    # TD_1: ACEi + CCB + Thiazide → SUPPORTED (step 3)
    CombinationRule(
        drug_a="ACE_INHIBITOR",
        drug_b="THIAZIDE_DIURETIC",
        indication="hypertension",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG136 recommends adding a thiazide-like diuretic (e.g. indapamide) "
            "to ACEi/ARB + CCB as step-3 triple therapy when blood pressure remains "
            "above target on dual therapy."
        ),
        strength="Strong",
        section_ref="NG136 §1.4 – Step 3",
        url="https://www.nice.org.uk/guidance/ng136",
        rationale=(
            "Thiazide-like diuretics reduce plasma volume and sodium retention, "
            "complementing the vasodilatory mechanisms of ACEi and CCB. "
            "Triple therapy is standard-of-care in resistant hypertension."
        ),
        conditions=["Blood pressure above target on dual therapy (ACEi/ARB + CCB)"],
    ),

    CombinationRule(
        drug_a="CALCIUM_CHANNEL_BLOCKER",
        drug_b="THIAZIDE_DIURETIC",
        indication="hypertension",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG136 step-3 therapy: CCB + thiazide-like diuretic is part of the "
            "recommended triple combination ACEi/ARB + CCB + thiazide-like diuretic."
        ),
        strength="Strong",
        section_ref="NG136 §1.4 – Step 3",
        url="https://www.nice.org.uk/guidance/ng136",
        rationale="Complementary mechanisms; CCB vasodilates, thiazide reduces volume.",
        conditions=["As part of triple therapy per NG136 step 3"],
    ),

    # TA_8: Dual ACE inhibitor → NOT_RECOMMENDED
    CombinationRule(
        drug_a="ACE_INHIBITOR",
        drug_b="ACE_INHIBITOR",
        indication="hypertension",
        recommendation="NOT_RECOMMENDED",
        recommendation_text=(
            "NICE NG136 does not support combining two ACE inhibitors (or an ACEi with "
            "an ARB) for hypertension. Both agents block the same RAAS pathway (ACE "
            "inhibition), providing no additional blood-pressure reduction beyond "
            "uptitrating one agent, while significantly increasing risks of "
            "hyperkalaemia, acute kidney injury, and symptomatic hypotension."
        ),
        strength="Strong",
        section_ref="NG136 §1.4 – Pharmacological management",
        url="https://www.nice.org.uk/guidance/ng136/chapter/Recommendations#pharmacological-management",
        rationale=(
            "Dual RAAS blockade at the same enzymatic target is pharmacologically "
            "redundant. NICE explicitly advises against ACEi + ARB combination; "
            "dual ACE inhibitors carry identical mechanistic and safety concerns."
        ),
        conditions=[],
    ),

    # ACEi + ARB also not recommended (same RAAS mechanism)
    CombinationRule(
        drug_a="ACE_INHIBITOR",
        drug_b="ARB",
        indication="hypertension",
        recommendation="NOT_RECOMMENDED",
        recommendation_text=(
            "NICE NG136 does not recommend combining an ACE inhibitor with an ARB "
            "(dual RAAS blockade) for hypertension. Increased risk of hyperkalaemia, "
            "AKI, and hypotension without clinically meaningful additional BP reduction."
        ),
        strength="Strong",
        section_ref="NG136 §1.4",
        url="https://www.nice.org.uk/guidance/ng136",
        rationale="Dual RAAS blockade: same pathway, additive adverse effects, no benefit.",
        conditions=[],
    ),
]

# ──────────────────────────────────────────────────────────────────────────────
# NG238 – Cardiovascular disease: risk assessment and reduction (2023)
# ──────────────────────────────────────────────────────────────────────────────
NG238_RULES = [

    # TD_2: Statin + Ezetimibe → SUPPORTED
    CombinationRule(
        drug_a="STATIN",
        drug_b="EZETIMIBE",
        indication="hypercholesterolaemia",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG238 recommends adding ezetimibe to a maximally tolerated statin "
            "when LDL-cholesterol remains above the treatment threshold in secondary "
            "prevention (post-MI, stroke, or established atherosclerotic CVD). "
            "The combination produces greater LDL reduction than either agent alone."
        ),
        strength="Strong",
        section_ref="NG238 §1.4 – Lipid-lowering therapy",
        url="https://www.nice.org.uk/guidance/ng238/chapter/1-Recommendations",
        rationale=(
            "Statins inhibit hepatic cholesterol synthesis (HMG-CoA reductase); "
            "ezetimibe inhibits intestinal cholesterol absorption (NPC1L1 transporter). "
            "Complementary mechanisms produce additive ~25% further LDL reduction "
            "and improved cardiovascular outcomes in secondary prevention."
        ),
        conditions=[
            "LDL-C above treatment target despite maximally tolerated statin",
            "Secondary prevention (established CVD or equivalent high risk)",
        ],
    ),
]

# ──────────────────────────────────────────────────────────────────────────────
# NG106 – Chronic heart failure in adults (2018, updated 2023)
# ──────────────────────────────────────────────────────────────────────────────
NG106_RULES = [

    # TD_3: ACEi + Beta-blocker → SUPPORTED
    CombinationRule(
        drug_a="ACE_INHIBITOR",
        drug_b="BETA_BLOCKER",
        indication="heart_failure",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG106 recommends offering both an ACE inhibitor AND a beta-blocker "
            "licensed for heart failure to all patients with HFrEF (LVEF ≤40%) to "
            "reduce mortality and hospitalisation."
        ),
        strength="Strong",
        section_ref="NG106 §1.3 – Pharmacological treatment for HFrEF",
        url="https://www.nice.org.uk/guidance/ng106",
        rationale=(
            "ACEi reduces afterload via RAAS blockade; beta-blockers reduce sympathetic "
            "activation and heart rate. Mechanisms are distinct and mortality benefits "
            "are additive. Both are first-line in all HFrEF guidelines."
        ),
        conditions=["HFrEF (LVEF ≤40%)"],
    ),

    # TD_3: ACEi + MRA (spironolactone) → SUPPORTED
    CombinationRule(
        drug_a="ACE_INHIBITOR",
        drug_b="MINERALOCORTICOID_RECEPTOR_ANTAGONIST",
        indication="heart_failure",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG106 recommends adding a mineralocorticoid receptor antagonist (MRA) "
            "such as spironolactone or eplerenone to ACEi + beta-blocker in patients "
            "with HFrEF who remain symptomatic (NYHA class II–IV) to further reduce "
            "mortality and hospitalisation."
        ),
        strength="Strong",
        section_ref="NG106 §1.3.6",
        url="https://www.nice.org.uk/guidance/ng106",
        rationale=(
            "MRAs block aldosterone, reducing fluid retention and cardiac remodelling "
            "via a pathway distinct from ACEi/ARB. The RALES and EMPHASIS-HF trials "
            "demonstrated significant mortality benefit added to background ACEi + BB."
        ),
        conditions=[
            "HFrEF LVEF ≤35%",
            "Symptomatic despite ACEi/ARB + beta-blocker",
            "Monitor potassium and renal function",
        ],
    ),

    # TD_3: Beta-blocker + MRA → SUPPORTED
    CombinationRule(
        drug_a="BETA_BLOCKER",
        drug_b="MINERALOCORTICOID_RECEPTOR_ANTAGONIST",
        indication="heart_failure",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG106 supports beta-blocker combined with MRA as part of guideline-"
            "directed medical therapy for HFrEF. Both are recommended concurrently "
            "with ACEi/ARB."
        ),
        strength="Strong",
        section_ref="NG106 §1.3",
        url="https://www.nice.org.uk/guidance/ng106",
        rationale="Distinct mechanisms (sympathetic blockade vs aldosterone blockade); mortality benefit additive.",
        conditions=["HFrEF LVEF ≤35%", "As part of triple/quadruple neurohormonal blockade"],
    ),

    # TD_3: ACEi + SGLT2i → SUPPORTED
    CombinationRule(
        drug_a="ACE_INHIBITOR",
        drug_b="SGLT2_INHIBITOR",
        indication="heart_failure",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG106 (2023 update) recommends adding an SGLT2 inhibitor (dapagliflozin "
            "or empagliflozin) to standard HFrEF therapy (ACEi/ARB + beta-blocker ± MRA) "
            "to reduce cardiovascular death and worsening heart failure."
        ),
        strength="Strong",
        section_ref="NG106 §1.3.9 (2023 update)",
        url="https://www.nice.org.uk/guidance/ng106",
        rationale=(
            "SGLT2 inhibitors reduce cardiac preload via natriuresis/osmotic diuresis "
            "and have direct cardioprotective effects independent of ACEi mechanism. "
            "DAPA-HF and EMPEROR-Reduced trials showed benefit on top of full GDMT."
        ),
        conditions=["HFrEF regardless of diabetes status"],
    ),

    # TD_3: Beta-blocker + SGLT2i → SUPPORTED
    CombinationRule(
        drug_a="BETA_BLOCKER",
        drug_b="SGLT2_INHIBITOR",
        indication="heart_failure",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG106 supports adding SGLT2 inhibitor to beta-blocker-based HFrEF "
            "regimen. SGLT2 inhibitors are recommended irrespective of diabetes status "
            "as add-on to maximally tolerated GDMT including beta-blockers."
        ),
        strength="Strong",
        section_ref="NG106 §1.3.9",
        url="https://www.nice.org.uk/guidance/ng106",
        rationale="SGLT2i and beta-blockers act on distinct pathways; benefit is additive in HFrEF.",
        conditions=["HFrEF regardless of diabetes status"],
    ),

    # TD_3: MRA + SGLT2i → SUPPORTED
    CombinationRule(
        drug_a="MINERALOCORTICOID_RECEPTOR_ANTAGONIST",
        drug_b="SGLT2_INHIBITOR",
        indication="heart_failure",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG106 supports MRA + SGLT2 inhibitor as part of quadruple therapy "
            "for HFrEF. Monitor potassium; SGLT2i may partially offset hyperkalaemia "
            "risk associated with MRA use."
        ),
        strength="Strong",
        section_ref="NG106 §1.3.9",
        url="https://www.nice.org.uk/guidance/ng106",
        rationale="MRA reduces aldosterone-driven remodelling; SGLT2i provides natriuresis and cardioprotection via separate pathways.",
        conditions=["HFrEF", "Monitor serum potassium and eGFR"],
    ),
]

# ──────────────────────────────────────────────────────────────────────────────
# NG28 – Type 2 diabetes in adults (2022)
# ──────────────────────────────────────────────────────────────────────────────
NG28_RULES = [

    # TD_4: Metformin + SGLT2i → SUPPORTED
    CombinationRule(
        drug_a="BIGUANIDE",
        drug_b="SGLT2_INHIBITOR",
        indication="type2_diabetes",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG28 recommends adding an SGLT2 inhibitor to metformin as a "
            "dual or triple oral therapy option for type 2 diabetes when HbA1c "
            "remains above 58 mmol/mol (7.5%) on metformin monotherapy, particularly "
            "when cardiovascular or renal comorbidities are present."
        ),
        strength="Strong",
        section_ref="NG28 §1.7 – Intensifying glucose-lowering therapy",
        url="https://www.nice.org.uk/guidance/ng28",
        rationale=(
            "Metformin activates AMPK reducing hepatic glucose production; SGLT2 "
            "inhibitors increase renal glucose excretion. Complementary mechanisms "
            "provide additive glycaemic control with additional cardiorenal benefits "
            "(SGLT2i class effect: HF hospitalisation ↓, CKD progression ↓)."
        ),
        conditions=[
            "HbA1c above 58 mmol/mol (7.5%) on metformin",
            "Consider SGLT2i first-line add-on in established CVD or high CV risk",
        ],
    ),

    # TD_4: Metformin + Sulfonylurea → SUPPORTED
    CombinationRule(
        drug_a="BIGUANIDE",
        drug_b="SULFONYLUREA",
        indication="type2_diabetes",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG28 supports adding a sulfonylurea (e.g. gliclazide) to metformin "
            "as a cost-effective intensification option when HbA1c remains above target. "
            "Counsel patients about hypoglycaemia risk, particularly with gliclazide MR."
        ),
        strength="Strong",
        section_ref="NG28 §1.7",
        url="https://www.nice.org.uk/guidance/ng28",
        rationale=(
            "Sulfonylureas stimulate pancreatic insulin secretion via ATP-sensitive K⁺ "
            "channel closure — a mechanism entirely distinct from metformin's AMPK "
            "activation. Combination provides additive glucose lowering."
        ),
        conditions=[
            "HbA1c above target on metformin monotherapy",
            "Counsel on hypoglycaemia risk",
        ],
    ),

    # TD_4: SGLT2i + Sulfonylurea → SUPPORTED (as part of triple)
    CombinationRule(
        drug_a="SGLT2_INHIBITOR",
        drug_b="SULFONYLUREA",
        indication="type2_diabetes",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG28 supports triple therapy with SGLT2 inhibitor + sulfonylurea "
            "(+ metformin) when dual therapy is insufficient. Distinct glucose-lowering "
            "mechanisms (renal excretion vs insulin secretion) allow combination use."
        ),
        strength="Strong",
        section_ref="NG28 §1.7",
        url="https://www.nice.org.uk/guidance/ng28",
        rationale="Renal glucose excretion (SGLT2i) and pancreatic insulin secretion (SU) are additive and mechanistically independent.",
        conditions=["As part of triple oral therapy; monitor for hypoglycaemia"],
    ),

    # TA_10: Dual basal insulin → NOT_RECOMMENDED
    CombinationRule(
        drug_a="INSULIN_LONG_ACTING",
        drug_b="INSULIN_LONG_ACTING",
        indication="type2_diabetes",
        recommendation="NOT_RECOMMENDED",
        recommendation_text=(
            "NICE NG28 recommends insulin therapy using a single appropriately titrated "
            "basal insulin agent. Combining two long-acting/basal insulins (e.g. insulin "
            "glargine + insulin detemir) provides no glycaemic advantage over optimally "
            "dosed monotherapy and substantially increases hypoglycaemia risk."
        ),
        strength="Strong",
        section_ref="NG28 §1.8 – Insulin therapy",
        url="https://www.nice.org.uk/guidance/ng28/chapter/1-Recommendations",
        rationale=(
            "Both agents are basal insulins acting via the same mechanism (insulin "
            "receptor activation reducing hepatic glucose output and increasing peripheral "
            "uptake). Doubling basal insulin coverage is pharmacologically redundant and "
            "increases hypoglycaemia risk without clinical benefit."
        ),
        conditions=[],
    ),
]

# ──────────────────────────────────────────────────────────────────────────────
# NG100 – Rheumatoid arthritis in adults (2018)
# ──────────────────────────────────────────────────────────────────────────────
NG100_RULES = [

    # TD_5: Methotrexate + Sulfasalazine → SUPPORTED
    CombinationRule(
        drug_a="CONVENTIONAL_DMARD",
        drug_b="CONVENTIONAL_DMARD",
        indication="rheumatoid_arthritis",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG100 recommends offering combination csDMARD therapy (e.g. "
            "methotrexate + sulfasalazine ± hydroxychloroquine — 'triple therapy') "
            "when disease activity is not controlled on methotrexate monotherapy, "
            "prior to escalation to biologic DMARDs."
        ),
        strength="Strong",
        section_ref="NG100 §1.3 – Conventional disease-modifying antirheumatic drugs",
        url="https://www.nice.org.uk/guidance/ng100",
        rationale=(
            "Methotrexate inhibits dihydrofolate reductase (anti-proliferative / "
            "anti-inflammatory via adenosine pathway); sulfasalazine has distinct "
            "immunomodulatory mechanisms (NF-κB inhibition, cytokine suppression). "
            "Combination improves ACR response rates vs monotherapy."
        ),
        conditions=[
            "Active RA not controlled on methotrexate monotherapy",
            "Supplement with folic acid (not on same day as methotrexate)",
        ],
    ),

    # TD_5: Methotrexate + Folic acid → SUPPORTED (supporting role)
    CombinationRule(
        drug_a="CONVENTIONAL_DMARD",
        drug_b="FOLATE_SUPPLEMENT",
        indication="rheumatoid_arthritis",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG100 recommends routinely prescribing folic acid supplementation "
            "alongside methotrexate to reduce gastrointestinal, haematological and "
            "hepatic adverse effects, without compromising efficacy."
        ),
        strength="Strong",
        section_ref="NG100 §1.3.4",
        url="https://www.nice.org.uk/guidance/ng100",
        rationale="Folic acid replenishes folate depleted by methotrexate, reducing toxicity while preserving therapeutic benefit.",
        conditions=["Do not take folic acid on the same day as methotrexate"],
    ),
]

# ──────────────────────────────────────────────────────────────────────────────
# NG33 – Tuberculosis (2016, updated 2019)
# ──────────────────────────────────────────────────────────────────────────────
NG33_RULES = [

    # TD_6: HRZE quad therapy → SUPPORTED (mandatory combination)
    CombinationRule(
        drug_a="ANTIMYCOBACTERIAL",
        drug_b="ANTIMYCOBACTERIAL",
        indication="tuberculosis",
        recommendation="SUPPORTED",
        recommendation_text=(
            "NICE NG33 mandates the standard four-drug initial phase regimen: "
            "isoniazid (H) + rifampicin (R) + pyrazinamide (Z) + ethambutol (E) "
            "for 2 months in pulmonary tuberculosis. This combination is not "
            "therapeutic duplication — it is the standard of care required to "
            "prevent resistance and achieve sterilisation."
        ),
        strength="Strong",
        section_ref="NG33 §1.3 – Standard treatment",
        url="https://www.nice.org.uk/guidance/ng33",
        rationale=(
            "Each drug targets a distinct step in mycobacterial metabolism: "
            "isoniazid (mycolic acid synthesis), rifampicin (RNA polymerase), "
            "pyrazinamide (acidic intracellular environment activity), ethambutol "
            "(arabinosyl transferase). Multi-drug therapy is mandatory to prevent "
            "acquired drug resistance; this is combination-by-necessity, not duplication."
        ),
        conditions=[
            "2-month intensive phase",
            "Followed by 4-month continuation phase (isoniazid + rifampicin)",
            "All four drugs given concurrently",
        ],
    ),
]

# ──────────────────────────────────────────────────────────────────────────────
# NG226 – Osteoarthritis in over 16s (2022)
# ──────────────────────────────────────────────────────────────────────────────
NG226_RULES = [

    # TD_7: Dual NSAID → NOT_RECOMMENDED
    CombinationRule(
        drug_a="NSAID",
        drug_b="NSAID",
        indication="osteoarthritis",
        recommendation="NOT_RECOMMENDED",
        recommendation_text=(
            "NICE NG226 recommends using one NSAID at the lowest effective dose for "
            "the shortest duration necessary in osteoarthritis. Combining two NSAIDs "
            "(e.g. ibuprofen + naproxen) provides no additional analgesic benefit "
            "beyond an optimally dosed single agent and markedly increases the risk "
            "of serious gastrointestinal bleeding, cardiovascular events, and renal "
            "injury."
        ),
        strength="Strong",
        section_ref="NG226 §Recommendations – Pharmacological management",
        url="https://www.nice.org.uk/guidance/ng226/chapter/Recommendations#pharmacological-management",
        rationale=(
            "Both agents inhibit cyclooxygenase non-selectively (COX-1 and COX-2), "
            "producing the same pharmacological effect via identical mechanisms. "
            "Analgesic ceiling is reached with appropriate monotherapy dosing; "
            "combining two NSAIDs only multiplies adverse effects without benefit."
        ),
        conditions=[],
    ),

    # Also flag dual NSAID for pain (not just OA)
    CombinationRule(
        drug_a="NSAID",
        drug_b="NSAID",
        indication="pain",
        recommendation="NOT_RECOMMENDED",
        recommendation_text=(
            "NICE guidance advises against combining two NSAIDs for any painful "
            "condition. Dual NSAID use doubles the risk of GI bleeding and renal "
            "injury without additional analgesic benefit."
        ),
        strength="Strong",
        section_ref="NG226 – Pharmacological management",
        url="https://www.nice.org.uk/guidance/ng226/chapter/Recommendations#pharmacological-management",
        rationale="Same COX inhibition mechanism; analgesic ceiling effect; compounded harm profile.",
        conditions=[],
    ),

    # COX2i + NSAID also not recommended
    CombinationRule(
        drug_a="NSAID",
        drug_b="COX2_INHIBITOR",
        indication="osteoarthritis",
        recommendation="NOT_RECOMMENDED",
        recommendation_text=(
            "Combining a non-selective NSAID with a COX-2 selective inhibitor is "
            "not recommended. The COX-1 protective effect of a selective COX-2 "
            "inhibitor is negated by concurrent non-selective NSAID use, while "
            "additive renal and cardiovascular risks persist."
        ),
        strength="Strong",
        section_ref="NG226 – Pharmacological management",
        url="https://www.nice.org.uk/guidance/ng226/chapter/Recommendations#pharmacological-management",
        rationale="Overlapping cyclooxygenase inhibition; no analgesic benefit; compounded harms.",
        conditions=[],
    ),
]

# ──────────────────────────────────────────────────────────────────────────────
# NG222 – Depression in adults (2022)
# ──────────────────────────────────────────────────────────────────────────────
NG222_RULES = [

    # TA_9: Dual SSRI → NOT_RECOMMENDED
    CombinationRule(
        drug_a="SSRI",
        drug_b="SSRI",
        indication="depression",
        recommendation="NOT_RECOMMENDED",
        recommendation_text=(
            "NICE NG222 does not support combining two SSRIs for major depressive "
            "disorder. Co-prescribing two agents from the same antidepressant class "
            "provides no additional antidepressant efficacy and significantly increases "
            "the risk of serotonin syndrome (agitation, hyperthermia, autonomic "
            "instability), as well as QT prolongation."
        ),
        strength="Strong",
        section_ref="NG222 §1.7 – Antidepressant medication",
        url="https://www.nice.org.uk/guidance/ng222/chapter/Recommendations",
        rationale=(
            "Both agents act via the same mechanism — inhibition of the serotonin "
            "reuptake transporter (SERT). Dual SERT blockade does not produce additive "
            "antidepressant benefit (receptor saturation is approached at therapeutic "
            "doses) but compounds serotonergic toxicity and adverse-effect burden."
        ),
        conditions=[],
    ),

    # SSRI + SNRI → conditional (use with caution, not outright contraindicated)
    CombinationRule(
        drug_a="SSRI",
        drug_b="SNRI",
        indication="depression",
        recommendation="NOT_RECOMMENDED",
        recommendation_text=(
            "NICE NG222 does not recommend routinely combining an SSRI with an SNRI. "
            "Both share serotonin reuptake inhibition as a core mechanism; co-use "
            "increases serotonin syndrome risk without clear evidence of superior "
            "antidepressant efficacy."
        ),
        strength="Strong",
        section_ref="NG222 §1.7",
        url="https://www.nice.org.uk/guidance/ng222/chapter/Recommendations",
        rationale="Shared SERT inhibition: additive serotonergic toxicity, no established additional efficacy.",
        conditions=[],
    ),
]

# ──────────────────────────────────────────────────────────────────────────────
# Master index
# ──────────────────────────────────────────────────────────────────────────────

NICE_GUIDELINES: Dict[str, NICEGuideline] = {

    "NG136": NICEGuideline(
        code="NG136",
        title="Hypertension in adults: diagnosis and management",
        url="https://www.nice.org.uk/guidance/ng136",
        combination_rules=NG136_RULES,
    ),

    "NG238": NICEGuideline(
        code="NG238",
        title="Cardiovascular disease: risk assessment and reduction, including lipid modification",
        url="https://www.nice.org.uk/guidance/ng238",
        combination_rules=NG238_RULES,
    ),

    "NG106": NICEGuideline(
        code="NG106",
        title="Chronic heart failure in adults: diagnosis and management",
        url="https://www.nice.org.uk/guidance/ng106",
        combination_rules=NG106_RULES,
    ),

    "NG28": NICEGuideline(
        code="NG28",
        title="Type 2 diabetes in adults: management",
        url="https://www.nice.org.uk/guidance/ng28",
        combination_rules=NG28_RULES,
    ),

    "NG100": NICEGuideline(
        code="NG100",
        title="Rheumatoid arthritis in adults: management",
        url="https://www.nice.org.uk/guidance/ng100",
        combination_rules=NG100_RULES,
    ),

    "NG33": NICEGuideline(
        code="NG33",
        title="Tuberculosis",
        url="https://www.nice.org.uk/guidance/ng33",
        combination_rules=NG33_RULES,
    ),

    "NG226": NICEGuideline(
        code="NG226",
        title="Osteoarthritis in over 16s: diagnosis and management",
        url="https://www.nice.org.uk/guidance/ng226",
        combination_rules=NG226_RULES,
    ),

    "NG222": NICEGuideline(
        code="NG222",
        title="Depression in adults: treatment and management",
        url="https://www.nice.org.uk/guidance/ng222",
        combination_rules=NG222_RULES,
    ),
}