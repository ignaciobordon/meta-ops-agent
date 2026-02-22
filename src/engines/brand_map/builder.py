from datetime import datetime

from src.schemas.brand_map import BrandMap
from src.database.vector.db_client import VectorDBClient
from src.utils.logging_config import logger, get_trace_id
from backend.src.llm.router import get_llm_router
from backend.src.llm.schema import LLMRequest

SYSTEM_PROMPT = """You are a brand strategy architect with deep expertise in direct-response marketing.
Your task is to perform an "Architect Analysis": extract a complete, structured brand map from raw brand text.

Rules:
- Never leave a required field empty. If data is not explicit in the input, infer it logically from context.
- For missing competitors or opportunities, generate reasonable placeholders based on the brand category.
- Be specific and actionable — avoid generic filler.
- All list fields must have at least one item.
- For opportunity gap_id use format: OPP-001, OPP-002, etc.

If you cannot use a tool, respond ONLY with a valid JSON object (no markdown, no explanation) with this exact structure:
{
  "core_identity": {"mission": "", "values": [], "tone_voice": "", "personality_traits": []},
  "offer_layer": {"main_product": "", "upsells": [], "pricing_psychology": "", "risk_reversal": ""},
  "audience_model": [{"avatar_name": "", "demographics": "", "psychographics": "", "pains": [], "desires": [], "triggers": []}],
  "differentiation_layer": {"usp": "", "competitive_moat": "", "proof_points": []},
  "narrative_assets": {"lore": "", "story_hooks": [], "core_myths": []},
  "creative_dna": {"color_palette": [], "typography_intent": "", "visual_constraints": []},
  "market_context": {"seasonal_factors": [], "current_trends": []},
  "competitor_map": [{"name": "", "strategy_type": "", "weak_points": []}],
  "opportunity_map": [{"gap_id": "OPP-001", "strategy_recommendation": "", "estimated_impact": 75, "impact_reasoning": ""}]
}
"""

BRAND_MAP_TOOL = {
    "type": "function",
    "function": {
        "name": "extract_brand_map",
        "description": "Extract a complete structured brand map from raw brand text.",
        "parameters": {
            "type": "object",
            "properties": {
                "core_identity": {
                    "type": "object",
                    "properties": {
                        "mission": {"type": "string"},
                        "values": {"type": "array", "items": {"type": "string"}},
                        "tone_voice": {"type": "string"},
                        "personality_traits": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["mission", "values", "tone_voice", "personality_traits"],
                },
                "offer_layer": {
                    "type": "object",
                    "properties": {
                        "main_product": {"type": "string"},
                        "upsells": {"type": "array", "items": {"type": "string"}},
                        "pricing_psychology": {"type": "string"},
                        "risk_reversal": {"type": "string"},
                    },
                    "required": ["main_product", "upsells", "pricing_psychology", "risk_reversal"],
                },
                "audience_model": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "avatar_name": {"type": "string"},
                            "demographics": {"type": "string"},
                            "psychographics": {"type": "string"},
                            "pains": {"type": "array", "items": {"type": "string"}},
                            "desires": {"type": "array", "items": {"type": "string"}},
                            "triggers": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["avatar_name", "demographics", "psychographics", "pains", "desires", "triggers"],
                    },
                },
                "differentiation_layer": {
                    "type": "object",
                    "properties": {
                        "usp": {"type": "string"},
                        "competitive_moat": {"type": "string"},
                        "proof_points": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["usp", "competitive_moat", "proof_points"],
                },
                "narrative_assets": {
                    "type": "object",
                    "properties": {
                        "lore": {"type": "string"},
                        "story_hooks": {"type": "array", "items": {"type": "string"}},
                        "core_myths": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["lore", "story_hooks", "core_myths"],
                },
                "creative_dna": {
                    "type": "object",
                    "properties": {
                        "color_palette": {"type": "array", "items": {"type": "string"}},
                        "typography_intent": {"type": "string"},
                        "visual_constraints": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["color_palette", "typography_intent", "visual_constraints"],
                },
                "market_context": {
                    "type": "object",
                    "properties": {
                        "seasonal_factors": {"type": "array", "items": {"type": "string"}},
                        "current_trends": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["seasonal_factors", "current_trends"],
                },
                "competitor_map": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "strategy_type": {"type": "string"},
                            "weak_points": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name", "strategy_type", "weak_points"],
                    },
                },
                "opportunity_map": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "gap_id": {"type": "string"},
                            "strategy_recommendation": {"type": "string"},
                            "estimated_impact": {
                                "type": "number",
                                "description": "Estimated business impact of pursuing this opportunity, 0-100. Consider market size, competitive gap severity, brand readiness, and revenue potential.",
                            },
                            "impact_reasoning": {
                                "type": "string",
                                "description": "1-2 sentences explaining why this impact score was assigned.",
                            },
                        },
                        "required": ["gap_id", "strategy_recommendation", "estimated_impact", "impact_reasoning"],
                    },
                },
            },
            "required": [
                "core_identity", "offer_layer", "audience_model", "differentiation_layer",
                "narrative_assets", "creative_dna", "market_context", "competitor_map", "opportunity_map",
            ],
        },
    },
}


class BrandMapBuilder:
    def __init__(self):
        self.db = VectorDBClient()

    def build(self, raw_text: str) -> BrandMap:
        trace_id = get_trace_id()
        logger.info(f"BRANDMAP_GEN_STARTED | trace_id={trace_id} | input_length={len(raw_text)}")

        content_hash = BrandMap.content_hash(raw_text)
        logger.info(f"BRANDMAP_VERSION_HASH | hash={content_hash}")

        user_content = (
            "Perform an Architect Analysis on the following brand text "
            f"and extract the complete brand map:\n\n{raw_text}"
        )

        request = LLMRequest(
            task_type="brand_map",
            system_prompt=SYSTEM_PROMPT,
            user_content=user_content,
            max_tokens=8192,
            tools=[BRAND_MAP_TOOL],
            tool_choice={"type": "function", "function": {"name": "extract_brand_map"}},
        )

        response = get_llm_router().generate(request)
        data = self._normalize_data(response.content)

        now = datetime.utcnow()
        brand_map = BrandMap.model_validate({
            **data,
            "metadata": {
                "hash": content_hash,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        })

        self._store_in_chromadb(brand_map, content_hash)
        logger.info(f"BRANDMAP_GEN_COMPLETE | hash={content_hash} | avatars={len(brand_map.audience_model)}")

        return brand_map

    def _normalize_data(self, data: dict) -> dict:
        """Coerce common LLM output quirks into schema-compliant values.
        - String fields that are None → ""
        - List-of-strings where items are dicts → stringify them
        """
        def to_str(val) -> str:
            if val is None:
                return ""
            if isinstance(val, dict):
                # e.g. {"shade": "#F7D2C4", "name": "Peachykeen Pink"} → "Peachykeen Pink (#F7D2C4)"
                name = val.get("name") or val.get("shade") or val.get("color") or ""
                shade = val.get("shade") or val.get("hex") or ""
                return f"{name} ({shade})".strip(" ()") if (name or shade) else str(val)
            return str(val)

        def normalize_str_list(lst) -> list:
            if not isinstance(lst, list):
                return [to_str(lst)] if lst else []
            return [to_str(item) if not isinstance(item, str) else item for item in lst]

        # creative_dna
        if "creative_dna" in data:
            dna = data["creative_dna"]
            if "color_palette" in dna:
                dna["color_palette"] = normalize_str_list(dna["color_palette"])
            if "visual_constraints" in dna:
                dna["visual_constraints"] = normalize_str_list(dna["visual_constraints"])
            for field in ("typography_intent",):
                if dna.get(field) is None:
                    dna[field] = ""

        # Null-guard all top-level string fields across the whole payload
        def fix_nulls(obj):
            if isinstance(obj, dict):
                return {k: fix_nulls(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [fix_nulls(i) for i in obj]
            if obj is None:
                return ""
            return obj

        return fix_nulls(data)

    def _store_in_chromadb(self, brand_map: BrandMap, content_hash: str):
        # Placeholder embedding until real embedding pipeline is wired in CP2
        placeholder_embedding = [float(b) / 255.0 for b in bytes.fromhex(content_hash.ljust(768 * 2, "0")[:768 * 2])]

        self.db.upsert(
            collection_name="brand_maps",
            ids=[content_hash],
            embeddings=[placeholder_embedding],
            metadatas=[{
                "hash": content_hash,
                "mission": brand_map.core_identity.mission[:200],
                "main_product": brand_map.offer_layer.main_product[:200],
                "created_at": brand_map.metadata.created_at.isoformat(),
            }],
        )
        logger.info(f"BRANDMAP_STORED_IN_DB | collection=brand_maps | id={content_hash}")
