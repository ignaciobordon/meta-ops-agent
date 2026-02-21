"""
CP3 — Creative Scorer
Evaluates ad creative assets against a BrandMap using LLM Chain-of-Thought
scoring across 5 rubric dimensions, normalized to 0-10.
"""
from __future__ import annotations

from src.schemas.brand_map import BrandMap
from src.schemas.scoring import DimensionScore, EvaluationScore
from src.utils.logging_config import logger, get_trace_id
from backend.src.llm.router import get_llm_router
from backend.src.llm.schema import LLMRequest

WEIGHTS = {
    "hook_strength": 0.25,
    "brand_alignment": 0.20,
    "clarity": 0.20,
    "audience_fit": 0.20,
    "cta_quality": 0.15,
}

SYSTEM_PROMPT = """You are a direct-response creative strategist and performance marketing expert.
Your task is to evaluate an ad creative asset against the provided brand context using a 5-dimension rubric.

Scoring rules:
- Score each dimension from 0 to 10 (decimals allowed, e.g. 7.5).
- 0-3: Poor. 4-6: Average. 7-8: Good. 9-10: Exceptional.
- Be precise and calibrated — most ads score 4-7. Reserve 9-10 for truly exceptional work.
- Provide 1-2 sentences of specific reasoning per dimension that references the actual copy.
- overall_reasoning: 2-3 sentences summarizing the creative's key strength and main weakness.
- Never leave reasoning fields empty.
"""

EVALUATE_TOOL = {
    "type": "function",
    "function": {
        "name": "evaluate_creative",
        "description": "Score an ad creative across 5 dimensions and provide reasoning.",
        "parameters": {
            "type": "object",
            "properties": {
                "hook_strength": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number", "description": "0-10"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["score", "reasoning"],
                },
                "brand_alignment": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number", "description": "0-10"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["score", "reasoning"],
                },
                "clarity": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number", "description": "0-10"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["score", "reasoning"],
                },
                "audience_fit": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number", "description": "0-10"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["score", "reasoning"],
                },
                "cta_quality": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number", "description": "0-10"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["score", "reasoning"],
                },
                "overall_reasoning": {
                    "type": "string",
                    "description": "2-3 sentences on the creative's main strength and weakness.",
                },
            },
            "required": [
                "hook_strength", "brand_alignment", "clarity",
                "audience_fit", "cta_quality", "overall_reasoning",
            ],
        },
    },
}

def _brand_map_context(brand_map: BrandMap) -> str:
    """Serialize the most scoring-relevant BrandMap fields into a compact prompt block."""
    avatars = brand_map.audience_model
    avatar_summary = "; ".join(
        f"{a.avatar_name}: pains={a.pains[:2]}, desires={a.desires[:2]}"
        for a in avatars[:2]
    ) if avatars else "N/A"

    return (
        f"BRAND CONTEXT:\n"
        f"Mission: {brand_map.core_identity.mission}\n"
        f"Tone/Voice: {brand_map.core_identity.tone_voice}\n"
        f"Personality: {', '.join(brand_map.core_identity.personality_traits[:4])}\n"
        f"USP: {brand_map.differentiation_layer.usp}\n"
        f"Main Product: {brand_map.offer_layer.main_product}\n"
        f"Risk Reversal: {brand_map.offer_layer.risk_reversal}\n"
        f"Target Audiences: {avatar_summary}\n"
    )


class Scorer:
    def __init__(self):
        pass

    def evaluate(self, asset: str, brand_map: BrandMap) -> EvaluationScore:
        trace_id = get_trace_id()
        logger.info(
            f"SCORER_EVAL_STARTED | trace_id={trace_id} "
            f"| asset_length={len(asset)} | brand_hash={brand_map.metadata.hash}"
        )

        brand_context = _brand_map_context(brand_map)
        user_content = (
            f"{brand_context}\n\n"
            f"AD CREATIVE TO EVALUATE:\n{asset}\n\n"
            "Evaluate this creative against the brand context using the scoring rubric."
        )

        request = LLMRequest(
            task_type="scoring",
            system_prompt=SYSTEM_PROMPT,
            user_content=user_content,
            max_tokens=1024,
            tools=[EVALUATE_TOOL],
            tool_choice={"type": "function", "function": {"name": "evaluate_creative"}},
        )
        response = get_llm_router().generate(request)
        data = response.content

        # Guard: LLM may return a string instead of a dict when tool_use fails
        if isinstance(data, str):
            import json as _json
            try:
                data = _json.loads(data)
            except (ValueError, TypeError):
                logger.warning("SCORER_EVAL_BAD_RESPONSE | got string instead of dict, using fallback scores")
                data = {
                    dim: {"score": 5.0, "reasoning": "Could not parse LLM response"}
                    for dim in WEIGHTS
                }
                data["overall_reasoning"] = "LLM response could not be parsed; fallback scores applied."
        if not isinstance(data, dict) or not all(dim in data for dim in WEIGHTS):
            logger.warning("SCORER_EVAL_INCOMPLETE | missing dimensions, using fallback scores")
            for dim in WEIGHTS:
                if dim not in data or not isinstance(data.get(dim), dict):
                    data[dim] = {"score": 5.0, "reasoning": "Missing from LLM response"}
            data.setdefault("overall_reasoning", "Partial LLM response; some fallback scores applied.")

        overall = self._weighted_score(data)

        result = EvaluationScore(
            hook_strength=DimensionScore(**data["hook_strength"]),
            brand_alignment=DimensionScore(**data["brand_alignment"]),
            clarity=DimensionScore(**data["clarity"]),
            audience_fit=DimensionScore(**data["audience_fit"]),
            cta_quality=DimensionScore(**data["cta_quality"]),
            overall_score=round(overall, 2),
            overall_reasoning=data.get("overall_reasoning", ""),
            asset_snippet=asset[:100],
            brand_map_hash=brand_map.metadata.hash,
        )

        logger.info(
            f"SCORER_EVAL_DONE | overall={result.overall_score} "
            f"| hook={result.hook_strength.score} "
            f"| brand={result.brand_alignment.score}"
        )
        return result

    def _weighted_score(self, data: dict) -> float:
        total = sum(
            data[dim]["score"] * weight
            for dim, weight in WEIGHTS.items()
        )
        return min(10.0, max(0.0, total))

