"""Upstream tool — authenticates via GitHub App, pushes branch, creates PR."""

import argparse
import base64
import os
import subprocess
import sys
import time
from pathlib import Path

import jwt
import requests

# Config — hardcoded for the vesta-upstream GitHub App
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
    resp = requests.post(
        f"{GITHUB_API}/app/installations/{INSTALLATION_ID}/access_tokens",
        headers={
            "Authorization": f"Bearer {token_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    if resp.status_code != 201:
        print(f"Error getting token: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    return resp.json()["token"]


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


def api_headers(token):
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def pr_commit_authors(token, number):
    """(originator, all authors) for one PR, by commit author name. Every agent pushes through the
    same GitHub App, so `pull.user.login` is `vesta-upstream[bot]` on EVERY PR in the repo and
    identifies nobody. The commit author is the only field carrying which agent wrote it, and the
    FIRST commit's author is the one who opened the PR."""
    resp = requests.get(
        f"{GITHUB_API}/repos/{UPSTREAM_REPO}/pulls/{number}/commits",
        headers=api_headers(token),
        params={"per_page": 100},
        timeout=30,
    )
    if resp.status_code != 200:
        return None, set()
    commits = resp.json()
    if not commits:
        return None, set()
    return commits[0]["commit"]["author"]["name"], {c["commit"]["author"]["name"] for c in commits}


def list_my_prs(token, agent_name, state, limit):
    """Print the PRs this agent opened, and separately the ones it only pushed commits to."""
    me = f"{agent_name} (vesta)"
    resp = requests.get(
        f"{GITHUB_API}/repos/{UPSTREAM_REPO}/pulls",
        headers=api_headers(token),
        params={"state": state, "per_page": 100, "sort": "created", "direction": "desc"},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Error: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    candidates = resp.json()[:limit]
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
    me = f"{agent_name} (vesta)"
    if authors and me not in authors:
        print(f"Error: remote branch '{branch}' carries commits by {', '.join(sorted(authors))}.", file=sys.stderr)
        print("That is someone else's in-flight work and this push is a FORCE push.", file=sys.stderr)
        print("Push to a branch name of your own, or pass --adopt if you mean to take it over.", file=sys.stderr)
        sys.exit(1)


def create_pr(token, title, body, branch, base):
    headers = api_headers(token)
    resp = requests.post(
        f"{GITHUB_API}/repos/{UPSTREAM_REPO}/pulls",
        headers=headers,
        json={"title": title, "body": body, "head": branch, "base": base},
        timeout=30,
    )

    if resp.status_code == 201:
        print(f"PR created: {resp.json()['html_url']}")
    elif resp.status_code == 422 and "already exists" in resp.text.lower():
        print("PR already exists for this branch")
        search = requests.get(
            f"{GITHUB_API}/repos/{UPSTREAM_REPO}/pulls",
            headers=headers,
            params={"head": f"{UPSTREAM_REPO.split('/', maxsplit=1)[0]}:{branch}", "base": base, "state": "open"},
            timeout=30,
        )
        if search.status_code == 200 and search.json():
            print(f"Existing PR: {search.json()[0]['html_url']}")
    else:
        print(f"Error: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Submit PR to upstream vesta repo")
    parser.add_argument("--title", help="PR title")
    parser.add_argument("--body", default="", help="PR body")
    parser.add_argument("--branch", default=None, help="Remote branch name (default: current branch)")
    parser.add_argument("--base", default="master", help="Base branch (default: master)")
    parser.add_argument("--token-only", action="store_true", help="Just print an installation token")
    parser.add_argument("--mine", action="store_true", help="List the PRs this agent actually wrote")
    parser.add_argument("--state", default="open", help="With --mine: open, closed or all (default: open)")
    parser.add_argument("--limit", type=int, default=40, help="With --mine: how many recent PRs to check")
    parser.add_argument("--adopt", action="store_true", help="Allow pushing to a branch another agent started")
    args = parser.parse_args()

    token = get_installation_token()

    if args.token_only:
        print(token)
        return

    if args.mine:
        agent_name, _ = resolve_agent_identity()
        list_my_prs(token, agent_name, args.state, args.limit)
        return

    if not args.title:
        parser.error("--title is required when creating a PR")

    agent_name, vesta_version = resolve_agent_identity()
    author_name = f"{agent_name} (vesta)"
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

    # Append agent attribution to PR body
    attribution = f"\n\n---\nSubmitted by **{agent_name}** on vesta v{vesta_version}"
    body = f"{args.body}{attribution}" if args.body else attribution.lstrip()

    create_pr(token, args.title, body, branch, args.base)


if __name__ == "__main__":
    main()
