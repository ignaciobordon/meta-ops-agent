"""
CI Auto-Discovery Service — LLM-powered competitor suggestions.

Given an industry or niche keyword, uses LLM to suggest potential competitors
with their names and website URLs.
"""
import json
import re
from typing import Any, Dict, List

from backend.src.llm.router import get_llm_router
from backend.src.llm.schema import LLMRequest
from src.utils.logging_config import logger


_DISCOVERY_PROMPT = """You are a competitive intelligence researcher specializing in digital marketing.
Given an industry, niche, or brand name, suggest the top competitors
that a business in that space should monitor.

You MUST respond with valid JSON matching this exact schema:
{
  "competitors": [
    {
      "name": "Company Name",
      "website_url": "https://example.com",
      "reason": "Brief reason why this is a relevant competitor to monitor"
    }
  ]
}

CRITICAL RULES:
- Unless the user specifies a country, suggest only GLOBAL/INTERNATIONAL brands known worldwide.
- NEVER default to Argentina, Latin America, or any specific region.
- DO NOT append country names to company names (e.g. "Gold's Gym Argentina" is WRONG, use "Gold's Gym").
- DO NOT suggest local franchises or country-specific branches. Suggest the parent brand.
- Use each company's main GLOBAL website URL (e.g. https://www.goldsgym.com, NOT goldsgym.com.ar).
- Only suggest real, existing companies with real website URLs.
- Focus on companies that actively advertise and have a strong digital presence.
- Order by relevance/threat level (most relevant first).
- Include a mix of direct competitors and adjacent competitors.
- Write reasons in Spanish.

EXAMPLES of CORRECT suggestions for "fitness":
  - Gold's Gym (https://www.goldsgym.com) — global chain
  - Equinox (https://www.equinox.com) — premium fitness
  - Planet Fitness (https://www.planetfitness.com) — budget chain
EXAMPLES of WRONG suggestions (DO NOT DO THIS):
  - "Megatlon" (local chain) — WRONG, too local
  - "Gold's Gym Argentina" — WRONG, do not append country
  - "SportClub Buenos Aires" — WRONG, do not use local branch"""


class CIDiscoveryService:
    """Service for LLM-powered competitor discovery."""

    def discover(
        self,
        query: str,
        country: str = "",
        limit: int = 5,
    ) -> Dict[str, Any]:
        """Discover potential competitors for a given niche/industry.

        Returns dict with: competitors list [{name, website_url, reason}]
        """
        logger.info(
            "CI_DISCOVERY_START | query={} | country={} | limit={}",
            query, country, limit,
        )

        llm_router = get_llm_router()
        response = llm_router.generate(
            LLMRequest(
                task_type="ci_analysis",
                system_prompt=_DISCOVERY_PROMPT,
                user_content=(
                    f"Industry/Niche: {query}\n"
                    + (f"Target Country: {country}\n" if country else "Scope: WORLDWIDE (do not limit to any single country)\n")
                    + f"Suggest up to {limit} competitors."
                ),
                max_tokens=1024,
                temperature=0.5,
            )
        )

        # Parse response
        result = response.content
        if isinstance(result, dict) and "competitors" in result:
            competitors = result["competitors"][:limit]
        else:
            # Fallback: try raw_text
            raw = response.raw_text or ""
            try:
                parsed = json.loads(raw)
                competitors = parsed.get("competitors", [])[:limit]
            except (json.JSONDecodeError, TypeError):
                # Try extracting JSON from markdown fences
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                        competitors = parsed.get("competitors", [])[:limit]
                    except (json.JSONDecodeError, TypeError):
                        competitors = []
                else:
                    competitors = []

        logger.info(
            "CI_DISCOVERY_DONE | query={} | found={} | model={} | tokens={}",
            query, len(competitors), response.model, response.tokens_used,
        )

        return {
            "competitors": competitors,
            "model": response.model,
            "tokens_used": response.tokens_used,
        }
