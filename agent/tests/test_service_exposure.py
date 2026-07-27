"""Pins which services reach the tunnel without a credential.

vestad is the single gate in front of a private service, so a service registered public is
gated by nothing and must carry nothing sensitive. Exposure is asked for by two routes, and
both are scanned here: a daemon declares `--port-mode` to the shared runner, and a skill that
registers a port of its own passes `--public` (or posts `"public": true`) directly. Adding a
public service by either route fails these tests until it is named, which is what stops a
sensitive surface from reaching the tunnel ungated.
"""

import pathlib as pl
import re

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "agent/skills"
# The helper and the runner carry the flag as their own interface, not as a request for it.
EXPOSURE_OWNERS = {SKILLS_DIR / "vestad/scripts/register-service", SKILLS_DIR / "vestad/scripts/daemon-lifecycle"}

# Public means a page that must load with no credential at all: an inbound webhook from a sender
# that can hold no key, and a shareable file link. Everything else is private, and a consumer
# holding no app credential reaches it with a minted service key.
EXPECTED_PORT_MODE = {
    "agentmail": "public",
}

# A skill that registers its own port rather than declaring one to the runner. Keyed by file
# because a service name is often built at runtime, from an instance or a constant.
EXPECTED_DIRECT_PUBLIC = {
    "browser/cli/src/vesta_browser/handover.py",  # the handover page opens with no credential
    "file-host/file-host",  # the share link is fetched from outside the tunnel
    "whatsapp/cli/link.go",  # the QR link page a stranger's phone opens
}

DIRECT_PUBLIC = re.compile(r'--public|"public"\s*:\s*true')


def _declaring_files():
    for path in sorted(SKILLS_DIR.rglob("*")):
        if not path.is_file() or path.suffix == ".md" or path in EXPOSURE_OWNERS:
            continue
        if "/tests/" in str(path) or "/.venv/" in str(path):
            continue
        try:
            yield path, path.read_text()
        except (UnicodeDecodeError, OSError):
            continue


def _declared_port_modes() -> dict[str, str]:
    """Maps service name to the port mode its daemon declares to the shared runner."""
    modes = {}
    for path, text in _declaring_files():
        # Both a shell wrapper and a CLI argument list spell the flag and its value as adjacent
        # tokens, so quoting and commas are the only difference between them.
        tokens = re.sub(r"[\"',\\]", " ", text).split()
        if tokens.count("--port-mode") == 0:
            continue
        assert tokens.count("--port-mode") == 1, f"{path} declares more than one daemon, so its service pairing is ambiguous"
        modes[tokens[tokens.index("--service") + 1]] = tokens[tokens.index("--port-mode") + 1]
    return modes


def _direct_public_files() -> set[str]:
    """Files asking vestad for a public port without going through the runner."""
    return {str(path.relative_to(SKILLS_DIR)) for path, text in _declaring_files() if DIRECT_PUBLIC.search(text)}


def test_every_daemon_declares_the_exposure_it_is_allowed():
    assert _declared_port_modes() == EXPECTED_PORT_MODE


def test_only_named_skills_register_a_public_port_themselves():
    assert _direct_public_files() == EXPECTED_DIRECT_PUBLIC


def test_the_signature_pad_is_never_public():
    """The pad takes a signature the agent stamps onto a document and verifies nothing itself."""
    assert "sign-service/sign-service" not in _direct_public_files()


def test_the_shared_finance_api_is_never_public():
    """moneypot serves the user's shared expenses and holds no credential of its own."""
    assert "moneypot/moneypot" not in _direct_public_files()
