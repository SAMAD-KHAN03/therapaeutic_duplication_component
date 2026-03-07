"""
nice_api_client.py
------------------
Fetches NICE guideline combination rules and evaluates them via Gemini.

Resolution order inside find_combination_rules()
-------------------------------------------------
  1. PostgreSQL cache           (combination_rules table)
  2. Static curated rules       (nice_guidelines_db.py)
  3. Live NICE Evidence Search  (last resort when static returns nothing)

After retrieval (steps 2 or 3), ALL retrieved guideline text is assembled
into a RAG context block and sent to gemini_evaluator.evaluate_combination()
which replaces all regex/substring classification of guideline text.

Key features:
  - Bidirectional class-level matching (drug_a/drug_b are class strings)
  - Same-class detection (NSAID+NSAID, SSRI+SSRI, etc.)
  - Indication matching with "any" wildcard
  - Antimycobacterial multi-drug TB support
  - CONVENTIONAL_DMARD same-class + different MOA detection
  - All rule caching via PostgreSQL (no disk/memory cache)
"""

from __future__ import annotations

import json
import logging
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
        url = "%s?%s" % (url, urlencode(params))
    req = Request(
        url,
        headers={
            "User-Agent": "TherapeuticDuplicationChecker/2.0",
            "Accept": "application/json",
        },
    )
    try:
        time.sleep(_RATE_LIMIT_DELAY_SECONDS)
        with urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        if exc.code in (404, 410):
            return None
        raise NICEAPIError("NICE API HTTP %d: %s" % (exc.code, url)) from exc
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


# ---------------------------------------------------------------------------
# Serialisation helpers for PostgreSQL storage
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Build Gemini RAG context from retrieved rules
# ---------------------------------------------------------------------------

def _rules_to_gemini_contexts(
    rules: List[Tuple[str, CombinationRule]],
) -> List[Dict[str, str]]:
    """
    Convert a list of (code, CombinationRule) into the context block format
    expected by gemini_evaluator.evaluate_combination().
    """
    contexts = []
    for code, rule in rules:
        text = "\n".join(filter(None, [
            "Recommendation : %s" % rule.recommendation_text,
            "Rationale      : %s" % rule.rationale,
            "Conditions     : %s" % ("; ".join(rule.conditions) if rule.conditions else ""),
            "Strength       : %s" % rule.strength,
        ]))
        contexts.append({
            "source":  code,
            "title":   "NICE %s" % code,
            "section": rule.section_ref,
            "text":    text,
            "url":     rule.url,
        })
    return contexts


def _search_item_to_context(
    item: Dict,
    drug_a: str,
    drug_b: str,
) -> Optional[Dict[str, str]]:
    """
    Convert a raw NICE Evidence Search result item into a Gemini context block.
    Relevance filter: at least one of the drug names must appear in the text.
    """
    title   = item.get("title", "")
    summary = item.get("summary", item.get("excerpt", ""))
    url     = item.get("url", "")
    code    = item.get("niceGuidanceRef", "NICE_SEARCH")
    combined = ("%s %s" % (title, summary)).lower()

    a_hit = drug_a.lower().replace("_", " ") in combined
    b_hit = drug_b.lower().replace("_", " ") in combined
    if not (a_hit or b_hit):
        return None

    return {
        "source":  code,
        "title":   title,
        "section": code,
        "text":    summary[:600] if summary else title,
        "url":     url,
    }


class NICEAPIClient:
    """
    Fetches NICE guideline combination rules and evaluates them via Gemini.

    After retrieving rules (static DB or live NICE API), all guideline text
    is passed as RAG context to gemini_evaluator.evaluate_combination(), which
    returns a structured verdict (SUPPORTED / CONDITIONAL / NOT_RECOMMENDED /
    CONTRAINDICATED).  No regex or substring classification is used.
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
        """
        Bidirectional class+name matching against the curated static rule set.
        The recommendation field in each matched CombinationRule is used only
        as a hint; the final verdict always comes from Gemini.
        """
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

    def _fetch_nice_api_contexts(
        self,
        drug_a_class: str,
        drug_b_class: str,
        drug_a_name: str,
        drug_b_name: str,
        shared_indications: Set[str],
    ) -> List[Dict[str, str]]:
        """
        Query the live NICE Evidence Search API and return raw context blocks
        (no classification -- Gemini will do that).
        """
        contexts: List[Dict[str, str]] = []
        ind_term = (
            list(shared_indications)[0].replace("_", " ")
            if shared_indications else ""
        )

        for a in [drug_a_name, drug_a_class.lower().replace("_", " ")]:
            for b in [drug_b_name, drug_b_class.lower().replace("_", " ")]:
                query = ("%s %s combination %s" % (a, b, ind_term)).strip()
                try:
                    data = _nice_get(
                        NICE_EVIDENCE_SEARCH_BASE,
                        {"q": query, "type": "guideline", "size": 5},
                    )
                    if not data:
                        continue
                    items = data.get("documents", data.get("results", []))
                    for item in items[:3]:
                        ctx = _search_item_to_context(item, drug_a_class, drug_b_class)
                        if ctx and ctx not in contexts:
                            contexts.append(ctx)
                except NICEAPIError as exc:
                    logger.error("NICE API error: %s", exc)

        return contexts

    def find_combination_rules(
        self,
        drug_a_class: str,
        drug_b_class: str,
        drug_a_name: str,
        drug_b_name: str,
        shared_indications: Set[str],
        # full DrugProfile objects -- used to give Gemini class + MOA context
        profile_a=None,
        profile_b=None,
    ) -> List[Tuple[str, CombinationRule]]:
        """
        Retrieve NICE rules then ask Gemini to evaluate the combination.

        Returns a list containing a single (code, CombinationRule) tuple whose
        recommendation, rationale, conditions, and strength are populated from
        the Gemini verdict rather than from regex matching.
        """
        from gemini_evaluator import evaluate_combination

        ind_list = sorted(shared_indications)

        # 1 -- PostgreSQL cache
        try:
            cached = pg_store.load_combination_rules(
                drug_a_class, drug_b_class, drug_a_name, drug_b_name, ind_list
            )
            if cached is not None:
                logger.debug("PG cache hit for %s+%s", drug_a_name, drug_b_name)
                return _results_from_json(cached)
        except Exception as exc:
            logger.warning("PG rule load failed: %s", exc)

        # 2 -- Static rules -> build RAG contexts
        rag_contexts: List[Dict[str, str]] = []
        static_rules: List[Tuple[str, CombinationRule]] = []

        if self._use_static:
            static_rules = self._match_static_rules(
                drug_a_class, drug_b_class,
                drug_a_name,  drug_b_name,
                shared_indications,
            )
            if static_rules:
                logger.info(
                    "Static NICE rules matched for %s + %s: %d rule(s)",
                    drug_a_name, drug_b_name, len(static_rules),
                )
                rag_contexts = _rules_to_gemini_contexts(static_rules)

        # 3 -- Live NICE API -> more RAG contexts (used when static returns nothing)
        if not static_rules:
            try:
                api_contexts = self._fetch_nice_api_contexts(
                    drug_a_class, drug_b_class,
                    drug_a_name,  drug_b_name,
                    shared_indications,
                )
                rag_contexts.extend(api_contexts)
                if api_contexts:
                    logger.info(
                        "NICE API returned %d context block(s) for %s + %s",
                        len(api_contexts), drug_a_name, drug_b_name,
                    )
            except Exception as exc:
                logger.error("NICE live lookup failed: %s", exc)

        # 4 -- Gemini RAG evaluation
        #
        # Regardless of whether we got rules from the static DB, the live API,
        # or neither, we always send everything to Gemini.  Gemini uses the RAG
        # context if available, otherwise falls back to pharmacological reasoning.
        a_class = drug_a_class
        a_moa   = profile_a.mechanism_of_action if profile_a else "UNKNOWN"
        b_class = drug_b_class
        b_moa   = profile_b.mechanism_of_action if profile_b else "UNKNOWN"

        verdict = evaluate_combination(
            drug_a_name=drug_a_name,
            drug_a_class=a_class,
            drug_a_moa=a_moa,
            drug_b_name=drug_b_name,
            drug_b_class=b_class,
            drug_b_moa=b_moa,
            shared_indications=shared_indications,
            guideline_contexts=rag_contexts,
        )

        # Build a single CombinationRule from the Gemini verdict.
        # Use the first static/API rule's metadata (URL, section_ref) if available,
        # otherwise use sensible defaults.
        if static_rules:
            ref_code, ref_rule = static_rules[0]
            section_ref = ref_rule.section_ref
            url         = ref_rule.url
        elif rag_contexts:
            ref_code    = rag_contexts[0].get("source", "NICE")
            section_ref = rag_contexts[0].get("section", "")
            url         = rag_contexts[0].get("url", "")
        else:
            ref_code    = "NICE"
            section_ref = "No specific guideline found"
            url         = "https://www.nice.org.uk"

        gemini_rule = CombinationRule(
            drug_a=drug_a_name,
            drug_b=drug_b_name,
            indication=ind_list[0] if ind_list else "any",
            recommendation=verdict["recommendation"],
            recommendation_text=verdict["rationale"],
            strength=verdict.get("strength", "Moderate"),
            section_ref=section_ref,
            url=url,
            rationale=verdict["rationale"],
            conditions=verdict.get("conditions", []),
        )

        results = [(ref_code, gemini_rule)]

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
        url = "https://www.nice.org.uk/guidance/%s.json" % guideline_code.lower()
        return _nice_get(url)

    def list_available_guidelines(self) -> List[str]:
        return sorted({code for code, _ in self._get_static_rules()})

    def add_custom_rule(self, guideline_code: str, rule: CombinationRule) -> None:
        if self._static_rules is None:
            self._static_rules = _load_static_rules()
        self._static_rules.append((guideline_code, rule))
        logger.info(
            "Custom rule added: %s <-> %s [%s]",
            rule.drug_a, rule.drug_b, rule.recommendation,
        )
