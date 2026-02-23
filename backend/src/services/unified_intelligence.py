"""
Unified Intelligence Layer — Aggregates CI, BrandMap, Saturation, and Brain data
into a single LLM analysis to produce enriched, cross-referenced opportunities.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import (
    BrandMapProfile,
    EntityMemory,
    FeatureMemory,
    MetaCampaign,
    MetaInsightsDaily,
    InsightLevel,
    Organization,
)
from backend.src.ci.models import CICanonicalItem, CICompetitor, CICompetitorStatus
from backend.src.llm.router import LLMRouter
from backend.src.llm.schema import LLMRequest
from backend.src.services.analytics_service import (
    get_performance_summary,
    get_top_campaigns,
    generate_insights,
)
from sqlalchemy import func
from src.utils.logging_config import logger

import json

MAX_PILLAR_CHARS = 4000


class UnifiedIntelligenceService:
    """Aggregates all intelligence sources and generates enriched opportunities via LLM."""

    def __init__(self, db: Session, org_id):
        self.db = db
        self.org_id = UUID(org_id) if isinstance(org_id, str) else org_id

    @staticmethod
    def _summarize_pillar(data: Dict) -> Dict:
        """Enforce character budget per pillar. Serialize to JSON and truncate
        to MAX_PILLAR_CHARS so no single pillar can dominate the LLM context."""
        serialized = json.dumps(data, default=str)
        if len(serialized) <= MAX_PILLAR_CHARS:
            return data
        # Truncate the serialized JSON and re-parse a safe subset
        truncated = serialized[:MAX_PILLAR_CHARS - 20]
        # Find last complete key-value boundary to avoid broken JSON
        last_brace = truncated.rfind("}")
        last_bracket = truncated.rfind("]")
        cut = max(last_brace, last_bracket)
        if cut > 0:
            # Try to parse the truncated content
            attempts = [truncated[:cut + 1], truncated[:cut + 1] + "}"]
            for attempt in attempts:
                try:
                    return json.loads(attempt)
                except json.JSONDecodeError:
                    continue
        # Fallback: return original data (will be truncated as string in prompt)
        return data

    def gather_context(self, brand_profile_id: Optional[str] = None) -> Dict:
        """Gather intelligence context from all 4 modules with equal char budgets."""
        return {
            "brand_map": self._summarize_pillar(self._get_brand_map_context(brand_profile_id)),
            "ci_data": self._summarize_pillar(self._get_ci_context()),
            "saturation": self._summarize_pillar(self._get_saturation_context()),
            "brain": self._summarize_pillar(self._get_brain_context()),
        }

    def _get_brand_map_context(self, brand_profile_id: Optional[str] = None) -> Dict:
        """Extract brand positioning, strengths, weaknesses from latest BrandMap."""
        query = self.db.query(BrandMapProfile).filter(
            BrandMapProfile.org_id == self.org_id,
            BrandMapProfile.status == "ready",
        )
        if brand_profile_id:
            query = query.filter(BrandMapProfile.id == UUID(brand_profile_id))
        profile = query.order_by(BrandMapProfile.updated_at.desc()).first()

        if not profile or not profile.structured_json:
            return {"available": False}

        sj = profile.structured_json
        result = {
            "available": True,
            "brand_name": profile.name,
            "positioning": sj.get("positioning_statement", ""),
            "value_proposition": sj.get("value_proposition", ""),
            "target_audience": sj.get("target_audience", ""),
            "strengths": sj.get("strengths", []),
            "weaknesses": sj.get("weaknesses", []),
            "competitive_advantages": sj.get("competitive_advantages", []),
            "existing_opportunities": [
                {"gap_id": o.get("gap_id", ""), "strategy": o.get("strategy_recommendation", "")}
                for o in sj.get("opportunity_map", [])
            ][:10],
        }

        # Enrich with tone, personality, messaging, differentiators if present
        if sj.get("tone_of_voice"):
            result["tone_of_voice"] = sj["tone_of_voice"]
        if sj.get("brand_personality"):
            result["brand_personality"] = sj["brand_personality"]
        if sj.get("key_messages"):
            result["key_messages"] = sj["key_messages"][:5]
        if sj.get("differentiators"):
            result["differentiators"] = sj["differentiators"][:5]

        return result

    def _get_ci_context(self) -> Dict:
        """Extract competitor strategies — compact summaries per competitor.

        Every active competitor is queried and gets equal representation.
        Returns an extraction_audit with per-competitor item counts so the
        caller can verify full coverage.
        """
        competitors = self.db.query(CICompetitor).filter(
            CICompetitor.org_id == self.org_id,
            CICompetitor.status == CICompetitorStatus.ACTIVE,
        ).all()

        if not competitors:
            return {"available": False, "competitors": [], "competitor_names": [], "extraction_audit": {}}

        # Equal cap per competitor
        max_items_per_competitor = max(2, 10 // max(len(competitors), 1))

        from sqlalchemy import func

        comp_data = []
        all_competitor_names = [c.name for c in competitors]
        extraction_audit = {}  # per-competitor proof of extraction

        # Batch: get total counts per competitor in a single query
        competitor_ids = [c.id for c in competitors]
        count_rows = (
            self.db.query(CICanonicalItem.competitor_id, func.count(CICanonicalItem.id))
            .filter(CICanonicalItem.competitor_id.in_(competitor_ids))
            .group_by(CICanonicalItem.competitor_id)
            .all()
        )
        total_counts = {row[0]: row[1] for row in count_rows}

        # Batch: fetch all items for all competitors (capped per competitor via Python)
        all_items = (
            self.db.query(CICanonicalItem)
            .filter(CICanonicalItem.competitor_id.in_(competitor_ids))
            .order_by(CICanonicalItem.competitor_id, CICanonicalItem.last_seen_at.desc())
            .all()
        )
        items_by_comp = {}
        for item in all_items:
            items_by_comp.setdefault(item.competitor_id, []).append(item)

        for comp in competitors:
            total_in_db = total_counts.get(comp.id, 0)
            items = items_by_comp.get(comp.id, [])[:max_items_per_competitor]

            sample_titles = []
            angles_seen = []
            threat_level = ""
            analyzed_count = 0
            last_cta = ""

            for item in items:
                sample_titles.append((item.title or "")[:80])
                canonical = item.canonical_json or {}
                cta = ", ".join(canonical.get("cta_phrases", [])[:2]) if canonical.get("cta_phrases") else ""
                if cta:
                    last_cta = cta

                aj = item.analysis_json
                if isinstance(aj, dict) and aj:
                    analyzed_count += 1
                    analysis = aj.get("analysis", aj)
                    item_angles = (analysis.get("messaging_angles", []) or [])[:3]
                    angles_seen.extend(item_angles)
                    if not threat_level:
                        threat_level = analysis.get("threat_level", "")

            key_themes = "; ".join(dict.fromkeys(a for a in angles_seen if a))[:150]
            comp_data.append({
                "name": comp.name,
                "website": comp.website_url or "",
                "item_count": len(items),
                "analyzed": analyzed_count,
                "threat_level": threat_level,
                "key_themes": key_themes or "no analysis yet",
                "sample_titles": sample_titles[:3],
                "cta": last_cta,
            })

            extraction_audit[comp.name] = {
                "total_items_in_db": total_in_db,
                "items_extracted": len(items),
                "items_with_analysis": analyzed_count,
                "cap_applied": max_items_per_competitor,
                "has_themes": bool(key_themes),
                "has_threat_level": bool(threat_level),
            }

        # Log per-competitor extraction for auditability
        logger.info(
            "CI_EXTRACTION_AUDIT | org={} | competitors={} | audit={}",
            self.org_id, len(competitors), json.dumps(extraction_audit, default=str),
        )

        return {
            "available": len(comp_data) > 0,
            "competitor_names": all_competitor_names,
            "total_competitors": len(all_competitor_names),
            "competitors": comp_data,
            "extraction_audit": extraction_audit,
        }

    def _get_conversion_model(self) -> str:
        """Read conversion_model from org settings. Defaults to 'online'."""
        org = self.db.query(Organization).filter(Organization.id == self.org_id).first()
        if org and org.settings:
            return org.settings.get("conversion_model", "online")
        return "online"

    def _get_saturation_context(self) -> Dict:
        """Extract creative health + Meta campaign performance data."""
        since = datetime.utcnow() - timedelta(days=14)

        # ── Ad-level fatigue signals ──
        insights = self.db.query(MetaInsightsDaily).filter(
            MetaInsightsDaily.org_id == self.org_id,
            MetaInsightsDaily.level == InsightLevel.AD,
            MetaInsightsDaily.date_start >= since,
        ).order_by(MetaInsightsDaily.date_start.desc()).limit(50).all()

        ad_fatigue = {"saturated_creatives": [], "fresh_creatives": [], "total_ads_analyzed": 0}

        if insights:
            ad_data: Dict[str, list] = {}
            for row in insights:
                ad_data.setdefault(row.entity_meta_id, []).append(row)

            saturated = []
            fresh = []
            for ad_id, rows in ad_data.items():
                if len(rows) < 2:
                    continue
                avg_freq = sum(r.frequency or 0 for r in rows) / len(rows)
                avg_ctr = sum(r.ctr or 0 for r in rows) / len(rows)
                first_ctr = rows[-1].ctr or 0
                last_ctr = rows[0].ctr or 0

                if avg_freq > 3.0 and last_ctr < first_ctr:
                    saturated.append({"name": ad_id[:60], "frequency": round(avg_freq, 1), "ctr_decline": round(first_ctr - last_ctr, 2)})
                elif avg_freq < 2.0 and avg_ctr > 1.0:
                    fresh.append({"name": ad_id[:60], "ctr": round(avg_ctr, 2)})

            ad_fatigue = {
                "saturated_creatives": saturated[:5],
                "fresh_creatives": fresh[:5],
                "total_ads_analyzed": len(ad_data),
            }

        # ── Campaign performance from analytics_service ──
        try:
            perf = get_performance_summary(self.db, self.org_id, days=14)
        except Exception:
            perf = {}

        try:
            top_camps = get_top_campaigns(self.db, self.org_id, days=14, limit=8)
        except Exception:
            top_camps = []

        conversion_model = self._get_conversion_model()

        try:
            rule_insights = generate_insights(self.db, self.org_id, days=14, conversion_model=conversion_model)
        except Exception:
            rule_insights = []

        # Compact top campaigns — truncate names, keep key metrics only
        top_campaigns_compact = [
            {
                "name": c["name"][:40],
                "objective": c.get("objective", ""),
                "spend": c.get("spend", 0),
                "ctr": c.get("ctr", 0),
                "cpc": c.get("cpc", 0),
                "roas": c.get("roas", 0),
                "frequency": c.get("frequency", 0),
            }
            for c in top_camps
        ]

        # Bottom 3 by CTR (campaigns with impressions, sorted ascending by CTR)
        camps_with_traffic = [c for c in top_camps if c.get("impressions", 0) > 100]
        bottom_campaigns = sorted(camps_with_traffic, key=lambda c: c.get("ctr", 0))[:3]
        bottom_campaigns_compact = [
            {
                "name": c["name"][:40],
                "objective": c.get("objective", ""),
                "spend": c.get("spend", 0),
                "ctr": c.get("ctr", 0),
                "cpc": c.get("cpc", 0),
                "roas": c.get("roas", 0),
            }
            for c in bottom_campaigns
        ]

        # Compact insights
        insights_compact = [
            {
                "type": i.get("type", ""),
                "title": i.get("title", ""),
                "description": i.get("description", "")[:120],
                "metric_value": i.get("metric_value", ""),
            }
            for i in rule_insights[:6]
        ]

        # Compact performance summary — drop redundant fields
        perf_summary = {}
        if perf:
            perf_summary = {
                "spend": perf.get("total_spend", 0),
                "impressions": perf.get("total_impressions", 0),
                "clicks": perf.get("total_clicks", 0),
                "conversions": perf.get("total_conversions", 0),
                "ctr": perf.get("avg_ctr", 0),
                "cpc": perf.get("avg_cpc", 0),
                "cpm": perf.get("avg_cpm", 0),
                "roas": perf.get("avg_roas", 0),
                "spend_trend": perf.get("spend_trend"),
                "ctr_trend": perf.get("ctr_trend"),
                "roas_trend": perf.get("roas_trend"),
            }

        # If offline conversion model, strip ROAS/conversion data and add note
        if conversion_model == "offline":
            if perf_summary:
                perf_summary.pop("conversions", None)
                perf_summary.pop("roas", None)
                perf_summary.pop("roas_trend", None)
                perf_summary["note"] = "Conversions tracked offline — ROAS/CPA not available from Meta"
            for c in top_campaigns_compact:
                c.pop("roas", None)
            for c in bottom_campaigns_compact:
                c.pop("roas", None)

        has_data = bool(insights) or bool(perf_summary) or bool(top_campaigns_compact)
        return {
            "available": has_data,
            "performance_summary": perf_summary,
            "top_campaigns": top_campaigns_compact,
            "bottom_campaigns": bottom_campaigns_compact,
            "insights": insights_compact,
            "ad_fatigue": ad_fatigue,
        }

    def _get_brain_context(self) -> Dict:
        """Extract trust scores, winning features, learned patterns + campaign performance patterns."""
        # Top trusted entities
        entities = self.db.query(EntityMemory).filter(
            EntityMemory.org_id == self.org_id,
        ).order_by(EntityMemory.trust_score.desc()).limit(5).all()

        # Top winning features
        features = self.db.query(FeatureMemory).filter(
            FeatureMemory.org_id == self.org_id,
            FeatureMemory.samples >= 3,
        ).order_by(FeatureMemory.win_rate.desc()).limit(5).all()

        # ── Campaign performance patterns (last 30 days) ──
        campaign_patterns = {}
        try:
            since_30d = datetime.utcnow() - timedelta(days=30)
            camp_rows = self.db.query(
                MetaInsightsDaily.entity_meta_id,
                func.sum(MetaInsightsDaily.spend).label("total_spend"),
                func.sum(MetaInsightsDaily.clicks).label("total_clicks"),
                func.sum(MetaInsightsDaily.impressions).label("total_impressions"),
                func.avg(MetaInsightsDaily.purchase_roas).label("avg_roas"),
                MetaCampaign.name,
                MetaCampaign.objective,
            ).outerjoin(
                MetaCampaign,
                (MetaCampaign.meta_campaign_id == MetaInsightsDaily.entity_meta_id) &
                (MetaCampaign.org_id == MetaInsightsDaily.org_id),
            ).filter(
                MetaInsightsDaily.org_id == self.org_id,
                MetaInsightsDaily.level == InsightLevel.CAMPAIGN,
                MetaInsightsDaily.date_start >= since_30d,
            ).group_by(
                MetaInsightsDaily.entity_meta_id,
                MetaCampaign.name,
                MetaCampaign.objective,
            ).all()

            if camp_rows:
                camps = []
                for r in camp_rows:
                    spend = float(r.total_spend or 0)
                    impressions = int(r.total_impressions or 0)
                    clicks = int(r.total_clicks or 0)
                    roas = float(r.avg_roas or 0)
                    ctr = (clicks / impressions * 100) if impressions > 0 else 0
                    camps.append({
                        "name": (r.name or r.entity_meta_id)[:40],
                        "objective": r.objective or "",
                        "spend": round(spend, 2),
                        "roas": round(roas, 2),
                        "ctr": round(ctr, 2),
                    })

                total_spend = sum(c["spend"] for c in camps)
                avg_roas = sum(c["roas"] for c in camps) / len(camps) if camps else 0

                # Best/worst by ROAS (only campaigns with spend > 0)
                camps_with_spend = [c for c in camps if c["spend"] > 0]
                by_roas = sorted(camps_with_spend, key=lambda c: c["roas"], reverse=True)
                best_roas = by_roas[:3]
                worst_roas = by_roas[-3:] if len(by_roas) >= 3 else by_roas

                # Objective performance breakdown
                obj_map: Dict[str, list] = {}
                for c in camps:
                    obj = c["objective"] or "Unknown"
                    obj_map.setdefault(obj, []).append(c)

                objective_perf = []
                for obj, obj_camps in obj_map.items():
                    obj_spend = sum(c["spend"] for c in obj_camps)
                    obj_avg_ctr = sum(c["ctr"] for c in obj_camps) / len(obj_camps)
                    obj_avg_roas = sum(c["roas"] for c in obj_camps) / len(obj_camps)
                    objective_perf.append({
                        "objective": obj,
                        "spend": round(obj_spend, 2),
                        "avg_ctr": round(obj_avg_ctr, 2),
                        "avg_roas": round(obj_avg_roas, 2),
                        "campaign_count": len(obj_camps),
                    })

                campaign_patterns = {
                    "total_campaigns": len(camps),
                    "total_spend_30d": round(total_spend, 2),
                    "avg_roas": round(avg_roas, 2),
                    "best_roas_campaigns": best_roas,
                    "worst_roas_campaigns": worst_roas,
                    "objective_performance": objective_perf,
                }
        except Exception:
            campaign_patterns = {}

        if not entities and not features and not campaign_patterns:
            return {"available": False}

        # If offline conversion model, strip ROAS from campaign patterns
        conversion_model = self._get_conversion_model()
        if conversion_model == "offline" and campaign_patterns:
            campaign_patterns.pop("avg_roas", None)
            for c in campaign_patterns.get("best_roas_campaigns", []):
                c.pop("roas", None)
            for c in campaign_patterns.get("worst_roas_campaigns", []):
                c.pop("roas", None)
            for o in campaign_patterns.get("objective_performance", []):
                o.pop("avg_roas", None)
            campaign_patterns["note"] = "Conversions tracked offline — ROAS not available from Meta"

        return {
            "available": True,
            "top_entities": [
                {"id": e.entity_id, "type": e.entity_type, "trust": round(e.trust_score, 1)}
                for e in entities
            ],
            "winning_features": [
                {"key": f.feature_key, "type": f.feature_type, "win_rate": round(f.win_rate, 2), "samples": f.samples}
                for f in features
            ],
            "campaign_patterns": campaign_patterns,
        }

    def analyze(self, brand_profile_id: Optional[str] = None) -> List[Dict]:
        """Run unified intelligence analysis via two isolated LLM passes.

        Pass 1 — Internal pillars (brand, saturation, brain): generates 6
        opportunities with ZERO competitor data in context, eliminating CI bias.

        Pass 2 — Competitive pillar (CI + light brand context): generates 2
        opportunities focused on competitive gaps.

        This structural isolation guarantees non-CI opportunities are never
        influenced by competitor data.
        """
        context = self.gather_context(brand_profile_id)

        competitor_names = context["ci_data"].get("competitor_names", [])
        n_competitors = len(competitor_names)
        competitor_list_str = ", ".join(competitor_names) if competitor_names else "none"

        # Log pillar sizes for verification
        pillar_sizes = {
            k: len(json.dumps(v, default=str))
            for k, v in context.items()
        }
        logger.info(
            "UNIFIED_INTELLIGENCE_PILLAR_SIZES | org={} | sizes={}",
            self.org_id, pillar_sizes,
        )

        router = LLMRouter()
        now_iso = datetime.utcnow().isoformat()
        conversion_model = self._get_conversion_model()

        # Build offline sales instruction if applicable
        offline_instruction = ""
        if conversion_model == "offline":
            offline_instruction = (
                "\n\nIMPORTANT: This business closes sales offline (outside Meta). "
                "Do NOT flag zero conversions or low ROAS as problems. "
                "ROAS and conversion data from Meta are NOT meaningful for this business. "
                "Focus on top-of-funnel metrics: CTR, CPM, frequency, reach, engagement.\n"
            )

        # ── PASS 1: Internal pillars (brand + saturation + brain) ────────
        # CI data is deliberately excluded so the LLM cannot be biased by it.
        internal_available = [
            k for k in ("brand_map", "saturation", "brain")
            if context[k].get("available")
        ]

        pass1_system = f"""You are a strategic marketing analyst. You receive data from 3 internal intelligence sources about OUR brand's own positioning and performance. There is NO competitor data — do not invent or reference any competitors.{offline_instruction}

## THE 3 PILLARS
1. **BRAND** — positioning, strengths, weaknesses, audience, value proposition, tone, differentiators
2. **SATURATION** — campaign KPIs, top/bottom campaigns by performance, ad fatigue, rule-based insights from Meta Ads data
3. **BRAIN** — trust scores, winning features, campaign ROAS/CTR patterns, objective performance breakdowns

## RULES
1. Generate EXACTLY 6 opportunities: 2 x primary_source="brandmap", 2 x primary_source="saturation", 2 x primary_source="brain".
2. Each opportunity must be grounded in the ACTUAL DATA from its pillar — reference specific campaign names, metrics, entity IDs, win rates, scores.
3. Do NOT mention, reference, or compare to any competitor or external brand. These opportunities are about OUR OWN data only.
4. Each opportunity must propose a unique strategic angle.
5. Confidence: 3 internal sources confirm = 0.85-0.95, 2 = 0.6-0.75, 1 = 0.35-0.5.

## OUTPUT FORMAT
Return a JSON array with exactly 6 objects:
{{
  "id": "opp-N",
  "gap_id": "short_snake_case_id",
  "title": "Clear, actionable title",
  "description": "What and why — referencing actual data",
  "strategy": "Numbered action steps with specific metrics/names",
  "priority": "high|medium|low",
  "estimated_impact": 0.0-1.0,
  "impact_reasoning": "Why this score, citing data",
  "confidence": 0.0-1.0,
  "primary_source": "brandmap|saturation|brain",
  "sources": ["list", "of", "supporting", "sources"],
  "identified_at": "{now_iso}"
}}

If a pillar has no data (available=false), redistribute its 2 slots across available pillars."""

        pass1_user = f"""## Internal Intelligence Data (No Competitor Data)

### BrandMap
{json.dumps(context['brand_map'], indent=2, default=str)}

### Saturation & Campaign Performance
{json.dumps(context['saturation'], indent=2, default=str)}

### Brain — Learned Patterns & Campaign Patterns
{json.dumps(context['brain'], indent=2, default=str)}

### Metadata
- Available internal sources: {', '.join(internal_available)} ({len(internal_available)}/3)

Generate EXACTLY 6 opportunities: 2 x brandmap, 2 x saturation, 2 x brain. Do NOT reference any competitors."""

        pass1_request = LLMRequest(
            task_type="ci_analysis",
            system_prompt=pass1_system,
            user_content=pass1_user,
            temperature=0.4,
            max_tokens=4096,
        )
        pass1_response = router.generate(pass1_request)
        internal_opps = self._parse_opportunities(pass1_response.raw_text or "")

        logger.info(
            "UNIFIED_INTELLIGENCE_PASS1_DONE | org={} | internal_opps={}",
            self.org_id, len(internal_opps),
        )

        # ── PASS 2: Competitive pillar (CI + light brand context) ────────
        ci_opps = []
        if context["ci_data"].get("available"):
            # Include minimal brand context so CI opportunities can reference
            # our positioning, but NO saturation/brain data
            brand_name = context["brand_map"].get("brand_name", "Our brand")
            brand_brief = {
                "brand_name": brand_name,
                "positioning": context["brand_map"].get("positioning", ""),
                "value_proposition": context["brand_map"].get("value_proposition", ""),
            }

            pass2_system = f"""You are a competitive intelligence analyst. You receive data about {n_competitors} competitor(s) and a brief summary of OUR brand positioning.{offline_instruction}

## RULES
1. Generate EXACTLY 2 competitive opportunities with primary_source="ci".
2. Each must reference a DIFFERENT competitor if multiple exist. Competitors: {competitor_list_str}.
3. Focus on exploitable gaps, counter-positioning, and strategic weaknesses.
4. Reference specific competitor data: themes, threat levels, sample titles.
5. Confidence: 0.5-0.75 (competitive intelligence is inherently less certain).

## OUTPUT FORMAT
Return a JSON array with exactly 2 objects:
{{
  "id": "opp-7",
  "gap_id": "short_snake_case_id",
  "title": "Clear, actionable competitive title",
  "description": "The competitive gap and why it matters",
  "strategy": "Numbered action steps to exploit the gap",
  "priority": "high|medium|low",
  "estimated_impact": 0.0-1.0,
  "impact_reasoning": "Why this score, citing competitor data",
  "confidence": 0.0-1.0,
  "primary_source": "ci",
  "sources": ["ci"],
  "identified_at": "{now_iso}"
}}"""

            pass2_user = f"""## Our Brand (brief)
{json.dumps(brand_brief, indent=2, default=str)}

## Competitive Intelligence — {n_competitors} competitors: {competitor_list_str}
{json.dumps(context['ci_data'], indent=2, default=str)}

Generate EXACTLY 2 CI opportunities, each about a different competitor if possible."""

            pass2_request = LLMRequest(
                task_type="ci_analysis",
                system_prompt=pass2_system,
                user_content=pass2_user,
                temperature=0.4,
                max_tokens=2048,
            )
            pass2_response = router.generate(pass2_request)
            ci_opps = self._parse_opportunities(pass2_response.raw_text or "")

            logger.info(
                "UNIFIED_INTELLIGENCE_PASS2_DONE | org={} | ci_opps={} | competitors={}",
                self.org_id, len(ci_opps), competitor_list_str,
            )

        # ── Merge, re-number, and validate ─────────────────────────────
        opportunities = internal_opps + ci_opps
        for idx, opp in enumerate(opportunities, 1):
            opp["id"] = f"opp-{idx}"

        # ── Post-generation validation ───────────────────────────────────
        validation = self._validate_opportunities(opportunities, competitor_names)

        # Attach audit metadata to the output
        extraction_audit = context["ci_data"].get("extraction_audit", {})

        logger.info(
            "UNIFIED_INTELLIGENCE_DONE | org={} | opportunities={} | sources={} "
            "| competitors_analyzed={} | extraction_audit={} | validation={}",
            self.org_id, len(opportunities),
            {k: v.get("available", False) for k, v in context.items()},
            competitor_list_str,
            json.dumps(extraction_audit, default=str),
            json.dumps(validation, default=str),
        )

        return opportunities

    @staticmethod
    def _validate_opportunities(
        opportunities: List[Dict], competitor_names: List[str]
    ) -> Dict:
        """Validate the final opportunities for pillar balance and competitor isolation.

        Returns an audit dict with pass/fail checks — logged for traceability.
        Does NOT modify or reject opportunities; it reports issues.
        """
        checks: Dict[str, Any] = {}

        # Check 1: Source distribution
        source_counts: Dict[str, int] = {}
        for opp in opportunities:
            src = opp.get("primary_source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
        checks["source_distribution"] = source_counts
        checks["balanced"] = all(
            source_counts.get(s, 0) >= 1
            for s in ("brandmap", "saturation", "brain", "ci")
            if s != "ci" or competitor_names  # CI only expected if competitors exist
        )

        # Check 2: Competitor name isolation — non-CI opportunities must not
        # contain competitor names (case-insensitive check on all text fields)
        competitor_names_lower = [n.lower() for n in competitor_names]
        leaked = []
        for opp in opportunities:
            if opp.get("primary_source") == "ci":
                continue
            text_blob = " ".join([
                opp.get("title", ""),
                opp.get("description", ""),
                opp.get("strategy", ""),
                opp.get("impact_reasoning", ""),
            ]).lower()
            for cname in competitor_names_lower:
                if cname in text_blob:
                    leaked.append({
                        "opp_id": opp.get("id", ""),
                        "source": opp.get("primary_source", ""),
                        "leaked_competitor": cname,
                    })
        checks["competitor_leaks"] = leaked
        checks["isolation_clean"] = len(leaked) == 0

        # Check 3: CI competitor coverage — which competitors are referenced
        ci_opps = [o for o in opportunities if o.get("primary_source") == "ci"]
        referenced_competitors = set()
        for opp in ci_opps:
            text_blob = " ".join([
                opp.get("title", ""),
                opp.get("description", ""),
                opp.get("strategy", ""),
            ]).lower()
            for cname in competitor_names_lower:
                if cname in text_blob:
                    referenced_competitors.add(cname)
        checks["ci_competitors_referenced"] = list(referenced_competitors)
        checks["ci_coverage_ratio"] = (
            f"{len(referenced_competitors)}/{len(competitor_names)}"
            if competitor_names else "N/A"
        )

        return checks

    @staticmethod
    def _parse_opportunities(raw_text: str) -> List[Dict]:
        """Parse LLM response into opportunities list."""
        import re

        # Try direct JSON parse
        try:
            result = json.loads(raw_text)
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and "opportunities" in result:
                return result["opportunities"]
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown fences
        match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', raw_text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding a JSON array in the text
        match = re.search(r'(\[[\s\S]*\])', raw_text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        logger.warning("UNIFIED_INTELLIGENCE_PARSE_FAILED | Could not parse LLM response")
        return []
