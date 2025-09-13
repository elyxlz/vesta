import asyncio
import json
import shlex
import toml
from pathlib import Path
from claude_code_sdk import query, ClaudeCodeOptions
from claude_code_sdk.types import McpStdioServerConfig, HookMatcher


def load_mcp_config():
    settings_file = Path(".claude/settings.json")
    if not settings_file.exists():
        return {}

    settings = json.loads(settings_file.read_text())
    return {
        name: McpStdioServerConfig(
            command=config["command"], args=config.get("args", [])
        )
        for name, config in settings.get("mcpServers", {}).items()
    }


async def run_hook(cmd, data):
    proc = await asyncio.create_subprocess_exec(
        *shlex.split(cmd), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate(json.dumps(data).encode())
    return json.loads(stdout) if proc.returncode == 0 and stdout else {}


def load_hooks():
    hooks_file = Path(".claude/hooks.toml")
    if not hooks_file.exists():
        return {}

    hooks = {}
    for hook in toml.loads(hooks_file.read_text()).get("hooks", []):
        event = hook["event"]
        cmd = hook["command"]

        async def wrapper(data, tool_use_id, context, cmd=cmd):
            return await run_hook(cmd, data)

        matcher = HookMatcher(matcher=hook.get("matcher", "any"), hooks=[wrapper])
        hooks.setdefault(event, []).append(matcher)

    return hooks


async def run_vesta():
    memory = Path("CLAUDE.md").read_text() if Path("CLAUDE.md").exists() else ""

    notifications = []
    if Path("notifications").exists():
        for f in sorted(Path("notifications").glob("*.json")):
            notifications.append(json.loads(f.read_text()))
            f.unlink()

    prompt = (
        "New notifications:\n"
        + "\n".join(
            [
                f"{n['source']}: {n['data'].get('message', n['data'].get('content', json.dumps(n['data'])))}"
                for n in notifications
            ]
        )
        if notifications
        else "Check for pending tasks."
    )

    options = ClaudeCodeOptions(
        system_prompt=memory, mcp_servers=load_mcp_config(), hooks=load_hooks()
    )

    async for msg in query(prompt=prompt, options=options):
        print(msg)


def main():
    asyncio.run(run_vesta())


def run():
    main()
