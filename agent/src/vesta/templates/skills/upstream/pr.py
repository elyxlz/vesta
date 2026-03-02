# /// script
# requires-python = ">=3.10"
# dependencies = ["PyJWT>=2.8.0", "cryptography>=41.0.0", "requests>=2.31.0"]
# ///
"""Upstream PR tool — authenticates via GitHub App, pushes branch, creates PR."""

import argparse
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


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and result.stderr:
        print(result.stderr, file=sys.stderr)
    return result


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

    # Get current branch
    result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if result.returncode != 0:
        print("Error: not in a git repo", file=sys.stderr)
        sys.exit(1)
    current_branch = result.stdout.strip()
    branch = args.branch or current_branch

    # Configure upstream remote
    remote_url = f"https://x-access-token:{token}@github.com/{UPSTREAM_REPO}.git"
    result = run(["git", "remote", "get-url", "upstream"])
    if result.returncode != 0:
        run(["git", "remote", "add", "upstream", remote_url])
    else:
        run(["git", "remote", "set-url", "upstream", remote_url])

    # Push
    print(f"Pushing {current_branch} -> upstream/{branch}...")
    result = run(["git", "push", "upstream", f"{current_branch}:{branch}", "--force"])
    if result.returncode != 0:
        print("Push failed", file=sys.stderr)
        sys.exit(1)
    print("Push ok")

    # Create PR
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = requests.post(
        f"{GITHUB_API}/repos/{UPSTREAM_REPO}/pulls",
        headers=headers,
        json={"title": args.title, "body": args.body, "head": branch, "base": args.base},
        timeout=30,
    )

    if resp.status_code == 201:
        print(f"PR created: {resp.json()['html_url']}")
    elif resp.status_code == 422 and "already exists" in resp.text.lower():
        print("PR already exists for this branch")
        search = requests.get(
            f"{GITHUB_API}/repos/{UPSTREAM_REPO}/pulls",
            headers=headers,
            params={"head": f"{UPSTREAM_REPO.split('/')[0]}:{branch}", "base": args.base, "state": "open"},
            timeout=30,
        )
        if search.status_code == 200 and search.json():
            print(f"Existing PR: {search.json()[0]['html_url']}")
    else:
        print(f"Error: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
