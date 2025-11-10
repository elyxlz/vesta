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

func WriteNotification(
	notifDir, messageID, chatJID, chatName, contactName, contactPhone string,
	contactSaved, isDirectChat bool,
	sender, content, mediaType string, isForwarded bool,
) error {
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
	if contactName != "" {
		metadata["contact_name"] = contactName
	}
	if contactPhone != "" {
		metadata["contact_phone"] = contactPhone
	}
	metadata["contact_saved"] = contactSaved
	if !contactSaved && isDirectChat {
		metadata["needs_contact_confirmation"] = true
	}

	if mediaType != "" {
		metadata["media_type"] = mediaType
	}
	if isForwarded {
		metadata["is_forwarded"] = isForwarded
	}
	replyInstruction := "Reply to this chat using the send_message tool."
	metadata["reply_instruction"] = replyInstruction

	notification := map[string]interface{}{
		"timestamp": time.Now().Format(time.RFC3339),
		"source":    "whatsapp",
		"type":      "message",
		"message":   content,
		"sender":    sender,
		"metadata":  metadata,
	}
	noteParts := []string{replyInstruction}
	if !contactSaved && isDirectChat {
		noteParts = append(noteParts, "Ask the user who this is. Be careful and add them as a contact once you know.")
	}
	if len(noteParts) > 0 {
		notification["note"] = strings.Join(noteParts, " ")
	}

	data, err := json.MarshalIndent(notification, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal notification: %v", err)
	}

	// Use UUID to prevent race conditions in concurrent notifications
	filename := fmt.Sprintf("%s-whatsapp-message.json", uuid.New().String())
	filePath := filepath.Join(notifDir, filename)

	return os.WriteFile(filePath, data, 0644)
}

func WriteReactionNotification(
	notifDir, targetMessageID, chatJID, chatName, contactName, contactPhone string,
	contactSaved, isDirectChat bool,
	sender, emoji string, isRemoved bool,
) error {
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
	if contactName != "" {
		metadata["contact_name"] = contactName
	}
	if contactPhone != "" {
		metadata["contact_phone"] = contactPhone
	}
	metadata["contact_saved"] = contactSaved
	if !contactSaved && isDirectChat {
		metadata["needs_contact_confirmation"] = true
	}
	if emoji != "" {
		metadata["emoji"] = emoji
	}
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

	// Use UUID to prevent race conditions in concurrent notifications
	filename := fmt.Sprintf("%s-whatsapp-reaction.json", uuid.New().String())
	filePath := filepath.Join(notifDir, filename)

	return os.WriteFile(filePath, data, 0644)
}
