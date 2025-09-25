#!/usr/bin/env python3
"""Quick test to send WhatsApp message"""

import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def send_message():
    server_params = StdioServerParameters(
        command="./whatsapp-mcp",
        args=["--data-dir", "/home/elyx/Repos/vesta2/data/whatsapp-mcp", "--notifications-dir", "/home/elyx/Repos/vesta2/notifications"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected to WhatsApp MCP")

            # Wait longer for WhatsApp to connect
            print("Waiting for WhatsApp to connect...")
            await asyncio.sleep(8)

            # Send message directly
            print("Sending message...")
            result = await session.call_tool(
                "send_message",
                {
                    "recipient": "+393483589770",
                    "message": "Hello! This is a test message from the WhatsApp MCP Go implementation. The conversion to Go is complete and working!",
                },
            )

            if result.isError:
                print(f"Error: {result.error}")
            else:
                print(f"Result: {result.content[0].text if result.content else 'No content'}")


if __name__ == "__main__":
    # Run with longer timeout
    try:
        asyncio.run(asyncio.wait_for(send_message(), timeout=25))
    except asyncio.TimeoutError:
        print("\nTimeout after 25 seconds")
    except Exception as e:
        print(f"\nError: {e}")
