package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/google/uuid"
)

// Field conventions: booleans are named so `true` is the interesting case so `,omitempty`
// drops the common-case `false` entirely, keeping notifications terse in the agent's context.
type messageNotif struct {
	Source         string `json:"source"`
	Type           string `json:"type"`
	Instance       string `json:"instance,omitempty"`
	ContactName    string `json:"contact_name,omitempty"`
	Message        string `json:"message"`
	Sender         string `json:"sender,omitempty"`
	ChatName       string `json:"chat_name,omitempty"`
	Username       string `json:"username,omitempty"`
	MediaType      string `json:"media_type,omitempty"`
	ReplyToID      int64  `json:"reply_to_id,omitempty"`
	Timestamp      string `json:"timestamp"`
	MessageID      int64  `json:"message_id,omitempty"`
	ContactUnknown bool   `json:"contact_unknown,omitempty"`
	ReplyHint      string `json:"reply_hint,omitempty"`
}

type reactionNotif struct {
	Source          string `json:"source"`
	Type            string `json:"type"`
	Instance        string `json:"instance,omitempty"`
	ContactName     string `json:"contact_name,omitempty"`
	Emoji           string `json:"emoji,omitempty"`
	Sender          string `json:"sender,omitempty"`
	ChatName        string `json:"chat_name,omitempty"`
	Username        string `json:"username,omitempty"`
	IsRemoved       bool   `json:"is_removed,omitempty"`
	Timestamp       string `json:"timestamp"`
	TargetMessageID int64  `json:"target_message_id"`
	ContactUnknown  bool   `json:"contact_unknown,omitempty"`
}

// callbackNotif is emitted when the owner taps an inline-keyboard button. CallbackID is needed to
// answer the tap (telegram answer-callback --callback-id ...); ChatID+MessageID locate the message
// to edit in place if updating the UI.
type callbackNotif struct {
	Source         string `json:"source"`
	Type           string `json:"type"`
	Instance       string `json:"instance,omitempty"`
	ContactName    string `json:"contact_name,omitempty"`
	Data           string `json:"data"`
	CallbackID     string `json:"callback_id"`
	ChatID         int64  `json:"chat_id,omitempty"`
	MessageID      int64  `json:"message_id,omitempty"`
	Sender         string `json:"sender,omitempty"`
	Username       string `json:"username,omitempty"`
	Timestamp      string `json:"timestamp"`
	ContactUnknown bool   `json:"contact_unknown,omitempty"`
}

func WriteCallbackNotification(
	notifDir, callbackID, data string, chatID, messageID int64,
	contactName, sender, username, instance string, contactSaved bool,
) error {
	if notifDir == "" {
		return nil
	}
	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}
	notif := callbackNotif{
		Source:         "telegram",
		Type:           "callback_query",
		Instance:       instance,
		ContactName:    contactName,
		Data:           data,
		CallbackID:     callbackID,
		ChatID:         chatID,
		MessageID:      messageID,
		Sender:         sender,
		Username:       username,
		Timestamp:      time.Now().Format(time.RFC3339),
		ContactUnknown: !contactSaved,
	}
	out, err := json.MarshalIndent(notif, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal callback notification: %v", err)
	}
	filename := fmt.Sprintf("%s-telegram-callback.json", uuid.New().String())
	return os.WriteFile(filepath.Join(notifDir, filename), out, 0644)
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
		Source:         "telegram",
		Type:           "message",
		Instance:       instance,
		ContactName:    contactName,
		Message:        content,
		Username:       username,
		MediaType:      mediaType,
		ReplyToID:      replyToID,
		Timestamp:      time.Now().Format(time.RFC3339),
		MessageID:      messageID,
		ContactUnknown: !contactSaved,
		ReplyHint:      "reply with `telegram send`, and think about how you can best show your personality",
	}
	if !isDirectChat {
		notif.ChatName = chatName
		notif.ReplyHint = "reply with `telegram send`, and think about how you can best show your personality; this is a group chat, so it may not be expecting a reply from you"
		if sender != chatName {
			notif.Sender = sender
		}
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
		ContactUnknown:  !contactSaved,
	}
	if !isDirectChat {
		notif.ChatName = chatName
		if sender != chatName {
			notif.Sender = sender
		}
	}

	data, err := json.MarshalIndent(notif, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal reaction notification: %v", err)
	}

	filename := fmt.Sprintf("%s-telegram-reaction.json", uuid.New().String())
	return os.WriteFile(filepath.Join(notifDir, filename), data, 0644)
}
