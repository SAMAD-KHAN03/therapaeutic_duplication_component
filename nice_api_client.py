"""
nice_api_client.py
------------------
Fetches NICE guideline combination rules.

Resolution order:
  1. PostgreSQL cache (combination_rules table)
  2. Static curated rules (nice_guidelines_db.py)  <- primary source
  3. Live NICE Evidence Search API                 <- fallback when static returns nothing

Key features:
  - Bidirectional class-level matching (drug_a/drug_b are class strings)
  - Same-class detection (e.g. NSAID vs NSAID, SSRI vs SSRI)
  - Indication matching with "any" wildcard
  - Antimycobacterial multi-drug TB support
  - CONVENTIONAL_DMARD same-class + different MOA detection
  - All caching via PostgreSQL (no disk/memory cache)
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
class CombinationRule:
    drug_a: str
    drug_b: str
    indication: str
    recommendation: str
    recommendation_text: str
    strength: str
    section_ref: str
    url: str
    rationale: str
    conditions: List[str] = field(default_factory=list)


NICE_EVIDENCE_SEARCH_BASE = "https://api.nice.org.uk/services/search/documents"
_REQUEST_TIMEOUT_SECONDS  = 12
_RATE_LIMIT_DELAY_SECONDS = 0.3


class NICEAPIError(Exception):
    pass


def _nice_get(url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "TherapeuticDuplicationChecker/2.0",
                                "Accept": "application/json"})
    try:
        time.sleep(_RATE_LIMIT_DELAY_SECONDS)
        with urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        if exc.code in (404, 410):
            return None
        raise NICEAPIError(f"NICE API HTTP {exc.code}: {url}") from exc
    except URLError as exc:
        logger.warning("NICE API unreachable (%s).", exc.reason)
        return None


def _load_static_rules() -> List[Tuple[str, CombinationRule]]:
    try:
        from nice_guidelines_db import NICE_GUIDELINES, CombinationRule as StaticRule
        results = []
        for code, guideline in NICE_GUIDELINES.items():
            for rule in guideline.combination_rules:
                results.append((code, CombinationRule(
                    drug_a=rule.drug_a,
                    drug_b=rule.drug_b,
                    indication=rule.indication,
                    recommendation=rule.recommendation,
                    recommendation_text=rule.recommendation_text,
                    strength=rule.strength,
                    section_ref=rule.section_ref,
                    url=rule.url,
                    rationale=rule.rationale,
                    conditions=list(rule.conditions),
                )))
        return results
    except ImportError:
        logger.warning("nice_guidelines_db not found; static rules unavailable.")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Serialisation helpers for PostgreSQL storage
# ──────────────────────────────────────────────────────────────────────────────

def _rule_to_dict(rule: CombinationRule) -> Dict:
    return {**rule.__dict__, "conditions": list(rule.conditions)}


def _rule_from_dict(d: Dict) -> CombinationRule:
    d = d.copy()
    d["conditions"] = list(d.get("conditions", []))
    return CombinationRule(**d)


def _results_to_json(results: List[Tuple[str, CombinationRule]]) -> List[Dict]:
    return [{"code": code, "rule": _rule_to_dict(rule)} for code, rule in results]


def _results_from_json(data: List[Dict]) -> List[Tuple[str, CombinationRule]]:
    return [(item["code"], _rule_from_dict(item["rule"])) for item in data]


class NICEAPIClient:
    """
    Fetches NICE guideline combination rules.

    Matching is class-level and bidirectional.
    All results are persisted to and read from PostgreSQL (combination_rules table).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        use_static_fallback: bool = True,
    ):
        self._api_key    = api_key
        self._use_static = use_static_fallback
        self._static_rules: Optional[List[Tuple[str, CombinationRule]]] = None

    def _get_static_rules(self) -> List[Tuple[str, CombinationRule]]:
        if self._static_rules is None:
            self._static_rules = _load_static_rules()
            logger.info("Loaded %d static NICE rules.", len(self._static_rules))
        return self._static_rules

    def _match_static_rules(
        self,
        drug_a_class: str,
        drug_b_class: str,
        drug_a_name: str,
        drug_b_name: str,
        shared_indications: Set[str],
    ) -> List[Tuple[str, CombinationRule]]:
        matched: List[Tuple[str, CombinationRule]] = []

        ids_a = {drug_a_class, drug_a_name}
        ids_b = {drug_b_class, drug_b_name}
        same_class = drug_a_class == drug_b_class

        for code, rule in self._get_static_rules():
            ra = rule.drug_a
            rb = rule.drug_b

            if same_class:
                if ra != drug_a_class and ra not in ids_a:
                    continue
                if rb != drug_b_class and rb not in ids_b:
                    continue
                if ra != drug_a_class and rb != drug_a_class:
                    continue
            else:
                forward  = (ra in ids_a or ra == drug_a_class) and \
                           (rb in ids_b or rb == drug_b_class)
                backward = (ra in ids_b or ra == drug_b_class) and \
                           (rb in ids_a or rb == drug_a_class)
                if not (forward or backward):
                    continue

            ind_match = (
                rule.indication == "any"
                or rule.indication in shared_indications
                or not shared_indications
            )
            if not ind_match:
                continue

            matched.append((code, rule))

        return matched

    def _query_nice_api(
        self,
        drug_a_class: str,
        drug_b_class: str,
        drug_a_name: str,
        drug_b_name: str,
        shared_indications: Set[str],
    ) -> List[Tuple[str, CombinationRule]]:
        """Live NICE Evidence Search API query (last resort)."""
        results: List[Tuple[str, CombinationRule]] = []
        ind_term = list(shared_indications)[0].replace("_", " ") if shared_indications else ""

        for a in [drug_a_name, drug_a_class.lower().replace("_", " ")]:
            for b in [drug_b_name, drug_b_class.lower().replace("_", " ")]:
                query = f"{a} {b} combination {ind_term}".strip()
                try:
                    data = _nice_get(NICE_EVIDENCE_SEARCH_BASE,
                                     {"q": query, "type": "guideline", "size": 5})
                    if not data:
                        continue
                    items = data.get("documents", data.get("results", []))
                    for item in items[:3]:
                        rule = self._parse_search_item(item, drug_a_class, drug_b_class,
                                                       shared_indications)
                        if rule:
                            code = item.get("niceGuidanceRef", "NICE_SEARCH")
                            results.append((code, rule))
                except NICEAPIError as exc:
                    logger.error("NICE API error: %s", exc)

        return results

    def _parse_search_item(
        self,
        item: Dict,
        drug_a: str,
        drug_b: str,
        shared_indications: Set[str],
    ) -> Optional[CombinationRule]:
        title   = item.get("title", "")
        summary = item.get("summary", item.get("excerpt", ""))
        url     = item.get("url", "")
        code    = item.get("niceGuidanceRef", "NICE")
        text    = f"{title} {summary}".lower()

        a_found = drug_a.lower().replace("_", " ") in text
        b_found = drug_b.lower().replace("_", " ") in text
        if not (a_found or b_found):
            return None

        if re.search(r"\bcontraindicated\b|\bdo not (prescribe|use|combine)\b", text):
            rec = "CONTRAINDICATED"
        elif re.search(r"\bnot recommended\b|\bavoid\b|\bshould not\b", text):
            rec = "NOT_RECOMMENDED"
        elif re.search(r"\b(consider|may be used|can be used)\b", text):
            rec = "CONDITIONAL"
        elif re.search(r"\b(offer|recommend|use|add)\b", text):
            rec = "SUPPORTED"
        else:
            rec = "CONDITIONAL"

        ind = list(shared_indications)[0] if shared_indications else "any"
        return CombinationRule(
            drug_a=drug_a, drug_b=drug_b, indication=ind,
            recommendation=rec,
            recommendation_text=summary[:400] if summary else title,
            strength="Strong" if rec in ("CONTRAINDICATED", "NOT_RECOMMENDED", "SUPPORTED") else "Conditional",
            section_ref=code, url=url,
            rationale=f"Extracted from NICE guidance: {title}",
            conditions=[],
        )

    def find_combination_rules(
        self,
        drug_a_class: str,
        drug_b_class: str,
        drug_a_name: str,
        drug_b_name: str,
        shared_indications: Set[str],
    ) -> List[Tuple[str, CombinationRule]]:
        ind_list = sorted(shared_indications)

        # 1 — PostgreSQL cache
        try:
            cached = pg_store.load_combination_rules(
                drug_a_class, drug_b_class, drug_a_name, drug_b_name, ind_list
            )
            if cached is not None:
                logger.debug("PG cache hit for %s+%s", drug_a_name, drug_b_name)
                return _results_from_json(cached)
        except Exception as exc:
            logger.warning("PG rule load failed: %s", exc)

        results: List[Tuple[str, CombinationRule]] = []

        # 2 — Static rules
        if self._use_static:
            results = self._match_static_rules(
                drug_a_class, drug_b_class,
                drug_a_name,  drug_b_name,
                shared_indications,
            )
            if results:
                logger.info(
                    "Static NICE rules matched for %s + %s: %d rule(s)",
                    drug_a_name, drug_b_name, len(results),
                )

        # 3 — Live NICE API
        if not results:
            try:
                api_results = self._query_nice_api(
                    drug_a_class, drug_b_class,
                    drug_a_name,  drug_b_name,
                    shared_indications,
                )
                results.extend(api_results)
                if api_results:
                    logger.info("NICE API returned %d rule(s) for %s + %s",
                                len(api_results), drug_a_name, drug_b_name)
            except Exception as exc:
                logger.error("NICE live lookup failed: %s", exc)

        # Persist to PostgreSQL
        try:
            pg_store.save_combination_rules(
                drug_a_class, drug_b_class, drug_a_name, drug_b_name,
                ind_list, _results_to_json(results),
            )
        except Exception as exc:
            logger.warning("PG rule save failed: %s", exc)

        return results

    def get_guideline_summary(self, guideline_code: str) -> Optional[Dict]:
        url = f"https://www.nice.org.uk/guidance/{guideline_code.lower()}.json"
        return _nice_get(url)

    def list_available_guidelines(self) -> List[str]:
        return sorted({code for code, _ in self._get_static_rules()})

    def add_custom_rule(self, guideline_code: str, rule: CombinationRule) -> None:
        if self._static_rules is None:
            self._static_rules = _load_static_rules()
        self._static_rules.append((guideline_code, rule))
        logger.info("Custom rule added: %s <-> %s [%s]",
                    rule.drug_a, rule.drug_b, rule.recommendation)