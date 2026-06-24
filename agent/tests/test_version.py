"""Startup version reporting."""

import core.main as main
import core.models as vm


def test_reads_version_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')
    config = vm.VestaConfig(agent_dir=tmp_path)
    assert main._vesta_version(config=config) == "9.9.9"


def test_missing_pyproject_returns_unknown(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path)
    assert main._vesta_version(config=config) == "unknown"


def test_malformed_pyproject_returns_unknown(tmp_path):
    (tmp_path / "pyproject.toml").write_text("not = valid = toml ==")
    config = vm.VestaConfig(agent_dir=tmp_path)
    assert main._vesta_version(config=config) == "unknown"
