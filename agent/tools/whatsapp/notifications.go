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
	Source       string `json:"source"`
	Type         string `json:"type"`
	ContactName  string `json:"contact_name,omitempty"`
	Message      string `json:"message"`
	Sender       string `json:"sender,omitempty"`
	ChatName     string `json:"chat_name,omitempty"`
	ContactPhone string `json:"contact_phone,omitempty"`
	MediaType    string `json:"media_type,omitempty"`
	IsForwarded  bool   `json:"is_forwarded,omitempty"`
	Timestamp    string `json:"timestamp"`
	MessageID    string `json:"message_id,omitempty"`
	ContactSaved bool   `json:"contact_saved"`
	Note         string `json:"note,omitempty"`
}

type reactionNotif struct {
	Source          string `json:"source"`
	Type            string `json:"type"`
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

func WriteNotification(
	notifDir, messageID, chatName, contactName, contactPhone string,
	contactSaved, isDirectChat bool,
	sender, content, mediaType string, isForwarded bool,
) error {
	if notifDir == "" {
		return nil
	}

	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}

	n := messageNotif{
		Source:       "whatsapp",
		Type:         "message",
		ContactName:  contactName,
		Message:      content,
		ContactPhone: contactPhone,
		MediaType:    mediaType,
		IsForwarded:  isForwarded,
		Timestamp:    time.Now().Format(time.RFC3339),
		MessageID:    messageID,
		ContactSaved: contactSaved,
	}
	if !isDirectChat {
		n.Sender = sender
		n.ChatName = chatName
	}
	if !contactSaved && isDirectChat {
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
	notifDir, targetMessageID, chatName, contactName, contactPhone string,
	contactSaved, isDirectChat bool,
	sender, emoji string, isRemoved bool,
) error {
	if notifDir == "" {
		return nil
	}

	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}

	n := reactionNotif{
		Source:          "whatsapp",
		Type:            "reaction",
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
	if !contactSaved && isDirectChat {
		n.Note = "Unknown contact. Ask the user who this is and add them as a contact once you know."
	}

	data, err := json.MarshalIndent(n, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal reaction notification: %v", err)
	}

	filename := fmt.Sprintf("%s-whatsapp-reaction.json", uuid.New().String())
	return os.WriteFile(filepath.Join(notifDir, filename), data, 0644)
}
