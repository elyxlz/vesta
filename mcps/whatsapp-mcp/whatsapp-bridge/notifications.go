package main

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
)

func WriteNotification(chatJID, chatName, sender, content string, mediaType string) {
	os.MkdirAll("notifications", 0755)
	
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
		},
	}, "", "  ")
	
	os.WriteFile(fmt.Sprintf("notifications/%d-whatsapp-message.json", 
		time.Now().UnixNano()), data, 0644)
}