"""Title policy: the repo taxonomy is type(scope): description."""

import re

TYPES = ("feat", "fix", "refactor", "perf", "docs", "test", "ci", "chore", "style", "build")
LENGTH_WARN = 72
_TITLE_RE = re.compile(r"^(?P<type>\w+)(\((?P<scope>[^)]*)\))?: (?P<desc>.*)$")
_SCOPE_RE = re.compile(r"^[a-z0-9/._-]+$")
FORMAT_HELP = (
    "titles are `type(scope): description`, e.g. `fix(skills/restart): retry a failed daemon start`; "
    f"type one of {', '.join(TYPES)}; scope lowercase letters, digits, or / . _ -; "
    "description starts lowercase, no trailing period"
)


def title_errors(title: str) -> list[str]:
    """Every broken rule, so a title breaking two is refused once rather than twice."""
    match = _TITLE_RE.match(title)
    if match is None:
        return [f"missing `type(scope): ` prefix. {FORMAT_HELP}"]
    if match["scope"] is None:
        return [f"missing (scope). {FORMAT_HELP}"]
    errors = []
    if match["type"] not in TYPES:
        errors.append(f"unknown type `{match['type']}`. {FORMAT_HELP}")
    if not _SCOPE_RE.match(match["scope"]):
        errors.append(f"scope must be lowercase. {FORMAT_HELP}")
    if not match["desc"][:1].islower():
        errors.append(f"description must start lowercase. {FORMAT_HELP}")
    if title.endswith("."):
        errors.append(f"no trailing period. {FORMAT_HELP}")
    return errors


def title_warnings(title: str) -> list[str]:
    if len(title) > LENGTH_WARN:
        return [f"title is {len(title)} chars; aim for {LENGTH_WARN} or fewer"]
    return []
