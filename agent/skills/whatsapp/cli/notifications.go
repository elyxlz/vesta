package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/google/uuid"
)

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
	ContactSaved    bool   `json:"contact_saved"`
	Note            string `json:"note,omitempty"`
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
	IsRemoved       bool   `json:"is_removed"`
	Timestamp       string `json:"timestamp"`
	TargetMessageID string `json:"target_message_id"`
	ContactSaved    bool   `json:"contact_saved"`
	Note            string `json:"note,omitempty"`
}

// writeNotificationFile marshals data to JSON and writes it as a timestamped
// notification file. notifType is used in the filename (e.g. "message", "reaction").
func writeNotificationFile(notifDir string, data interface{}, notifType string) error {
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

// unknownContactNote is appended to DM notifications from unsaved contacts.
const unknownContactNote = "Unknown contact. Ask the user who this is and add them as a contact once you know."

func WriteNotification(
	notifDir, messageID, chatName, contactName, contactPhone, instance string,
	contactSaved, isDirectChat bool,
	sender, content, mediaType string, isForwarded bool,
	quotedMessageID, quotedText string,
) error {
	n := messageNotif{
		Source:          "whatsapp",
		Type:            "message",
		Instance:        instance,
		ContactName:     contactName,
		Message:         content,
		ContactPhone:    contactPhone,
		MediaType:       mediaType,
		IsForwarded:     isForwarded,
		QuotedMessageID: quotedMessageID,
		QuotedText:      quotedText,
		Timestamp:       time.Now().Format(time.RFC3339),
		MessageID:       messageID,
		ContactSaved:    contactSaved,
	}
	if !isDirectChat {
		n.Sender = sender
		n.ChatName = chatName
	}
	if !contactSaved && isDirectChat && instance == "" {
		n.Note = unknownContactNote
	}
	return writeNotificationFile(notifDir, n, "message")
}

func WriteReactionNotification(
	notifDir, targetMessageID, chatName, contactName, contactPhone, instance string,
	contactSaved, isDirectChat bool,
	sender, emoji string, isRemoved bool,
) error {
	n := reactionNotif{
		Source:          "whatsapp",
		Type:            "reaction",
		Instance:        instance,
		ContactName:     contactName,
		Emoji:           emoji,
		ContactPhone:    contactPhone,
		IsRemoved:       isRemoved,
		Timestamp:       time.Now().Format(time.RFC3339),
		TargetMessageID: targetMessageID,
		ContactSaved:    contactSaved,
	}
	if !isDirectChat {
		n.Sender = sender
		n.ChatName = chatName
	}
	if !contactSaved && isDirectChat && instance == "" {
		n.Note = unknownContactNote
	}
	return writeNotificationFile(notifDir, n, "reaction")
}
