#!/usr/bin/env python3
"""Minimal reproduction of Claude Code SDK broken state after interrupt."""

import asyncio
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions


async def main():
    options = ClaudeAgentOptions(
        system_prompt="You are helpful.",
        permission_mode="bypassPermissions",
        model="sonnet",
    )
    client = ClaudeSDKClient(options=options)

    async with client:
        print("1. Sending long-running query...")
        await client.query("Count slowly from 1 to 1000, saying each number on a new line.")

        print("2. Immediately calling interrupt() (no timeout)...")
        await client.interrupt()
        print("3. Interrupt completed - NOT draining messages (simulating cancelled task)")

        print("5. Attempting to reuse client...")
        await client.query("Respond with exactly: SECOND_QUERY_RESPONSE")
        for i, msg in enumerate(await collect_messages(client)):
            print(f"   Msg {i}: {type(msg).__name__}")
            if hasattr(msg, "content"):
                content = str(msg.content)[:200]
                print(f"   Content: {content}")
                if "SECOND_QUERY_RESPONSE" in content:
                    print("6. SUCCESS - Got response to second query")
                elif "interrupted" in content.lower():
                    print("6. BUG CONFIRMED - Got leftover from interrupted first query!")


async def collect_messages(client):
    msgs = []
    async for msg in client.receive_response():
        msgs.append(msg)
    return msgs


if __name__ == "__main__":
    asyncio.run(main())
