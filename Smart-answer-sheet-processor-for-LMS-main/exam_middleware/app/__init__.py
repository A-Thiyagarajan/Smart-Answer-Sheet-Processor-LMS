"""
Examination Middleware Application Package
"""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from .main import app

__version__ = "1.0.0"
__all__ = ["app"]
