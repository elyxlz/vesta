"""Authentication-related tools for Microsoft MCP"""

import argparse
import httpx
import logging
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dotenv import load_dotenv, find_dotenv
from mcp.server.fastmcp import FastMCP, Context
from . import auth, monitor
from .context import MicrosoftContext


@asynccontextmanager
async def microsoft_lifespan(server: FastMCP) -> AsyncIterator[MicrosoftContext]:
    """Manage Microsoft MCP lifecycle"""
    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--notifications-dir", type=str, required=True)
    args, _ = parser.parse_known_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    notif_dir = Path(args.notifications_dir).resolve()
    notif_dir.mkdir(parents=True, exist_ok=True)

    cache_file = data_dir / "auth_cache.bin"
    http_client = httpx.Client(timeout=30.0, follow_redirects=True)

    # Setup monitor
    monitor_base_dir = data_dir / "monitor"
    monitor_base_dir.mkdir(parents=True, exist_ok=True)
    monitor_state_file = monitor_base_dir / "state.txt"
    monitor_log_file = monitor_base_dir / "monitor.log"

    monitor_logger = logging.getLogger("microsoft_mcp.monitor")
    monitor_logger.setLevel(logging.INFO)
    if not monitor_logger.handlers:
        file_handler = logging.FileHandler(monitor_log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        monitor_logger.addHandler(file_handler)

    monitor_stop_event = threading.Event()

    # Initialize constants
    scopes = ["https://graph.microsoft.com/.default"]
    base_url = "https://graph.microsoft.com/v1.0"
    upload_chunk_size = 15 * 320 * 1024
    folders = {
        k.casefold(): v
        for k, v in {
            "inbox": "inbox",
            "sent": "sentitems",
            "drafts": "drafts",
            "deleted": "deleteditems",
            "junk": "junkemail",
            "archive": "archive",
        }.items()
    }

    ctx = MicrosoftContext(
        cache_file=cache_file,
        http_client=http_client,
        notif_dir=notif_dir,
        monitor_base_dir=monitor_base_dir,
        monitor_state_file=monitor_state_file,
        monitor_log_file=monitor_log_file,
        monitor_logger=monitor_logger,
        monitor_stop_event=monitor_stop_event,
        scopes=scopes,
        base_url=base_url,
        upload_chunk_size=upload_chunk_size,
        folders=folders,
    )

    # Start monitor thread
    monitor_thread = threading.Thread(target=monitor.run, args=(ctx,), daemon=True)
    monitor_thread.start()

    try:
        yield ctx
    finally:
        monitor_stop_event.set()
        monitor_thread.join(timeout=5)
        http_client.close()


mcp = FastMCP("microsoft-mcp", lifespan=microsoft_lifespan)


@mcp.tool()
def list_accounts(ctx: Context) -> list[dict[str, str]]:
    context: MicrosoftContext = ctx.request_context.lifespan_context
    return [{"username": acc.username, "account_id": acc.account_id} for acc in auth.list_accounts(context.cache_file)]


@mcp.tool()
def authenticate_account(ctx: Context) -> dict[str, str]:
    context: MicrosoftContext = ctx.request_context.lifespan_context
    app = auth.get_app(context.cache_file)
    flow = app.initiate_device_flow(scopes=context.scopes)

    if "user_code" not in flow:
        error_msg = flow.get("error_description", "Unknown error")
        raise Exception(f"Failed to get device code: {error_msg}")

    verification_url = flow.get(
        "verification_uri",
        flow.get("verification_url", "https://microsoft.com/devicelogin"),
    )

    return {
        "status": "authentication_required",
        "instructions": "To authenticate a new Microsoft account:",
        "step1": f"Visit: {verification_url}",
        "step2": f"Enter code: {flow['user_code']}",
        "step3": "Sign in with the Microsoft account you want to add",
        "step4": "After authenticating, use the 'complete_authentication' tool to finish the process",
        "device_code": flow["user_code"],
        "verification_url": verification_url,
        "expires_in": flow.get("expires_in", 900),
        "_flow_cache": str(flow),
    }


@mcp.tool()
def complete_authentication(ctx: Context, flow_cache: str) -> dict[str, str]:
    """flow_cache: use _flow_cache value from authenticate_account response"""
    import ast

    context: MicrosoftContext = ctx.request_context.lifespan_context

    try:
        flow = ast.literal_eval(flow_cache)
    except (ValueError, SyntaxError):
        raise ValueError("Invalid flow cache data")

    app = auth.get_app(context.cache_file)
    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        error_msg = result.get("error_description", result["error"])
        if "authorization_pending" in error_msg:
            return {
                "status": "pending",
                "message": "Authentication is still pending. The user needs to complete the authentication process.",
                "instructions": "Please ensure you've visited the URL and entered the code, then try again.",
            }
        raise Exception(f"Authentication failed: {error_msg}")

    # Save the token cache
    cache = app.token_cache
    if isinstance(cache, auth.msal.SerializableTokenCache) and cache.has_state_changed:
        auth._write_cache(context.cache_file, cache.serialize())

    # Get the newly added account
    accounts = app.get_accounts()
    if accounts:
        # Find the account that matches the token we just got
        for account in accounts:
            if account.get("username", "").lower() == result.get("id_token_claims", {}).get("preferred_username", "").lower():
                return {
                    "status": "success",
                    "username": account["username"],
                    "account_id": account["home_account_id"],
                    "message": f"Successfully authenticated {account['username']}",
                }
        # If exact match not found, return the last account
        account = accounts[-1]
        return {
            "status": "success",
            "username": account["username"],
            "account_id": account["home_account_id"],
            "message": f"Successfully authenticated {account['username']}",
        }

    return {
        "status": "error",
        "message": "Authentication succeeded but no account was found",
    }
