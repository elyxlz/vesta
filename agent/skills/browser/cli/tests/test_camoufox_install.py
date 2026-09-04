import hashlib
import io
import json
import pathlib as pl
import subprocess
import sys
import zipfile

import pytest
from vesta_browser import camoufox_install as ci
from vesta_browser import runtime_paths

SCRIPT = pl.Path(ci.__file__)


def _zip_bytes(with_exec_bit: bool) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("camoufox")
        info.external_attr = (0o755 if with_exec_bit else 0o644) << 16
        z.writestr(info, "#!/bin/sh\n")
        z.writestr("properties.json", "{}")
    return buf.getvalue()


def test_tags_agree_between_installer_and_runtime_paths():
    assert ci.CAMOUFOX_RELEASE_TAG == runtime_paths.CAMOUFOX_RELEASE_TAG


def test_install_is_a_no_op_when_the_tag_is_present(tmp_path):
    home = tmp_path / ci.CAMOUFOX_RELEASE_TAG
    home.mkdir()
    (home / "camoufox").write_text("")
    assert ci.install(root=tmp_path, arch="x86_64", download=lambda url, dest: pytest.fail("downloaded")) == home / "camoufox"


def test_install_downloads_verifies_extracts_and_publishes(tmp_path, monkeypatch):
    payload = _zip_bytes(with_exec_bit=True)
    monkeypatch.setitem(ci.CAMOUFOX_ASSETS, "x86_64", ("asset.zip", hashlib.sha256(payload).hexdigest()))
    urls = []

    def fake_download(url, dest):
        urls.append(url)
        pl.Path(dest).write_bytes(payload)

    exe = ci.install(root=tmp_path, arch="x86_64", download=fake_download)
    assert exe == tmp_path / ci.CAMOUFOX_RELEASE_TAG / "camoufox" and exe.stat().st_mode & 0o111
    assert urls == [f"{ci.RELEASE_DOWNLOAD_URL}/{ci.CAMOUFOX_RELEASE_TAG}/asset.zip"]
    assert not list(tmp_path.glob(".*"))  # no .part or .staging left behind


def test_sha_mismatch_refuses_and_leaves_no_install(tmp_path, monkeypatch):
    payload = _zip_bytes(with_exec_bit=True)
    monkeypatch.setitem(ci.CAMOUFOX_ASSETS, "x86_64", ("asset.zip", "0" * 64))
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        ci.install(root=tmp_path, arch="x86_64", download=lambda url, dest: pl.Path(dest).write_bytes(payload))
    assert not (tmp_path / ci.CAMOUFOX_RELEASE_TAG).exists()


def test_unsupported_arch_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match="unsupported architecture"):
        ci.install(root=tmp_path, arch="mips")


def test_repair_search_stub_is_idempotent(tmp_path):
    omni = tmp_path / "omni.ja"
    with zipfile.ZipFile(omni, "w") as z:
        z.writestr(ci._OMNI_SEARCH_SELECTOR, "prefix " + ci._BROKEN_SEARCH_STUB + " suffix")
    ci.repair_search_stub(tmp_path)
    ci.repair_search_stub(tmp_path)
    with zipfile.ZipFile(omni) as z:
        assert z.read(ci._OMNI_SEARCH_SELECTOR).decode() == "prefix " + ci._REPAIRED_SEARCH_STUB + " suffix"


def test_script_runs_standalone_under_the_system_python(tmp_path):
    """install-engines.sh runs this file by path with /usr/bin/python3, so it must not import the package."""
    home = tmp_path / ci.CAMOUFOX_RELEASE_TAG
    home.mkdir()
    (home / "camoufox").write_text("")
    result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0 and json.loads(result.stdout) == {"installed": str(home / "camoufox")}
