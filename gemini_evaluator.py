"""
gemini_evaluator.py
-------------------
All Gemini API calls for the Therapeutic Duplication Checker.

Two public functions
---------------------
evaluate_combination(...)
    Takes a drug pair + all retrieved NICE guideline context (the RAG) and
    returns a structured clinical verdict:
        SUPPORTED | CONDITIONAL | NOT_RECOMMENDED | CONTRAINDICATED

classify_drug(...)
    Takes a drug name + whatever raw text FDA + RxNorm returned and asks
    Gemini to infer pharmacological class and MOA when local lookup tables
    produced UNKNOWN.

Environment variable
---------------------
    GEMINI_API_KEY   -- Google AI Studio key
                        https://aistudio.google.com/app/apikey

Optional overrides (also in .env)
-----------------------------------
    GEMINI_MODEL     -- default: gemini-1.5-flash
    GEMINI_TIMEOUT   -- default: 30

Fallback behaviour
------------------
If the SDK is missing, the API key is absent, or Gemini returns an
unparseable response, every public function returns a safe default so the
pipeline continues without crashing.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK
# ---------------------------------------------------------------------------
try:
    import google.generativeai as genai
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    logger.warning(
        "google-generativeai not installed. "
        "Run: ./venv/bin/pip install google-generativeai  "
        "Gemini calls will be skipped and safe fallback values returned."
    )

_MODEL_NAME     = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
_TIMEOUT        = int(os.getenv("GEMINI_TIMEOUT", "30"))
_RETRY_ATTEMPTS = 2
_RETRY_DELAY    = 2.0

_VALID_RECOMMENDATIONS = {"SUPPORTED", "CONDITIONAL", "NOT_RECOMMENDED", "CONTRAINDICATED"}

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------
_client: Optional[Any] = None


def _get_client() -> Optional[Any]:
    global _client
    if _client is not None:
        return _client
    if not _SDK_AVAILABLE:
        return None
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning(
            "GEMINI_API_KEY not set -- Gemini evaluation disabled. "
            "Add GEMINI_API_KEY=<key> to your .env file."
        )
        return None
    genai.configure(api_key=api_key)
    _client = genai.GenerativeModel(_MODEL_NAME)
    logger.info("Gemini client initialised (model: %s)", _MODEL_NAME)
    return _client


def _call_gemini(prompt: str) -> Optional[str]:
    """Send prompt, return raw text or None on failure."""
    client = _get_client()
    if client is None:
        return None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            response = client.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=1024,
                ),
            )
            return response.text.strip()
        except Exception as exc:
            logger.warning("Gemini attempt %d/%d failed: %s", attempt, _RETRY_ATTEMPTS, exc)
            if attempt < _RETRY_ATTEMPTS:
                time.sleep(_RETRY_DELAY)
    return None


def _parse_json(text: str) -> Optional[Dict]:
    """Extract JSON from a Gemini response, stripping markdown fences if present."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    logger.warning("Could not parse JSON from Gemini response: %.200s", text)
    return None


# ===========================================================================
# 1.  NICE RAG -> combination verdict
# ===========================================================================

_EVAL_SYSTEM = (
    "You are a senior clinical pharmacologist and NICE guideline analyst.\n\n"
    "Evaluate whether prescribing the two drugs listed below together is clinically "
    "appropriate, using the NICE guideline evidence provided (RAG context).\n\n"
    "Respond ONLY with a valid JSON object -- no markdown, no preamble, no text outside the JSON:\n\n"
    "{\n"
    '  "recommendation": "<SUPPORTED | CONDITIONAL | NOT_RECOMMENDED | CONTRAINDICATED>",\n'
    '  "strength": "<Strong | Moderate | Weak | Insufficient>",\n'
    '  "rationale": "<2-4 sentences citing the evidence provided>",\n'
    '  "conditions": ["<monitoring or dose condition if any>"],\n'
    '  "confidence": "<HIGH | MEDIUM | LOW>",\n'
    '  "nice_section": "<guideline code + section if identifiable, else empty string>"\n'
    "}\n\n"
    "Definitions:\n"
    "  SUPPORTED       -- explicitly recommended or standard care per the evidence\n"
    "  CONDITIONAL     -- acceptable only under specific clinical conditions / monitoring\n"
    "  NOT_RECOMMENDED -- should be avoided; evidence shows net harm or no added benefit\n"
    "  CONTRAINDICATED -- must not be combined; evidence shows serious risk\n\n"
    "If the evidence does not directly mention this combination, base your answer on "
    "the pharmacological classes and general clinical knowledge, set confidence to LOW, "
    "and note the absence of direct evidence in rationale."
)


def evaluate_combination(
    drug_a_name:        str,
    drug_a_class:       str,
    drug_a_moa:         str,
    drug_b_name:        str,
    drug_b_class:       str,
    drug_b_moa:         str,
    shared_indications: Set[str],
    guideline_contexts: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Send the drug pair + all retrieved NICE guideline text to Gemini and
    return a structured verdict dict.

    guideline_contexts: list of dicts with keys:
        source   -- guideline code or "NICE_SEARCH"
        title    -- document title
        section  -- section ref
        text     -- guideline text excerpt
        url      -- source URL

    Returns dict with keys:
        recommendation, strength, rationale, conditions,
        confidence, nice_section, gemini_used (bool)
    """
    if guideline_contexts:
        blocks = []
        for i, ctx in enumerate(guideline_contexts, 1):
            blocks.append(
                "--- Evidence %d ---\n"
                "Source  : %s\n"
                "Title   : %s\n"
                "Section : %s\n"
                "URL     : %s\n"
                "Content :\n%s\n"
                % (
                    i,
                    ctx.get("source", "NICE"),
                    ctx.get("title", ""),
                    ctx.get("section", ""),
                    ctx.get("url", ""),
                    ctx.get("text", ""),
                )
            )
        rag_text = "\n".join(blocks)
    else:
        rag_text = "No specific guideline evidence retrieved."

    indications_str = (
        ", ".join(sorted(shared_indications)) if shared_indications else "not specified"
    )

    prompt = "\n\n".join([
        _EVAL_SYSTEM,
        "=== DRUG COMBINATION ===\n\n"
        "Drug A : %s\n  Class : %s\n  MOA   : %s\n\n"
        "Drug B : %s\n  Class : %s\n  MOA   : %s\n\n"
        "Shared indications : %s"
        % (
            drug_a_name, drug_a_class, drug_a_moa,
            drug_b_name, drug_b_class, drug_b_moa,
            indications_str,
        ),
        "=== NICE GUIDELINE EVIDENCE (RAG) ===\n\n" + rag_text,
        "=== YOUR JSON VERDICT ===",
    ])

    logger.info(
        "Sending RAG to Gemini: %s + %s (%d block(s))",
        drug_a_name, drug_b_name, len(guideline_contexts),
    )

    raw     = _call_gemini(prompt)
    verdict = _parse_json(raw) if raw else None

    if verdict and verdict.get("recommendation") in _VALID_RECOMMENDATIONS:
        verdict["gemini_used"] = True
        verdict.setdefault("strength",     "Moderate")
        verdict.setdefault("conditions",   [])
        verdict.setdefault("confidence",   "MEDIUM")
        verdict.setdefault("nice_section", "")
        logger.info(
            "Gemini verdict: %s + %s -> %s (confidence=%s)",
            drug_a_name, drug_b_name,
            verdict["recommendation"], verdict.get("confidence"),
        )
        return verdict

    logger.warning(
        "Gemini evaluation failed for %s + %s -- using CONDITIONAL fallback",
        drug_a_name, drug_b_name,
    )
    return {
        "recommendation": "CONDITIONAL",
        "strength":       "Insufficient",
        "rationale": (
            "Gemini evaluation unavailable or returned an unparseable response. "
            "This combination requires manual clinical review using current BNF and SPC."
        ),
        "conditions":   ["Manual clinical review required"],
        "confidence":   "LOW",
        "nice_section": "",
        "gemini_used":  False,
    }


# ===========================================================================
# 2.  FDA + RxNorm raw text -> drug classification
# ===========================================================================

_CLASSIFY_SYSTEM = (
    "You are a clinical pharmacology expert.\n\n"
    "Given a drug name and any available pharmacological text, identify:\n"
    "  1. The canonical pharmacological class\n"
    "  2. The canonical mechanism of action\n\n"
    "Respond ONLY with a valid JSON object -- no markdown, no preamble:\n\n"
    "{\n"
    '  "drug_class": "<canonical class>",\n'
    '  "mechanism_of_action": "<canonical MOA>",\n'
    '  "confidence": "<HIGH | MEDIUM | LOW>",\n'
    '  "reasoning": "<1-2 sentences explaining your classification>"\n'
    "}\n\n"
    "Canonical drug_class values (use exactly where applicable, else UPPER_SNAKE_CASE):\n"
    "  ACE_INHIBITOR, ARB, ARNI, BETA_BLOCKER, CALCIUM_CHANNEL_BLOCKER,\n"
    "  STATIN, EZETIMIBE, VITAMIN_K_ANTAGONIST, DOAC_FACTOR_Xa_INHIBITOR,\n"
    "  DOAC_THROMBIN_INHIBITOR, SGLT2_INHIBITOR, GLP1_AGONIST, DPP4_INHIBITOR,\n"
    "  BIGUANIDE, SULFONYLUREA, INSULIN_LONG_ACTING, SSRI, SNRI, NSAID,\n"
    "  COX2_INHIBITOR, PPI, THIAZIDE_DIURETIC,\n"
    "  MINERALOCORTICOID_RECEPTOR_ANTAGONIST, CONVENTIONAL_DMARD,\n"
    "  ANTIMYCOBACTERIAL, FOLATE_SUPPLEMENT, UNKNOWN\n\n"
    "Canonical mechanism_of_action values (use exactly where applicable, else UPPER_SNAKE_CASE):\n"
    "  RAAS_INHIBITION_ACEi, RAAS_INHIBITION_ARB, RAAS_INHIBITION_ARNI,\n"
    "  BETA_ADRENERGIC_BLOCKADE, CALCIUM_CHANNEL_BLOCKADE,\n"
    "  HMG_COA_REDUCTASE_INHIBITION, INTESTINAL_CHOLESTEROL_ABSORPTION_INHIBITION,\n"
    "  VITAMIN_K_CYCLE_INHIBITION, FACTOR_Xa_INHIBITION_DIRECT,\n"
    "  DIRECT_THROMBIN_INHIBITION, SGLT2_INHIBITION_RENAL_GLUCOSE_EXCRETION,\n"
    "  GLP1_RECEPTOR_AGONISM, DPP4_INHIBITION_GLP1_AUGMENTATION,\n"
    "  AMPK_ACTIVATION_HEPATIC_GLUCOSE_REDUCTION,\n"
    "  PANCREATIC_INSULIN_SECRETION_ATP_K_CHANNEL, INSULIN_RECEPTOR_ACTIVATION,\n"
    "  SEROTONIN_REUPTAKE_INHIBITION, SEROTONIN_NOREPINEPHRINE_REUPTAKE_INHIBITION,\n"
    "  COX_INHIBITION_NONSELECTIVE, COX2_INHIBITION_SELECTIVE, H_K_ATPase_INHIBITION,\n"
    "  RENAL_SODIUM_CHLORIDE_REABSORPTION_INHIBITION, ALDOSTERONE_RECEPTOR_BLOCKADE,\n"
    "  DIHYDROFOLATE_REDUCTASE_INHIBITION, IMMUNOMODULATION,\n"
    "  ANTIMYCOBACTERIAL_ACTIVITY, UNKNOWN"
)


def classify_drug(
    drug_name:            str,
    raw_pharm_class:      List[str],
    rxnorm_classes:       List[str],
    fda_moa_text:         str,
    fda_description_text: str,
) -> Dict[str, str]:
    """
    Ask Gemini to classify a drug when local lookups gave UNKNOWN.

    Parameters
    ----------
    drug_name            : generic drug name
    raw_pharm_class      : pharm_class_epc + pharm_class_moa from FDA label
    rxnorm_classes       : class names from RxNorm RxClass API
    fda_moa_text         : mechanism_of_action / clinical_pharmacology from FDA
    fda_description_text : description text from FDA label

    Returns dict with keys:
        drug_class, mechanism_of_action, confidence, reasoning, gemini_used (bool)
    """
    prompt = "\n\n".join([
        _CLASSIFY_SYSTEM,
        "=== DRUG TO CLASSIFY ===\n\n"
        "Drug name         : %s\n"
        "FDA pharm class   : %s\n"
        "RxNorm drug class : %s\n"
        "FDA MOA text      : %s\n"
        "FDA description   : %s"
        % (
            drug_name,
            "; ".join(raw_pharm_class) or "not available",
            "; ".join(rxnorm_classes)  or "not available",
            fda_moa_text[:800]         or "not available",
            fda_description_text[:600] or "not available",
        ),
        "=== YOUR JSON CLASSIFICATION ===",
    ])

    logger.info("Asking Gemini to classify drug: %s", drug_name)

    raw    = _call_gemini(prompt)
    result = _parse_json(raw) if raw else None

    if result and result.get("drug_class") and result.get("mechanism_of_action"):
        result["gemini_used"] = True
        result.setdefault("confidence", "MEDIUM")
        result.setdefault("reasoning",  "")
        logger.info(
            "Gemini classified '%s': class=%s moa=%s (confidence=%s)",
            drug_name,
            result["drug_class"],
            result["mechanism_of_action"],
            result.get("confidence"),
        )
        return result

    logger.warning("Gemini classification failed for '%s'", drug_name)
    return {
        "drug_class":          "UNKNOWN",
        "mechanism_of_action": "UNKNOWN",
        "confidence":          "LOW",
        "reasoning":           "Gemini classification unavailable.",
        "gemini_used":         False,
    }
