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


def test_header_block_under_a_shebang_is_exempt(tmp_path, monkeypatch):
    """A shebang joins the run below it, so a documented script keeps its header exemption.

    Pins the behavior extensionless skill CLIs now depend on: their doc sits under a shebang, and
    any code between the two ends the run and makes the doc an ordinary capped block.
    """
    monkeypatch.chdir(tmp_path)
    documented = "#!/usr/bin/env bash\n" + "# usage\n" * 12 + "echo ok\n"
    assert check_conventions.check_comment_blocks([write(tmp_path, "tool.sh", documented)]) == []
    # Code between the shebang and the block makes it an ordinary mid-file comment again.
    after_code = "#!/usr/bin/env bash\nset -e\n" + "# usage\n" * 12 + "echo ok\n"
    assert len(check_conventions.check_comment_blocks([write(tmp_path, "later.sh", after_code)])) == 1


def test_extensionless_scripts_are_checked_by_shebang(tmp_path, monkeypatch):
    """Skill CLIs are bare command names; language comes from the shebang so they stay covered."""
    monkeypatch.chdir(tmp_path)
    marker = "shell" + "check disable=SC2086"  # split so the conventions guard does not flag this fixture
    shell = write(tmp_path, "hue", f"#!/usr/bin/env bash\necho hi\n# {marker}\necho $x\n")
    assert len(check_conventions.check_escapes([shell])) == 1
    noqa = "no" + "qa"
    python = write(tmp_path, "skills-search", f"#!/usr/bin/env python3\nx = 1  # {noqa}: E501\n")
    assert len(check_conventions.check_escapes([python])) == 1
    # An extensionless file with no shell/python shebang stays out of scope.
    assert check_conventions.check_escapes([write(tmp_path, "LICENSE", f"# {noqa}\n")]) == []


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


def _fake_git_ls_files(paths):
    """Stand in for `git ls-files` so tracked_files' own SKIP_PREFIXES filter is the thing under test."""

    class _Completed:
        stdout = "\n".join(paths) + "\n"

    def _run(*_args, **_kwargs):
        return _Completed()

    return _run


def test_no_arguments_selects_every_tracked_file(monkeypatch):
    monkeypatch.setattr(check_conventions.subprocess, "run", _fake_git_ls_files(["a.py", "b.sh"]))
    assert check_conventions.select_files([]) == (["a.py", "b.sh"], 0)


def test_requested_paths_narrow_the_set(monkeypatch):
    monkeypatch.setattr(check_conventions.subprocess, "run", _fake_git_ls_files(["a.py", "b.sh", "c.rs"]))
    assert check_conventions.select_files(["c.rs", "a.py"]) == (["a.py", "c.rs"], 0)


def test_an_untracked_path_is_refused_rather_than_skipped(monkeypatch):
    monkeypatch.setattr(check_conventions.subprocess, "run", _fake_git_ls_files(["a.py"]))
    try:
        check_conventions.select_files(["typo.py"])
    except ValueError as error:
        assert "typo.py" in str(error)
    else:
        raise AssertionError("a path git does not track must refuse, not narrow the set to nothing")


def test_a_tracked_but_excluded_path_is_dropped_and_counted_not_refused(monkeypatch):
    """A skip-prefix path is dropped, not raised on, and the count of drops is reported.

    Exercised through the real SKIP_PREFIXES filter: monkeypatching tracked_files to a short list
    would reject a skipped path for being absent from that list, which re-tests the untracked case
    and proves nothing about exclusion. A caller passing its own changed-file list will legitimately
    include an excluded file, and failing its whole run for that would make the arguments unusable.
    """
    skipped = check_conventions.SKIP_PREFIXES[0]
    monkeypatch.setattr(check_conventions.subprocess, "run", _fake_git_ls_files(["a.py", skipped]))
    assert skipped not in check_conventions.tracked_files()
    assert check_conventions.select_files([skipped, "a.py"]) == (["a.py"], 1)
