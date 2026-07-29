#!/usr/bin/env python3
"""Compatibility entry point for feature generation.

Prefer running from the project root:

    python backend/scripts/generate_features.py --symbol RELIANCE
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

BACKEND_SCRIPT = Path(__file__).resolve().parent.parent / "backend" / "scripts" / "generate_features.py"

if __name__ == "__main__":
    if not BACKEND_SCRIPT.exists():
        print(f"Feature generation script not found: {BACKEND_SCRIPT}", file=sys.stderr)
        raise SystemExit(1)
    runpy.run_path(str(BACKEND_SCRIPT), run_name="__main__")
