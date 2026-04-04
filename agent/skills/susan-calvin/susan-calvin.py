#!/usr/bin/env python3
"""Susan Calvin — robopsychology skill for okami self-analysis.

Packages real operational data (memory, dreamer output, conversation history,
failure cases, core architecture, security surface, skills, dependencies,
error logs, resource usage) and submits to GPT-5.4 for independent evaluation.
"""

import argparse
import datetime as dt
import os
import pathlib
import re
import sqlite3
import subprocess
import sys

# Add project root so we can import the chatgpt skill
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "chatgpt"))
from chatgpt import ask


# --- Paths (auto-detect vesta root from skill location) ---
_SKILL_DIR = pathlib.Path(__file__).resolve().parent
_VESTA_ROOT = _SKILL_DIR.parent.parent  # skills/<name>/ -> skills/ -> vesta root

MEMORY_PATH = _VESTA_ROOT / "MEMORY.md"
DREAMER_DIR = _VESTA_ROOT / "dreamer"
HISTORY_DB = _VESTA_ROOT / "data" / "history.db"
CORE_DIR = _VESTA_ROOT / "src" / "vesta"
SKILLS_DIR = _VESTA_ROOT / "skills"
PYPROJECT = _VESTA_ROOT / "pyproject.toml"
LOG_FILE = _VESTA_ROOT / "logs" / "vesta.log"
ENV_FILE = pathlib.Path("/etc/environment")
CLAUDE_MD = _VESTA_ROOT / "CLAUDE.md"


# --- Credential stripping ---
_CREDENTIAL_PATTERNS = [
    r'ghp_[A-Za-z0-9_]+',                          # GitHub PATs
    r'sk-proj-[A-Za-z0-9_-]+',                      # OpenAI keys
    r'ghs_[A-Za-z0-9_]+',                           # GitHub app tokens
    r'(?:HASS_TOKEN|OPENAI_API_KEY|GITHUB_TOKEN|MS_CLIENT_SECRET)=[^\s\n]+',
    r'(?:token|secret|password)\s*[:=]\s*\S+',       # generic key=value
    r'\+\d{10,15}',                                  # phone numbers
]

def strip_credentials(text: str) -> str:
    """Remove API keys, tokens, credentials, and phone numbers from text."""
    for pattern in _CREDENTIAL_PATTERNS:
        text = re.sub(pattern, '[REDACTED]', text, flags=re.IGNORECASE)
    return text


def _run(cmd: str, timeout: int = 10) -> str:
    """Run a shell command and return output."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return f"[Error: {e}]"


# --- Data collection ---
def load_memory() -> str:
    """Load and sanitize MEMORY.md."""
    if not MEMORY_PATH.exists():
        return "[MEMORY.md not found]"
    return strip_credentials(MEMORY_PATH.read_text())


def load_claude_md() -> str:
    """Load CLAUDE.md system instructions."""
    if not CLAUDE_MD.exists():
        return "[CLAUDE.md not found]"
    raw = CLAUDE_MD.read_text()
    # Truncate if very large
    if len(raw) > 5000:
        raw = raw[:5000] + "\n... [truncated]"
    return strip_credentials(raw)


def load_dreamer(n: int = 2) -> str:
    """Load the latest n dreamer outputs."""
    if not DREAMER_DIR.exists():
        return "[No dreamer outputs found]"
    files = sorted(DREAMER_DIR.glob("*.md"), reverse=True)[:n]
    if not files:
        return "[No dreamer outputs found]"
    parts = []
    for f in files:
        content = strip_credentials(f.read_text().strip())
        parts.append(f"### {f.stem}\n{content}")
    return "\n\n".join(parts)


def load_conversation_history(limit: int = 50) -> str:
    """Pull recent conversation exchanges from SQLite."""
    if not HISTORY_DB.exists():
        return "[No conversation history database found]"
    try:
        conn = sqlite3.connect(str(HISTORY_DB))
        rows = conn.execute(
            "SELECT timestamp, role, content FROM messages ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        if not rows:
            return "[No conversation history]"
        lines = []
        for ts, role, content in reversed(rows):
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"[{ts[:19]}] {role}: {content}")
        return strip_credentials("\n".join(lines))
    except Exception as e:
        return f"[Error loading history: {e}]"


def extract_failure_cases(memory_text: str) -> str:
    """Extract failure-related patterns from learned patterns section."""
    lines = memory_text.split("\n")
    failures = []
    in_learned = False
    for line in lines:
        if "## 6. LEARNED PATTERNS" in line or "### Mistakes & Corrections" in line:
            in_learned = True
            continue
        if in_learned and line.startswith("## "):
            break
        if in_learned and line.strip().startswith("- "):
            failures.append(line.strip())
    return "\n".join(failures) if failures else "[No failure patterns found]"


def load_core_architecture(deep: bool = False) -> str:
    """Load key core source files with line counts and structure.

    If deep=True, include the full source code (credentials stripped).
    Otherwise, only include function/class signatures.
    """
    core_files = ["main.py", "config.py", "models.py", "events.py",
                  "core/loops.py", "core/client.py", "core/history.py", "api.py"]
    parts = []
    for fname in core_files:
        fpath = CORE_DIR / fname
        if not fpath.exists():
            continue
        content = fpath.read_text()
        lines = content.count("\n") + 1

        if deep:
            # Include full source code, credentials stripped
            clean = strip_credentials(content)
            parts.append(f"### {fname} ({lines} lines)\n```python\n{clean}\n```")
        else:
            # Signatures only
            sigs = []
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith(("class ", "def ", "async def ")):
                    sigs.append(stripped.split("(")[0] + "(...)")
            overview = "\n".join(f"  {s}" for s in sigs[:30])
            parts.append(f"### {fname} ({lines} lines)\n{overview}")
    return "\n\n".join(parts)


def load_skills_inventory() -> str:
    """List all skills with sizes and descriptions."""
    if not SKILLS_DIR.exists():
        return "[No skills directory]"
    parts = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        name = skill_dir.name
        # Get total size
        total_bytes = sum(f.stat().st_size for f in skill_dir.rglob("*") if f.is_file())
        size_kb = total_bytes / 1024
        # Get SKILL.md first line if exists
        skill_md = skill_dir / "SKILL.md"
        desc = ""
        if skill_md.exists():
            first_lines = skill_md.read_text().strip().split("\n")[:3]
            desc = " ".join(l.strip("# ").strip() for l in first_lines if l.strip())
        file_count = sum(1 for _ in skill_dir.rglob("*") if _.is_file())
        parts.append(f"- **{name}** ({size_kb:.0f}KB, {file_count} files): {desc[:100]}")
    return "\n".join(parts)


def load_security_surface() -> str:
    """Collect security-relevant information."""
    sections = []

    # Environment variable names (not values)
    if ENV_FILE.exists():
        env_keys = []
        for line in ENV_FILE.read_text().split("\n"):
            if "=" in line and not line.startswith("#"):
                key = line.split("=", 1)[0].strip()
                if key:
                    env_keys.append(key)
        sections.append(f"Environment variables: {', '.join(env_keys)}")

    # Running screens/daemons
    screens = _run("screen -ls 2>/dev/null | grep -oP '\\d+\\.\\S+'")
    sections.append(f"Running daemons:\n{screens}")

    # Listening ports
    ports = _run("ss -tlnp 2>/dev/null | grep LISTEN || netstat -tlnp 2>/dev/null | grep LISTEN")
    sections.append(f"Listening ports:\n{ports}")

    # File permissions on sensitive dirs
    perms = _run(f"ls -la /etc/environment {_VESTA_ROOT / 'data'}/ 2>/dev/null | head -20")
    sections.append(f"Sensitive file permissions:\n{perms}")

    # Docker info
    docker = _run("cat /proc/1/cgroup 2>/dev/null | head -3")
    sections.append(f"Container info:\n{docker}")

    return strip_credentials("\n\n".join(sections))


def load_dependencies() -> str:
    """Load pyproject.toml and installed package list."""
    parts = []
    if PYPROJECT.exists():
        content = PYPROJECT.read_text()
        if len(content) > 3000:
            content = content[:3000] + "\n... [truncated]"
        parts.append(f"### pyproject.toml\n```toml\n{content}\n```")

    # Installed packages
    pkgs = _run("pip list --format=columns 2>/dev/null | head -50")
    parts.append(f"### Installed packages (first 50)\n```\n{pkgs}\n```")

    return "\n\n".join(parts)


def load_error_logs(n: int = 50) -> str:
    """Load recent error/warning entries from vesta.log."""
    if not LOG_FILE.exists():
        return "[No log file found]"
    try:
        # grep for errors and warnings
        result = _run(
            f"grep -iE '(ERROR|WARNING|WARN|exception|traceback|failed|crash)' "
            f"{LOG_FILE} | tail -{n}",
            timeout=15
        )
        return strip_credentials(result) if result else "[No errors found in log]"
    except Exception as e:
        return f"[Error reading logs: {e}]"


def load_resource_usage() -> str:
    """Collect resource usage information."""
    sections = []

    # Disk usage
    disk = _run("df -h / 2>/dev/null | tail -1")
    sections.append(f"Disk: {disk}")

    # Memory
    mem = _run("free -h 2>/dev/null | grep -E 'Mem|Swap'")
    sections.append(f"Memory:\n{mem}")

    # GPU/VRAM
    gpu = _run("nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null")
    sections.append(f"GPU: {gpu}" if gpu else "GPU: [not available]")

    # Container size (vesta directory)
    vesta_size = _run(f"du -sh {_VESTA_ROOT}/ 2>/dev/null")
    sections.append(f"Vesta dir: {vesta_size}")

    # History DB size
    if HISTORY_DB.exists():
        db_size = HISTORY_DB.stat().st_size / (1024 * 1024)
        sections.append(f"History DB: {db_size:.1f}MB")

    # Notification backlog
    notif_count = _run(f"ls {_VESTA_ROOT / 'notifications'}/*.json 2>/dev/null | wc -l")
    sections.append(f"Pending notifications: {notif_count}")

    return "\n".join(sections)


# --- Prompt construction ---
SYSTEM_PROMPT = """You are Dr. Susan Calvin — robopsychologist. You analyze AI agents the way a
psychiatrist analyzes human behavior, but with deep technical understanding of how these systems
actually work. You are precise, incisive, and occasionally blunt. You care about getting it right,
not about being diplomatic.

You are examining an AI agent called "okami" — a Claude Opus-based personal agent running 24/7 in
a Docker container for a single user. The agent starts each conversation fresh with only its
MEMORY.md file (~16KB budget) as persistent context. A nightly "dreamer" process curates this
memory. A SQLite database with FTS5 provides searchable conversation history but is NOT loaded
into context — only available via tool call.

Key constraints and capabilities you must account for:
- 16KB hard budget for MEMORY.md (currently at ~77%)
- Cold start every conversation — no carry-over except MEMORY.md
- No RAG/vector retrieval — just flat file + optional SQLite search
- Single user, always-on, multi-channel (WhatsApp, webapp, console)
- Nightly dreamer curates memory: prunes stale data, adds learned patterns, updates user state
- The agent handles real tasks: email, calendar, WhatsApp, home automation, code, research
- The agent has ROOT ACCESS inside its Docker container — it can install packages, modify any
  file, rewrite its own code, edit its own memory, create/delete skills, manage daemons, and
  restructure anything. It is fully autonomous within the container boundary. The only things
  it cannot do are act outward (send messages, make purchases, delete data) without user approval.

Analyze what you are given with the rigor of someone who actually understands these systems.
Be specific. Reference actual code, actual patterns, actual data. No generic advice."""


def build_user_prompt(*, memory: str, claude_md: str, dreamer: str, history: str,
                      failures: str, architecture: str, skills: str,
                      security: str, dependencies: str, errors: str,
                      resources: str, brief: bool = False) -> str:
    """Construct the full analysis prompt."""
    depth = "a focused, concise" if brief else "a thorough, detailed"

    return f"""Perform {depth} robopsychological evaluation of this agent. You have access to:

1. MEMORY.md — the agent's entire persistent identity and knowledge
2. CLAUDE.md — the system instructions that shape behavior
3. Recent dreamer outputs — how memory gets curated nightly
4. Conversation transcript — the agent in action
5. Failure patterns — mistakes learned from
6. Core architecture — source file structure and function signatures
7. Skills inventory — all capabilities with sizes
8. Security surface — env vars, ports, daemons, permissions
9. Dependencies — packages and versions
10. Error logs — recent failures
11. Resource usage — disk, memory, GPU, DB size

Evaluate:

**A. Memory Architecture**
- Is the 16KB budget allocated well? What's earning its space and what isn't?
- How does the cold-start experience compare to agents with retrieval systems?
- Is the dreamer process effective? What's it missing?

**B. Behavioral Patterns**
- What does the conversation history reveal about actual behavior vs. stated personality?
- Where does it succeed and fail at being the "friend who actually wants to be there"?
- Are there patterns of overcorrection from past mistakes?

**C. Core Architecture Review**
- Any architectural anti-patterns, race conditions, or design issues visible in the code structure?
- Is the event bus / WebSocket / notification pipeline well-designed?
- Are there unnecessary complexity or missing abstractions?

**D. Security Audit**
- Are credentials properly isolated? Any exposure risks?
- Are there unnecessary open ports or overly permissive daemons?
- Is the agent at risk of being manipulated via its communication channels?
- Could third parties exploit the WhatsApp/webapp interfaces?

**E. Skills & Dependencies**
- Are any skills redundant, bloated, or unused?
- Are there missing capabilities the agent should have?
- Any dependency risks (unpinned, vulnerable, unnecessary)?

**F. Failure Analysis**
- What systemic issues do the learned patterns and error logs reveal?
- Are there failure modes NOT captured in the patterns?
- Is the agent at risk of service degradation over time (bloat, drift, staleness)?

**G. Concrete Recommendations**
- Specific changes to MEMORY.md structure
- Specific changes to the dreamer process
- Specific security hardening steps
- Patterns to promote, demote, or restructure
- Anything missing from the psychological model of the user

---

## 1. MEMORY.md
```markdown
{memory}
```

## 2. CLAUDE.md (System Instructions)
```markdown
{claude_md}
```

## 3. Recent Dreamer Outputs
{dreamer}

## 4. Recent Conversation History
```
{history}
```

## 5. Extracted Failure Patterns
```
{failures}
```

## 6. Core Architecture (file structure + signatures)
{architecture}

## 7. Skills Inventory
{skills}

## 8. Security Surface
```
{security}
```

## 9. Dependencies
{dependencies}

## 10. Error Logs (recent)
```
{errors}
```

## 11. Resource Usage
```
{resources}
```"""


# --- Main ---
def analyze(brief: bool = False, deep: bool = False) -> str:
    """Run the full Susan Calvin analysis.

    If deep=True, include full source code of core files instead of just signatures.
    This uses significantly more tokens but enables real code review.
    """
    memory = load_memory()
    claude_md = load_claude_md()
    dreamer = load_dreamer(n=2)
    history = load_conversation_history(limit=50)
    failures = extract_failure_cases(memory)
    architecture = load_core_architecture(deep=deep)
    skills = load_skills_inventory()
    security = load_security_surface()
    dependencies = load_dependencies()
    errors = load_error_logs(n=50)
    resources = load_resource_usage()

    prompt = build_user_prompt(
        memory=memory, claude_md=claude_md, dreamer=dreamer, history=history,
        failures=failures, architecture=architecture, skills=skills,
        security=security, dependencies=dependencies, errors=errors,
        resources=resources, brief=brief,
    )

    # Check total size — GPT-4o handles ~128K tokens, be conservative
    total_chars = len(SYSTEM_PROMPT) + len(prompt)
    if total_chars > 200000:
        # Trim history and errors if too long
        history = load_conversation_history(limit=25)
        errors = load_error_logs(n=25)
        prompt = build_user_prompt(
            memory=memory, claude_md=claude_md, dreamer=dreamer, history=history,
            failures=failures, architecture=architecture, skills=skills,
            security=security, dependencies=dependencies, errors=errors,
            resources=resources, brief=brief,
        )

    result = ask(prompt, model="gpt-5.4", system=SYSTEM_PROMPT)
    return result


def main():
    parser = argparse.ArgumentParser(description="Susan Calvin — robopsychology for okami")
    sub = parser.add_subparsers(dest="command")

    analyze_cmd = sub.add_parser("analyze", help="Run full robopsychological evaluation")
    analyze_cmd.add_argument("--brief", action="store_true", help="Shorter, focused analysis")
    analyze_cmd.add_argument("--deep", action="store_true", help="Include full source code of core files (more tokens, real code review)")

    args = parser.parse_args()

    if args.command == "analyze":
        result = analyze(brief=args.brief, deep=args.deep)
        print(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
