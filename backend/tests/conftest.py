"""Make the backend package importable no matter the pytest working directory."""

import sys
from pathlib import Path

# Insert backend/ (parent of tests/) so `import app...` resolves when pytest is invoked
# from the repo root as `python -m pytest backend/tests`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
