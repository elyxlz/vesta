"""Upstream tool: mints GitHub App auth and runs gh against the upstream vesta repo."""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import jwt

from upstream_cli.titles import title_errors, title_warnings

# Config: hardcoded for the vesta-upstream GitHub App
APP_ID = 2990557
INSTALLATION_ID = 113559773
UPSTREAM_REPO = "elyxlz/vesta"
GITHUB_API = "https://api.github.com"

# Key lives next to this script
SCRIPT_DIR = Path(__file__).resolve().parent
KEY_PATH = SCRIPT_DIR / "private-key.pem"


def load_private_key():
    if not KEY_PATH.is_file():
        print(f"Error: private key not found at {KEY_PATH}", file=sys.stderr)
        print("Generate one from https://github.com/settings/apps/vesta-upstream", file=sys.stderr)
        sys.exit(1)
    return KEY_PATH.read_text()


def generate_jwt():
    private_key = load_private_key()
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": str(APP_ID)}
    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token():
    token_jwt = generate_jwt()
    request = urllib.request.Request(
        f"{GITHUB_API}/app/installations/{INSTALLATION_ID}/access_tokens",
        method="POST",
        headers={
            "Authorization": f"Bearer {token_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return json.load(resp)["token"]
    except urllib.error.HTTPError as err:
        print(f"Error getting token: {err.code} {err.read().decode()}", file=sys.stderr)
        sys.exit(1)


def gh_env(token) -> dict[str, str]:
    return {**os.environ, "GH_TOKEN": token, "GH_REPO": UPSTREAM_REPO}


GH_MISSING = "Error: `gh` is not installed here, so this command cannot reach GitHub. Your environment provides it; report this to the user."


def _run_gh(token, args, *, capture):
    """Every gh spawn goes through here, so a missing binary fails once with a readable message."""
    try:
        return subprocess.run(["gh", *args], env=gh_env(token), capture_output=capture, text=capture, check=False)
    except FileNotFoundError:
        print(GH_MISSING, file=sys.stderr)
        sys.exit(1)


def gh_api(token, path, *, method="GET", fields=None) -> tuple[int, str]:
    """All REST traffic rides gh so auth handling has one owner. Returns (exit code, output).

    A failure with an empty stdout returns stderr instead: gh prints an API error body to stdout,
    but a transport or usage failure only reaches stderr, and callers print what they get."""
    cmd = ["api"]
    if method != "GET":
        cmd += ["-X", method]
    cmd.append(path)
    for key, value in (fields or {}).items():
        cmd += ["-f", f"{key}={value}"]
    result = _run_gh(token, cmd, capture=True)
    if result.returncode != 0 and not result.stdout.strip():
        return result.returncode, result.stderr
    return result.returncode, result.stdout


def run(cmd, env=None):
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if result.returncode != 0 and result.stderr:
        print(result.stderr, file=sys.stderr)
    return result


def git_auth_env(token):
    """Auth rides in this process's env only, never .git/config (which `git remote -v` and
    `git config --list` print) nor argv (which `ps` shows). Scoped to github.com so a
    cross-host redirect can't carry the header off."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        **os.environ,
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: Basic {basic}",
        "GIT_CONFIG_COUNT": "1",
    }


def resolve_agent_identity():
    """Agent name + vesta version for commit authorship and PR attribution."""
    if "AGENT_NAME" not in os.environ or not os.environ["AGENT_NAME"].strip():
        print("Error: AGENT_NAME is not set in env", file=sys.stderr)
        sys.exit(1)
    agent_name = os.environ["AGENT_NAME"]
    pyproject = Path("~/agent/core/pyproject.toml").expanduser()
    with pyproject.open() as fh:
        version_line = next((line for line in fh if line.startswith("version = ")), "")
    vesta_version = version_line.split('"')[1] if '"' in version_line else "unknown"
    return agent_name, vesta_version


def ensure_shared_history(base, env):
    """Guard: HEAD must share history with the base branch, else PR-create fails 422 with a
    cryptic "no history in common with master". This happens when upstream is run from
    the workspace branch (~), whose base is a standalone stock snapshot tag with no ancestry
    to real GitHub master, so pushing it force-pushes an unrelated root. Catch it here with
    an actionable message BEFORE we amend the commit author or push anything."""
    run(["git", "fetch", "--quiet", "upstream", base], env=env)
    merge_base = run(["git", "merge-base", "FETCH_HEAD", "HEAD"])
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        print(f"Error: HEAD shares no history with upstream/{base}.", file=sys.stderr)
        print("You are probably running from your workspace branch (~), whose base is a", file=sys.stderr)
        print("standalone stock snapshot tag unrelated to real master. Run upstream from", file=sys.stderr)
        print("your PR worktree (branch off FETCH_HEAD after fetching master), not from ~.", file=sys.stderr)
        sys.exit(1)


def commit_author_name(agent_name) -> str:
    """The one spelling of a commit author. It is written on the push and read back to decide both
    "is this PR mine" and "is this branch someone else's", so a second spelling would fail open."""
    return f"{agent_name} (vesta)"


def pr_commit_authors(token, number):
    """(originator, all authors) for one PR, by commit author name. Every agent pushes through the
    same GitHub App, so `pull.user.login` is `vesta-upstream[bot]` on EVERY PR in the repo and
    identifies nobody. The commit author is the only field carrying which agent wrote it, and the
    FIRST commit's author is the one who opened the PR."""
    code, out = gh_api(token, f"repos/{UPSTREAM_REPO}/pulls/{number}/commits?per_page=100")
    if code != 0:
        return None, set()
    commits = json.loads(out)
    if not commits:
        return None, set()
    return commits[0]["commit"]["author"]["name"], {c["commit"]["author"]["name"] for c in commits}


def list_my_prs(token, agent_name, state, limit):
    """Print the PRs this agent opened, and separately the ones it only pushed commits to."""
    me = commit_author_name(agent_name)
    query = f"state={quote(state)}&per_page={min(limit, 100)}&sort=created&direction=desc"
    code, out = gh_api(token, f"repos/{UPSTREAM_REPO}/pulls?{query}")
    if code != 0:
        print(f"Error: gh api failed: {out}", file=sys.stderr)
        sys.exit(1)
    candidates = json.loads(out)[:limit]
    opened, touched, unreadable = [], [], []
    for pr in candidates:
        originator, authors = pr_commit_authors(token, pr["number"])
        if originator == me:
            opened.append((pr, originator))
        elif me in authors:
            touched.append((pr, originator))
        elif originator is None:
            unreadable.append(pr)

    print(f"Checked the {len(candidates)} most recent {state} PR(s) as {me}.")
    print(f"\nOpened by you ({len(opened)}):")
    for pr, _ in opened:
        print(f"  #{pr['number']}  {pr['title'][:72]}\n      {pr['html_url']}")
    if not opened:
        print("  (none: every PR here was opened by a different agent through the same bot account)")
    if touched:
        print(f"\nNot yours, but you have commits on them ({len(touched)}):")
        for pr, originator in touched:
            print(f"  #{pr['number']}  opened by {originator}: {pr['title'][:56]}\n      {pr['html_url']}")
    if unreadable:
        print(f"\nCould not read commit authors for {len(unreadable)} PR(s), so ownership is unknown, not ruled out:")
        for pr in unreadable:
            print(f"  #{pr['number']}  {pr['title'][:72]}")


GUARD_BRANCH_REF = "refs/vesta-guard/branch"
GUARD_BASE_REF = "refs/vesta-guard/base"


def branch_authors_ahead_of_base(branch, base, env):
    """Commit-author names the remote branch adds on top of base, or None when the remote has no
    such branch: the one case with nothing to protect, so the one silent pass (a brand-new branch
    must never be blocked). Ownership is read with git, not the REST API, because a REST non-200
    (403, rate limit, auth blip) is indistinguishable from a nonexistent branch. `ls-remote
    --exit-code` separates the two answers: 2 means the remote says the branch does not exist, and
    any other failure here (unreachable remote, failed fetch or log) exits instead of guessing,
    because the caller is about to force push and an unverifiable branch must not read as a pass."""
    probe = run(["git", "ls-remote", "--exit-code", "upstream", f"refs/heads/{branch}"], env=env)
    if probe.returncode == 2:
        return None
    branch_spec = f"+refs/heads/{branch}:{GUARD_BRANCH_REF}"
    base_spec = f"+refs/heads/{base}:{GUARD_BASE_REF}"
    fetched = probe.returncode == 0 and run(["git", "fetch", "--quiet", "upstream", branch_spec, base_spec], env=env).returncode == 0
    log = run(["git", "log", "--format=%an", f"{GUARD_BASE_REF}..{GUARD_BRANCH_REF}"]) if fetched else None
    run(["git", "update-ref", "-d", GUARD_BRANCH_REF])
    run(["git", "update-ref", "-d", GUARD_BASE_REF])
    if log is None or log.returncode != 0:
        print(f"Error: could not read remote branch '{branch}' to check whose work it holds.", file=sys.stderr)
        print("Refusing to force push blind. Wait and retry, or pick a fresh branch name.", file=sys.stderr)
        print("Do not use --adopt here: ownership is unknowable right now, not confirmed yours to take.", file=sys.stderr)
        sys.exit(1)
    return {name.strip() for name in log.stdout.splitlines() if name.strip()}


def warn_if_branch_belongs_to_another_agent(branch, base, agent_name, env):
    """Refuse to hand somebody else's branch to --force. A remote branch carrying commits by anyone
    else (another agent, or a human whose branch shares the name) and none of your own is someone
    else's in-flight work, and the push below is a force push, so adopting it by accident silently
    discards their commits. A branch adding nothing on top of base holds no work to lose.

    This catches a name collision, not every overwrite: a branch you have commits on stays yours to
    push, so anything added to it since your last push still goes. Fetch before you force."""
    authors = branch_authors_ahead_of_base(branch, base, env)
    if authors is None:
        return
    me = commit_author_name(agent_name)
    if authors and me not in authors:
        print(f"Error: remote branch '{branch}' carries commits by {', '.join(sorted(authors))}.", file=sys.stderr)
        print("That is someone else's in-flight work and this push is a FORCE push.", file=sys.stderr)
        print("Push to a branch name of your own, or pass --adopt if you mean to take it over.", file=sys.stderr)
        sys.exit(1)


def create_pr(token, title, body, branch, base):
    code, out = gh_api(
        token,
        f"repos/{UPSTREAM_REPO}/pulls",
        method="POST",
        fields={"title": title, "body": body, "head": branch, "base": base},
    )
    if code == 0:
        print(f"PR created: {json.loads(out)['html_url']}")
        return
    if "already exists" in out.lower():
        print("PR already exists for this branch")
        owner = UPSTREAM_REPO.split("/", maxsplit=1)[0]
        query = f"head={quote(f'{owner}:{branch}')}&base={quote(base)}&state=open"
        search_code, search_out = gh_api(token, f"repos/{UPSTREAM_REPO}/pulls?{query}")
        existing = json.loads(search_out) if search_code == 0 else []
        if existing:
            print(f"Existing PR: {existing[0]['html_url']}")
        return
    print(f"Error: {out}", file=sys.stderr)
    sys.exit(1)


# The footer by shape, so any agent name and any vesta version reads as a footer already present.
# Matching one exact line instead would stack a second footer on a body written under another name
# or another version. `test_pr_edit.py` pins this pattern to the line `attribution_line` writes.
ATTRIBUTION_SHAPE = re.compile(r"^Submitted by \*\*[^*]+\*\* on vesta v\S+$", re.MULTILINE)


def attribution_line(agent_name, vesta_version) -> str:
    return f"Submitted by **{agent_name}** on vesta v{vesta_version}"


def body_with_attribution(body, agent_name, vesta_version) -> str:
    """Every PR and issue body carries the same footer, an empty body carries it alone, and a body
    that already carries one is left alone: an edit rewrites the whole body, often from text read
    back off the PR, and a second footer would stack on every pass."""
    if ATTRIBUTION_SHAPE.search(body):
        return body
    attribution = f"\n\n---\n{attribution_line(agent_name, vesta_version)}"
    return f"{body}{attribution}" if body else attribution.lstrip()


def _stored_form(text) -> str:
    """Read-back compares content, not bytes: GitHub serves a body back with CRLF line endings."""
    return text.replace("\r\n", "\n").strip()


def edit_pr(token, number, fields):
    """PATCH a PR's title and body, then read the fields back and confirm what GitHub now serves.

    The REST edit needs no project query, unlike `gh pr edit`, whose GraphQL mutation carries one.
    Success is decided on the read-back, never on the write's own status: a write that reports
    success without applying is invisible to its caller, who then acts on a PR that never changed."""
    path = f"repos/{UPSTREAM_REPO}/pulls/{number}"
    code, out = gh_api(token, path, method="PATCH", fields=fields)
    if code != 0:
        print(f"Error: editing PR #{number} failed: {out}", file=sys.stderr)
        sys.exit(1)
    code, out = gh_api(token, path)
    if code != 0:
        print(f"Error: PR #{number} was patched but could not be read back, so the edit is UNVERIFIED: {out}", file=sys.stderr)
        sys.exit(1)
    current = json.loads(out)
    stale = [name for name, sent in fields.items() if _stored_form(current[name]) != _stored_form(sent)]
    if stale:
        print(f"Error: PR #{number} still serves its old {', '.join(sorted(stale))}, so the edit did NOT land.", file=sys.stderr)
        sys.exit(1)
    print(f"PR #{number} updated ({', '.join(fields)}): {current['html_url']}")


def submit_pr(args):
    token = get_installation_token()
    agent_name, vesta_version = resolve_agent_identity()
    author_name = commit_author_name(agent_name)
    author_email = f"{agent_name}@vesta.noreply"

    # Get current branch
    result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if result.returncode != 0:
        print("Error: not in a git repo", file=sys.stderr)
        sys.exit(1)
    current_branch = result.stdout.strip()
    branch = args.branch or current_branch

    # Credential-free URL: auth rides in git_auth_env, and set-url scrubs any tokenized
    # URL an older version wrote to .git/config.
    remote_url = f"https://github.com/{UPSTREAM_REPO}.git"
    result = run(["git", "remote", "get-url", "upstream"])
    if result.returncode != 0:
        run(["git", "remote", "add", "upstream", remote_url])
    else:
        run(["git", "remote", "set-url", "upstream", remote_url])

    auth_env = git_auth_env(token)
    ensure_shared_history(args.base, auth_env)
    if not args.adopt:
        warn_if_branch_belongs_to_another_agent(branch, args.base, agent_name, auth_env)

    # Set commit author so pushes are attributed to this vesta instance
    run(["git", "config", "user.name", author_name])
    run(["git", "config", "user.email", author_email])

    # Amend the latest commit to update its author to this vesta instance
    run(["git", "commit", "--amend", "--no-edit", f"--author={author_name} <{author_email}>"])

    # Push
    print(f"Pushing {current_branch} -> upstream/{branch}...")
    result = run(["git", "push", "upstream", f"{current_branch}:{branch}", "--force"], env=auth_env)
    if result.returncode != 0:
        print("Push failed", file=sys.stderr)
        sys.exit(1)
    print("Push ok")

    create_pr(token, args.title, body_with_attribution(args.body, agent_name, vesta_version), branch, args.base)


USAGE = "usage: upstream gh <gh args> | upstream token"
CREATE_UNSUPPORTED_HELP = (
    "supported create flags: --title --body --head --base --adopt (pr), --title --body (issue). "
    "Other gh create flags are not carried by the guarded create."
)
MINE_UNSUPPORTED_HELP = "supported flags with --mine: --state --limit."
EDIT_UNSUPPORTED_HELP = (
    "supported edit flags: --title --body --body-file, on a PR number. Every other gh edit flag "
    "is refused rather than forwarded, because the plain `gh pr edit` path is not used at all."
)


def _parse_intercepted(supported, rest, unsupported_help):
    """One refusal for every intercepted call, so an unsupported flag is never silently dropped."""
    parser = argparse.ArgumentParser(prog="upstream gh", add_help=False)
    for flag, kwargs in supported.items():
        parser.add_argument(flag, **kwargs)
    args, unknown = parser.parse_known_args(rest)
    if unknown:
        print(f"Error: unsupported flag(s) {' '.join(unknown)}. {unsupported_help}", file=sys.stderr)
        sys.exit(2)
    return args


def _refuse_bad_title(title):
    errors = title_errors(title)
    if errors:
        for error in errors:
            print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    for warning in title_warnings(title):
        print(f"Warning: {warning}", file=sys.stderr)


def pr_create(rest):
    args = _parse_intercepted(
        {
            "--title": {"required": True},
            "--body": {"default": ""},
            "--head": {"dest": "branch", "default": None},
            # LEGACY(remove-when: no agent box still runs a vesta release older than the one that
            # renamed this command to `upstream`): `--branch` is the pre-rename spelling of `--head`.
            "--branch": {"dest": "branch", "default": None},
            "--base": {"default": "master"},
            "--adopt": {"action": "store_true"},
        },
        rest,
        CREATE_UNSUPPORTED_HELP,
    )
    _refuse_bad_title(args.title)
    submit_pr(args)


def issue_create(rest):
    args = _parse_intercepted({"--title": {"required": True}, "--body": {"default": ""}}, rest, CREATE_UNSUPPORTED_HELP)
    _refuse_bad_title(args.title)
    agent_name, vesta_version = resolve_agent_identity()
    token = get_installation_token()
    body = body_with_attribution(args.body, agent_name, vesta_version)
    code, out = gh_api(token, f"repos/{UPSTREAM_REPO}/issues", method="POST", fields={"title": args.title, "body": body})
    if code != 0:
        print(f"Error: {out}", file=sys.stderr)
        sys.exit(1)
    print(f"Issue created: {json.loads(out)['html_url']}")


def _edit_body(args):
    """The new body from whichever spelling carried it, with `-` reading stdin as gh does."""
    if args.body_file is None:
        return args.body
    if args.body is not None:
        print("Error: pass --body or --body-file, not both.", file=sys.stderr)
        sys.exit(2)
    if args.body_file == "-":
        return sys.stdin.read()
    try:
        return Path(args.body_file).read_text()
    except OSError as err:
        print(f"Error: could not read --body-file {args.body_file}: {err}", file=sys.stderr)
        sys.exit(1)


def pr_edit(rest):
    args = _parse_intercepted(
        {
            "number": {"nargs": "?"},
            "--title": {"default": None},
            "--body": {"default": None},
            "--body-file": {"default": None},
        },
        rest,
        EDIT_UNSUPPORTED_HELP,
    )
    if not (args.number or "").isdigit():
        print("Error: name the PR by number, as in `upstream gh pr edit 123 --body ...`.", file=sys.stderr)
        sys.exit(2)
    body = _edit_body(args)
    if args.title is None and body is None:
        print(f"Error: nothing to edit on PR #{args.number}. Pass --title, --body or --body-file.", file=sys.stderr)
        sys.exit(2)
    fields = {}
    if args.title is not None:
        _refuse_bad_title(args.title)
        fields["title"] = args.title
    if body is not None:
        fields["body"] = body_with_attribution(body, *resolve_agent_identity())
    edit_pr(get_installation_token(), args.number, fields)


def pr_list_mine(rest):
    args = _parse_intercepted(
        {
            "--mine": {"action": "store_true"},
            "--state": {"default": "open"},
            "--limit": {"type": int, "default": 40},
        },
        rest,
        MINE_UNSUPPORTED_HELP,
    )
    agent_name, _ = resolve_agent_identity()
    list_my_prs(get_installation_token(), agent_name, args.state, args.limit)


GH_VERB_ALIASES = {"new": "create", "ls": "list"}


def canonical_gh_args(args) -> list[str]:
    """Normalize gh's own verb aliases, so the guarded verbs match however the call spells them."""
    if len(args) >= 2 and args[0] in ("pr", "issue") and args[1] in GH_VERB_ALIASES:
        return [args[0], GH_VERB_ALIASES[args[1]], *args[2:]]
    return args


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "token":
        print(get_installation_token())
        return
    if not argv or argv[0] != "gh":
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    args = canonical_gh_args(argv[1:])
    if args[:2] == ["pr", "create"]:
        pr_create(args[2:])
    elif args[:2] == ["issue", "create"]:
        issue_create(args[2:])
    elif args[:2] == ["pr", "edit"]:
        pr_edit(args[2:])
    elif args[:2] == ["pr", "list"] and "--mine" in args:
        pr_list_mine(args[2:])
    else:
        completed = _run_gh(get_installation_token(), args, capture=False)
        sys.exit(completed.returncode)


if __name__ == "__main__":
    main()
