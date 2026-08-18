"""Title policy: the repo taxonomy is type(scope): description."""

import re

TYPES = ("feat", "fix", "refactor", "perf", "docs", "test", "ci", "chore", "style", "build")
LENGTH_WARN = 72
_TITLE_RE = re.compile(r"^(?P<type>[a-z]+)\((?P<scope>[a-z0-9/._-]+)\): (?P<desc>[a-z].*)$")
FORMAT_HELP = (
    "titles are `type(scope): description`, e.g. `fix(skills/restart): retry a failed daemon start`; "
    f"type one of {', '.join(TYPES)}; scope lowercase; description starts lowercase, no trailing period"
)


def title_errors(title: str) -> list[str]:
    match = _TITLE_RE.match(title)
    if match is None:
        lowered = re.match(r"^(?P<type>\w+)(\((?P<scope>[^)]*)\))?: ", title)
        if lowered is None:
            return [f"missing `type(scope): ` prefix. {FORMAT_HELP}"]
        if lowered["scope"] is None:
            return [f"missing (scope). {FORMAT_HELP}"]
        if lowered["type"] not in TYPES or lowered["type"] != lowered["type"].lower():
            return [f"unknown or uppercased type `{lowered['type']}`. {FORMAT_HELP}"]
        if lowered["scope"] != lowered["scope"].lower():
            return [f"scope must be lowercase. {FORMAT_HELP}"]
        return [f"description must start lowercase. {FORMAT_HELP}"]
    errors = []
    if match["type"] not in TYPES:
        errors.append(f"unknown type `{match['type']}`. {FORMAT_HELP}")
    if title.endswith("."):
        errors.append(f"no trailing period. {FORMAT_HELP}")
    return errors


def title_warnings(title: str) -> list[str]:
    if len(title) > LENGTH_WARN:
        return [f"title is {len(title)} chars; aim for {LENGTH_WARN} or fewer"]
    return []
