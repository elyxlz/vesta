package main

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
)

var NotificationsDir string = "../../../notifications"

func WriteNotification(messageID, chatJID, chatName, sender, content string, mediaType string, isForwarded bool) {
	notifDir := NotificationsDir
	os.MkdirAll(notifDir, 0755)

	// Build metadata - only include non-empty values
	metadata := make(map[string]interface{})
	metadata["message_id"] = messageID
	metadata["chat_jid"] = chatJID
	metadata["chat_name"] = chatName
	metadata["sender"] = sender

	if mediaType != "" {
		metadata["media_type"] = mediaType
	}
	if isForwarded {
		metadata["is_forwarded"] = isForwarded
	}

	// Use standardized structure
	data, _ := json.MarshalIndent(map[string]interface{}{
		"timestamp": time.Now().Format(time.RFC3339),
		"source":    "whatsapp",
		"type":      "message",
		"message":   content,  // Primary message content at top level
		"metadata":  metadata, // All additional data in metadata
	}, "", "  ")
	
	os.WriteFile(fmt.Sprintf("%s/%d-whatsapp-message.json", notifDir,
		time.Now().UnixNano()), data, 0644)
}

func WriteReactionNotification(targetMessageID, chatJID, chatName, sender, emoji string, isRemoved bool) {
	notifDir := NotificationsDir
	os.MkdirAll(notifDir, 0755)

	metadata := make(map[string]interface{})
	metadata["target_message_id"] = targetMessageID
	metadata["chat_jid"] = chatJID
	metadata["chat_name"] = chatName
	metadata["sender"] = sender
	metadata["is_removed"] = isRemoved

	message := ""
	if isRemoved {
		message = fmt.Sprintf("%s removed their reaction", sender)
	} else {
		message = fmt.Sprintf("%s reacted with %s", sender, emoji)
	}

	data, _ := json.MarshalIndent(map[string]interface{}{
		"timestamp": time.Now().Format(time.RFC3339),
		"source":    "whatsapp",
		"type":      "reaction",
		"message":   message,
		"metadata":  metadata,
	}, "", "  ")

	os.WriteFile(fmt.Sprintf("%s/%d-whatsapp-reaction.json", notifDir,
		time.Now().UnixNano()), data, 0644)
}