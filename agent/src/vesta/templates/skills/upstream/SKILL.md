---
name: upstream
description: Use when you need to submit a PR to the upstream vesta repo (elyxlz/vesta). This skill handles authentication via a GitHub App and creates pull requests.
---

# Upstream PRs

Submit improvements back to https://github.com/elyxlz/vesta so all vesta instances benefit.

## Setup

1. Create a GitHub App at https://github.com/settings/apps/new:
   - Name: `vesta-upstream`
   - Permissions: Contents (R/W), Pull requests (R/W), Metadata (Read)
   - Uncheck Webhook Active
   - Where can this be installed: Only on this account
2. Install it on the vesta repo
3. Generate a private key and save it:
   ```bash
   mkdir -p ~/.config/vesta-upstream
   # Save the .pem file as ~/.config/vesta-upstream/private-key.pem
   chmod 600 ~/.config/vesta-upstream/private-key.pem
   ```
4. Save the app config:
   ```bash
   cat > ~/.config/vesta-upstream/config <<EOF
   App ID: <from app settings>
   Installation ID: <from install URL>
   EOF
   ```

## Usage

The script below handles everything: JWT generation, token exchange, push, and PR creation.

```bash
# From inside the vesta repo, on a feature branch:
uv run {skills_dir}/upstream/pr.py --title "What changed" --body "Why it changed"
```

To just get a token for raw API access:
```bash
uv run {skills_dir}/upstream/pr.py --token-only
```

## What to PR
- Skill improvements, bug fixes, new tools, prompt upgrades
- Don't PR user-specific config, personal data, or credentials

## Script: pr.py

The embedded script lives at `{skills_dir}/upstream/pr.py`. If it doesn't exist, create it from the code block below:

```python
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

import jwt
import requests

CONFIG_DIR = os.path.expanduser("~/.config/vesta-upstream")
DEFAULT_KEY_PATH = os.path.join(CONFIG_DIR, "private-key.pem")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config")
UPSTREAM_REPO = "elyxlz/vesta"
GITHUB_API = "https://api.github.com"


def load_config():
    """Load app ID and installation ID from config file."""
    if not os.path.isfile(CONFIG_PATH):
        print(f"Error: config not found at {CONFIG_PATH}", file=sys.stderr)
        print("Run the setup steps in the upstream skill first.", file=sys.stderr)
        sys.exit(1)
    config = {}
    with open(CONFIG_PATH) as f:
        for line in f:
            if ":" in line:
                key, val = line.split(":", 1)
                config[key.strip()] = val.strip()
    return int(config["App ID"]), int(config["Installation ID"])


def load_private_key():
    key_path = os.environ.get("VESTA_UPSTREAM_KEY_PATH", DEFAULT_KEY_PATH)
    if not os.path.isfile(key_path):
        print(f"Error: private key not found at {key_path}", file=sys.stderr)
        sys.exit(1)
    with open(key_path) as f:
        return f.read()


def generate_jwt(app_id, private_key):
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": str(app_id)}
    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token(app_id, installation_id):
    private_key = load_private_key()
    token_jwt = generate_jwt(app_id, private_key)
    resp = requests.post(
        f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
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

    app_id, installation_id = load_config()
    token = get_installation_token(app_id, installation_id)

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
```
