import subprocess
import os
import sys
import atexit
import threading
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from whatsapp import (
    search_contacts as whatsapp_search_contacts,
    list_messages as whatsapp_list_messages,
    list_chats as whatsapp_list_chats,
    get_chat as whatsapp_get_chat,
    get_direct_chat_by_contact as whatsapp_get_direct_chat_by_contact,
    get_contact_chats as whatsapp_get_contact_chats,
    get_last_interaction as whatsapp_get_last_interaction,
    get_message_context as whatsapp_get_message_context,
    send_message as whatsapp_send_message,
    send_file as whatsapp_send_file,
    send_audio_message as whatsapp_audio_voice_message,
    download_media as whatsapp_download_media,
)

# Initialize FastMCP server
mcp = FastMCP("whatsapp")

# Global variables to track the bridge process and monitor thread
bridge_process = None
monitor_thread = None
shutdown_flag = False

def tail_log_file(log_path, lines=10):
    """Tail a log file and print recent lines to stderr"""
    try:
        if log_path.exists():
            with open(log_path, 'r') as f:
                content = f.readlines()
                for line in content[-lines:]:
                    print(f"[LOG] {line.rstrip()}", file=sys.stderr)
    except Exception:
        pass  # Silently ignore errors in tailing

def start_whatsapp_bridge():
    """Start the WhatsApp bridge if it's not already running"""
    global bridge_process

    # Check if bridge is already running
    if bridge_process and bridge_process.poll() is None:
        return

    # Find the bridge directory
    bridge_dir = Path(__file__).parent.parent / "whatsapp-bridge"
    bridge_exe = bridge_dir / "whatsapp-bridge"

    if not bridge_exe.exists():
        # Try to build the bridge
        print("Building WhatsApp bridge...", file=sys.stderr)
        build_result = subprocess.run(
            ["go", "build", "-o", "whatsapp-bridge", "."],
            cwd=bridge_dir,
            capture_output=True,
            text=True
        )
        if build_result.returncode != 0:
            print(f"Failed to build WhatsApp bridge: {build_result.stderr}", file=sys.stderr)
            return False

    # Create logs directory
    logs_dir = Path(__file__).parent.parent.parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Open log files
    stdout_log = open(logs_dir / "whatsapp-bridge-stdout.log", "a")
    stderr_log = open(logs_dir / "whatsapp-bridge-stderr.log", "a")

    # Write timestamp
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    stdout_log.write(f"\n=== WhatsApp Bridge Started at {timestamp} ===\n")
    stdout_log.flush()
    stderr_log.write(f"\n=== WhatsApp Bridge Started at {timestamp} ===\n")
    stderr_log.flush()

    # Get notifications directory from environment or use default
    notifications_dir = os.environ.get("NOTIFICATIONS_DIR")
    if not notifications_dir:
        # Use the same directory structure as logs
        notifications_dir = str(Path(__file__).parent.parent.parent.parent / "notifications")

    # Start the bridge
    print("Starting WhatsApp bridge...", file=sys.stderr)
    print(f"Logs will be saved to {logs_dir}", file=sys.stderr)
    print(f"Notifications will be saved to {notifications_dir}", file=sys.stderr)

    try:
        bridge_env = os.environ.copy()
        bridge_env["PYTHONUNBUFFERED"] = "1"
        bridge_env["NOTIFICATIONS_DIR"] = notifications_dir

        bridge_process = subprocess.Popen(
            [str(bridge_exe)],
            cwd=bridge_dir,
            stdout=stdout_log,
            stderr=stderr_log,
            env=bridge_env
        )
        print("WhatsApp bridge started successfully", file=sys.stderr)

        # Also log to stderr for real-time monitoring
        threading.Thread(target=lambda: tail_log_file(logs_dir / "whatsapp-bridge-stdout.log"), daemon=True).start()

        return True
    except Exception as e:
        print(f"Failed to start WhatsApp bridge: {e}", file=sys.stderr)
        stdout_log.close()
        stderr_log.close()
        return False

def stop_whatsapp_bridge():
    """Stop the WhatsApp bridge if it's running"""
    global bridge_process, shutdown_flag
    shutdown_flag = True
    if bridge_process and bridge_process.poll() is None:
        print("Stopping WhatsApp bridge...", file=sys.stderr)
        bridge_process.terminate()
        try:
            bridge_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bridge_process.kill()
        bridge_process = None

def monitor_bridge():
    """Monitor the bridge process and restart it if it crashes"""
    global bridge_process, shutdown_flag
    while not shutdown_flag:
        if bridge_process is None or bridge_process.poll() is not None:
            if not shutdown_flag:
                print("WhatsApp bridge not running, restarting...", file=sys.stderr)
                start_whatsapp_bridge()
        time.sleep(5)  # Check every 5 seconds

def start_bridge_monitor():
    """Start the bridge monitor thread"""
    global monitor_thread
    if monitor_thread is None or not monitor_thread.is_alive():
        monitor_thread = threading.Thread(target=monitor_bridge, daemon=True)
        monitor_thread.start()
        print("WhatsApp bridge monitor started", file=sys.stderr)

# DON'T start the bridge here - Vesta's main.py handles it
# Having multiple bridges causes WebSocket disconnection issues
# start_whatsapp_bridge()
# start_bridge_monitor()
# atexit.register(stop_whatsapp_bridge)


@mcp.tool()
def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number.

    Args:
        query: Search term to match against contact names or phone numbers
    """
    contacts = whatsapp_search_contacts(query)
    return contacts


@mcp.tool()
def list_messages(
    after: Optional[str] = None,
    before: Optional[str] = None,
    sender_phone_number: Optional[str] = None,
    chat_jid: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_context: bool = True,
    context_before: int = 1,
    context_after: int = 1,
) -> List[Dict[str, Any]]:
    """Get WhatsApp messages matching specified criteria with optional context.

    Args:
        after: Optional ISO-8601 formatted string to only return messages after this date
        before: Optional ISO-8601 formatted string to only return messages before this date
        sender_phone_number: Optional phone number to filter messages by sender
        chat_jid: Optional chat JID to filter messages by chat
        query: Optional search term to filter messages by content
        limit: Maximum number of messages to return (default 20)
        page: Page number for pagination (default 0)
        include_context: Whether to include messages before and after matches (default True)
        context_before: Number of messages to include before each match (default 1)
        context_after: Number of messages to include after each match (default 1)
    """
    messages = whatsapp_list_messages(
        after=after,
        before=before,
        sender_phone_number=sender_phone_number,
        chat_jid=chat_jid,
        query=query,
        limit=limit,
        page=page,
        include_context=include_context,
        context_before=context_before,
        context_after=context_after,
    )
    return messages


@mcp.tool()
def list_chats(
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active",
) -> List[Dict[str, Any]]:
    """Get WhatsApp chats matching specified criteria.

    Args:
        query: Optional search term to filter chats by name or JID
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
        include_last_message: Whether to include the last message in each chat (default True)
        sort_by: Field to sort results by, either "last_active" or "name" (default "last_active")
    """
    chats = whatsapp_list_chats(
        query=query,
        limit=limit,
        page=page,
        include_last_message=include_last_message,
        sort_by=sort_by,
    )
    return chats


@mcp.tool()
def get_chat(chat_jid: str, include_last_message: bool = True) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by JID.

    Args:
        chat_jid: The JID of the chat to retrieve
        include_last_message: Whether to include the last message (default True)
    """
    chat = whatsapp_get_chat(chat_jid, include_last_message)
    return chat


@mcp.tool()
def get_direct_chat_by_contact(sender_phone_number: str) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by sender phone number.

    Args:
        sender_phone_number: The phone number to search for
    """
    chat = whatsapp_get_direct_chat_by_contact(sender_phone_number)
    return chat


@mcp.tool()
def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Dict[str, Any]]:
    """Get all WhatsApp chats involving the contact.

    Args:
        jid: The contact's JID to search for
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
    """
    chats = whatsapp_get_contact_chats(jid, limit, page)
    return chats


@mcp.tool()
def get_last_interaction(jid: str) -> str:
    """Get most recent WhatsApp message involving the contact.

    Args:
        jid: The JID of the contact to search for
    """
    message = whatsapp_get_last_interaction(jid)
    return message


@mcp.tool()
def get_message_context(
    message_id: str, before: int = 5, after: int = 5
) -> Dict[str, Any]:
    """Get context around a specific WhatsApp message.

    Args:
        message_id: The ID of the message to get context for
        before: Number of messages to include before the target message (default 5)
        after: Number of messages to include after the target message (default 5)
    """
    context = whatsapp_get_message_context(message_id, before, after)
    return context


@mcp.tool()
def send_message(recipient: str, message: str) -> Dict[str, Any]:
    """Send a WhatsApp message to a person or group. For group chats use the JID.

    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        message: The message text to send

    Returns:
        A dictionary containing success status and a status message
    """
    # Validate input
    if not recipient:
        return {"success": False, "message": "Recipient must be provided"}

    # Call the whatsapp_send_message function with the unified recipient parameter
    success, status_message = whatsapp_send_message(recipient, message)
    return {"success": success, "message": status_message}


@mcp.tool()
def send_file(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send a file such as a picture, raw audio, video or document via WhatsApp to the specified recipient. For group messages use the JID.

    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        media_path: The absolute path to the media file to send (image, video, document)

    Returns:
        A dictionary containing success status and a status message
    """

    # Call the whatsapp_send_file function
    success, status_message = whatsapp_send_file(recipient, media_path)
    return {"success": success, "message": status_message}


@mcp.tool()
def send_audio_message(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send any audio file as a WhatsApp audio message to the specified recipient. For group messages use the JID. If it errors due to ffmpeg not being installed, use send_file instead.

    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        media_path: The absolute path to the audio file to send (will be converted to Opus .ogg if it's not a .ogg file)

    Returns:
        A dictionary containing success status and a status message
    """
    success, status_message = whatsapp_audio_voice_message(recipient, media_path)
    return {"success": success, "message": status_message}


@mcp.tool()
def download_media(message_id: str, chat_jid: str) -> Dict[str, Any]:
    """Download media from a WhatsApp message and get the local file path.

    Args:
        message_id: The ID of the message containing the media
        chat_jid: The JID of the chat containing the message

    Returns:
        A dictionary containing success status, a status message, and the file path if successful
    """
    file_path = whatsapp_download_media(message_id, chat_jid)

    if file_path:
        return {
            "success": True,
            "message": "Media downloaded successfully",
            "file_path": file_path,
        }
    else:
        return {"success": False, "message": "Failed to download media"}


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport="stdio")
