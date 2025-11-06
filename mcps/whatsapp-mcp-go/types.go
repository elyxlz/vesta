package main

import (
	"time"
)

type Message struct {
	ID          string    `json:"id"`
	ChatJID     string    `json:"chat_jid"`
	ChatName    string    `json:"chat_name,omitempty"`
	Sender      string    `json:"sender"`
	Content     string    `json:"content"`
	Timestamp   time.Time `json:"timestamp"`
	IsFromMe    bool      `json:"is_from_me"`
	IsForwarded bool      `json:"is_forwarded"`
	MediaType   string    `json:"media_type,omitempty"`
	Filename    string    `json:"filename,omitempty"`
}

type Chat struct {
	JID             string    `json:"jid"`
	Name            string    `json:"name,omitempty"`
	LastMessageTime time.Time `json:"last_message_time,omitempty"`
	LastMessage     string    `json:"last_message,omitempty"`
	LastSender      string    `json:"last_sender,omitempty"`
	LastIsFromMe    bool      `json:"last_is_from_me,omitempty"`
	IsGroup         bool      `json:"is_group"`
}

type Contact struct {
	PhoneNumber string `json:"phone_number"`
	Name        string `json:"name,omitempty"`
	JID         string `json:"jid"`
}

type MessageContext struct {
	Message Message   `json:"message"`
	Before  []Message `json:"before"`
	After   []Message `json:"after"`
}

// Tool Input/Output types for MCP

type SearchContactsInput struct {
	Query string `json:"query" jsonschema:"Search query for contact name or phone number"`
}

type SearchContactsOutput struct {
	Contacts []Contact `json:"contacts"`
}

type ListMessagesInput struct {
	After          string `json:"after,omitempty" jsonschema:"ISO-8601 datetime to filter messages after"`
	Before         string `json:"before,omitempty" jsonschema:"ISO-8601 datetime to filter messages before"`
	SenderPhone    string `json:"sender_phone_number,omitempty" jsonschema:"Filter by sender phone number"`
	ChatJID        string `json:"chat_jid,omitempty" jsonschema:"Filter by chat JID"`
	Query          string `json:"query,omitempty" jsonschema:"Search query for message content"`
	Limit          int    `json:"limit,omitempty" jsonschema:"Maximum number of messages to return"`
	Page           int    `json:"page,omitempty" jsonschema:"Page number for pagination"`
	IncludeContext bool   `json:"include_context,omitempty" jsonschema:"Include surrounding messages for context"`
	ContextBefore  int    `json:"context_before,omitempty" jsonschema:"Number of messages before for context"`
	ContextAfter   int    `json:"context_after,omitempty" jsonschema:"Number of messages after for context"`
}

type ListMessagesOutput struct {
	Messages []Message `json:"messages"`
}

type ListChatsInput struct {
	Query              string `json:"query,omitempty" jsonschema:"Search query for chat name"`
	Limit              int    `json:"limit,omitempty" jsonschema:"Maximum number of chats to return"`
	Page               int    `json:"page,omitempty" jsonschema:"Page number for pagination"`
	IncludeLastMessage bool   `json:"include_last_message,omitempty" jsonschema:"Include last message in chat"`
	SortBy             string `json:"sort_by,omitempty" jsonschema:"Sort by 'last_active' or 'name'"`
}

type ListChatsOutput struct {
	Chats []Chat `json:"chats"`
}

type GetChatInput struct {
	ChatJID            string `json:"chat_jid" jsonschema:"Chat JID to retrieve"`
	IncludeLastMessage bool   `json:"include_last_message,omitempty" jsonschema:"Include last message in chat"`
}

type GetChatOutput struct {
	Chat Chat `json:"chat"`
}

type GetDirectChatInput struct {
	SenderPhoneNumber string `json:"sender_phone_number" jsonschema:"Phone number to find chat for"`
}

type GetDirectChatOutput struct {
	Chat Chat `json:"chat"`
}

type SendMessageInput struct {
	Recipient string `json:"recipient" jsonschema:"Phone number or group JID"`
	Message   string `json:"message" jsonschema:"Text message to send"`
}

type SendMessageOutput struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

type SendFileInput struct {
	Recipient string `json:"recipient" jsonschema:"Phone number or group JID"`
	FilePath  string `json:"file_path" jsonschema:"Path to file to send"`
	Caption   string `json:"caption,omitempty" jsonschema:"Optional caption for the file"`
}

type SendFileOutput struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

type DownloadMediaInput struct {
	MessageID    string `json:"message_id" jsonschema:"Message ID containing media"`
	DownloadPath string `json:"download_path,omitempty" jsonschema:"Optional path to save media"`
	JID          string `json:"jid,omitempty" jsonschema:"Chat JID"`
}

type DownloadMediaOutput struct {
	Success  bool   `json:"success"`
	FilePath string `json:"file_path,omitempty"`
	Message  string `json:"message"`
}

type SendReactionInput struct {
	MessageID string `json:"message_id" jsonschema:"Message ID to react to"`
	Emoji     string `json:"emoji" jsonschema:"Emoji reaction"`
	JID       string `json:"jid" jsonschema:"Chat JID"`
}

type SendReactionOutput struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

type CreateGroupInput struct {
	GroupName    string   `json:"group_name" jsonschema:"Name for the new group"`
	Participants []string `json:"participants" jsonschema:"List of phone numbers to add"`
}

type CreateGroupOutput struct {
	Success  bool   `json:"success"`
	GroupJID string `json:"group_jid,omitempty"`
	Message  string `json:"message"`
}

type LeaveGroupInput struct {
	GroupJID string `json:"group_jid" jsonschema:"Group JID to leave"`
}

type LeaveGroupOutput struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

type ListGroupsInput struct {
	Limit int `json:"limit,omitempty" jsonschema:"Maximum number of groups"`
	Page  int `json:"page,omitempty" jsonschema:"Page number"`
}

type ListGroupsOutput struct {
	Groups []Chat `json:"groups"`
}

type UpdateGroupParticipantsInput struct {
	GroupJID     string   `json:"group_jid" jsonschema:"Group JID"`
	Action       string   `json:"action" jsonschema:"Action to perform (add or remove)"`
	Participants []string `json:"participants" jsonschema:"List of phone numbers"`
}

type UpdateGroupParticipantsOutput struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

type GetContactInput struct {
	JID string `json:"jid" jsonschema:"Contact JID"`
}

type GetContactOutput struct {
	Contact Contact `json:"contact"`
}