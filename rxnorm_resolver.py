"""
rxnorm_resolver.py
------------------
Queries the NLM RxNorm + RxClass REST APIs to retrieve drug class and
mechanism of action for a drug name.

Used as Tier 3 in FDADrugResolver when the FDA label parser cannot resolve
drug_class or mechanism_of_action from local lookup tables.

All APIs are public -- no key required.

RxNorm base  : https://rxnav.nlm.nih.gov/REST
RxClass base : https://rxnav.nlm.nih.gov/REST/rxclass

Resolution steps inside get_rxnorm_classes()
---------------------------------------------
  1. /rxcui.json?name=<drug>           -- name -> RxCUI (exact match)
  2. /approximateTerm.json?term=<drug> -- fuzzy fallback if exact fails
  3. /rxcui/<id>/allrelated.json       -- unwrap branded/pack CUI -> ingredient CUI
  4. RxClass /class/byRxcui            -- EPC + MOA + PE + TC class types

Returns
-------
RxNormResult:
    rxcui          : str         -- RxNorm CUI (empty if not found)
    drug_classes   : List[str]   -- EPC / PE / TC class names
    moa_classes    : List[str]   -- MOA class names
    all_class_text : str         -- joined summary passed to Gemini
    found          : bool
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

RXNORM_BASE  = "https://rxnav.nlm.nih.gov/REST"
RXCLASS_BASE = "https://rxnav.nlm.nih.gov/REST/rxclass"
_TIMEOUT     = 10
_RATE_DELAY  = 0.3


@dataclass
class RxNormResult:
    rxcui:          str       = ""
    drug_classes:   List[str] = field(default_factory=list)
    moa_classes:    List[str] = field(default_factory=list)
    all_class_text: str       = ""
    found:          bool      = False


def _rx_get(url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    if params:
        url = "%s?%s" % (url, urlencode(params))
    req = Request(url, headers={
        "User-Agent": "TherapeuticDuplicationChecker/2.0",
        "Accept": "application/json",
    })
    try:
        time.sleep(_RATE_DELAY)
        with urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        if exc.code == 404:
            return None
        logger.warning("RxNorm HTTP %d: %s", exc.code, url)
        return None
    except URLError as exc:
        logger.warning("RxNorm unreachable: %s", exc.reason)
        return None
    except Exception as exc:
        logger.warning("RxNorm error: %s", exc)
        return None


def _resolve_rxcui(drug_name: str) -> Optional[str]:
    """Name -> RxCUI.  Tries exact match then approximate."""
    # Exact
    data = _rx_get("%s/rxcui.json" % RXNORM_BASE, {"name": drug_name, "allsrc": 0})
    if data:
        ids = data.get("idGroup", {}).get("rxnormId", [])
        if ids:
            logger.debug("RxNorm exact CUI for '%s': %s", drug_name, ids[0])
            return ids[0]

    # Approximate
    data = _rx_get(
        "%s/approximateTerm.json" % RXNORM_BASE,
        {"term": drug_name, "maxEntries": 5, "option": 0},
    )
    if data:
        candidates = data.get("approximateGroup", {}).get("candidate", [])
        if candidates:
            best = max(candidates, key=lambda c: int(c.get("score", 0)))
            rxcui = best.get("rxcui")
            if rxcui:
                logger.debug(
                    "RxNorm approximate CUI for '%s': %s (score=%s)",
                    drug_name, rxcui, best.get("score"),
                )
                return rxcui
    return None


def _ingredient_rxcui(rxcui: str) -> str:
    """
    Branded / clinical pack CUIs map to a product, not an ingredient.
    Class lookups live on the ingredient CUI -- unwrap if needed.
    """
    data = _rx_get("%s/rxcui/%s/allrelated.json" % (RXNORM_BASE, rxcui))
    if not data:
        return rxcui
    groups = data.get("allRelatedGroup", {}).get("conceptGroup", [])
    for group in groups:
        if group.get("tty") in ("IN", "PIN"):
            props = group.get("conceptProperties", [])
            if props:
                ing = props[0].get("rxcui", rxcui)
                if ing != rxcui:
                    logger.debug("RxNorm: unwrapped %s -> ingredient %s", rxcui, ing)
                return ing
    return rxcui


# Class types to query and which bucket they belong in
_CLASS_QUERIES = [
    ("EPC",    "drug_classes"),   # Established Pharmacologic Class
    ("MOA",    "moa_classes"),    # Mechanism of Action
    ("PE",     "drug_classes"),   # Physiologic Effect
    ("TC",     "drug_classes"),   # Therapeutic Category (VA)
    ("MESHPA", "drug_classes"),   # MeSH Pharmacological Action
]


def _fetch_rxclass(rxcui: str) -> Dict[str, List[str]]:
    drug_classes: List[str] = []
    moa_classes:  List[str] = []
    for class_type, bucket in _CLASS_QUERIES:
        data = _rx_get(
            "%s/class/byRxcui.json" % RXCLASS_BASE,
            {"rxcui": rxcui, "relaSource": class_type},
        )
        if not data:
            continue
        entries = (
            data.get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", [])
        )
        for entry in entries:
            name = entry.get("rxclassMinConceptItem", {}).get("className", "").strip()
            if not name:
                continue
            if bucket == "moa_classes":
                if name not in moa_classes:
                    moa_classes.append(name)
            else:
                if name not in drug_classes:
                    drug_classes.append(name)
    return {"drug_classes": drug_classes, "moa_classes": moa_classes}


def get_rxnorm_classes(drug_name: str) -> RxNormResult:
    """
    Main entry point.  Resolves drug_name through RxNorm + RxClass.

    Usage
    -----
    result = get_rxnorm_classes("metformin")
    if result.found:
        print(result.all_class_text)   # pass to gemini_evaluator.classify_drug()
    """
    rxcui = _resolve_rxcui(drug_name)
    if not rxcui:
        logger.info("RxNorm: no CUI found for '%s'", drug_name)
        return RxNormResult(found=False)

    ing_cui = _ingredient_rxcui(rxcui)
    classes = _fetch_rxclass(ing_cui)

    drug_classes = classes["drug_classes"]
    moa_classes  = classes["moa_classes"]

    if not drug_classes and not moa_classes:
        logger.info("RxNorm: CUI %s found for '%s' but no class data", ing_cui, drug_name)
        return RxNormResult(rxcui=ing_cui, found=False)

    parts = []
    if drug_classes:
        parts.append("Drug classes: " + "; ".join(drug_classes))
    if moa_classes:
        parts.append("Mechanisms of action: " + "; ".join(moa_classes))
    all_class_text = "  |  ".join(parts)

    logger.info("RxNorm resolved '%s' (CUI %s): %s", drug_name, ing_cui, all_class_text)
    return RxNormResult(
        rxcui=ing_cui,
        drug_classes=drug_classes,
        moa_classes=moa_classes,
        all_class_text=all_class_text,
        found=True,
    )
