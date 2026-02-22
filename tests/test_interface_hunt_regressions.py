"""
Test Interface Hunt Regressions — asserts no legacy method references
remain in production code. Catches regressions where someone re-introduces
old method names like generate_script, scorer.score, etc.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from pathlib import Path

# Directories to scan for legacy patterns
PROJECT_ROOT = Path(__file__).parent.parent
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"
SRC_ENGINES = PROJECT_ROOT / "src" / "engines"


def _scan_python_files(*dirs):
    """Collect all .py files from the given directories."""
    files = []
    for d in dirs:
        if d.exists():
            files.extend(d.rglob("*.py"))
    return files


class TestNoLegacyGenerateScript:

    def test_no_generate_script_singular_in_backend(self):
        """No production code should call .generate_script (singular).
        The canonical method is .generate_scripts (plural)."""
        for py_file in _scan_python_files(BACKEND_SRC):
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            # Match .generate_script( but NOT .generate_scripts(
            lines = source.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if ".generate_script(" in line and ".generate_scripts(" not in line:
                    assert False, (
                        f"Legacy .generate_script() found in {py_file}:{i}: {stripped}"
                    )

    def test_no_generate_script_singular_in_engines(self):
        """No engine code should reference generate_script (singular)."""
        for py_file in _scan_python_files(SRC_ENGINES):
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            lines = source.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if ".generate_script(" in line and ".generate_scripts(" not in line:
                    assert False, (
                        f"Legacy .generate_script() found in {py_file}:{i}: {stripped}"
                    )


class TestNoLegacyScorerScore:

    def test_no_scorer_score_in_backend(self):
        """No production code should call scorer.score().
        The canonical method is scorer.evaluate()."""
        for py_file in _scan_python_files(BACKEND_SRC):
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            lines = source.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "scorer.score(" in line:
                    assert False, (
                        f"Legacy scorer.score() found in {py_file}:{i}: {stripped}"
                    )

    def test_no_scorer_score_in_engines(self):
        """No engine code should define or call .score() on Scorer."""
        for py_file in _scan_python_files(SRC_ENGINES):
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            lines = source.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("\"\"\""):
                    continue
                # Check for def score( in Scorer class files
                if "def score(" in line and "scorer" in str(py_file).lower():
                    assert False, (
                        f"Legacy def score() found in {py_file}:{i}: {stripped}"
                    )


class TestNoLegacyScriptsVariants:

    def test_no_scripts_variants_in_backend(self):
        """scripts.variants doesn't exist — generate_scripts() returns List[AdScript]."""
        for py_file in _scan_python_files(BACKEND_SRC):
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            lines = source.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "scripts.variants" in line:
                    assert False, (
                        f"Legacy scripts.variants found in {py_file}:{i}: {stripped}. "
                        f"generate_scripts() returns List[AdScript], not an object with .variants"
                    )


class TestTaskRunnerDispatchConsistency:

    def test_all_job_types_have_handlers(self):
        """Every job type in QUEUE_ROUTING should have a handler in _dispatch."""
        from backend.src.jobs.queue import QUEUE_ROUTING
        task_runner_path = BACKEND_SRC / "jobs" / "task_runner.py"
        source = task_runner_path.read_text(encoding="utf-8")

        for job_type in QUEUE_ROUTING:
            assert f'"{job_type}"' in source, (
                f"Job type '{job_type}' is in QUEUE_ROUTING but has no handler in task_runner._dispatch"
            )
