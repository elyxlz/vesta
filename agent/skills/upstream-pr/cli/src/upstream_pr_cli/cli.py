"""Upstream PR tool — authenticates via GitHub App, pushes branch, creates PR."""

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
    if "AGENT_NAME" not in os.environ:
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
    cryptic "no history in common with master". This happens when upstream-pr is run from
    the workspace branch (~), whose base is a standalone stock snapshot tag with no ancestry
    to real GitHub master, so pushing it force-pushes an unrelated root. Catch it here with
    an actionable message BEFORE we amend the commit author or push anything."""
    run(["git", "fetch", "--quiet", "upstream", base], env=env)
    merge_base = run(["git", "merge-base", "FETCH_HEAD", "HEAD"])
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        print(f"Error: HEAD shares no history with upstream/{base}.", file=sys.stderr)
        print("You are probably running from your workspace branch (~), whose base is a", file=sys.stderr)
        print("standalone stock snapshot tag unrelated to real master. Run upstream-pr from", file=sys.stderr)
        print("your PR worktree (branch off FETCH_HEAD after fetching master), not from ~.", file=sys.stderr)
        sys.exit(1)


def create_pr(token, title, body, branch, base):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
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
    args = parser.parse_args()

    token = get_installation_token()

    if args.token_only:
        print(token)
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
