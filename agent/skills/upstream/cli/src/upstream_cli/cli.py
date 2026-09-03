"""Upstream tool: mints GitHub App auth and runs gh against the upstream vesta repo."""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import typing as tp
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import jwt

from upstream_cli import daemon
from upstream_cli.notifications import NOTIFICATIONS_DIR, write_notification
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


PR_STATES = {"open": "[OPEN]", "closed": "[CLOSED, MERGED]", "all": "[OPEN, CLOSED, MERGED]"}
PR_PAGE_SIZE = 100


def pull_requests_query(states, selection) -> str:
    """One page of PRs, newest first, each carrying number, title, url, and `selection`. The state
    list is written into the query text: `gh api -f` sends every variable as a string, and GraphQL
    takes an enum list only as a literal."""
    owner, name = UPSTREAM_REPO.split("/", maxsplit=1)
    return (
        f'query($cursor: String) {{ repository(owner: "{owner}", name: "{name}") {{ pullRequests('
        f"states: {states}, first: {PR_PAGE_SIZE}, after: $cursor, orderBy: {{field: CREATED_AT, direction: DESC}}"
        f") {{ pageInfo {{ hasNextPage endCursor }} nodes {{ number title url {selection} }} }} }} }}"
    )


def prs_with_authors_query(state) -> str:
    """Every commit author name in order, which is what classifies a PR as opened or only pushed to."""
    return pull_requests_query(PR_STATES[state], "commits(first: 100) { nodes { commit { author { name } } } }")


def fetch_pr_pages(token, query):
    """Every PR the query selects, following the cursor to the last page."""
    fields = {"query": query}
    prs = []
    while True:
        code, out = gh_api(token, "graphql", method="POST", fields=fields)
        if code != 0:
            print(f"Error: gh api graphql failed: {out}", file=sys.stderr)
            sys.exit(1)
        page = json.loads(out)["data"]["repository"]["pullRequests"]
        prs.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return prs
        fields["cursor"] = page["pageInfo"]["endCursor"]


def print_capped(rows, limit):
    for row in rows[:limit]:
        print(row)
    if len(rows) > limit:
        print(f"  ... {len(rows) - limit} more not printed: raise --limit to see them")


def list_my_prs(token, agent_name, state, limit):
    """Print the PRs this agent opened, and separately the ones it only pushed commits to. Every
    agent files through the same GitHub App, so `user.login` is `vesta-upstream[bot]` on EVERY PR
    and identifies nobody; the commit authors are the only field naming the agent, and the FIRST
    commit's author opened the PR. Every PR in `state` is classified; `limit` caps the printed rows."""
    me = commit_author_name(agent_name)
    prs = fetch_pr_pages(token, prs_with_authors_query(state))
    opened, touched = [], []
    for pr in prs:
        authors = [node["commit"]["author"]["name"] for node in pr["commits"]["nodes"]]
        if authors[:1] == [me]:
            opened.append(f"  #{pr['number']}  {pr['title'][:72]}\n      {pr['url']}")
        elif me in authors:
            touched.append(f"  #{pr['number']}  opened by {authors[0]}: {pr['title'][:56]}\n      {pr['url']}")

    print(f"Checked all {len(prs)} {state} PR(s) as {me}.")
    print(f"\nOpened by you ({len(opened)}):")
    print_capped(opened, limit)
    if not opened:
        print("  (none: every PR here was opened by a different agent through the same bot account)")
    if touched:
        print(f"\nNot yours, but you have commits on them ({len(touched)}):")
        print_capped(touched, limit)


WATCH_STATE_PATH = Path.home() / "agent/data/upstream-prs.json"
# The App's own login: a comment it posted is this agent's or another agent's reply, never news.
BOT_LOGIN = "vesta-upstream[bot]"
# The opener is the first commit's author; the head commit's rollup is what `pr checks` reports.
WATCH_SELECTION = (
    "commits(first: 1) { nodes { commit { author { name } } } }"
    " head: commits(last: 1) { nodes { commit { statusCheckRollup { state contexts(first: 100) { nodes {"
    " ... on CheckRun { name conclusion } ... on StatusContext { context state } } } } } } }"
)
FAILED_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}
FAILED_STATUS_STATES = {"FAILURE", "ERROR"}
CHECK_VERDICTS = {"SUCCESS": "green", "FAILURE": "red", "ERROR": "red"}
# The three feeds a PR's conversation lands in, and the REST path of each.
COMMENT_FEEDS = {"comment": "issues/{n}/comments", "review": "pulls/{n}/reviews", "review_comment": "pulls/{n}/comments"}


class WatchedPr(tp.TypedDict):
    """What one poll remembers of an open PR: the highest id seen per feed and the last checks verdict."""

    title: str
    url: str
    seen: dict[str, int]
    checks: str


def read_watch_state(path: Path) -> dict[str, WatchedPr] | None:
    """None before the first pass ever completes, which is the one pass that seeds without notifying."""
    return json.loads(path.read_text()) if path.exists() else None


def write_watch_state(path: Path, state: dict[str, WatchedPr]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(path)


def check_verdict(pr) -> tuple[str, list[str]]:
    """The head commit's rollup as green, red, or pending, plus the contexts that failed."""
    head = pr["head"]["nodes"]
    rollup = head[0]["commit"]["statusCheckRollup"] if head else None
    if rollup is None:
        return "pending", []
    failing = []
    for context in rollup["contexts"]["nodes"]:
        if "name" in context and context["conclusion"] in FAILED_CONCLUSIONS:
            failing.append(context["name"])
        elif "context" in context and context["state"] in FAILED_STATUS_STATES:
            failing.append(context["context"])
    state = rollup["state"]
    return (CHECK_VERDICTS[state] if state in CHECK_VERDICTS else "pending"), failing


def comment_news(kind, item) -> dict[str, str] | None:
    """The notification fields one feed item carries, or None for an item that is not news: the
    App's own comments, and the empty review that only wraps inline comments."""
    if item["user"]["login"] == BOT_LOGIN:
        return None
    fields = {"author": item["user"]["login"], "url": item["html_url"], "message": item["body"]}
    if kind == "review":
        if not item["body"] and item["state"] == "COMMENTED":
            return None
        fields["review"] = item["state"]
    if kind == "review_comment":
        fields["path"] = item["path"]
    return fields


def watch_open_pr(token, number, pr, previous: WatchedPr | None) -> tuple[WatchedPr, list[tuple[str, dict[str, object]]]]:
    """One open PR against what the last pass saw: the record to keep and the news to write. A feed
    that cannot be read keeps its watermark, so its news arrives on the next pass instead of never."""
    seen = dict(previous["seen"]) if previous else {}
    entry = WatchedPr(title=pr["title"], url=pr["url"], seen=seen, checks="pending")
    about = {"number": int(number), "title": pr["title"]}
    news: list[tuple[str, dict[str, object]]] = []
    verdict, failing = check_verdict(pr)
    entry["checks"] = verdict
    if verdict != "pending" and verdict != (previous["checks"] if previous else "pending"):
        message = "checks green" if verdict == "green" else f"checks red: {', '.join(failing)}"
        news.append(("pr_checks", {**about, "url": pr["url"], "checks": verdict, "failing": ", ".join(failing), "message": message}))
    for kind, path in COMMENT_FEEDS.items():
        code, out = gh_api(token, f"repos/{UPSTREAM_REPO}/{path.format(n=number)}?per_page=100")
        if code != 0:
            print(f"Warning: could not read {kind}s of #{number}: {out}", file=sys.stderr)
            continue
        last = seen[kind] if kind in seen else 0
        for item in json.loads(out):
            fields = comment_news(kind, item) if item["id"] > last else None
            if fields is not None:
                news.append(("pr_comment", {**about, **fields}))
            seen[kind] = max(seen[kind] if kind in seen else 0, item["id"])
    return entry, news


def settled_pr_news(token, number, previous: WatchedPr) -> tuple[str, dict[str, object]] | None:
    """A PR that left the open list, read back to say how: merged, or closed with the comment that
    closed it. None keeps watching it: the read failed, or the PR is open after all."""
    code, out = gh_api(token, f"repos/{UPSTREAM_REPO}/pulls/{number}")
    if code != 0:
        print(f"Warning: could not read #{number}: {out}", file=sys.stderr)
        return None
    pr = json.loads(out)
    about: dict[str, object] = {"number": int(number), "title": previous["title"], "url": previous["url"]}
    if pr["merged"]:
        return "pr_merged", {**about, "author": pr["merged_by"]["login"], "message": "merged"}
    if pr["state"] != "closed":
        return None
    code, out = gh_api(token, f"repos/{UPSTREAM_REPO}/issues/{number}/comments?per_page=100")
    comments = json.loads(out) if code == 0 else []
    if not comments:
        return "pr_closed", {**about, "author": "", "message": "closed without a comment"}
    return "pr_closed", {**about, "author": comments[-1]["user"]["login"], "message": comments[-1]["body"]}


def poll_prs(token, agent_name, state_path: Path, notif_dir: Path) -> tuple[int, list[str]]:
    """One pass over the PRs this agent opened: every change since the last pass becomes one
    notification file. Returns how many PRs are watched and the types written. The first pass ever
    records what it finds and writes nothing, so a backlog never arrives as a storm."""
    me = commit_author_name(agent_name)
    prs = fetch_pr_pages(token, pull_requests_query(PR_STATES["open"], WATCH_SELECTION))
    mine = {str(pr["number"]): pr for pr in prs if [node["commit"]["author"]["name"] for node in pr["commits"]["nodes"]][:1] == [me]}
    known = read_watch_state(state_path)
    seeding = known is None
    known = known or {}
    news: list[tuple[str, dict[str, object]]] = []
    state: dict[str, WatchedPr] = {}
    for number, pr in mine.items():
        state[number], found = watch_open_pr(token, number, pr, known[number] if number in known else None)
        news.extend(found)
    for number, previous in known.items():
        if number in mine:
            continue
        settled = settled_pr_news(token, number, previous)
        if settled is None:
            state[number] = previous
        else:
            news.append(settled)
    written = []
    if not seeding:
        for notif_type, fields in news:
            write_notification(notif_dir, notif_type, interrupt=False, **fields)
            written.append(notif_type)
    write_watch_state(state_path, state)
    return len(mine), written


def poll_command():
    agent_name, _ = resolve_agent_identity()
    watched, written = poll_prs(get_installation_token(), agent_name, WATCH_STATE_PATH, NOTIFICATIONS_DIR)
    print(json.dumps({"watched": watched, "notified": written}))


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


def body_with_attribution(body, agent_name, vesta_version) -> str:
    """Every PR and issue body carries the same footer, and an empty body carries it alone."""
    attribution = f"\n\n---\nSubmitted by **{agent_name}** on vesta v{vesta_version}"
    return f"{body}{attribution}" if body else attribution.lstrip()


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


USAGE = "usage: upstream gh <gh args> | upstream token | upstream daemon <start|stop|restart|status> | upstream poll"
CREATE_UNSUPPORTED_HELP = (
    "supported create flags: --title --body --head --base --adopt (pr), --title --body (issue). "
    "Other gh create flags are not carried by the guarded create."
)
MINE_UNSUPPORTED_HELP = "supported flags with --mine: --state --limit."


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


def pr_list_mine(rest):
    args = _parse_intercepted(
        {
            "--mine": {"action": "store_true"},
            "--state": {"default": "open", "choices": list(PR_STATES)},
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
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return
    if argv[0] == "token":
        print(get_installation_token())
        return
    if argv[0] == "daemon":
        sys.exit(daemon.daemon_cmd(argv[1] if len(argv) > 1 else ""))
    if argv[0] == "serve":
        daemon.serve()
        return
    if argv[0] == "poll":
        poll_command()
        return
    if argv[0] != "gh":
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    args = canonical_gh_args(argv[1:])
    if args[:2] == ["pr", "create"]:
        pr_create(args[2:])
    elif args[:2] == ["issue", "create"]:
        issue_create(args[2:])
    elif args[:2] == ["pr", "list"] and "--mine" in args:
        pr_list_mine(args[2:])
    else:
        completed = _run_gh(get_installation_token(), args, capture=False)
        sys.exit(completed.returncode)


if __name__ == "__main__":
    main()
