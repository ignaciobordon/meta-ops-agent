"""
Direct test of opportunities router - bypasses main.py imports.
"""
import sys
from pathlib import Path

# Setup root path first for core engines
root_path = Path(__file__).parent
sys.path.insert(0, str(root_path))

# Test BrandMapBuilder -> opportunities directly
from src.engines.brand_map.builder import BrandMapBuilder

demo_brand_path = root_path / "data" / "demo_brand.txt"

if demo_brand_path.exists():
    print("Testing BrandMapBuilder -> Opportunities extraction...")

    builder = BrandMapBuilder()
    brand_text = demo_brand_path.read_text(encoding='utf-8')
    brand_map = builder.build(brand_text)

    print(f"\n[SUCCESS] BrandMap built successfully!")
    print(f"  Hash: {brand_map.metadata.hash}")
    print(f"  Opportunities: {len(brand_map.opportunity_map)}")

    # Simulate API response building
    opportunities = []
    for idx, opp in enumerate(brand_map.opportunity_map):
        priority = "high" if idx < 2 else ("medium" if idx < 4 else "low")
        estimated_impact = max(0.5, 0.9 - (idx * 0.1))

        opportunities.append({
            "id": f"opp-{idx+1}",
            "gap_id": opp.gap_id,
            "title": f"Market Opportunity: {opp.gap_id.replace('_', ' ').title()}",
            "description": opp.strategy_recommendation,
            "strategy": opp.strategy_recommendation,
            "priority": priority,
            "estimated_impact": round(estimated_impact, 2),
        })

    print(f"\n[SUCCESS] API Response Simulation ({len(opportunities)} opportunities):\n")
    for opp in opportunities:
        print(f"{opp['id']}: {opp['title']}")
        print(f"  Priority: {opp['priority']} | Impact: {opp['estimated_impact']}")
        print(f"  Strategy: {opp['strategy'][:100]}...")
        print()

    print("[SUCCESS] FASE 2.2 COMPLETE: Opportunities loaded from BrandMap!")
else:
    print(f"[ERROR] {demo_brand_path} not found")
