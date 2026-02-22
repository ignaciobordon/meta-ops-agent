"""
Quick test script for opportunities API endpoint.
"""
import sys
from pathlib import Path

# Setup paths - root MUST be first for src.core imports
root_path = Path(__file__).parent
sys.path.insert(0, str(root_path))
sys.path.insert(0, str(root_path / "backend"))

# Now we can import
from fastapi.testclient import TestClient

# Import main from the backend directory context
import os
os.chdir(root_path / "backend")
from main import app
os.chdir(root_path)

client = TestClient(app)

# Test opportunities endpoint
print("Testing /api/opportunities endpoint...")
response = client.get("/api/opportunities/")
print(f"Status Code: {response.status_code}")

if response.status_code == 200:
    opportunities = response.json()
    print(f"\n✓ Success! Opportunities returned: {len(opportunities)}")
    print("\n--- API RESPONSE ---")
    for opp in opportunities:
        print(f"{opp['id']}: {opp['title']}")
        print(f"  Priority: {opp['priority']} | Impact: {opp['estimated_impact']}")
        print(f"  Strategy: {opp['strategy'][:100]}...")
        print()
else:
    print(f"\n✗ Error: {response.status_code}")
    print(response.text)
