package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
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
	EventID         string `json:"event_id,omitempty"`
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
	EventID         string `json:"event_id,omitempty"`
}

func WriteNotification(
	notifDir, messageID, chatName, contactName, contactPhone, instance string,
	contactSaved, isDirectChat bool,
	sender, content, mediaType string, isForwarded bool,
	quotedMessageID, quotedText string,
) error {
	if notifDir == "" {
		return nil
	}

	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}

	// Build event_id: wa:msg:<id> for main, wa.<instance>:msg:<id> for named instances
	prefix := "wa"
	if instance != "" {
		prefix = "wa." + instance
	}
	eventID := fmt.Sprintf("%s:msg:%s", prefix, messageID)

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
		EventID:         eventID,
	}
	if !isDirectChat {
		n.Sender = sender
		n.ChatName = chatName
	}
	if !contactSaved && isDirectChat && instance == "" {
		n.Note = "Unknown contact. Ask the user who this is and add them as a contact once you know."
	}

	data, err := json.MarshalIndent(n, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal notification: %v", err)
	}

	filename := fmt.Sprintf("%s-whatsapp-message.json", uuid.New().String())
	return os.WriteFile(filepath.Join(notifDir, filename), data, 0644)
}

func WriteReactionNotification(
	notifDir, targetMessageID, chatName, contactName, contactPhone, instance string,
	contactSaved, isDirectChat bool,
	sender, emoji string, isRemoved bool,
) error {
	if notifDir == "" {
		return nil
	}

	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}

	// Build event_id: wa:react:<target_id>:<emoji>:<sender> for main, wa.<instance>:react:... for named instances
	prefix := "wa"
	if instance != "" {
		prefix = "wa." + instance
	}
	eventID := fmt.Sprintf("%s:react:%s:%s:%s", prefix, targetMessageID, emoji, strings.TrimPrefix(contactPhone, "+"))

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
		EventID:         eventID,
	}
	if !isDirectChat {
		n.Sender = sender
		n.ChatName = chatName
	}
	if !contactSaved && isDirectChat && instance == "" {
		n.Note = "Unknown contact. Ask the user who this is and add them as a contact once you know."
	}

	data, err := json.MarshalIndent(n, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal reaction notification: %v", err)
	}

	filename := fmt.Sprintf("%s-whatsapp-reaction.json", uuid.New().String())
	return os.WriteFile(filepath.Join(notifDir, filename), data, 0644)
}
