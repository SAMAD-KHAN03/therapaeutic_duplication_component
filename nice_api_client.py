import json
import logging
from typing import List, Dict, Optional, Tuple, Set
from urllib.request import Request, urlopen
from urllib.error import HTTPError

logger = logging.getLogger(__name__)

class NICEAPIClient:
    """
    Direct Retrieval Client: Skips keyword searching.
    Fetches structured guideline JSON and evaluates via Gemini.
    """
    def __init__(self, use_static_fallback: bool = True):
        self.use_static = use_static_fallback
        self.base_url = "https://www.nice.org.uk/guidance"

    def fetch_guideline_json(self, code: str) -> Optional[Dict]:
        """Directly fetches the JSON content of a specific NICE guideline."""
        url = f"{self.base_url}/{code.lower()}.json"
        req = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            logger.warning(f"Could not fetch guideline {code}: {e.code}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving {code}: {e}")
            return None

    def find_combination_rules(
        self,
        drug_a_name: str,
        drug_b_name: str,
        profile_a,  # DrugProfile object
        profile_b,  # DrugProfile object
        shared_indications: Set[str]
    ) -> List[Tuple[str, any]]:
        from gemini_evaluator import evaluate_combination

        # 1. Collect all relevant guideline codes from both drug profiles
        target_codes = set(profile_a.nice_guideline_codes + profile_b.nice_guideline_codes)
        rag_contexts = []

        # 2. Direct Retrieval: Skip searching, just fetch the known guidelines
        for code in target_codes:
            content = self.fetch_guideline_json(code)
            if content:
                # Extract the most relevant clinical text for Gemini
                # Usually found in 'chapters' or 'recommendations' in NICE JSON
                summary_text = str(content.get('title', '')) + "\n" + str(content.get('embedded', {}))
                rag_contexts.append({
                    "source": code.upper(),
                    "title": content.get("title", f"NICE {code}"),
                    "text": summary_text[:2000], # Token management
                    "url": f"https://www.nice.org.uk/guidance/{code}"
                })

        # 3. Add built-in Same-Class knowledge if applicable
        if profile_a.drug_class == profile_b.drug_class:
            from nice_api_client import _same_class_knowledge_context
            knowledge = _same_class_knowledge_context(profile_a.drug_class)
            if knowledge:
                rag_contexts.insert(0, knowledge)

        # 4. Final Verdict via Gemini
        verdict = evaluate_combination(
            drug_a_name=drug_a_name,
            drug_a_class=profile_a.drug_class,
            drug_a_moa=profile_a.mechanism_of_action,
            drug_b_name=drug_b_name,
            drug_b_class=profile_b.drug_class,
            drug_b_moa=profile_b.mechanism_of_action,
            shared_indications=shared_indications,
            guideline_contexts=rag_contexts
        )

        # Wrap in the expected return format for your checker
        from nice_api_client import CombinationRule
        res_rule = CombinationRule(
            drug_a=drug_a_name,
            drug_b=drug_b_name,
            indication=list(shared_indications)[0] if shared_indications else "any",
            recommendation=verdict["recommendation"],
            recommendation_text=verdict["rationale"],
            strength=verdict.get("strength", "Moderate"),
            section_ref="Direct API Retrieval",
            url=rag_contexts[0]["url"] if rag_contexts else "https://www.nice.org.uk",
            rationale=verdict["rationale"],
            conditions=verdict.get("conditions", [])
        )
        
        return [("NICE", res_rule)]