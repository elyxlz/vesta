import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
import whatsapp
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
    send_reaction as whatsapp_send_reaction,
    create_group as whatsapp_create_group,
    leave_group as whatsapp_leave_group,
    list_groups as whatsapp_list_groups,
    get_group_invite_link as whatsapp_get_group_invite_link,
    update_group_participants as whatsapp_update_group_participants,
    update_contact as whatsapp_update_contact,
    get_contact as whatsapp_get_contact,
)

mcp = FastMCP("whatsapp")


@mcp.tool()
def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number."""
    return whatsapp_search_contacts(query)


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
    """Get WhatsApp messages with filters. Dates in ISO-8601 format. Include context shows surrounding messages."""
    return whatsapp_list_messages(
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


@mcp.tool()
def list_chats(
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active",
) -> List[Dict[str, Any]]:
    """Get WhatsApp chats sorted by 'last_active' or 'name'."""
    return whatsapp_list_chats(
        query=query,
        limit=limit,
        page=page,
        include_last_message=include_last_message,
        sort_by=sort_by,
    )


@mcp.tool()
def get_chat(chat_jid: str, include_last_message: bool = True) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by JID."""
    return whatsapp_get_chat(chat_jid, include_last_message)


@mcp.tool()
def get_direct_chat_by_contact(sender_phone_number: str) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by phone number."""
    return whatsapp_get_direct_chat_by_contact(sender_phone_number)


@mcp.tool()
def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Dict[str, Any]]:
    """Get all WhatsApp chats involving the contact."""
    return whatsapp_get_contact_chats(jid, limit, page)


@mcp.tool()
def get_last_interaction(jid: str) -> str:
    """Get formatted string of last interaction with contact."""
    return whatsapp_get_last_interaction(jid)


@mcp.tool()
def get_message_context(
    jid: str, message_id: str, context_before: int = 3, context_after: int = 3
) -> List[Dict[str, Any]]:
    """Get messages around a specific message for context."""
    return whatsapp_get_message_context(jid, message_id, context_before, context_after)


@mcp.tool()
def send_message(recipient: str, message: str) -> Dict[str, Any]:
    """Send text message to WhatsApp contact or group."""
    return whatsapp_send_message(recipient, message)


@mcp.tool()
def send_file(
    recipient: str, file_path: str, caption: Optional[str] = None
) -> Dict[str, Any]:
    """Send file to WhatsApp contact or group."""
    return whatsapp_send_file(recipient, file_path, caption)


@mcp.tool()
def send_audio_message(recipient: str, file_path: str) -> Dict[str, Any]:
    """Send audio file as voice message to WhatsApp."""
    return whatsapp_audio_voice_message(recipient, file_path)


@mcp.tool()
def download_media(
    message_id: str, download_path: Optional[str] = None, jid: Optional[str] = None
) -> Dict[str, Any]:
    """Download media from WhatsApp message."""
    return whatsapp_download_media(message_id, download_path, jid)


@mcp.tool()
def send_reaction(message_id: str, emoji: str, jid: str) -> Dict[str, Any]:
    """Send emoji reaction to WhatsApp message."""
    return whatsapp_send_reaction(message_id, emoji, jid)


@mcp.tool()
def create_group(group_name: str, participants: List[str]) -> Dict[str, Any]:
    """Create WhatsApp group with participants."""
    return whatsapp_create_group(group_name, participants)


@mcp.tool()
def leave_group(group_jid: str) -> Dict[str, Any]:
    """Leave WhatsApp group."""
    return whatsapp_leave_group(group_jid)


@mcp.tool()
def list_groups(limit: int = 50, page: int = 0) -> List[Dict[str, Any]]:
    """List WhatsApp groups."""
    return whatsapp_list_groups(limit, page)


@mcp.tool()
def get_group_invite_link(group_jid: str) -> Dict[str, Any]:
    """Get invite link for WhatsApp group."""
    return whatsapp_get_group_invite_link(group_jid)


@mcp.tool()
def update_group_participants(
    group_jid: str, action: str, participants: List[str]
) -> Dict[str, Any]:
    """Add or remove participants from WhatsApp group. Action can be 'add' or 'remove'."""
    return whatsapp_update_group_participants(group_jid, action, participants)


@mcp.tool()
def update_contact(jid: str, name: str) -> Dict[str, Any]:
    """Update contact name in WhatsApp."""
    return whatsapp_update_contact(jid, name)


@mcp.tool()
def get_contact(jid: str) -> Dict[str, Any]:
    """Get contact information by JID."""
    return whatsapp_get_contact(jid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WhatsApp MCP Server")
    parser.add_argument(
        "--data-dir",
        type=str,
        required=True,
        help="Directory for storing persistent data (database copies)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    whatsapp.MESSAGES_DB_PATH = str(data_dir / "messages.db")
    print(f"WhatsApp MCP using data directory: {data_dir}")

    mcp.run()
