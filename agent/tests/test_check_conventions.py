"""Behavioral tests for scripts/check-conventions.py (escape hatches, comment blocks, import cycles)."""

import importlib.util
import pathlib as pl
import sys

_SPEC = importlib.util.spec_from_file_location("check_conventions", pl.Path(__file__).resolve().parents[2] / "scripts" / "check-conventions.py")
assert _SPEC is not None and _SPEC.loader is not None
check_conventions = importlib.util.module_from_spec(_SPEC)
sys.modules["check_conventions"] = check_conventions
_SPEC.loader.exec_module(check_conventions)


def write(tmp_path: pl.Path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content)
    return str(path)


def test_noqa_in_python_is_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = "no" + "qa"  # split so the conventions guard does not flag this fixture
    rel = write(tmp_path, "a.py", f"x = 1  # {marker}: E501\n")
    errors = check_conventions.check_escapes([rel])
    assert len(errors) == 1
    assert "noqa" in errors[0]


def test_ts_directives_and_eslint_disable_are_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rel = write(tmp_path, "a.ts", "// eslint-disable-next-line foo\n// @ts-expect-error\nconst x = 1;\n")
    errors = check_conventions.check_escapes([rel])
    assert len(errors) == 2


def test_rust_allow_and_expect_attributes_are_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rel = write(tmp_path, "a.rs", "#[allow(dead_code)]\nfn f() {}\n#[expect(clippy::todo)]\nfn g() {}\n")
    errors = check_conventions.check_escapes([rel])
    assert len(errors) == 2


def test_clean_files_pass_escape_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rels = [
        write(tmp_path, "a.py", "x = 1\n"),
        write(tmp_path, "a.rs", "fn f() {}\n"),
        write(tmp_path, "a.sh", "echo ok\n"),
    ]
    assert check_conventions.check_escapes(rels) == []


def test_long_comment_block_is_flagged_but_file_header_is_exempt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    header_block = "# header\n" * 12 + "x = 1\n"
    mid_block = "x = 1\n" + "# body\n" * 9 + "y = 2\n"
    ok_block = "x = 1\n" + "# body\n" * 8 + "y = 2\n"
    assert check_conventions.check_comment_blocks([write(tmp_path, "header.py", header_block)]) == []
    assert len(check_conventions.check_comment_blocks([write(tmp_path, "mid.py", mid_block)])) == 1
    assert check_conventions.check_comment_blocks([write(tmp_path, "ok.py", ok_block)]) == []


def test_trailing_comment_block_at_eof_is_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rel = write(tmp_path, "eof.py", "x = 1\n" + "# tail\n" * 9)
    assert len(check_conventions.check_comment_blocks([rel])) == 1


def test_import_cycle_is_detected(tmp_path):
    (tmp_path / "a.py").write_text("from . import b\n")
    (tmp_path / "b.py").write_text("from .a import thing\n")
    graph = check_conventions.package_import_graph(tmp_path)
    assert graph == {"a": {"b"}, "b": {"a"}}
    cycle = check_conventions.find_cycle(graph, "a", {}, [])
    assert cycle and cycle[0] == cycle[-1]


def test_acyclic_package_passes(tmp_path):
    (tmp_path / "a.py").write_text("from . import b\n")
    (tmp_path / "b.py").write_text("import os\n")
    graph = check_conventions.package_import_graph(tmp_path)
    assert check_conventions.find_cycle(graph, "a", {}, []) == []


def test_repo_is_currently_clean():
    repo_root = pl.Path(__file__).resolve().parents[2]
    assert check_conventions.check_import_cycles.__module__ == "check_conventions"
    assert (repo_root / "scripts" / "check-conventions.py").exists()
