"""
rxnorm_resolver.py
------------------
Queries the NLM RxNorm + RxClass REST APIs to retrieve pharmacological
class and mechanism of action for a drug name.

Tier 3 in FDADrugResolver -- called only when FDA local parsing gives UNKNOWN.

APIs (all public, no key required)
------------------------------------
  RxNorm  : https://rxnav.nlm.nih.gov/REST
  RxClass : https://rxnav.nlm.nih.gov/REST/rxclass

Resolution order inside get_rxnorm_classes()
---------------------------------------------
  1. /rxcui.json?name=<drug>           exact name -> RxCUI
  2. /approximateTerm.json             fuzzy fallback
  3. /rxcui/<id>/allrelated.json       unwrap branded/pack CUI -> ingredient CUI
  4. /rxclass/class/byRxcui.json       classTypes=EPC|MOA|PE|TC|MESHPA  (PRIMARY)
  5. /rxclass/class/byDrugName.json    same classTypes, by name (FALLBACK)

IMPORTANT -- correct RxClass parameter
----------------------------------------
  The parameter is  classTypes=EPC  (NOT relaSource=EPC).
  Using relaSource causes HTTP 400 Bad Request on every call.
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
_RATE_DELAY  = 0.25   # seconds between requests -- NLM rate limit is lenient


@dataclass
class RxNormResult:
    rxcui:          str       = ""
    drug_classes:   List[str] = field(default_factory=list)
    moa_classes:    List[str] = field(default_factory=list)
    all_class_text: str       = ""
    found:          bool      = False


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _rx_get(url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    if params:
        url = "%s?%s" % (url, urlencode(params))
    req = Request(url, headers={
        "User-Agent": "TherapeuticDuplicationChecker/2.0",
        "Accept":     "application/json",
    })
    try:
        time.sleep(_RATE_DELAY)
        with urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        # 400 = bad request, 404 = not found -- both non-fatal, log at DEBUG
        if exc.code in (400, 404):
            logger.debug("RxNorm/RxClass %d (skipped): %s", exc.code, url)
        else:
            logger.warning("RxNorm HTTP %d: %s", exc.code, url)
        return None
    except URLError as exc:
        logger.warning("RxNorm unreachable: %s", exc.reason)
        return None
    except Exception as exc:
        logger.warning("RxNorm error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Step 1+2 : name -> RxCUI
# ---------------------------------------------------------------------------

def _resolve_rxcui(drug_name: str) -> Optional[str]:
    # Exact match
    data = _rx_get("%s/rxcui.json" % RXNORM_BASE, {"name": drug_name, "allsrc": 0})
    if data:
        ids = data.get("idGroup", {}).get("rxnormId", [])
        if ids:
            logger.debug("RxNorm exact CUI for '%s': %s", drug_name, ids[0])
            return ids[0]

    # Fuzzy / approximate
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


# ---------------------------------------------------------------------------
# Step 3 : branded/pack CUI -> ingredient CUI
# ---------------------------------------------------------------------------

def _ingredient_rxcui(rxcui: str) -> str:
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


# ---------------------------------------------------------------------------
# Steps 4+5 : RxCUI / drug name -> classes via RxClass
#
# CORRECT parameter name: classTypes   (NOT relaSource -- that causes HTTP 400)
# ---------------------------------------------------------------------------

# (classType, bucket)
_CLASS_TYPES = [
    ("EPC",    "drug_classes"),   # Established Pharmacologic Class
    ("MOA",    "moa_classes"),    # Mechanism of Action
    ("PE",     "drug_classes"),   # Physiologic Effect
    ("TC",     "drug_classes"),   # Therapeutic Category (VA)
    ("MESHPA", "drug_classes"),   # MeSH Pharmacological Action
]


def _parse_rxclass_entries(data: Dict, bucket: str,
                            drug_classes: List[str],
                            moa_classes:  List[str]) -> None:
    entries = data.get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", [])
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


def _fetch_by_rxcui(rxcui: str) -> Dict[str, List[str]]:
    """Primary lookup: /rxclass/class/byRxcui.json?rxcui=X&classTypes=Y"""
    drug_classes: List[str] = []
    moa_classes:  List[str] = []
    for class_type, bucket in _CLASS_TYPES:
        data = _rx_get(
            "%s/class/byRxcui.json" % RXCLASS_BASE,
            {"rxcui": rxcui, "classTypes": class_type},   # classTypes -- NOT relaSource
        )
        if data:
            _parse_rxclass_entries(data, bucket, drug_classes, moa_classes)
    return {"drug_classes": drug_classes, "moa_classes": moa_classes}


def _fetch_by_drug_name(drug_name: str) -> Dict[str, List[str]]:
    """
    Fallback lookup: /rxclass/class/byDrugName.json?drugName=X&classTypes=Y
    Better coverage for drugs where the ingredient CUI has sparse RxClass data.
    """
    drug_classes: List[str] = []
    moa_classes:  List[str] = []
    for class_type, bucket in _CLASS_TYPES:
        data = _rx_get(
            "%s/class/byDrugName.json" % RXCLASS_BASE,
            {"drugName": drug_name, "classTypes": class_type},
        )
        if data:
            _parse_rxclass_entries(data, bucket, drug_classes, moa_classes)
    return {"drug_classes": drug_classes, "moa_classes": moa_classes}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_rxnorm_classes(drug_name: str) -> RxNormResult:
    """
    Resolve drug_name -> RxNorm CUI -> RxClass drug classes + MOA.

    Returns RxNormResult with found=True if at least one class was retrieved.
    """
    rxcui = _resolve_rxcui(drug_name)
    if not rxcui:
        logger.info("RxNorm: no CUI found for '%s'", drug_name)
        return RxNormResult(found=False)

    ing_cui = _ingredient_rxcui(rxcui)

    # Primary attempt: by CUI
    classes = _fetch_by_rxcui(ing_cui)

    # Fallback: by drug name (catches drugs with sparse CUI-based coverage)
    if not classes["drug_classes"] and not classes["moa_classes"]:
        logger.debug(
            "byRxcui returned nothing for CUI %s -- trying byDrugName for '%s'",
            ing_cui, drug_name,
        )
        classes = _fetch_by_drug_name(drug_name)

    drug_classes = classes["drug_classes"]
    moa_classes  = classes["moa_classes"]

    if not drug_classes and not moa_classes:
        logger.info(
            "RxNorm: CUI %s found for '%s' but RxClass returned no class data",
            ing_cui, drug_name,
        )
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
