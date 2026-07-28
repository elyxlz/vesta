import pathlib
import sys

# daemon_lifecycle.py has no dependency on imap_tools/msal, so it can be
# imported directly for pure-logic tests without the skill's on-box venv.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
