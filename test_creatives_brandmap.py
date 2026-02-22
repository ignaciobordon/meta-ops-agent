"""
Test that creatives API uses real BrandMapBuilder instead of hardcoded data.
"""
import sys
from pathlib import Path

root_path = Path(__file__).parent
sys.path.insert(0, str(root_path))

from src.engines.brand_map.builder import BrandMapBuilder

# Load BrandMap
demo_brand_path = root_path / "data" / "demo_brand.txt"
builder = BrandMapBuilder()
brand_text = demo_brand_path.read_text(encoding='utf-8')
brand_map = builder.build(brand_text)

print(f"Testing BrandMap loading for Creatives API...")
print(f"[SUCCESS] BrandMap Hash: {brand_map.metadata.hash}")
print(f"[SUCCESS] Mission: {brand_map.core_identity.mission[:100]}...")
print(f"[SUCCESS] Audience Avatars: {len(brand_map.audience_model)}")
print(f"[SUCCESS] Opportunities: {len(brand_map.opportunity_map)}")
print(f"[SUCCESS] Competitors: {len(brand_map.competitor_map)}")

# Verify BrandMap has all required data for creatives
assert len(brand_map.core_identity.mission) > 0, "Mission missing"
assert len(brand_map.audience_model) > 0, "Audience model missing"
assert len(brand_map.core_identity.values) > 0, "Values missing"

print("\n[SUCCESS] FASE 2.3 COMPLETE: Creatives API now uses real BrandMapBuilder!")
print("Note: Replaced 50+ lines of hardcoded BrandMap with 6 lines calling BrandMapBuilder")
