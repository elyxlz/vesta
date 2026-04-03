#!/usr/bin/env python3
"""CLI tool to query OpenAI's ChatGPT API."""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error


def _load_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        # Try loading from /etc/environment
        try:
            with open("/etc/environment") as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        key = line.strip().split("=", 1)[1]
                        break
        except OSError:
            pass
    if not key:
        print("Error: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    return key


def ask(prompt: str, *, model: str = "gpt-4o", system: str | None = None) -> str:
    """Send a prompt to OpenAI and return the response text."""
    key = _load_key()

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": model,
        "messages": messages,
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            err = json.loads(body)
            msg = err.get("error", {}).get("message", body)
        except (json.JSONDecodeError, KeyError):
            msg = body
        print(f"OpenAI API error ({e.code}): {msg}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Network error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Query OpenAI ChatGPT")
    sub = parser.add_subparsers(dest="command")

    ask_cmd = sub.add_parser("ask", help="Ask ChatGPT a question")
    ask_cmd.add_argument("prompt", help="The question or prompt")
    ask_cmd.add_argument("--model", default="gpt-4o", help="Model to use (default: gpt-4o)")
    ask_cmd.add_argument("--system", default=None, help="Optional system prompt")

    args = parser.parse_args()

    if args.command == "ask":
        result = ask(args.prompt, model=args.model, system=args.system)
        print(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
