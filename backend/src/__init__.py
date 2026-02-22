"""Backend package."""
import sys
from pathlib import Path

# Add project root to path so we can import src.core, src.schemas, etc.
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
