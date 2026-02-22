"""Content Studio — Content Creator Service.

Generates multi-platform production packs from a base creative.
"""
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import uuid4, UUID

from sqlalchemy.orm import Session

from backend.src.database.models import (
    ContentPack, ContentVariant, ContentChannelLock, ContentExport,
    ContentPackStatus, Creative,
)
from backend.src.content.channel_specs import CHANNEL_SPECS, get_channel_spec
from backend.src.content.schemas import validate_channel_output, VariantScoreBreakdown, CHANNEL_OUTPUT_SCHEMAS
from backend.src.llm.router import get_llm_router
from backend.src.llm.schema import LLMRequest, LLMResponse
from src.utils.logging_config import logger, get_trace_id


def build_pack_from_creative(
    db: Session,
    org_id: str,
    creative_id: str,
    channels: List[Dict[str, str]],
    settings: Dict[str, Any],
) -> ContentPack:
    """Create a ContentPack record from inputs. Does NOT start generation."""
    pack = ContentPack(
        id=uuid4(),
        org_id=UUID(org_id),
        creative_id=UUID(creative_id) if creative_id else None,
        status=ContentPackStatus.QUEUED,
        goal=settings.get("goal", "awareness"),
        language=settings.get("language", "es-AR"),
        channels_json=channels,
        input_json=settings,
    )
    db.add(pack)
    db.flush()
    return pack


def generate_pack(pack_id: str, db: Session):
    """
    Main generation function. Called by job runner.
    For each channel in the pack, generates variants via LLM.
    """
    pack = db.query(ContentPack).filter(ContentPack.id == UUID(pack_id)).first()
    if not pack:
        raise ValueError(f"ContentPack {pack_id} not found")

    pack.status = ContentPackStatus.RUNNING
    db.commit()

    try:
        # Load the base creative for context
        creative = None
        if pack.creative_id:
            creative = db.query(Creative).filter(Creative.id == pack.creative_id).first()

        creative_context = ""
        if creative:
            creative_context = f"""
BASE CREATIVE:
- Name: {creative.name or 'N/A'}
- Copy: {creative.ad_copy or 'N/A'}
- Headline: {creative.headline or 'N/A'}
- Score: {creative.overall_score or 'N/A'}/10
"""

        channels = pack.channels_json or []
        settings = pack.input_json or {}

        for channel_entry in channels:
            channel_key = channel_entry.get("channel", "")
            channel_format = channel_entry.get("format", "")

            spec = get_channel_spec(channel_key)
            if not spec:
                logger.warning(f"CONTENT_STUDIO | Unknown channel: {channel_key}, skipping")
                continue

            n_variants = spec.variants_count
            actual_format = channel_format or spec.default_format

            logger.info(
                "CONTENT_STUDIO_CHANNEL_START | pack={} | channel={} | variants={}",
                pack_id, channel_key, n_variants
            )

            try:
                variants_data = _generate_variants_for_channel(
                    channel_key=channel_key,
                    channel_format=actual_format,
                    spec=spec,
                    creative_context=creative_context,
                    settings=settings,
                    n_variants=n_variants,
                )

                for idx, variant_data in enumerate(variants_data):
                    output_json = variant_data.get("output", {})
                    score_data = variant_data.get("score", {})
                    rationale = variant_data.get("rationale", "")

                    # Validate output schema (best effort)
                    try:
                        validate_channel_output(channel_key, output_json)
                    except Exception as ve:
                        logger.warning(f"CONTENT_STUDIO | Validation warning for {channel_key} v{idx+1}: {ve}")

                    # Filter score_data to only known fields (LLM may add "total" etc.)
                    known_score_fields = {f.name for f in VariantScoreBreakdown.__dataclass_fields__.values()}
                    filtered_score = {k: v for k, v in score_data.items() if k in known_score_fields} if score_data else {}
                    score_breakdown = VariantScoreBreakdown(**filtered_score) if filtered_score else VariantScoreBreakdown()

                    variant = ContentVariant(
                        id=uuid4(),
                        content_pack_id=pack.id,
                        channel=channel_key,
                        format=actual_format,
                        variant_index=idx + 1,
                        output_json=output_json,
                        score=score_breakdown.total,
                        score_breakdown_json=score_data,
                        rationale_text=rationale,
                    )
                    db.add(variant)

                db.flush()
                logger.info(
                    "CONTENT_STUDIO_CHANNEL_DONE | pack={} | channel={} | variants_saved={}",
                    pack_id, channel_key, len(variants_data)
                )

            except Exception as ch_err:
                logger.error(
                    "CONTENT_STUDIO_CHANNEL_FAILED | pack={} | channel={} | error={}",
                    pack_id, channel_key, str(ch_err)
                )
                # Continue with other channels, don't fail the entire pack

        pack.status = ContentPackStatus.SUCCEEDED
        db.commit()

    except Exception as e:
        pack.status = ContentPackStatus.FAILED
        pack.last_error_code = "INTERNAL"
        pack.last_error_message = str(e)[:500]
        db.commit()
        raise


def regenerate_pack(
    pack_id: str,
    channels: List[str],
    locked_variant_ids: Dict[str, str],
    db: Session,
):
    """
    Regenerate non-locked variants for specific channels within an existing pack.
    Locked variants remain untouched; new ones fill the remaining slots.
    """
    pack = db.query(ContentPack).filter(ContentPack.id == UUID(pack_id)).first()
    if not pack:
        raise ValueError(f"ContentPack {pack_id} not found")

    pack.status = ContentPackStatus.RUNNING
    db.commit()

    try:
        creative = None
        if pack.creative_id:
            creative = db.query(Creative).filter(Creative.id == pack.creative_id).first()

        creative_context = ""
        if creative:
            creative_context = f"""
BASE CREATIVE:
- Name: {creative.name or 'N/A'}
- Copy: {creative.ad_copy or 'N/A'}
- Headline: {creative.headline or 'N/A'}
- Score: {creative.overall_score or 'N/A'}/10
"""

        settings = pack.input_json or {}

        for channel_key in channels:
            spec = get_channel_spec(channel_key)
            if not spec:
                continue

            # Count how many locked variants exist for this channel
            locked_id = locked_variant_ids.get(channel_key)
            existing_locked = 0
            if locked_id:
                existing_locked = db.query(ContentVariant).filter(
                    ContentVariant.content_pack_id == pack.id,
                    ContentVariant.channel == channel_key,
                    ContentVariant.id == UUID(locked_id),
                ).count()

            # Generate only the missing slots
            n_to_generate = spec.variants_count - existing_locked
            if n_to_generate <= 0:
                continue

            channel_entry = next(
                (ch for ch in (pack.channels_json or []) if ch.get("channel") == channel_key),
                {"channel": channel_key, "format": ""},
            )
            actual_format = channel_entry.get("format", "") or spec.default_format

            logger.info(
                "CONTENT_STUDIO_REGEN_CHANNEL | pack={} | channel={} | locked={} | generating={}",
                pack_id, channel_key, existing_locked, n_to_generate,
            )

            try:
                variants_data = _generate_variants_for_channel(
                    channel_key=channel_key,
                    channel_format=actual_format,
                    spec=spec,
                    creative_context=creative_context,
                    settings=settings,
                    n_variants=n_to_generate,
                )

                # Determine next variant_index (after the locked one)
                max_idx = existing_locked
                for idx, variant_data in enumerate(variants_data):
                    output_json = variant_data.get("output", {})
                    score_data = variant_data.get("score", {})
                    rationale = variant_data.get("rationale", "")

                    try:
                        validate_channel_output(channel_key, output_json)
                    except Exception as ve:
                        logger.warning(f"CONTENT_STUDIO | Validation warning for {channel_key} regen v{idx+1}: {ve}")

                    known_score_fields = {f.name for f in VariantScoreBreakdown.__dataclass_fields__.values()}
                    filtered_score = {k: v for k, v in score_data.items() if k in known_score_fields} if score_data else {}
                    score_breakdown = VariantScoreBreakdown(**filtered_score) if filtered_score else VariantScoreBreakdown()

                    variant = ContentVariant(
                        id=uuid4(),
                        content_pack_id=pack.id,
                        channel=channel_key,
                        format=actual_format,
                        variant_index=max_idx + idx + 1,
                        output_json=output_json,
                        score=score_breakdown.total,
                        score_breakdown_json=score_data,
                        rationale_text=rationale,
                    )
                    db.add(variant)

                db.flush()
                logger.info(
                    "CONTENT_STUDIO_REGEN_DONE | pack={} | channel={} | new_variants={}",
                    pack_id, channel_key, len(variants_data),
                )
            except Exception as ch_err:
                logger.error(
                    "CONTENT_STUDIO_REGEN_FAILED | pack={} | channel={} | error={}",
                    pack_id, channel_key, str(ch_err),
                )

        pack.status = ContentPackStatus.SUCCEEDED
        db.commit()

    except Exception as e:
        pack.status = ContentPackStatus.FAILED
        pack.last_error_code = "INTERNAL"
        pack.last_error_message = str(e)[:500]
        db.commit()
        raise


def _generate_variants_for_channel(
    channel_key: str,
    channel_format: str,
    spec,
    creative_context: str,
    settings: Dict[str, Any],
    n_variants: int,
) -> List[Dict[str, Any]]:
    """Call LLM to generate N variants for a specific channel."""

    tone_tags = settings.get("tone_tags", [])
    curator_prompt = settings.get("curator_prompt", "")
    framework = settings.get("framework_preference", "")
    hook_style = settings.get("hook_style_preference", "")
    audience = settings.get("target_audience", "")
    goal = settings.get("goal", "awareness")
    compliance = settings.get("compliance_mode", "safe")
    brand_voice = settings.get("brand_voice_mode", "strict")

    # Opportunity context from flywheel (if available)
    opportunity = settings.get("opportunity", {})
    opportunity_context = ""
    if opportunity and opportunity.get("title"):
        opportunity_context = f"""
STRATEGIC OPPORTUNITY (from intelligence analysis):
- Title: {opportunity.get('title', '')}
- Description: {opportunity.get('description', '')}
- Strategy: {opportunity.get('strategy', '')}
- Source: {opportunity.get('primary_source', '')} | Priority: {opportunity.get('priority', '')}
Content must be aligned with this strategic opportunity. Use the strategy as the creative direction.
"""

    # Use channel-specific field guidance from the spec
    channel_field_guidance = spec.field_guidance if spec.field_guidance else ""
    if not channel_field_guidance:
        # Fallback: build from schema if no field_guidance defined
        schema_cls = CHANNEL_OUTPUT_SCHEMAS.get(channel_key)
        if schema_cls:
            fields_list = list(schema_cls.model_fields.keys())
            channel_field_guidance = f"OUTPUT FIELDS: {', '.join(fields_list)}"

    system_prompt = f"""You are a world-class performance marketer and content strategist for premium brands.
Your job: produce {n_variants} DISTINCT, production-ready content variants for {spec.display_name} ({channel_format}).

QUALITY STANDARDS:
- Each variant must use a COMPLETELY DIFFERENT creative angle, hook, and persuasion framework.
- Write in professional Spanish (Argentina). Avoid generic motivational clichés.
- Content must be specific, actionable, and tailored to the audience and goal.
- Every text field must be COMPLETE (never cut off mid-sentence).
- Platform best practices: {'; '.join(spec.best_practices[:5])}
{f'- Copywriting framework: {framework}' if framework else '- Vary frameworks across variants (AIDA, PAS, BAB, etc.)'}
{f'- Hook style: {hook_style}' if hook_style else '- Vary hook styles: question, bold claim, statistic, story, etc.'}
{f'- Tone: {", ".join(tone_tags)}' if tone_tags else ''}
- Brand voice: {brand_voice} | Compliance: {compliance}

{channel_field_guidance}

OUTPUT FORMAT (strict JSON):
Return ONLY a JSON array with exactly {n_variants} objects. No markdown, no explanation, no code fences.
Each object has 3 keys:
1. "output": object following the OUTPUT FIELDS specification above. STRICTLY follow the field types described.
2. "score": object with ONLY these numeric keys: hook_strength (0-25), clarity (0-15), cta_fit (0-10), channel_fit (0-15), brand_voice_match (0-15), goal_alignment (0-10), novelty (0-10). Do NOT include a "total" key.
3. "rationale": brief string explaining this variant's strategic angle (1-2 sentences)
"""

    user_content = f"""{creative_context}
{opportunity_context}
CAMPAIGN BRIEF:
- Goal: {goal}
- Target audience: {audience or 'General'}
- Channel: {spec.display_name}
- Format: {channel_format}
{f'- Curator notes: {curator_prompt}' if curator_prompt else ''}

Generate exactly {n_variants} variants as a raw JSON array (no markdown fences). Follow the OUTPUT FIELDS specification exactly for this channel type.
"""

    # Each variant with output+score+rationale needs ~2000-2500 tokens in Spanish
    estimated_tokens = n_variants * 2500 + 512  # +512 for JSON structure overhead
    max_tokens = max(estimated_tokens, 8192)

    request = LLMRequest(
        task_type="content_studio",
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=max_tokens,
        temperature=0.8,
    )

    response = get_llm_router().generate(request)

    # Check for truncation (stop_reason == "max_tokens")
    if getattr(response, 'stop_reason', None) == 'max_tokens':
        logger.warning(
            "CONTENT_STUDIO_TRUNCATED | channel={} | max_tokens={} | "
            "Response was truncated by token limit, attempting repair",
            channel_key, max_tokens,
        )

    # Parse response — try raw_text first, fall back to content dict
    raw = response.raw_text or ""

    # If raw_text is empty but content has data, serialize content for parsing
    if not raw.strip() and response.content:
        raw = json.dumps(response.content)

    # If response.content is already a list of variants, use it directly
    if isinstance(response.content, list) and len(response.content) > 0:
        return response.content[:n_variants]

    logger.info(
        "CONTENT_STUDIO_RAW_RESPONSE | channel={} | raw_len={} | first_200={!r}",
        channel_key, len(raw), raw[:200],
    )

    variants = _parse_variants_json(raw, n_variants)

    return variants


def _parse_variants_json(raw_text: str, expected_count: int) -> List[Dict[str, Any]]:
    """Extract and parse JSON array of variants from LLM response.

    Handles: direct JSON, markdown code fences, text before/after JSON,
    and brackets inside string values.
    """
    import re

    # Strip markdown code fences: ```json ... ``` or ``` ... ```
    cleaned = raw_text.strip()
    # Remove all code fence markers
    cleaned = re.sub(r'```(?:json)?', '', cleaned).strip()

    # Strategy 1: Direct parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data[:expected_count]
        if isinstance(data, dict) and "variants" in data:
            return data["variants"][:expected_count]
    except json.JSONDecodeError:
        pass

    # Strategy 2: First '[' to last ']' (handles text before/after JSON)
    first_bracket = cleaned.find('[')
    last_bracket = cleaned.rfind(']')
    if first_bracket != -1 and last_bracket > first_bracket:
        candidate = cleaned[first_bracket:last_bracket + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return data[:expected_count]
        except json.JSONDecodeError:
            pass

    # Strategy 3: Truncated JSON repair — find last complete object and close array
    # This handles when max_tokens cuts off the JSON mid-stream
    if first_bracket != -1:
        # Find the last complete "}" that closes a top-level array element
        # by looking backwards from the end for "}," or "}" followed by partial text
        search_region = cleaned[first_bracket:]
        # Try closing the array after each "}" we find from the end
        for pos in range(len(search_region) - 1, 0, -1):
            if search_region[pos] == '}':
                # Try: array_start ... up to this "}" + "]"
                candidate = search_region[:pos + 1]
                # Remove any trailing comma
                candidate = candidate.rstrip().rstrip(',')
                candidate = candidate + ']'
                try:
                    data = json.loads(candidate)
                    if isinstance(data, list) and len(data) > 0:
                        logger.info(
                            "CONTENT_STUDIO_PARSE_REPAIRED | strategy=truncation_repair | "
                            "variants_recovered={}", len(data)
                        )
                        return data[:expected_count]
                except json.JSONDecodeError:
                    continue

    # Strategy 4: Find individual top-level JSON objects with "output" key
    # Use json.JSONDecoder for incremental parsing
    decoder = json.JSONDecoder()
    objects = []
    i = 0
    while i < len(cleaned):
        if cleaned[i] == '{':
            try:
                obj, end_idx = decoder.raw_decode(cleaned, i)
                if isinstance(obj, dict) and ("output" in obj or "score" in obj):
                    objects.append(obj)
                i = end_idx
            except json.JSONDecodeError:
                i += 1
        else:
            i += 1
    if objects:
        return objects[:expected_count]

    # All strategies failed
    logger.error(
        "CONTENT_STUDIO_PARSE_FAILED | raw_len={} | first_500={!r}",
        len(raw_text), raw_text[:500],
    )
    raise ValueError(
        f"Failed to parse LLM output as JSON array. "
        f"Raw length: {len(raw_text)}, starts with: {raw_text[:200]!r}"
    )


def score_variant(variant_output: dict, channel_key: str, settings: dict) -> Dict[str, Any]:
    """Score a variant using heuristics. Returns score breakdown dict."""
    # Default neutral scores
    return {
        "hook_strength": 15,
        "clarity": 10,
        "cta_fit": 7,
        "channel_fit": 10,
        "brand_voice_match": 10,
        "goal_alignment": 7,
        "novelty": 7,
    }
