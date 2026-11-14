"""Each extract / action-pack module imports cleanly on its own (no circular imports).

Every import runs in a fresh interpreter: in-process tests always import
``src.evaluation.action_packs`` first, which hides import-order cycles.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

MODULES = (
    "src.evaluation.extract.evidence",
    "src.evaluation.extract.graph",
    "src.evaluation.action_packs",
    "src.evaluation.extract.providers",
)


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_in_fresh_interpreter(module):
    out = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
