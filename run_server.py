"""Wrapper to properly set up paths and start the API server."""
import sys
import os
from pathlib import Path

# Set up paths
project_root = Path(__file__).parent.absolute()
backend_path = project_root / "backend"

# Insert at beginning of sys.path - project_root MUST come first!
sys.path.insert(0, str(backend_path))
sys.path.insert(0, str(project_root))

# Set PYTHONPATH for child processes
os.environ["PYTHONPATH"] = f"{project_root}{os.pathsep}{backend_path}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"

# Debug: print paths
print(f"Project root: {project_root}")
print(f"Backend path: {backend_path}")
print(f"sys.path[0:3]: {sys.path[0:3]}")

# Now import and run the server
from simple_api import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
