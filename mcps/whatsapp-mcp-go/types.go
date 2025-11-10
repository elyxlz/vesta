package main

import (
	"time"
)

type Message struct {
	ID          string    `json:"id"`
	ChatJID     string    `json:"-"`
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
	JID             string    `json:"-"`
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
	JID         string `json:"-"`
	IsManual    bool   `json:"is_manual,omitempty"`
}

type MessageContext struct {
	Message Message   `json:"message"`
	Before  []Message `json:"before"`
	After   []Message `json:"after"`
}

type MediaInfo struct {
	MessageID     string
	ChatJID       string
	MediaType     string
	Filename      string
	URL           string
	MediaKey      []byte
	FileSHA256    []byte
	FileEncSHA256 []byte
	FileLength    uint64
}

// Tool Input/Output types for MCP

type SearchContactsInput struct {
	Query string `json:"query" jsonschema:"Search query for contact name or phone number"`
	Limit int    `json:"limit,omitempty" jsonschema:"Maximum number of contacts to return (default 50)"`
}

type SearchContactsOutput struct {
	Contacts []Contact `json:"contacts"`
}

type ListContactsInput struct {
	Query string `json:"query,omitempty" jsonschema:"Optional search query for contact name or phone number"`
	Limit int    `json:"limit,omitempty" jsonschema:"Maximum number of contacts to return (default 50)"`
}

type ListContactsOutput struct {
	Contacts []Contact `json:"contacts"`
}

type AddContactInput struct {
	Name        string `json:"name" jsonschema:"Display name for the contact"`
	PhoneNumber string `json:"phone_number" jsonschema:"Phone number in E.164 format (+1234567890)"`
}

type AddContactOutput struct {
	Contact Contact `json:"contact"`
}

type ListMessagesInput struct {
	After          string `json:"after,omitempty" jsonschema:"ISO-8601 datetime to filter messages after"`
	Before         string `json:"before,omitempty" jsonschema:"ISO-8601 datetime to filter messages before"`
	SenderPhone    string `json:"sender_phone_number,omitempty" jsonschema:"Filter by sender phone number"`
	To             string `json:"to,omitempty" jsonschema:"Filter by chat - accepts contact name, phone number, or group name"`
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

type SendMessageInput struct {
	To      string `json:"to" jsonschema:"Recipient - accepts contact name, phone number (+1234567890), or group name"`
	Message string `json:"message" jsonschema:"Text message to send"`
}

type SendMessageOutput struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

type SendFileInput struct {
	To       string `json:"to" jsonschema:"Recipient - accepts contact name, phone number (+1234567890), or group name"`
	FilePath string `json:"file_path" jsonschema:"Path to file to send"`
	Caption  string `json:"caption,omitempty" jsonschema:"Optional caption for the file"`
}

type SendFileOutput struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

type DownloadMediaInput struct {
	MessageID    string `json:"message_id" jsonschema:"Message ID containing media"`
	DownloadPath string `json:"download_path,omitempty" jsonschema:"Optional path to save media"`
	To           string `json:"to,omitempty" jsonschema:"Chat - accepts contact name, phone number, or group name"`
}

type DownloadMediaOutput struct {
	Success  bool   `json:"success"`
	FilePath string `json:"file_path,omitempty"`
	Message  string `json:"message"`
}

type SendReactionInput struct {
	MessageID string `json:"message_id" jsonschema:"Message ID to react to"`
	Emoji     string `json:"emoji" jsonschema:"Emoji reaction"`
	To        string `json:"to" jsonschema:"Chat - accepts contact name, phone number, or group name"`
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
	Success   bool   `json:"success"`
	GroupName string `json:"group_name"`
	Message   string `json:"message"`
}

type LeaveGroupInput struct {
	Group string `json:"group" jsonschema:"Group name (use list_groups to find it)"`
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
	Group        string   `json:"group" jsonschema:"Group name (use list_groups to find it)"`
	Action       string   `json:"action" jsonschema:"Action to perform (add or remove)"`
	Participants []string `json:"participants" jsonschema:"List of phone numbers"`
}

type UpdateGroupParticipantsOutput struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}
