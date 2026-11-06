"""Põe `src/` no sys.path para os scripts rodarem direto: python scripts/<nome>.py"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
