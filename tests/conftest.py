"""Shared pytest configuration for The Catalyst."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Force an isolated in-memory database BEFORE any backend module is imported.
# This must run at collection time so no test (regardless of import order) can
# ever bind to the real data/catalyst.db and clobber production data.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Ensure project root is on sys.path when running tests directly.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
