package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/google/uuid"
)

func WriteNotification(
	notifDir, messageID, chatName, contactName, contactPhone string,
	contactSaved, isDirectChat bool,
	sender, content, mediaType string, isForwarded bool,
) error {
	if notifDir == "" {
		return nil // Notifications disabled
	}

	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}

	notification := map[string]interface{}{
		"timestamp":     time.Now().Format(time.RFC3339),
		"source":        "whatsapp",
		"type":          "message",
		"message":       content,
		"sender":        sender,
		"contact_saved": contactSaved,
	}
	if contactName != "" {
		notification["contact_name"] = contactName
	}
	if contactPhone != "" {
		notification["contact_phone"] = contactPhone
	}
	if chatName != "" {
		notification["chat_name"] = chatName
	}
	if messageID != "" {
		notification["message_id"] = messageID
	}
	if mediaType != "" {
		notification["media_type"] = mediaType
	}
	if isForwarded {
		notification["is_forwarded"] = true
	}
	if !contactSaved && isDirectChat {
		notification["note"] = "Unknown contact. Ask the user who this is and add them as a contact once you know."
	}

	data, err := json.MarshalIndent(notification, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal notification: %v", err)
	}

	filename := fmt.Sprintf("%s-whatsapp-message.json", uuid.New().String())
	filePath := filepath.Join(notifDir, filename)

	return os.WriteFile(filePath, data, 0644)
}

func WriteReactionNotification(
	notifDir, targetMessageID, chatName, contactName, contactPhone string,
	contactSaved, isDirectChat bool,
	sender, emoji string, isRemoved bool,
) error {
	if notifDir == "" {
		return nil // Notifications disabled
	}

	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}

	notification := map[string]interface{}{
		"timestamp":         time.Now().Format(time.RFC3339),
		"source":            "whatsapp",
		"type":              "reaction",
		"sender":            sender,
		"contact_saved":     contactSaved,
		"target_message_id": targetMessageID,
		"is_removed":        isRemoved,
	}
	if emoji != "" {
		notification["emoji"] = emoji
	}
	if contactName != "" {
		notification["contact_name"] = contactName
	}
	if contactPhone != "" {
		notification["contact_phone"] = contactPhone
	}
	if chatName != "" {
		notification["chat_name"] = chatName
	}
	if !contactSaved && isDirectChat {
		notification["note"] = "Unknown contact. Ask the user who this is and add them as a contact once you know."
	}

	data, err := json.MarshalIndent(notification, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal reaction notification: %v", err)
	}

	filename := fmt.Sprintf("%s-whatsapp-reaction.json", uuid.New().String())
	filePath := filepath.Join(notifDir, filename)

	return os.WriteFile(filePath, data, 0644)
}
