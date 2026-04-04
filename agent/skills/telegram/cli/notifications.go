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
	Source      string `json:"source"`
	Type        string `json:"type"`
	Instance    string `json:"instance,omitempty"`
	ContactName string `json:"contact_name,omitempty"`
	Message     string `json:"message"`
	Sender      string `json:"sender,omitempty"`
	ChatName    string `json:"chat_name,omitempty"`
	Username    string `json:"username,omitempty"`
	MediaType   string `json:"media_type,omitempty"`
	ReplyToID   int64  `json:"reply_to_id,omitempty"`
	Timestamp   string `json:"timestamp"`
	MessageID   int64  `json:"message_id,omitempty"`
	ContactSaved bool  `json:"contact_saved"`
	Note        string `json:"note,omitempty"`
}

type reactionNotif struct {
	Source      string `json:"source"`
	Type        string `json:"type"`
	Instance    string `json:"instance,omitempty"`
	ContactName string `json:"contact_name,omitempty"`
	Emoji       string `json:"emoji,omitempty"`
	Sender      string `json:"sender,omitempty"`
	ChatName    string `json:"chat_name,omitempty"`
	Username    string `json:"username,omitempty"`
	IsRemoved   bool   `json:"is_removed"`
	Timestamp   string `json:"timestamp"`
	TargetMessageID int64 `json:"target_message_id"`
	ContactSaved bool  `json:"contact_saved"`
	Note        string `json:"note,omitempty"`
}

func WriteNotification(
	notifDir string, messageID int64, chatName, contactName, username, instance string,
	contactSaved, isDirectChat bool,
	sender, content, mediaType string,
	replyToID int64,
) error {
	if notifDir == "" {
		return nil
	}

	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}

	notif := messageNotif{
		Source:       "telegram",
		Type:         "message",
		Instance:     instance,
		ContactName:  contactName,
		Message:      content,
		Username:     username,
		MediaType:    mediaType,
		ReplyToID:    replyToID,
		Timestamp:    time.Now().Format(time.RFC3339),
		MessageID:    messageID,
		ContactSaved: contactSaved,
	}
	if !isDirectChat {
		notif.Sender = sender
		notif.ChatName = chatName
	}
	if !contactSaved && isDirectChat && instance == "" {
		notif.Note = "Unknown contact. Ask the user who this is and add them as a contact once you know."
	}

	data, err := json.MarshalIndent(notif, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal notification: %v", err)
	}

	filename := fmt.Sprintf("%s-telegram-message.json", uuid.New().String())
	return os.WriteFile(filepath.Join(notifDir, filename), data, 0644)
}

func WriteReactionNotification(
	notifDir string, targetMessageID int64, chatName, contactName, username, instance string,
	contactSaved, isDirectChat bool,
	sender, emoji string, isRemoved bool,
) error {
	if notifDir == "" {
		return nil
	}

	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}

	notif := reactionNotif{
		Source:          "telegram",
		Type:            "reaction",
		Instance:        instance,
		ContactName:     contactName,
		Emoji:           emoji,
		Username:        username,
		IsRemoved:       isRemoved,
		Timestamp:       time.Now().Format(time.RFC3339),
		TargetMessageID: targetMessageID,
		ContactSaved:    contactSaved,
	}
	if !isDirectChat {
		notif.Sender = sender
		notif.ChatName = chatName
	}
	if !contactSaved && isDirectChat && instance == "" {
		notif.Note = "Unknown contact. Ask the user who this is and add them as a contact once you know."
	}

	data, err := json.MarshalIndent(notif, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal reaction notification: %v", err)
	}

	filename := fmt.Sprintf("%s-telegram-reaction.json", uuid.New().String())
	return os.WriteFile(filepath.Join(notifDir, filename), data, 0644)
}
