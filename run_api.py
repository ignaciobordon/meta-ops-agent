"""
FastAPI server entry point - runs from project root.
"""
import sys
from pathlib import Path

# Add project root AND backend to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))  # For src.core, src.schemas, etc.
sys.path.insert(0, str(project_root / "backend"))  # For backend imports

from backend.main import app  # noqa

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("run_api:app", host="0.0.0.0", port=8000, reload=True)
