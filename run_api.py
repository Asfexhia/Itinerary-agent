"""
Start the HTTP API (POST /plan) on port 8000.
Run from project root:  python run_api.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure local src/ is on path when not installed as a package
_ROOT = Path(__file__).resolve().parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from itinerary_agent.api_server import main  # noqa: E402

if __name__ == "__main__":
    main()
