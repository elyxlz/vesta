from typing import List, Dict, Any, Optional
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
    send_reaction as whatsapp_send_reaction,
    create_group as whatsapp_create_group,
    leave_group as whatsapp_leave_group,
    list_groups as whatsapp_list_groups,
    get_group_invite_link as whatsapp_get_group_invite_link,
    update_group_participants as whatsapp_update_group_participants,
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
    """Get most recent WhatsApp message involving the contact."""
    return whatsapp_get_last_interaction(jid)


@mcp.tool()
def get_message_context(
    message_id: str, before: int = 5, after: int = 5
) -> Dict[str, Any]:
    """Get context around a specific WhatsApp message."""
    return whatsapp_get_message_context(message_id, before, after)


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
    if not recipient:
        return {"success": False, "message": "Recipient must be provided"}
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
def send_reaction(chat_jid: str, message_id: str, emoji: str, sender_jid: str | None = None) -> dict[str, Any]:
    try:
        success, message = whatsapp_send_reaction(chat_jid, message_id, emoji, sender_jid)
        return {"success": success, "message": message}
    except Exception as e:
        return {"success": False, "message": str(e)}




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
    return {"success": False, "message": "Failed to download media"}


@mcp.tool()
def transcribe_audio(file_path: str) -> str:
    """Transcribe audio file to text (supports 99 languages including Italian)."""
    from transcribe import transcribe
    return transcribe(file_path)


@mcp.tool()
def create_group(name: str, participants: List[str]) -> Dict[str, Any]:
    """Create a WhatsApp group with specified participants (phone numbers without country code symbols)."""
    success, group_jid, message = whatsapp_create_group(name, participants)
    return {"success": success, "group_jid": group_jid, "message": message}


@mcp.tool()
def leave_group(group_jid: str) -> Dict[str, Any]:
    """Leave a WhatsApp group by its JID."""
    success, message = whatsapp_leave_group(group_jid)
    return {"success": success, "message": message}


@mcp.tool()
def list_groups() -> List[Dict[str, str]]:
    """List all joined WhatsApp groups."""
    return whatsapp_list_groups()


@mcp.tool()
def add_group_participants(group_jid: str, participants: List[str]) -> Dict[str, Any]:
    """Add participants to a WhatsApp group."""
    success, message = whatsapp_update_group_participants(group_jid, participants, "add")
    return {"success": success, "message": message}


@mcp.tool()
def remove_group_participants(group_jid: str, participants: List[str]) -> Dict[str, Any]:
    """Remove participants from a WhatsApp group."""
    success, message = whatsapp_update_group_participants(group_jid, participants, "remove")
    return {"success": success, "message": message}


@mcp.tool()
def get_group_invite_link(group_jid: str) -> Dict[str, Any]:
    """Get an invite link for a WhatsApp group. Useful when adding participants directly fails."""
    success, link = whatsapp_get_group_invite_link(group_jid)
    if success:
        return {"success": True, "link": link}
    return {"success": False, "message": link}


@mcp.tool()
def promote_group_participants(group_jid: str, participants: List[str]) -> Dict[str, Any]:
    """Promote participants to admin in a WhatsApp group."""
    success, message = whatsapp_update_group_participants(group_jid, participants, "promote")
    return {"success": success, "message": message}


@mcp.tool()
def demote_group_participants(group_jid: str, participants: List[str]) -> Dict[str, Any]:
    """Demote admins to regular participants in a WhatsApp group."""
    success, message = whatsapp_update_group_participants(group_jid, participants, "demote")
    return {"success": success, "message": message}


if __name__ == "__main__":
    mcp.run(transport="stdio")