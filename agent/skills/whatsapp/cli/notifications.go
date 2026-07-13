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
	ReplyHint       string `json:"reply_hint,omitempty"`
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

type authNotif struct {
	Source    string `json:"source"`
	Type      string `json:"type"`
	Instance  string `json:"instance,omitempty"`
	Message   string `json:"message"`
	Timestamp string `json:"timestamp"`
}

// A live voice call surfaces to the agent as whatsapp notifications, so it reaches the model
// through the same interrupt-driven flow as a text message. `call_started` wakes the model on an
// inbound call it should greet; `call_utterance` delivers each thing the caller says (it drives
// the back-and-forth, and interrupts like any whatsapp message so the model answers live);
// `call_ended` closes the loop; `call_missed` reports a call that could not be answered.
type callNotif struct {
	Source       string `json:"source"`
	Type         string `json:"type"`
	Instance     string `json:"instance,omitempty"`
	Direction    string `json:"direction,omitempty"` // "inbound" | "outbound"
	ContactName  string `json:"contact_name,omitempty"`
	ContactPhone string `json:"contact_phone,omitempty"`
	Transcript   string `json:"transcript,omitempty"` // what the caller said (call_utterance)
	Reason       string `json:"reason,omitempty"`     // why a call ended or was missed
	Timestamp    string `json:"timestamp"`
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
		ReplyHint:       "reply with a short message, and think about how you can best show your personality",
	}
	if !ctx.IsDirectChat {
		n.ChatName = ctx.ChatName
		n.ReplyHint = "reply with a short message, and think about how you can best show your personality; this is a group chat, so it may not be expecting a reply from you"
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

func writeCallNotification(notifDir, instance string, n callNotif) error {
	n.Source = "whatsapp"
	n.Instance = instance
	n.Timestamp = time.Now().Format(time.RFC3339)
	return writeNotificationFile(notifDir, n, n.Type)
}

// WriteUnpairedNotification tells the agent the WhatsApp daemon came up without a
// device session and needs re-pairing. Called once per unpaired daemon boot.
func WriteUnpairedNotification(notifDir, instance string) error {
	n := authNotif{
		Source:    "whatsapp",
		Type:      "unpaired",
		Instance:  instance,
		Message:   "WhatsApp daemon started without a paired device session. Re-pairing is required: follow the whatsapp skill SETUP.md to scan a new QR code or use pair-phone.",
		Timestamp: time.Now().Format(time.RFC3339),
	}
	return writeNotificationFile(notifDir, n, "unpaired")
}
