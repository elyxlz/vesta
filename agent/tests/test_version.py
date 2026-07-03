"""Startup version reporting."""

import core.main as main
import core.models as vm


def _config(tmp_path) -> vm.VestaConfig:
    (tmp_path / "core").mkdir(exist_ok=True)
    return vm.VestaConfig(agent_dir=tmp_path)


def test_reads_version_from_pyproject(tmp_path):
    config = _config(tmp_path)
    (tmp_path / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')
    assert main._vesta_version(config=config) == "9.9.9"


def test_missing_pyproject_returns_unknown(tmp_path):
    assert main._vesta_version(config=_config(tmp_path)) == "unknown"


def test_malformed_pyproject_returns_unknown(tmp_path):
    config = _config(tmp_path)
    (tmp_path / "core" / "pyproject.toml").write_text("not = valid = toml ==")
    assert main._vesta_version(config=config) == "unknown"
