#!/usr/bin/env python3
"""Test the microsoft-mcp list_events tool directly (simulating MCP call)"""

import sys
from pathlib import Path
from dataclasses import dataclass
import httpx
import logging
import threading

sys.path.insert(0, str(Path(__file__).parent / "mcps" / "microsoft-mcp" / "src"))

from microsoft_mcp.settings import MicrosoftSettings
from microsoft_mcp.context import MicrosoftContext
from microsoft_mcp.calendar_tools import list_events


# Create a mock Context object
@dataclass
class MockRequestContext:
    lifespan_context: MicrosoftContext


@dataclass
class MockContext:
    request_context: MockRequestContext


def test_mcp_list_events():
    """Test list_events as if called through MCP"""

    # Setup paths
    data_dir = Path("/home/elyx/vesta/data/microsoft-mcp")
    log_dir = Path("/home/elyx/vesta/.vesta/logs")
    notif_dir = data_dir / "notifications"

    # Setup logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("microsoft_mcp")

    # Create context (simulating what happens in microsoft-mcp lifespan)
    settings = MicrosoftSettings()

    context = MicrosoftContext(
        cache_file=data_dir / "auth_cache.bin",
        http_client=httpx.Client(timeout=30.0, follow_redirects=True),
        log_dir=log_dir,
        notif_dir=notif_dir,
        monitor_base_dir=data_dir / "monitor",
        monitor_state_file=data_dir / "monitor" / "state.json",
        monitor_log_file=data_dir / "monitor.log",
        monitor_logger=logger,
        monitor_stop_event=threading.Event(),
        scopes=["https://graph.microsoft.com/.default"],
        base_url="https://graph.microsoft.com/v1.0",
        upload_chunk_size=320 * 1024,
        folders={
            "inbox": "Inbox",
            "sent": "SentItems",
            "drafts": "Drafts",
            "deleted": "DeletedItems",
            "junk": "JunkEmail",
            "archive": "Archive",
        },
        settings=settings,
    )

    # Create mock MCP context
    mock_ctx = MockContext(request_context=MockRequestContext(lifespan_context=context))

    print("=" * 60)
    print("Testing list_events for elio@pascarelli.com")
    print("=" * 60)

    try:
        events = list_events(mock_ctx, account_email="elio@pascarelli.com", days_ahead=7, days_back=0, include_details=False)
        print(f"\n✅ SUCCESS: Got {len(events)} events")
        for i, event in enumerate(events[:5], 1):
            print(f"  {i}. {event.get('subject', 'No subject')}")
        if len(events) > 5:
            print(f"  ... and {len(events) - 5} more")
    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 60)
    print("Testing list_events for elio@audiogen.co")
    print("=" * 60)

    try:
        events = list_events(mock_ctx, account_email="elio@audiogen.co", days_ahead=7, days_back=0, include_details=False)
        print(f"\n✅ SUCCESS: Got {len(events)} events")
        for i, event in enumerate(events, 1):
            print(f"  {i}. {event.get('subject', 'No subject')}")
    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()

    # Cleanup
    context.http_client.close()


if __name__ == "__main__":
    test_mcp_list_events()
