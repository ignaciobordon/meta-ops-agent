"""Launch uvicorn with correct sys.path for multiprocess workers on Windows."""
import sys
import os
from pathlib import Path

# Set PYTHONPATH as env var so spawned workers inherit it
project_root = str(Path(__file__).parent.parent)
backend_dir = str(Path(__file__).parent)

# Add to current process sys.path
for p in [project_root, backend_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Set env var so multiprocessing spawn inherits paths
existing = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = f"{project_root}{os.pathsep}{backend_dir}{os.pathsep}{existing}"

# Change to project root so .env is found by pydantic-settings
os.chdir(project_root)

if __name__ == "__main__":
    import uvicorn
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    uvicorn.run("main:app", host="0.0.0.0", port=8000, workers=workers)
