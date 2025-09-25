package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

func WriteNotification(notifDir, messageID, chatJID, chatName, sender, content, mediaType string, isForwarded bool) error {
	if notifDir == "" {
		return nil // Notifications disabled
	}

	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}

	metadata := make(map[string]interface{})
	metadata["message_id"] = messageID
	metadata["chat_jid"] = chatJID
	metadata["chat_name"] = chatName

	if mediaType != "" {
		metadata["media_type"] = mediaType
	}
	if isForwarded {
		metadata["is_forwarded"] = isForwarded
	}

	notification := map[string]interface{}{
		"timestamp": time.Now().Format(time.RFC3339),
		"source":    "whatsapp",
		"type":      "message",
		"message":   content,
		"sender":    sender,
		"metadata":  metadata,
	}

	data, err := json.MarshalIndent(notification, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal notification: %v", err)
	}

	filename := fmt.Sprintf("%d-whatsapp-message.json", time.Now().UnixNano())
	filePath := filepath.Join(notifDir, filename)

	return os.WriteFile(filePath, data, 0644)
}

func WriteReactionNotification(notifDir, targetMessageID, chatJID, chatName, sender, emoji string, isRemoved bool) error {
	if notifDir == "" {
		return nil // Notifications disabled
	}

	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}

	metadata := make(map[string]interface{})
	metadata["target_message_id"] = targetMessageID
	metadata["chat_jid"] = chatJID
	metadata["chat_name"] = chatName
	metadata["is_removed"] = isRemoved

	message := ""
	if isRemoved {
		message = fmt.Sprintf("%s removed their reaction", sender)
	} else {
		message = fmt.Sprintf("%s reacted with %s", sender, emoji)
	}

	notification := map[string]interface{}{
		"timestamp": time.Now().Format(time.RFC3339),
		"source":    "whatsapp",
		"type":      "reaction",
		"message":   message,
		"sender":    sender,
		"metadata":  metadata,
	}

	data, err := json.MarshalIndent(notification, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal reaction notification: %v", err)
	}

	filename := fmt.Sprintf("%d-whatsapp-reaction.json", time.Now().UnixNano())
	filePath := filepath.Join(notifDir, filename)

	return os.WriteFile(filePath, data, 0644)
}