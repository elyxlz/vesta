package main

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
)

var NotificationsDir string = "../../../notifications"

func WriteNotification(chatJID, chatName, sender, content string, mediaType string, isForwarded bool) {
	notifDir := NotificationsDir
	os.MkdirAll(notifDir, 0755)

	// Build metadata - only include non-empty values
	metadata := make(map[string]interface{})
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