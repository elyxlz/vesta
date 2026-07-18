"""A LEGACY pre-flat agent $HOME could be a git checkout that tracks dev tooling under .claude/ --
the same directory holding the agent's runtime .credentials.json. Left tracked, a later git op
(a sparse-checkout reapply on old boxes) could delete the untracked credentials alongside it. The
container entrypoint self-heals at boot on every box by dropping .claude from the index and
excluding it locally, so no later op can touch it. These tests pin that mechanism (the same git
commands the entrypoint runs) on a plain flat checkout."""

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _agent_workspace(tmp_path: Path) -> Path:
    """A plain flat checkout mirroring a real agent home, in the shape the guard must heal: the
    repo tracks dev tooling under .claude/, and the agent's live .credentials.json sits untracked
    alongside it."""
    repo = tmp_path / "home"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "agent@vesta")
    _git(repo, "config", "user.name", "agent")
    (repo / ".gitignore").write_text(".claude/*\n!.claude/skills/\n")
    (repo / "agent").mkdir()
    (repo / "agent" / "file.txt").write_text("agent payload\n")
    skill = repo / ".claude" / "skills" / "babysit-prs"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("dev skill\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _exclude_claude(repo: Path) -> None:
    """The boot-time self-heal from agent_container_entrypoint_cmd: untrack .claude + exclude it."""
    tracked = _git(repo, "ls-files", "--", ".claude").split()
    if tracked:
        _git(repo, "update-index", "--force-remove", *tracked)
    exclude = repo / ".git" / "info" / "exclude"
    if "/.claude/" not in exclude.read_text():
        with exclude.open("a") as handle:
            handle.write("/.claude/\n")


def _write_credentials(repo: Path) -> Path:
    creds = repo / ".claude" / ".credentials.json"
    creds.parent.mkdir(parents=True, exist_ok=True)
    creds.write_text('{"claudeAiOauth":{"accessToken":"x","refreshToken":"y","expiresAt":9999999999999}}')
    return creds


def test_boot_self_heal_untracks_and_excludes_claude(tmp_path: Path) -> None:
    """The contract: after the self-heal, git tracks nothing under .claude/ and excludes it --
    so no later git op can sparsify or delete it."""
    repo = _agent_workspace(tmp_path)
    assert ".claude/skills/babysit-prs/SKILL.md" in _git(repo, "ls-files", "--", ".claude")
    _exclude_claude(repo)
    assert _git(repo, "ls-files", "--", ".claude").strip() == ""
    assert "/.claude/" in (repo / ".git" / "info" / "exclude").read_text()


def test_self_heal_preserves_untracked_credentials(tmp_path: Path) -> None:
    repo = _agent_workspace(tmp_path)
    creds = _write_credentials(repo)
    _exclude_claude(repo)
    assert creds.exists()
    assert creds.read_text().startswith('{"claudeAiOauth"')


def test_self_heal_is_idempotent(tmp_path: Path) -> None:
    repo = _agent_workspace(tmp_path)
    _exclude_claude(repo)
    _exclude_claude(repo)
    assert (repo / ".git" / "info" / "exclude").read_text().count("/.claude/") == 1
