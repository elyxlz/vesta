package main

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
)

var NotificationsDir string = "../../../notifications"

func WriteNotification(chatJID, chatName, sender, content string, mediaType string) {
	notifDir := NotificationsDir
	os.MkdirAll(notifDir, 0755)

	data, _ := json.MarshalIndent(map[string]interface{}{
		"timestamp": time.Now().Format(time.RFC3339),
		"source":    "whatsapp",
		"type":      "message",
		"data": map[string]interface{}{
			"chat_jid":   chatJID,
			"chat_name":  chatName,
			"sender":     sender,
			"content":    content,
			"media_type": mediaType,
			"message":   content,
		},
	}, "", "  ")
	
	os.WriteFile(fmt.Sprintf("%s/%d-whatsapp-message.json", notifDir,
		time.Now().UnixNano()), data, 0644)
}