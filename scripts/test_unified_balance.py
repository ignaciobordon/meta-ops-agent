"""
Test script: Verify unified intelligence produces balanced, unbiased opportunities.

Runs the two-pass analysis directly against the DB and validates:
1. All competitors extracted equally (extraction_audit)
2. Source distribution is 6 internal + 2 CI
3. Zero competitor name leaks in non-CI opportunities
4. CI opportunities reference actual competitors

Usage: python scripts/test_unified_balance.py
"""
import json
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.src.database.session import get_db_context
from backend.src.database.models import Organization


def main():
    print("=" * 70)
    print("  Unified Intelligence - Balance & Bias Test")
    print("=" * 70)

    with get_db_context() as db:
        # Find an org with data
        org = db.query(Organization).first()
        if not org:
            print("\n  [ERROR] No organizations found in DB. Run seed_demo.py first.")
            return 1

        org_id = org.id
        print(f"\n  Org: {org.name} ({org_id})")

        # -- Step 1: Gather context and check data availability ------─
        print("\n-- Step 1: Gathering context from all 4 pillars --")
        from backend.src.services.unified_intelligence import UnifiedIntelligenceService

        svc = UnifiedIntelligenceService(db, org_id)
        context = svc.gather_context()

        for pillar, data in context.items():
            available = data.get("available", False)
            char_count = len(json.dumps(data, default=str))
            status = "OK" if available else "EMPTY"
            print(f"  [{status}] {pillar:15s} | {char_count:,} chars | available={available}")

        # -- Step 2: Verify CI extraction audit ----------------------─
        print("\n-- Step 2: CI Extraction Audit --")
        ci_data = context.get("ci_data", {})
        competitor_names = ci_data.get("competitor_names", [])
        extraction_audit = ci_data.get("extraction_audit", {})

        if not competitor_names:
            print("  [WARN] No competitors tracked. CI pass will be skipped.")
        else:
            print(f"  Competitors tracked: {len(competitor_names)}")
            for name, audit in extraction_audit.items():
                print(f"    {name:30s} | db_items={audit['total_items_in_db']:3d} "
                      f"| extracted={audit['items_extracted']:2d} "
                      f"| analyzed={audit['items_with_analysis']:2d} "
                      f"| themes={'Y' if audit['has_themes'] else 'N'} "
                      f"| threat={'Y' if audit['has_threat_level'] else 'N'}")

            # Check equal extraction
            extracted_counts = [a["items_extracted"] for a in extraction_audit.values()]
            if len(set(extracted_counts)) <= 1:
                print(f"  [PASS] Equal extraction: {extracted_counts[0]} items per competitor")
            else:
                print(f"  [WARN] Unequal extraction: {dict(zip(extraction_audit.keys(), extracted_counts))}")

        # -- Step 3: Run the two-pass analysis ------------------------
        print("\n-- Step 3: Running two-pass LLM analysis --")
        print("  Pass 1: brand + saturation + brain (no CI data) ...")
        print("  Pass 2: CI + light brand brief ...")

        opportunities = svc.analyze()
        print(f"  Total opportunities generated: {len(opportunities)}")

        # -- Step 4: Validate source distribution --------------------─
        print("\n-- Step 4: Source Distribution --")
        source_counts = {}
        for opp in opportunities:
            src = opp.get("primary_source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1

        for src in ("brandmap", "saturation", "brain", "ci"):
            count = source_counts.get(src, 0)
            expected = 2
            status = "PASS" if count >= expected else "FAIL"
            print(f"  [{status}] {src:12s}: {count} opportunities (expected {expected})")

        # -- Step 5: Competitor isolation check ----------------------─
        print("\n-- Step 5: Competitor Isolation Check --")
        competitor_names_lower = [n.lower() for n in competitor_names]
        leaks = []

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
                    leaks.append((opp.get("id"), opp.get("primary_source"), cname))

        if not leaks:
            print(f"  [PASS] Zero competitor name leaks in {len([o for o in opportunities if o.get('primary_source') != 'ci'])} non-CI opportunities")
        else:
            print(f"  [FAIL] {len(leaks)} leak(s) detected:")
            for opp_id, src, cname in leaks:
                print(f"    {opp_id} (source={src}) mentions '{cname}'")

        # -- Step 6: CI competitor coverage ----------------------------
        print("\n-- Step 6: CI Competitor Coverage --")
        ci_opps = [o for o in opportunities if o.get("primary_source") == "ci"]
        referenced = set()
        for opp in ci_opps:
            text_blob = " ".join([
                opp.get("title", ""),
                opp.get("description", ""),
                opp.get("strategy", ""),
            ]).lower()
            for cname in competitor_names_lower:
                if cname in text_blob:
                    referenced.add(cname)

        if competitor_names:
            print(f"  CI opportunities reference: {len(referenced)}/{len(competitor_names)} competitors")
            for cname in competitor_names:
                status = "REF" if cname.lower() in referenced else "MISS"
                print(f"    [{status}] {cname}")
        else:
            print("  [N/A] No competitors to check")

        # -- Step 7: Print all opportunities --------------------------
        print("\n-- Step 7: Full Opportunity Output --")
        for opp in opportunities:
            priority = opp.get("priority", "?").upper()
            source = opp.get("primary_source", "?")
            impact = opp.get("estimated_impact", 0)
            confidence = opp.get("confidence", 0)
            print(f"\n  [{priority}] {opp.get('id', '?')} | source={source} | impact={impact} | confidence={confidence}")
            print(f"  Title: {opp.get('title', 'N/A')}")
            print(f"  Description: {opp.get('description', 'N/A')[:200]}")
            print(f"  Strategy: {opp.get('strategy', 'N/A')[:200]}")

        # -- Summary --------------------------------------------------
        print("\n" + "=" * 70)
        all_pass = (
            len(leaks) == 0
            and source_counts.get("brandmap", 0) >= 2
            and source_counts.get("saturation", 0) >= 2
            and source_counts.get("brain", 0) >= 2
        )
        if all_pass:
            print("  RESULT: ALL CHECKS PASSED")
        else:
            print("  RESULT: SOME CHECKS FAILED - review output above")
        print("=" * 70)

        return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
