import sys
import os

# Ensure the project root (parent of api/) is on sys.path so that
# web_app.py, fhir/, agents/, and utils/ are all importable.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from web_app import app  # noqa: E402  (import after sys.path setup is intentional)
