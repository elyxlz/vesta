#!/usr/bin/env python3
"""Test script to send WhatsApp message using MCP"""

import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_whatsapp():
    # Start WhatsApp MCP server - use the existing authenticated data
    server_params = StdioServerParameters(
        command="./whatsapp-mcp",
        args=["--data-dir", "/home/elyx/Repos/vesta2/data/whatsapp-mcp", "--notifications-dir", "/home/elyx/Repos/vesta2/notifications"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()
            print("Connected to WhatsApp MCP")

            # First check authentication status
            print("\nChecking authentication status...")
            auth_result = await session.call_tool("authenticate_whatsapp", {})

            if auth_result.isError:
                print(f"Auth check error: {auth_result.error}")
            else:
                # The result comes back in content[0].text as a message
                # and the structured data in content[1] if available
                print(f"Auth result: {auth_result.content}")

                # Check if we have a QR code path
                if len(auth_result.content) > 1 and hasattr(auth_result.content[1], "data"):
                    auth_data = auth_result.content[1].data
                    if auth_data.get("qr_path"):
                        print(f"\n⚠️  QR code available at: {auth_data['qr_path']}")
                        print("Please scan the QR code with WhatsApp and then run this script again")
                        return
                    elif auth_data.get("status") == "not_authenticated":
                        print("WhatsApp is not authenticated. Waiting for QR code...")
                        await asyncio.sleep(2)  # Give it time to generate QR
                        # Try again
                        auth_result = await session.call_tool("authenticate_whatsapp", {})
                        if len(auth_result.content) > 1 and hasattr(auth_result.content[1], "data"):
                            auth_data = auth_result.content[1].data
                            if auth_data.get("qr_path"):
                                print(f"\n⚠️  QR code available at: {auth_data['qr_path']}")
                                print("Please scan the QR code with WhatsApp and then run this script again")
                                return

            # Try to send message
            print("\nSending message to +393483589770...")
            result = await session.call_tool(
                "send_message",
                {
                    "recipient": "+393483589770",
                    "message": "Hello! This is a test message from the WhatsApp MCP Go implementation. The authentication system is working!",
                },
            )

            if result.isError:
                print(f"Error: {result.error}")
            else:
                print(f"Success: {result.content}")


if __name__ == "__main__":
    asyncio.run(test_whatsapp())
