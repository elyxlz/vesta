"""Repo convention guards: no lint/type-checker escape hatches, no oversized comment
blocks, no import cycles. Run from the repo root: uv run python scripts/check-conventions.py"""

import ast
import pathlib as pl
import re
import subprocess
import sys

MAX_COMMENT_BLOCK = 8

# This file necessarily spells the banned markers; nothing under .claude is product code.
SKIP_PREFIXES = ("scripts/check-conventions.py", ".claude/")

ESCAPE_PATTERNS: list[tuple[str, re.Pattern[str], tuple[str, ...]]] = [
    ("noqa", re.compile(r"#\s*noqa"), (".py",)),
    ("type: ignore", re.compile(r"#\s*(type|ty):\s*ignore"), (".py",)),
    ("eslint-disable", re.compile(r"eslint-disable"), (".ts", ".tsx", ".js", ".mjs", ".cjs")),
    ("ts-comment directive", re.compile(r"@ts-(ignore|expect-error|nocheck)"), (".ts", ".tsx", ".js", ".mjs", ".cjs")),
    ("prettier-ignore", re.compile(r"prettier-ignore"), (".ts", ".tsx", ".js", ".mjs", ".cjs")),
    ("#[allow]/#[expect]", re.compile(r"#!?\[\s*(allow|expect)\("), (".rs",)),
    ("nolint", re.compile(r"//\s*nolint"), (".go",)),
    ("shellcheck disable", re.compile(r"#\s*shellcheck\s+disable"), (".sh",)),
]

COMMENT_MARKERS = {
    ".py": "#",
    ".sh": "#",
    ".rs": "//",
    ".go": "//",
    ".ts": "//",
    ".tsx": "//",
    ".js": "//",
    ".mjs": "//",
    ".cjs": "//",
}

# Packages whose intra-package import graph must stay a DAG (level-1 relative imports).
CYCLE_CHECKED_PACKAGES = ["agent/core", "agent/core/cc_sdk"]


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if not line.startswith(SKIP_PREFIXES)]


def check_escapes(files: list[str]) -> list[str]:
    errors = []
    for rel in files:
        path = pl.Path(rel)
        if not path.exists():
            continue
        patterns = [(name, rx) for name, rx, exts in ESCAPE_PATTERNS if path.suffix in exts]
        if not patterns:
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            for name, rx in patterns:
                if rx.search(line):
                    errors.append(f"{rel}:{lineno}: banned escape hatch ({name}): fix the finding or tune the rule in config")
    return errors


def file_comment_blocks(path: pl.Path, marker: str) -> list[tuple[int, int]]:
    blocks = []
    run_start = 0
    run_len = 0
    for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if line.strip().startswith(marker):
            if run_len == 0:
                run_start = lineno
            run_len += 1
        else:
            blocks.append((run_start, run_len))
            run_len = 0
    blocks.append((run_start, run_len))
    # A file-leading header block (shebang + module doc) is exempt.
    return [(start, length) for start, length in blocks if length > MAX_COMMENT_BLOCK and start > 1]


def check_comment_blocks(files: list[str]) -> list[str]:
    errors = []
    for rel in files:
        path = pl.Path(rel)
        marker = COMMENT_MARKERS.get(path.suffix, "")
        if not marker or not path.exists():
            continue
        for start, length in file_comment_blocks(path, marker):
            errors.append(f"{rel}:{start}: comment block of {length} lines (max {MAX_COMMENT_BLOCK}); simplify the code instead")
    return errors


def package_import_graph(package_dir: pl.Path) -> dict[str, set[str]]:
    modules = {path.stem for path in package_dir.glob("*.py")}
    graph: dict[str, set[str]] = {module: set() for module in modules}
    for path in package_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(errors="replace"))):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                targets = [node.module] if node.module else [alias.name for alias in node.names]
                graph[path.stem].update(target.split(".")[0] for target in targets if target.split(".")[0] in modules)
    return graph


def find_cycle(graph: dict[str, set[str]], module: str, state: dict[str, int], stack: list[str]) -> list[str]:
    state[module] = 1
    stack.append(module)
    for dep in sorted(graph[module]):
        if state.setdefault(dep, 0) == 1:
            return stack[stack.index(dep) :] + [dep]
        if state[dep] == 0:
            cycle = find_cycle(graph, dep, state, stack)
            if cycle:
                return cycle
    stack.pop()
    state[module] = 2
    return []


def check_import_cycles() -> list[str]:
    errors = []
    for package in CYCLE_CHECKED_PACKAGES:
        package_dir = pl.Path(package)
        if not package_dir.is_dir():
            continue
        graph = package_import_graph(package_dir)
        state: dict[str, int] = {}
        for module in sorted(graph):
            if state.setdefault(module, 0) == 0:
                cycle = find_cycle(graph, module, state, [])
                if cycle:
                    errors.append(f"{package}: import cycle: {' -> '.join(cycle)}")
    return errors


def main() -> int:
    files = tracked_files()
    errors = check_escapes(files) + check_comment_blocks(files) + check_import_cycles()
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print(f"{len(errors)} convention violation(s)", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
