package main

import (
	"context"
	"fmt"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func defaultLimit(limit int) int {
	if limit == 0 {
		return 50
	}
	return limit
}

func textResult(format string, args ...interface{}) *mcp.CallToolResult {
	return &mcp.CallToolResult{
		Content: []mcp.Content{
			&mcp.TextContent{Text: fmt.Sprintf(format, args...)},
		},
	}
}

func RegisterTools(s *mcp.Server, wac *WhatsAppClient) {
	// authenticate_whatsapp
	mcp.AddTool(s, &mcp.Tool{
		Name: "authenticate_whatsapp",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input struct{}) (*mcp.CallToolResult, struct {
		Status string `json:"status"`
		QRPath string `json:"qr_path,omitempty"`
	}, error) {
		status, qrPath := wac.GetAuthStatus()

		var message string
		switch status {
		case AuthStatusNotAuthenticated:
			message = "Not authenticated. Starting QR code generation..."
		case AuthStatusQRReady:
			message = fmt.Sprintf("QR code ready. Please scan the QR code at: %s", qrPath)
		case AuthStatusAuthenticated:
			message = "WhatsApp is authenticated and connected"
		default:
			message = fmt.Sprintf("Unknown status: %s", status)
		}

		return &mcp.CallToolResult{
				Content: []mcp.Content{
					&mcp.TextContent{Text: message},
				},
			}, struct {
				Status string `json:"status"`
				QRPath string `json:"qr_path,omitempty"`
			}{
				Status: string(status),
				QRPath: qrPath,
			}, nil
	})

	// search_contacts
	mcp.AddTool(s, &mcp.Tool{
		Name:        "search_contacts",
		Description: "Search WhatsApp contacts by name or phone number. Returns contacts excluding groups.",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input SearchContactsInput) (*mcp.CallToolResult, SearchContactsOutput, error) {
		contacts, err := wac.store.SearchContacts(input.Query, defaultLimit(input.Limit))
		if err != nil {
			return nil, SearchContactsOutput{}, err
		}
		return textResult("Found %d contacts", len(contacts)), SearchContactsOutput{Contacts: contacts}, nil
	})

	// add_contact
	mcp.AddTool(s, &mcp.Tool{
		Name:        "add_contact",
		Description: "Store a contact name and phone number so you can reference them by name before chatting.",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input AddContactInput) (*mcp.CallToolResult, AddContactOutput, error) {
		contact, err := wac.AddContact(input.Name, input.PhoneNumber)
		if err != nil {
			return nil, AddContactOutput{}, err
		}
		displayName := contact.Name
		if displayName == "" {
			displayName = contact.PhoneNumber
		}
		return textResult("Saved contact %s (%s)", displayName, contact.PhoneNumber), AddContactOutput{Contact: contact}, nil
	})

	// list_messages
	mcp.AddTool(s, &mcp.Tool{
		Name:        "list_messages",
		Description: "List WhatsApp messages with optional filters. Use 'to' to filter by chat (contact name, phone number, group name, or JID). Supports time range filtering and pagination.",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input ListMessagesInput) (*mcp.CallToolResult, ListMessagesOutput, error) {
		var after, before *time.Time
		if input.After != "" {
			t, _ := time.Parse(time.RFC3339, input.After)
			after = &t
		}
		if input.Before != "" {
			t, _ := time.Parse(time.RFC3339, input.Before)
			before = &t
		}

		// Resolve 'to' parameter to JID if provided
		var chatJID string
		if input.To != "" {
			jid, err := wac.ResolveRecipient(input.To)
			if err != nil {
				return nil, ListMessagesOutput{}, fmt.Errorf("failed to resolve chat: %v", err)
			}
			chatJID = jid.String()
		}

		limit := defaultLimit(input.Limit)
		messages, err := wac.store.ListMessages(
			after, before,
			input.SenderPhone, chatJID, input.Query,
			limit, input.Page*limit,
			input.IncludeContext,
			input.ContextBefore, input.ContextAfter,
		)
		if err != nil {
			return nil, ListMessagesOutput{}, err
		}
		return nil, ListMessagesOutput{Messages: messages}, nil
	})

	// list_chats
	mcp.AddTool(s, &mcp.Tool{
		Name:        "list_chats",
		Description: "List WhatsApp chats with optional sorting. Use 'sort_by' with 'last_active' (default) or 'name'.",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input ListChatsInput) (*mcp.CallToolResult, ListChatsOutput, error) {
		limit := defaultLimit(input.Limit)
		chats, err := wac.store.ListChats(
			input.Query,
			limit, input.Page*limit,
			input.IncludeLastMessage,
			input.SortBy,
		)
		if err != nil {
			return nil, ListChatsOutput{}, err
		}
		return nil, ListChatsOutput{Chats: chats}, nil
	})

	// send_message
	mcp.AddTool(s, &mcp.Tool{
		Name:        "send_message",
		Description: "Send a WhatsApp message. 'to' accepts contact name, phone number (+1234567890), group name, or JID.",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input SendMessageInput) (*mcp.CallToolResult, SendMessageOutput, error) {
		success, message := wac.SendMessageWithPresence(input.To, input.Message)
		return nil, SendMessageOutput{Success: success, Message: message}, nil
	})

	// send_file
	mcp.AddTool(s, &mcp.Tool{
		Name:        "send_file",
		Description: "Send a file via WhatsApp. 'to' accepts contact name, phone number (+1234567890), group name, or JID.",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input SendFileInput) (*mcp.CallToolResult, SendFileOutput, error) {
		success, message := wac.SendFile(input.To, input.FilePath, input.Caption)
		return nil, SendFileOutput{Success: success, Message: message}, nil
	})

	// download_media
	mcp.AddTool(s, &mcp.Tool{
		Name:        "download_media",
		Description: "Download media from a message. 'to' accepts contact name, phone number, group name, or JID.",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input DownloadMediaInput) (*mcp.CallToolResult, DownloadMediaOutput, error) {
		path, err := wac.DownloadMedia(input.MessageID, input.To, input.DownloadPath)
		success := err == nil
		msg := "Media downloaded"
		if err != nil {
			msg = err.Error()
		}
		return nil, DownloadMediaOutput{Success: success, FilePath: path, Message: msg}, nil
	})

	// send_reaction
	mcp.AddTool(s, &mcp.Tool{
		Name:        "send_reaction",
		Description: "React to a message with an emoji. 'to' accepts contact name, phone number, group name, or JID.",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input SendReactionInput) (*mcp.CallToolResult, SendReactionOutput, error) {
		success, message := wac.SendReaction(input.MessageID, input.Emoji, input.To)
		return nil, SendReactionOutput{Success: success, Message: message}, nil
	})

	// create_group
	mcp.AddTool(s, &mcp.Tool{
		Name:        "create_group",
		Description: "participants: array of phone numbers in E.164 format (['+1234567890', '+0987654321'])",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input CreateGroupInput) (*mcp.CallToolResult, CreateGroupOutput, error) {
		success, groupJID, message := wac.CreateGroup(input.GroupName, input.Participants)
		return nil, CreateGroupOutput{Success: success, GroupJID: groupJID, Message: message}, nil
	})

	// leave_group
	mcp.AddTool(s, &mcp.Tool{
		Name: "leave_group",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input LeaveGroupInput) (*mcp.CallToolResult, LeaveGroupOutput, error) {
		success, message := wac.LeaveGroup(input.GroupJID)
		return nil, LeaveGroupOutput{Success: success, Message: message}, nil
	})

	// list_groups
	mcp.AddTool(s, &mcp.Tool{
		Name: "list_groups",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input ListGroupsInput) (*mcp.CallToolResult, ListGroupsOutput, error) {
		limit := defaultLimit(input.Limit)
		groups, err := wac.store.ListGroups(limit, input.Page*limit)
		if err != nil {
			return nil, ListGroupsOutput{}, err
		}
		return nil, ListGroupsOutput{Groups: groups}, nil
	})

	// update_group_participants
	mcp.AddTool(s, &mcp.Tool{
		Name:        "update_group_participants",
		Description: "action: 'add' or 'remove'. participants: array of E.164 phone numbers",
	}, func(ctx context.Context, req *mcp.CallToolRequest, input UpdateGroupParticipantsInput) (*mcp.CallToolResult, UpdateGroupParticipantsOutput, error) {
		success, message := wac.UpdateGroupParticipants(input.GroupJID, input.Action, input.Participants)
		return nil, UpdateGroupParticipantsOutput{Success: success, Message: message}, nil
	})

}
