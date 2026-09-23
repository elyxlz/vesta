"""The Claude Code CLI pin: one file under core, applied by one script the image build and every
boot both run, so a bumped pin reaches an existing agent on its next restart."""

import pathlib as pl
import stat
import subprocess

import pytest

from core.claude_runtime import ensure_claude_code_version

CORE_DIR = pl.Path(__file__).resolve().parents[1] / "core"
SCRIPT = CORE_DIR / "claude-code-install.sh"
PIN = (CORE_DIR / "claude-code-version").read_text().strip()


def _executable(path: pl.Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_claude(bin_dir: pl.Path, version: str) -> None:
    _executable(bin_dir / "claude", f'#!/bin/sh\necho "{version} (Claude Code)"\n')


def _fake_installer(bin_dir: pl.Path, *, installs_version: str | None = None) -> pl.Path:
    """A `curl` that hands back an installer script writing a fake `claude` into the same bin
    dir, reporting the version the installer was asked for (or a fixed wrong one)."""
    called = bin_dir / "curl-called"
    reported = '"$1"' if installs_version is None else f'"{installs_version}"'
    installer = bin_dir / "installer.sh"
    write_claude = f"printf '#!/bin/sh\\necho \"%s (Claude Code)\"\\n' {reported} > {bin_dir}/claude"
    installer.write_text(f"#!/bin/sh\n{write_claude}\nchmod +x {bin_dir}/claude\n")
    _executable(bin_dir / "curl", f"#!/bin/sh\ntouch {called}\ncat {installer}\n")
    return called


def _run(bin_dir: pl.Path) -> subprocess.CompletedProcess[str]:
    """PATH holds only the fakes plus the system dirs, so the host's own `claude` and `curl` never answer."""
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(bin_dir)}
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False)


def _claude_version(bin_dir: pl.Path) -> str:
    return subprocess.run([str(bin_dir / "claude"), "--version"], capture_output=True, text=True, check=True).stdout.strip()


def test_pin_is_a_bare_version():
    assert PIN.count(".") == 2
    assert PIN.replace(".", "").isdigit()


def test_script_is_a_noop_when_the_pinned_version_is_already_on_path(tmp_path):
    _fake_claude(tmp_path, PIN)
    called = _fake_installer(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert not called.exists()


def test_script_installs_the_pinned_version_when_the_cli_is_missing(tmp_path):
    called = _fake_installer(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert called.exists()
    assert _claude_version(tmp_path) == f"{PIN} (Claude Code)"


def test_script_replaces_a_cli_of_another_version(tmp_path):
    _fake_claude(tmp_path, "2.1.200")
    _fake_installer(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert _claude_version(tmp_path) == f"{PIN} (Claude Code)"


def test_script_fails_when_the_installer_leaves_a_different_version(tmp_path):
    _fake_installer(tmp_path, installs_version="9.9.9")

    result = _run(tmp_path)

    assert result.returncode != 0


@pytest.mark.anyio
async def test_boot_converge_reports_success_when_the_script_exits_zero(tmp_path):
    _executable(tmp_path / "claude-code-install.sh", "#!/bin/sh\nexit 0\n")

    assert await ensure_claude_code_version(tmp_path) is True


@pytest.mark.anyio
async def test_boot_converge_tolerates_a_failing_script(tmp_path):
    _executable(tmp_path / "claude-code-install.sh", "#!/bin/sh\necho no network >&2\nexit 1\n")

    assert await ensure_claude_code_version(tmp_path) is False


@pytest.mark.anyio
async def test_boot_converge_gives_up_on_a_hung_installer(tmp_path):
    _executable(tmp_path / "claude-code-install.sh", "#!/bin/sh\nsleep 30\n")

    assert await ensure_claude_code_version(tmp_path, timeout_secs=0.2) is False
