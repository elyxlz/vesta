"""Pins which services reach the tunnel without a credential.

vestad is the single gate in front of a private service, so a service registered public is
gated by nothing and must carry nothing sensitive. A skill asks for a port by calling
`register-service`, passing `--public` (or posting `"public": true`) for an ungated one.
Adding a public service fails these tests until it is named, which is what stops a sensitive
surface from reaching the tunnel ungated.
"""

import pathlib as pl
import re

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "agent/skills"
# The helper carries the flag as its own interface, not as a request for it.
EXPOSURE_OWNERS = {SKILLS_DIR / "vestad/scripts/register-service"}

# A skill registers its own port. Keyed by file because a service name is often built at
# runtime, from an instance or a constant. Public means a page that must load with no credential
# at all: an inbound webhook from a sender that can hold no key, and a shareable file link.
# Everything else is private, and a consumer holding no app credential reaches it with a minted
# service key.
EXPECTED_DIRECT_PUBLIC = {
    "agentmail/cli/src/agentmail_bridge/daemon.py",  # the webhook an external mail sender posts to
    "browser/cli/src/vesta_browser/handover.py",  # the handover page opens with no credential
    "file-host/file-host",  # the share link is fetched from outside the tunnel
    "whatsapp/cli/link.go",  # the QR link page a stranger's phone opens
}

DIRECT_PUBLIC = re.compile(r'--public|"public"\s*:\s*true')


def _declaring_files(*, include_prose: bool = False):
    for path in sorted(SKILLS_DIR.rglob("*")):
        if not path.is_file() or path in EXPOSURE_OWNERS:
            continue
        if path.suffix == ".md" and not include_prose:
            continue
        if "/tests/" in str(path) or "/.venv/" in str(path):
            continue
        try:
            yield path, path.read_text()
        except (UnicodeDecodeError, OSError):
            continue


def _direct_public_files() -> set[str]:
    """Files asking vestad for a public port."""
    return {str(path.relative_to(SKILLS_DIR)) for path, text in _declaring_files() if DIRECT_PUBLIC.search(text)}


def test_no_skill_declares_a_port_mode():
    """`--port-mode` is not part of any interface here: a skill names its exposure to `register-service`.

    Prose is checked too, because a skill's own docs are where a flag nothing accepts regrows: the
    agent writes the next daemon from what the skills teach it.
    """
    declared = [str(path.relative_to(SKILLS_DIR)) for path, text in _declaring_files(include_prose=True) if "--port-mode" in text]
    assert declared == []


def test_only_named_skills_register_a_public_port_themselves():
    assert _direct_public_files() == EXPECTED_DIRECT_PUBLIC


def test_the_signature_pad_is_never_public():
    """The pad takes a signature the agent stamps onto a document and verifies nothing itself."""
    assert "sign-service/sign-service" not in _direct_public_files()


def test_the_shared_finance_api_is_never_public():
    """moneypot serves the user's shared expenses and holds no credential of its own."""
    assert "moneypot/moneypot" not in _direct_public_files()
