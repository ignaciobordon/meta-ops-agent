"""
CP6 — Creative Factory
Generates new ad scripts based on BrandMap context and target angles.
Uses LLM with forced tool_use to produce structured, on-brand copy.
"""
from __future__ import annotations

import uuid
from typing import Dict, Any, List, Optional

from src.schemas.brand_map import BrandMap
from src.schemas.factory import AdScript, Framework
from src.utils.logging_config import get_trace_id, logger
from backend.src.llm.router import get_llm_router
from backend.src.llm.schema import LLMRequest

SYSTEM_PROMPT = """You are an elite direct-response copywriter specializing in Meta Ads creative for local service businesses.

Your task: generate ad scripts that align perfectly with the brand's voice, target specific marketing angles, and follow proven copywriting frameworks.

Rules:
- Hook: 1-2 punchy sentences that grab attention in 3 seconds. Must be angle-specific.
- Body: 2-4 sentences that build desire, cite proof points, and address pain/desire.
- CTA: Clear, specific call to action with urgency or friction removal.
- Tone: Match the brand's tone_voice exactly. Never generic corporate speak.
- Visual Brief: 2-3 sentences describing what the video/image should show. Reference brand creative DNA.

When flywheel intelligence data is provided, USE IT to:
- Avoid patterns from saturated/fatigued ads
- Lean into proven winning features and high-trust entities
- Address the specific market gaps identified in opportunities
- Differentiate from what's already running

Each script must feel native to the brand, not like a template."""

SCRIPT_GEN_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_ad_scripts",
        "description": "Generate multiple ad script variations for a specific marketing angle.",
        "parameters": {
            "type": "object",
            "properties": {
                "scripts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "hook": {"type": "string"},
                            "body": {"type": "string"},
                            "cta": {"type": "string"},
                            "framework": {"type": "string", "enum": ["AIDA", "PAS", "PSF"]},
                            "target_avatar": {"type": "string"},
                            "visual_brief": {"type": "string"},
                        },
                        "required": ["hook", "body", "cta", "framework", "target_avatar", "visual_brief"],
                    },
                }
            },
            "required": ["scripts"],
        },
    },
}

def _brand_context(brand_map: BrandMap) -> str:
    """Serialize BrandMap into prompt context for the LLM."""
    avatars = brand_map.audience_model
    avatar_str = ""
    if avatars:
        a = avatars[0]
        avatar_str = (
            f"Primary Avatar: {a.avatar_name}\n"
            f"  - Demographics: {a.demographics}\n"
            f"  - Pains: {', '.join(a.pains[:3])}\n"
            f"  - Desires: {', '.join(a.desires[:3])}\n"
        )

    return (
        f"BRAND CONTEXT:\n"
        f"Mission: {brand_map.core_identity.mission}\n"
        f"Tone/Voice: {brand_map.core_identity.tone_voice}\n"
        f"Personality: {', '.join(brand_map.core_identity.personality_traits[:4])}\n"
        f"USP: {brand_map.differentiation_layer.usp}\n"
        f"Main Product: {brand_map.offer_layer.main_product}\n"
        f"Risk Reversal: {brand_map.offer_layer.risk_reversal}\n"
        f"{avatar_str}\n"
        f"Creative DNA:\n"
        f"  - Colors: {', '.join(brand_map.creative_dna.color_palette[:3])}\n"
        f"  - Typography: {brand_map.creative_dna.typography_intent}\n"
        f"  - Visual Constraints: {', '.join(brand_map.creative_dna.visual_constraints[:2])}\n"
    )


def _flywheel_context_prompt(flywheel_context: Dict[str, Any]) -> str:
    """Build an LLM prompt section from flywheel intelligence data."""
    sections = []

    # Opportunities
    opportunities = flywheel_context.get("all_opportunities", [])
    if opportunities:
        opp_lines = []
        for opp in opportunities[:5]:
            title = opp.get("title", opp.get("gap_id", ""))
            priority = opp.get("priority", "")
            opp_lines.append(f"  - [{priority.upper()}] {title}")
        sections.append("MARKET OPPORTUNITIES:\n" + "\n".join(opp_lines))

    # Winning features from Brain
    features = flywheel_context.get("winning_features", [])
    if features:
        feat_lines = [f"  - {f.get('key', '')} (win rate: {f.get('win_rate', 0):.0%}, {f.get('samples', 0)} samples)" for f in features[:5]]
        sections.append("PROVEN WINNING FEATURES:\n" + "\n".join(feat_lines))

    # Top trusted entities
    entities = flywheel_context.get("top_entities", [])
    if entities:
        ent_lines = [f"  - {e.get('entity_id', '')} ({e.get('type', '')}, trust: {e.get('trust_score', 0)})" for e in entities[:5]]
        sections.append("HIGH-TRUST ENTITIES:\n" + "\n".join(ent_lines))

    # Saturated ads to avoid
    saturated = flywheel_context.get("saturated_ads", [])
    if saturated:
        sat_lines = [f"  - {s.get('name', '')} (freq: {s.get('frequency', 0)}, CTR decline: {s.get('ctr_decline', 0)})" for s in saturated[:5]]
        sections.append("SATURATED ADS (avoid similar patterns):\n" + "\n".join(sat_lines))

    # Fresh ads performing well
    fresh = flywheel_context.get("fresh_ads", [])
    if fresh:
        fresh_lines = [f"  - {f.get('name', '')} (CTR: {f.get('ctr', 0)})" for f in fresh[:5]]
        sections.append("FRESH HIGH-PERFORMING ADS (learn from):\n" + "\n".join(fresh_lines))

    if not sections:
        return ""

    return "\n\nFLYWHEEL INTELLIGENCE:\n" + "\n\n".join(sections) + "\n"


class Factory:
    def __init__(self):
        pass

    def generate_scripts(
        self,
        brand_map: BrandMap,
        target_angles: List[str],
        num_variants: int = 3,
        framework: Framework = "PAS",
        flywheel_context: Optional[Dict[str, Any]] = None,
    ) -> List[AdScript]:
        """
        Generate ad scripts for the specified marketing angles.

        Args:
            brand_map: Brand context and DNA
            target_angles: L2 Driver tags (e.g., ["Social Proof", "Problem Agitation"])
            num_variants: Number of script variations per angle
            framework: Copywriting framework (AIDA, PAS, PSF)
            flywheel_context: Optional intelligence data from flywheel pipeline

        Returns:
            List of AdScript objects
        """
        trace_id = get_trace_id()
        logger.info(
            f"FACTORY_GEN_STARTED | trace_id={trace_id} "
            f"| angles={len(target_angles)} | variants={num_variants}"
            f"| has_flywheel_context={flywheel_context is not None}"
        )

        all_scripts: List[AdScript] = []

        for angle in target_angles:
            context = _brand_context(brand_map)
            flywheel_section = _flywheel_context_prompt(flywheel_context) if flywheel_context else ""
            user_content = (
                f"{context}\n\n"
                f"{flywheel_section}"
                f"TARGET ANGLE: {angle}\n"
                f"FRAMEWORK: {framework}\n"
                f"VARIANTS: {num_variants}\n\n"
                f"Generate {num_variants} ad script variations that target the '{angle}' angle. "
                f"Each script must follow the {framework} framework and match the brand tone perfectly."
            )
            if flywheel_context:
                user_content += (
                    " Use the flywheel intelligence above to create differentiated scripts"
                    " that avoid saturated patterns and leverage proven winning features."
                )

            request = LLMRequest(
                task_type="creative_factory",
                system_prompt=SYSTEM_PROMPT,
                user_content=user_content,
                max_tokens=2048,
                tools=[SCRIPT_GEN_TOOL],
                tool_choice={"type": "function", "function": {"name": "generate_ad_scripts"}},
            )
            response = get_llm_router().generate(request)
            scripts_data = response.content

            # Guard: LLM may return a string instead of a dict when tool_use fails
            if isinstance(scripts_data, str):
                import json as _json
                try:
                    scripts_data = _json.loads(scripts_data)
                except (ValueError, TypeError):
                    logger.warning("FACTORY_BAD_RESPONSE | got string instead of dict, skipping angle")
                    continue
            if not isinstance(scripts_data, dict):
                logger.warning(f"FACTORY_BAD_RESPONSE | expected dict, got {type(scripts_data).__name__}")
                continue

            for script_dict in scripts_data.get("scripts", []):
                # Handle case where LLM returns malformed data
                if not isinstance(script_dict, dict):
                    logger.warning(f"Skipping malformed script (not a dict): {type(script_dict)}")
                    continue

                script = AdScript(
                    script_id=f"script-{uuid.uuid4().hex[:8]}",
                    angle=angle,
                    hook=script_dict.get("hook", ""),
                    body=script_dict.get("body", ""),
                    cta=script_dict.get("cta", ""),
                    framework=script_dict.get("framework", framework),
                    target_avatar=script_dict.get("target_avatar", ""),
                    visual_brief=script_dict.get("visual_brief", ""),
                    brand_map_hash=brand_map.metadata.hash,
                )
                all_scripts.append(script)

        logger.info(f"FACTORY_GEN_DONE | scripts_generated={len(all_scripts)}")
        return all_scripts

