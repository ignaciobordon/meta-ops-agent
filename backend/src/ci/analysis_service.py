"""
CI Analysis Service — LLM-powered strategic analysis of competitor items.

Compares competitor messaging with the user's brand profile and generates
actionable insights, ad copy suggestions, and threat assessment.
"""
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.ci.models import CICanonicalItem
from backend.src.database.models import BrandMapProfile
from backend.src.llm.router import get_llm_router
from backend.src.llm.schema import LLMRequest
from src.utils.logging_config import logger


_SYSTEM_PROMPT = """You are a competitive intelligence analyst for a digital marketing agency.
Your job is to analyze a competitor's messaging, offers, and creative strategy,
then compare it with the user's brand profile and produce actionable strategic insights.

You MUST respond with valid JSON matching this exact schema:
{
  "competitor_strategy": "2-3 sentence summary of what the competitor is doing strategically",
  "messaging_angles": ["angle1", "angle2", ...],
  "brand_comparison": "2-3 sentence comparison with the user's brand (or generic if no brand context)",
  "recommendations": ["Action 1", "Action 2", "Action 3"],
  "ad_copy_suggestions": ["Suggested copy 1", "Suggested copy 2"],
  "opportunities": ["Gap or opportunity 1", "Gap or opportunity 2"],
  "threat_level": "low|medium|high"
}

Be specific, actionable, and strategic. Focus on what the brand can DO with this intelligence.
Write in the same language as the competitor content (Spanish if content is in Spanish, etc)."""


def _build_user_prompt(item: CICanonicalItem, brand_profile: Optional[Dict]) -> str:
    """Build the user prompt with item data and optional brand context."""
    canonical = item.canonical_json or {}

    parts = ["## Competitor Item\n"]

    competitor_name = canonical.get("competitor", "Unknown")
    parts.append(f"**Competitor:** {competitor_name}")
    parts.append(f"**Type:** {item.item_type.value if hasattr(item.item_type, 'value') else item.item_type}")
    if canonical.get("platform"):
        parts.append(f"**Platform:** {canonical['platform']}")

    if item.title:
        parts.append(f"\n**Headline:** {item.title}")
    if item.body_text:
        parts.append(f"\n**Body/Content:** {item.body_text[:1500]}")

    # Structured data from canonical_json
    if canonical.get("headlines"):
        parts.append(f"\n**Headlines:** {'; '.join(canonical['headlines'][:10])}")
    if canonical.get("offers"):
        parts.append(f"\n**Offers:** {'; '.join(canonical['offers'][:10])}")
    if canonical.get("cta"):
        parts.append(f"\n**CTA:** {canonical['cta']}")
    if canonical.get("cta_phrases"):
        parts.append(f"\n**CTA Phrases:** {'; '.join(canonical['cta_phrases'][:5])}")
    if canonical.get("keywords"):
        parts.append(f"\n**Keywords:** {', '.join(canonical['keywords'][:15])}")
    if canonical.get("hero_sections"):
        parts.append(f"\n**Hero Sections:** {'; '.join(canonical['hero_sections'][:3])}")
    if item.url:
        parts.append(f"\n**URL:** {item.url}")

    # Brand context
    if brand_profile:
        parts.append("\n\n## Your Brand Profile\n")
        sj = brand_profile
        if sj.get("core_identity"):
            ci = sj["core_identity"]
            if ci.get("mission"):
                parts.append(f"**Mission:** {ci['mission']}")
            if ci.get("vision"):
                parts.append(f"**Vision:** {ci['vision']}")
        if sj.get("audience_model"):
            am = sj["audience_model"]
            if isinstance(am, dict):
                parts.append(f"**Audience:** {json.dumps(am, ensure_ascii=False)[:500]}")
            elif isinstance(am, str):
                parts.append(f"**Audience:** {am[:500]}")
        if sj.get("differentiation"):
            diff = sj["differentiation"]
            if isinstance(diff, dict):
                if diff.get("usp"):
                    parts.append(f"**USP:** {diff['usp']}")
                if diff.get("competitive_advantages"):
                    parts.append(f"**Competitive Advantages:** {'; '.join(diff['competitive_advantages'][:5])}")
            elif isinstance(diff, str):
                parts.append(f"**Differentiation:** {diff[:500]}")
        if sj.get("tone_voice"):
            tv = sj["tone_voice"]
            if isinstance(tv, dict):
                parts.append(f"**Tone & Voice:** {json.dumps(tv, ensure_ascii=False)[:300]}")
            elif isinstance(tv, str):
                parts.append(f"**Tone & Voice:** {tv[:300]}")
        if sj.get("offer_layer"):
            ol = sj["offer_layer"]
            if isinstance(ol, dict):
                parts.append(f"**Offer Layer:** {json.dumps(ol, ensure_ascii=False)[:300]}")
            elif isinstance(ol, str):
                parts.append(f"**Offer Layer:** {ol[:300]}")

        parts.append("\n\nAnalyze the competitor item above and compare it with this brand profile. "
                      "Identify how the brand can leverage or counter the competitor's strategy.")
    else:
        parts.append("\n\nNo brand profile available. Provide a generic competitive analysis "
                      "with actionable strategic recommendations.")

    return "\n".join(parts)


def _sanitize_analysis(analysis: dict) -> dict:
    """Clean residual markdown/JSON artifacts from analysis string values."""
    for key in ("competitor_strategy", "brand_comparison"):
        val = analysis.get(key, "")
        if isinstance(val, str) and val.strip().startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", val.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned)
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    # LLM put whole JSON in one field — extract the correct field
                    analysis[key] = parsed.get(key, cleaned)
                else:
                    analysis[key] = str(parsed)
            except (json.JSONDecodeError, TypeError):
                analysis[key] = cleaned
    return analysis


class CIAnalysisService:
    """Service for LLM-powered CI item analysis."""

    def analyze_item(
        self,
        db: Session,
        org_id: UUID,
        item_id: UUID,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Analyze a single CI item using LLM.

        Returns dict with: item_id, has_brand_context, analysis, generated_at, model, cached, tokens_used
        """
        item = (
            db.query(CICanonicalItem)
            .filter(CICanonicalItem.org_id == org_id, CICanonicalItem.id == item_id)
            .first()
        )
        if not item:
            raise ValueError(f"Item {item_id} not found")

        # Return cached if available and not forcing refresh
        if item.analysis_json and not force_refresh:
            return {
                "item_id": str(item.id),
                "has_brand_context": item.analysis_json.get("brand_profile_id") is not None,
                "analysis": item.analysis_json.get("analysis", {}),
                "generated_at": item.analysis_json.get("generated_at"),
                "model": item.analysis_json.get("model", ""),
                "cached": True,
                "tokens_used": item.analysis_json.get("tokens_used", 0),
            }

        # Load brand profile if available
        brand_profile = None
        brand_profile_id = None
        bp = (
            db.query(BrandMapProfile)
            .filter(BrandMapProfile.org_id == org_id, BrandMapProfile.status == "ready")
            .order_by(BrandMapProfile.last_analyzed_at.desc())
            .first()
        )
        if bp and bp.structured_json:
            brand_profile = bp.structured_json
            brand_profile_id = str(bp.id)

        # Build prompt and call LLM
        user_prompt = _build_user_prompt(item, brand_profile)

        logger.info(
            "CI_ANALYSIS_START | org_id={} | item_id={} | has_brand={}",
            org_id, item_id, brand_profile is not None,
        )

        llm_router = get_llm_router()
        response = llm_router.generate(
            LLMRequest(
                task_type="ci_analysis",
                system_prompt=_SYSTEM_PROMPT,
                user_content=user_prompt,
                max_tokens=4096,
                temperature=0.7,
            )
        )

        # Parse analysis from response
        analysis = response.content

        def _try_extract_json(text: str) -> dict | None:
            """Try to extract a valid JSON dict from text with possible markdown fences."""
            text = text.strip()
            # Strip markdown code fences
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            # Try JSON parse
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and parsed.get("competitor_strategy"):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
            # Try extracting first JSON object via regex
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict) and parsed.get("competitor_strategy"):
                        return parsed
                except (json.JSONDecodeError, TypeError):
                    pass
            return None

        # Check if content is already a good analysis dict
        if not isinstance(analysis, dict) or not analysis.get("competitor_strategy") or \
                (isinstance(analysis.get("competitor_strategy"), str) and analysis["competitor_strategy"].strip().startswith("```")):
            # Try parsing raw_text
            extracted = _try_extract_json(response.raw_text or "")
            if extracted:
                analysis = extracted
            elif not isinstance(analysis, dict) or not analysis.get("competitor_strategy"):
                analysis = {
                    "competitor_strategy": (response.raw_text or "")[:500] or "Analysis failed",
                    "messaging_angles": [],
                    "brand_comparison": "",
                    "recommendations": [],
                    "ad_copy_suggestions": [],
                    "opportunities": [],
                    "threat_level": "medium",
                }

        # Sanitize any residual markdown artifacts
        analysis = _sanitize_analysis(analysis)

        # Store in DB
        analysis_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": response.model,
            "brand_profile_id": brand_profile_id,
            "analysis": analysis,
            "tokens_used": response.tokens_used,
        }
        item.analysis_json = analysis_data
        db.commit()

        logger.info(
            "CI_ANALYSIS_DONE | org_id={} | item_id={} | model={} | tokens={}",
            org_id, item_id, response.model, response.tokens_used,
        )

        return {
            "item_id": str(item.id),
            "has_brand_context": brand_profile_id is not None,
            "analysis": analysis,
            "generated_at": analysis_data["generated_at"],
            "model": response.model,
            "cached": False,
            "tokens_used": response.tokens_used,
        }

    def get_item_analysis(
        self,
        db: Session,
        org_id: UUID,
        item_id: UUID,
    ) -> Dict[str, Any]:
        """Get cached analysis for an item (no LLM call)."""
        item = (
            db.query(CICanonicalItem)
            .filter(CICanonicalItem.org_id == org_id, CICanonicalItem.id == item_id)
            .first()
        )
        if not item:
            raise ValueError(f"Item {item_id} not found")

        if not item.analysis_json:
            return {"has_analysis": False}

        return {
            "has_analysis": True,
            "analysis": item.analysis_json.get("analysis", {}),
            "generated_at": item.analysis_json.get("generated_at"),
            "model": item.analysis_json.get("model", ""),
            "has_brand_context": item.analysis_json.get("brand_profile_id") is not None,
            "tokens_used": item.analysis_json.get("tokens_used", 0),
        }
