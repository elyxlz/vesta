package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/google/uuid"
)

// Field conventions: booleans are named so `true` is the interesting case so `,omitempty`
// drops the common-case `false` entirely, keeping notifications terse in the agent's context.
type messageNotif struct {
	Source          string `json:"source"`
	Type            string `json:"type"`
	Instance        string `json:"instance,omitempty"`
	ContactName     string `json:"contact_name,omitempty"`
	Message         string `json:"message"`
	Sender          string `json:"sender,omitempty"`
	ChatName        string `json:"chat_name,omitempty"`
	ContactPhone    string `json:"contact_phone,omitempty"`
	MediaType       string `json:"media_type,omitempty"`
	IsForwarded     bool   `json:"is_forwarded,omitempty"`
	QuotedMessageID string `json:"quoted_message_id,omitempty"`
	QuotedText      string `json:"quoted_text,omitempty"`
	Timestamp       string `json:"timestamp"`
	MessageID       string `json:"message_id,omitempty"`
	ContactUnknown  bool   `json:"contact_unknown,omitempty"`
}

type reactionNotif struct {
	Source          string `json:"source"`
	Type            string `json:"type"`
	Instance        string `json:"instance,omitempty"`
	ContactName     string `json:"contact_name,omitempty"`
	Emoji           string `json:"emoji,omitempty"`
	Sender          string `json:"sender,omitempty"`
	ChatName        string `json:"chat_name,omitempty"`
	ContactPhone    string `json:"contact_phone,omitempty"`
	IsRemoved       bool   `json:"is_removed,omitempty"`
	Timestamp       string `json:"timestamp"`
	TargetMessageID string `json:"target_message_id"`
	ContactUnknown  bool   `json:"contact_unknown,omitempty"`
}

func writeNotificationFile(notifDir string, data any, notifType string) error {
	if notifDir == "" {
		return nil
	}
	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}
	b, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal %s notification: %v", notifType, err)
	}
	filename := fmt.Sprintf("%s-whatsapp-%s.json", uuid.New().String(), notifType)
	return os.WriteFile(filepath.Join(notifDir, filename), b, 0644)
}

func WriteNotification(
	ctx NotifContext,
	messageID, content, mediaType string, isForwarded bool,
	quotedMessageID, quotedText string,
) error {
	n := messageNotif{
		Source:          "whatsapp",
		Type:            "message",
		Instance:        ctx.Instance,
		ContactName:     ctx.ContactName,
		Message:         content,
		ContactPhone:    ctx.ContactPhone,
		MediaType:       mediaType,
		IsForwarded:     isForwarded,
		QuotedMessageID: quotedMessageID,
		QuotedText:      quotedText,
		Timestamp:       time.Now().Format(time.RFC3339),
		MessageID:       messageID,
		ContactUnknown:  !ctx.ContactSaved,
	}
	if !ctx.IsDirectChat {
		n.ChatName = ctx.ChatName
		// Drop Sender when it's just the same JID as the chat (happens for unsaved group participants).
		if ctx.Sender != ctx.ChatName {
			n.Sender = ctx.Sender
		}
	}
	return writeNotificationFile(ctx.NotifDir, n, "message")
}

func WriteReactionNotification(
	ctx NotifContext,
	targetMessageID, emoji string, isRemoved bool,
) error {
	n := reactionNotif{
		Source:          "whatsapp",
		Type:            "reaction",
		Instance:        ctx.Instance,
		ContactName:     ctx.ContactName,
		Emoji:           emoji,
		ContactPhone:    ctx.ContactPhone,
		IsRemoved:       isRemoved,
		Timestamp:       time.Now().Format(time.RFC3339),
		TargetMessageID: targetMessageID,
		ContactUnknown:  !ctx.ContactSaved,
	}
	if !ctx.IsDirectChat {
		n.ChatName = ctx.ChatName
		if ctx.Sender != ctx.ChatName {
			n.Sender = ctx.Sender
		}
	}
	return writeNotificationFile(ctx.NotifDir, n, "reaction")
}
