"""Repo convention guards: no lint/type-checker escape hatches, no unmarked removal notes, no
oversized comment blocks, no import cycles, single-line JSON envelopes from skill commands, no
narration of a previous design in agent/ prose, and the web app's brand copy and folder rules.
Run from the repo root: uv run python scripts/check-conventions.py"""

import ast
import io
import pathlib as pl
import re
import subprocess
import sys
import tokenize

MAX_COMMENT_BLOCK = 8

# This file necessarily spells the banned markers; nothing under .claude is product code.
SKIP_PREFIXES = ("scripts/check-conventions.py", ".claude/")

CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".rs", ".go", ".sh")

ESCAPE_PATTERNS: list[tuple[str, re.Pattern[str], tuple[str, ...]]] = [
    ("noqa", re.compile(r"#\s*noqa"), (".py",)),
    ("type: ignore", re.compile(r"#\s*(type|ty):\s*ignore"), (".py",)),
    ("eslint-disable", re.compile(r"eslint-disable"), (".ts", ".tsx", ".js", ".mjs", ".cjs")),
    ("ts-comment directive", re.compile(r"@ts-(ignore|expect-error|nocheck)"), (".ts", ".tsx", ".js", ".mjs", ".cjs")),
    ("prettier-ignore", re.compile(r"prettier-ignore"), (".ts", ".tsx", ".js", ".mjs", ".cjs")),
    ("#[allow]/#[expect]", re.compile(r"#!?\[\s*(allow|expect)\("), (".rs",)),
    ("nolint", re.compile(r"//\s*nolint"), (".go",)),
    ("shellcheck disable", re.compile(r"#\s*shellcheck\s+disable"), (".sh",)),
    # Code slated for removal carries a LEGACY(remove-when: ...) marker and nothing else.
    ("unmarked removal note", re.compile(r"\b(TEMPORARY|TODO|FIXME|XXX)\b(?!.*LEGACY\(remove-when:)"), CODE_SUFFIXES),
]

# The client apps' source trees, minus tests: what the brand-copy scan reads.
APP_SOURCE_RE = re.compile(r"^apps/(core|web|desktop|mobile)/src/.*\.(ts|tsx)$")
WEB_SRC = pl.Path("apps/web/src")
# A spaced em or en dash separating prose; a lone "—" literal is an empty-value placeholder.
DASH_SEPARATOR_RE = re.compile("\\s[\\u2014\\u2013]\\s")
# "box" as a word, never as a CSS term (box-shadow, flexbox) or a substring.
BOX_WORD_RE = re.compile(r"(?<![-\w])box(?![-\w])", re.IGNORECASE)
IMPORT_RE = re.compile(r"""from\s+["']([^"']+)["']""")

# An extensionless tracked file is still Python or shell when its shebang says so. Several skill CLIs
# are bare command names (hue, daemon, skills-install) and must keep those names to stay invocable, so
# language is resolved from the shebang rather than by renaming them.
SHEBANG_SUFFIXES = ((re.compile(r"^#!.*\bpython[\d.]*\b"), ".py"), (re.compile(r"^#!.*\b(ba|da|k|z)?sh\b"), ".sh"))

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

# A skill command's code: its cli/src package and its scripts/ (Python by suffix or shebang).
SKILL_COMMAND_RE = re.compile(r"^agent/skills/[^/]+/(cli/src/.*\.py|scripts/[^/]+)$")
# The calls that reach a command's stdout/stderr; a json.dumps they print may indent only under a
# pretty opt-in, an `if` whose test names it (`if args.json_pretty:`, `if want_pretty:`).
STDOUT_WRITERS = ("print", "click.echo")
PRETTY_OPT_IN = "pretty"

# The agent reads everything under agent/ cold, so prose there states the mechanism and never what
# came before it. MEMORY.md is one box's dated history and a migration describes the state it converges.
AGENT_PROSE_RE = re.compile(r"^agent/(?!MEMORY\.md$|core/migrations/).*")
# A phrase that narrates the old design, or a new value set against the old one ("120, not 30");
# a dotted address pair ("0.0.0.0, not 127.0.0.1") is a contrast of two live choices.
NARRATION_RE = re.compile(
    r"\b(previously|formerly|used to (be|say|do|have)|before this (change|fix|PR))\b|(?<![\d.])\d+, not \d+(?!\.\d)", re.IGNORECASE
)


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if not line.startswith(SKIP_PREFIXES)]


def effective_suffix(path: pl.Path) -> str:
    """The suffix deciding a file's language, read from the shebang when the name carries none."""
    if path.suffix:
        return path.suffix
    with path.open(errors="replace") as handle:
        first_line = handle.readline()
    for pattern, suffix in SHEBANG_SUFFIXES:
        if pattern.search(first_line):
            return suffix
    return ""


def check_escapes(files: list[str]) -> list[str]:
    errors = []
    for rel in files:
        path = pl.Path(rel)
        if not path.exists():
            continue
        suffix = effective_suffix(path)
        patterns = [(name, rx) for name, rx, exts in ESCAPE_PATTERNS if suffix in exts]
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
        if not path.exists():
            continue
        suffix = effective_suffix(path)
        marker = COMMENT_MARKERS[suffix] if suffix in COMMENT_MARKERS else ""
        if not marker:
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
            return [*stack[stack.index(dep) :], dep]
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
                    # One report per package: a found cycle leaves traversal state dirty.
                    errors.append(f"{package}: import cycle: {' -> '.join(cycle)}")
                    break
    return errors


def indented_stdout_dumps(node: ast.AST, pretty: bool) -> list[int]:
    """Line numbers of `print(json.dumps(..., indent=<n>))` calls outside a pretty opt-in's `if` body."""
    if isinstance(node, ast.If):
        body_pretty = pretty or PRETTY_OPT_IN in ast.unparse(node.test)
        return [
            *(line for child in node.body for line in indented_stdout_dumps(child, body_pretty)),
            *(line for child in node.orelse for line in indented_stdout_dumps(child, pretty)),
        ]
    hits = []
    if not pretty and isinstance(node, ast.Call) and ast.unparse(node.func) in STDOUT_WRITERS:
        for arg in node.args:
            if isinstance(arg, ast.Call) and ast.unparse(arg.func) == "json.dumps":
                hits.extend(
                    node.lineno
                    for kw in arg.keywords
                    if kw.arg == "indent" and isinstance(kw.value, ast.Constant) and kw.value.value is not None
                )
    return [*hits, *(line for child in ast.iter_child_nodes(node) for line in indented_stdout_dumps(child, pretty))]


def check_skill_envelopes(files: list[str]) -> list[str]:
    """A skill command prints a JSON envelope as one line, so a truncated pipe still shows the verdict."""
    errors = []
    for rel in files:
        path = pl.Path(rel)
        if not SKILL_COMMAND_RE.match(rel) or not path.exists() or effective_suffix(path) != ".py":
            continue
        errors.extend(
            f"{rel}:{lineno}: indented JSON printed by a skill command; an envelope prints as one line unless a pretty flag asks"
            for lineno in indented_stdout_dumps(ast.parse(path.read_text(errors="replace")), False)
        )
    return errors


def python_prose_lines(text: str) -> list[tuple[int, str]]:
    """Each comment and docstring line of a Python source, the lines a reader takes as prose."""
    lines = text.splitlines()
    prose: dict[int, str] = {}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                prose.update((lineno, lines[lineno - 1]) for lineno in range(first.lineno, (first.end_lineno or first.lineno) + 1))
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            prose[token.start[0]] = token.string
    return sorted(prose.items())


def check_narration(files: list[str]) -> list[str]:
    """Prose under agent/ (Markdown, Python comments and docstrings) never describes a previous design."""
    errors = []
    for rel in files:
        path = pl.Path(rel)
        if not AGENT_PROSE_RE.match(rel) or not path.exists():
            continue
        suffix = effective_suffix(path)
        if suffix == ".md":
            prose = list(enumerate(path.read_text(errors="replace").splitlines(), 1))
        elif suffix == ".py":
            prose = python_prose_lines(path.read_text(errors="replace"))
        else:
            continue
        errors.extend(
            f"{rel}:{lineno}: narrates a previous design ({match.group(0)!r}); state the mechanism, the change goes in the commit"
            for lineno, line in prose
            if (match := NARRATION_RE.search(line))
        )
    return errors


def code_lines(path: pl.Path) -> list[tuple[int, str]]:
    """Each line with its comments removed: `//` and `/* */` blocks, including JSX comment bodies."""
    lines = []
    in_block = False
    for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        text = line
        if in_block:
            close = text.find("*/")
            if close == -1:
                continue
            text = text[close + 2 :]
            in_block = False
        while "/*" in text:
            open_at = text.index("/*")
            close = text.find("*/", open_at + 2)
            if close == -1:
                text = text[:open_at]
                in_block = True
                break
            text = text[:open_at] + text[close + 2 :]
        stripped = text.strip()
        if stripped.startswith(("//", "*")):
            continue
        lines.append((lineno, re.sub(r"//.*$", "", text)))
    return lines


def check_brand_copy(files: list[str]) -> list[str]:
    """App strings never separate prose with a dash and never call the product a box."""
    errors = []
    for rel in files:
        if not APP_SOURCE_RE.match(rel) or ".test." in rel:
            continue
        path = pl.Path(rel)
        if not path.exists():
            continue
        for lineno, text in code_lines(path):
            if DASH_SEPARATOR_RE.search(text):
                errors.append(f"{rel}:{lineno}: dash separator in app copy; use a period, comma, or colon")
            if rel.startswith("apps/web/src/") and BOX_WORD_RE.search(text):
                errors.append(f'{rel}:{lineno}: "box" in app copy; the product noun is "agent" (or "gateway")')
    return errors


def web_importers(files: list[str]) -> dict[str, set[str]]:
    """Non-test importer files of every module under apps/web/src, keyed by the imported module's path."""
    importers: dict[str, set[str]] = {}
    for rel in files:
        if not rel.startswith("apps/web/src/") or ".test." in rel or not rel.endswith((".ts", ".tsx")):
            continue
        source = pl.Path(rel)
        if not source.exists():
            continue
        for match in IMPORT_RE.finditer(source.read_text(errors="replace")):
            spec = match.group(1)
            if spec.startswith("@/"):
                target = WEB_SRC / spec[2:]
            elif spec.startswith("."):
                target = source.parent / spec
            else:
                continue
            importers.setdefault(pl.Path(*target.parts).as_posix(), set()).add(rel)
    return importers


def check_hook_placement(files: list[str]) -> list[str]:
    """`hooks/` holds only hooks with two or more importers; a one-consumer hook lives beside it."""
    errors = []
    importers = web_importers(files)
    for hook in sorted((WEB_SRC / "hooks").glob("use-*.ts*")):
        if ".test." in hook.name:
            continue
        module = hook.with_suffix("").as_posix()
        count = len(importers.get(module, set()))
        if count < 2:
            errors.append(f"{hook.as_posix()}: {count} importer(s); a hook with one consumer lives beside it")
    return errors


def check_component_folders(files: list[str]) -> list[str]:
    """A non-index .tsx inside a component folder is private to that folder."""
    errors = []
    components = WEB_SRC / "components"
    for module, sources in web_importers(files).items():
        target = pl.Path(module)
        if not target.with_suffix(".tsx").exists():
            continue
        try:
            inside = target.relative_to(components)
        except ValueError:
            continue
        if len(inside.parts) < 2 or inside.parts[0] == "ui" or inside.name == "index":
            continue
        folder = components / inside.parts[0]
        errors.extend(
            f"{source}: imports {module}.tsx from outside its folder; give it a folder of its own"
            for source in sorted(sources)
            if not pl.Path(source).is_relative_to(folder)
        )
    return errors


def main() -> int:
    files = tracked_files()
    errors = (
        check_escapes(files)
        + check_comment_blocks(files)
        + check_import_cycles()
        + check_skill_envelopes(files)
        + check_narration(files)
        + check_brand_copy(files)
        + check_hook_placement(files)
        + check_component_folders(files)
    )
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print(f"{len(errors)} convention violation(s)", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
