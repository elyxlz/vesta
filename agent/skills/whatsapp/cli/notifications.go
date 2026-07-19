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
	Source          string `json:"source"`
	Type            string `json:"type"`
	Instance        string `json:"instance,omitempty"`
	ContactName     string `json:"contact_name,omitempty"`
	Message         string `json:"message"`
	Sender          string `json:"sender,omitempty"`
	ChatName        string `json:"chat_name,omitempty"`
	ContactPhone    string `json:"contact_phone,omitempty"`
	MediaType       string `json:"media_type,omitempty"`
	IsForwarded     bool   `json:"is_forwarded,omitempty"`
	QuotedMessageID string `json:"quoted_message_id,omitempty"`
	QuotedText      string `json:"quoted_text,omitempty"`
	Timestamp       string `json:"timestamp"`
	MessageID       string `json:"message_id,omitempty"`
	ContactUnknown  bool   `json:"contact_unknown,omitempty"`
	ReplyHint       string `json:"reply_hint,omitempty"`
}

type reactionNotif struct {
	Source          string `json:"source"`
	Type            string `json:"type"`
	Instance        string `json:"instance,omitempty"`
	ContactName     string `json:"contact_name,omitempty"`
	Emoji           string `json:"emoji,omitempty"`
	Sender          string `json:"sender,omitempty"`
	ChatName        string `json:"chat_name,omitempty"`
	ContactPhone    string `json:"contact_phone,omitempty"`
	IsRemoved       bool   `json:"is_removed,omitempty"`
	Timestamp       string `json:"timestamp"`
	TargetMessageID string `json:"target_message_id"`
	ContactUnknown  bool   `json:"contact_unknown,omitempty"`
}

// WhatsApp delivers an edit and a delete-for-everyone as a ProtocolMessage pointing at
// the original message rather than as new text, so both carry the target's ID plus the
// content as the agent last saw it. `edit` carries the current text in message (the same
// body field a plain message uses), so it reads like a normal message; `revoke` carries
// none, because the message is gone.
type editNotif struct {
	Source          string `json:"source"`
	Type            string `json:"type"`
	Instance        string `json:"instance,omitempty"`
	ContactName     string `json:"contact_name,omitempty"`
	Sender          string `json:"sender,omitempty"`
	ChatName        string `json:"chat_name,omitempty"`
	ContactPhone    string `json:"contact_phone,omitempty"`
	OldText         string `json:"old_text,omitempty"`
	Message         string `json:"message,omitempty"`
	Timestamp       string `json:"timestamp"`
	TargetMessageID string `json:"target_message_id"`
	ContactUnknown  bool   `json:"contact_unknown,omitempty"`
	ReplyHint       string `json:"reply_hint,omitempty"`
}

type authNotif struct {
	Source    string `json:"source"`
	Type      string `json:"type"`
	Instance  string `json:"instance,omitempty"`
	Message   string `json:"message"`
	Timestamp string `json:"timestamp"`
}

// A live voice call surfaces to the agent as whatsapp notifications, reaching the model through the
// same interrupt-driven flow as a text message. `call_started` wakes the model on an inbound call it
// should greet; `call_utterance` delivers each thing the caller says (it drives the back-and-forth,
// interrupting like any whatsapp message so the model answers live); `call_ended` closes the loop;
// `call_missed` reports a call that could not be answered. What the caller said rides in `message`,
// the same key a text message uses, so core renders it as the body rather than one more attribute:
// spoken words are the content of a call_utterance exactly as typed words are the content of a
// message. `type` already says it arrived as speech.
type callNotif struct {
	Source       string `json:"source"`
	Type         string `json:"type"`
	Instance     string `json:"instance,omitempty"`
	Direction    string `json:"direction,omitempty"` // "inbound" | "outbound"
	ContactName  string `json:"contact_name,omitempty"`
	ContactPhone string `json:"contact_phone,omitempty"`
	Message      string `json:"message,omitempty"` // what the caller said (call_utterance)
	Reason       string `json:"reason,omitempty"`  // why a call ended or was missed
	Timestamp    string `json:"timestamp"`
}

// notifPhone is the number to name in a notification, and only an unsaved contact gets one.
// For a saved contact the name is what `whatsapp send --to` takes, so carrying the number too
// just restates the name on every notification; when a name is ambiguous, send's own error
// lists the candidates with their numbers.
func notifPhone(ctx NotifContext) string {
	if ctx.ContactSaved {
		return ""
	}
	return ctx.ContactPhone
}

func writeNotificationFile(notifDir string, data any, notifType string) error {
	if notifDir == "" {
		return nil
	}
	if err := os.MkdirAll(notifDir, 0755); err != nil {
		return fmt.Errorf("failed to create notifications dir: %v", err)
	}
	b, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal %s notification: %v", notifType, err)
	}
	filename := fmt.Sprintf("%s-whatsapp-%s.json", uuid.New().String(), notifType)
	return os.WriteFile(filepath.Join(notifDir, filename), b, 0644)
}

func WriteNotification(
	ctx NotifContext,
	messageID, content, mediaType string, isForwarded bool,
	quotedMessageID, quotedText string,
) error {
	n := messageNotif{
		Source:          "whatsapp",
		Type:            "message",
		Instance:        ctx.Instance,
		ContactName:     ctx.ContactName,
		Message:         content,
		ContactPhone:    notifPhone(ctx),
		MediaType:       mediaType,
		IsForwarded:     isForwarded,
		QuotedMessageID: quotedMessageID,
		QuotedText:      quotedText,
		Timestamp:       time.Now().Format(time.RFC3339),
		MessageID:       messageID,
		ContactUnknown:  !ctx.ContactSaved,
		ReplyHint:       "reply with `whatsapp send`, and think about how you can best show your personality",
	}
	if !ctx.IsDirectChat {
		n.ChatName = ctx.ChatName
		n.ReplyHint = "reply with `whatsapp send`, and think about how you can best show your personality; this is a group chat, so it may not be expecting a reply from you"
		// Drop Sender when it's just the same JID as the chat (happens for unsaved group participants).
		if ctx.Sender != ctx.ChatName {
			n.Sender = ctx.Sender
		}
	}
	return writeNotificationFile(ctx.NotifDir, n, "message")
}

func WriteReactionNotification(
	ctx NotifContext,
	targetMessageID, emoji string, isRemoved bool,
) error {
	n := reactionNotif{
		Source:          "whatsapp",
		Type:            "reaction",
		Instance:        ctx.Instance,
		ContactName:     ctx.ContactName,
		Emoji:           emoji,
		ContactPhone:    notifPhone(ctx),
		IsRemoved:       isRemoved,
		Timestamp:       time.Now().Format(time.RFC3339),
		TargetMessageID: targetMessageID,
		ContactUnknown:  !ctx.ContactSaved,
	}
	if !ctx.IsDirectChat {
		n.ChatName = ctx.ChatName
		if ctx.Sender != ctx.ChatName {
			n.Sender = ctx.Sender
		}
	}
	return writeNotificationFile(ctx.NotifDir, n, "reaction")
}

// applyChatContext mirrors the group-chat handling the message and reaction writers do:
// name the chat, and name the sender unless it is just the chat's own JID.
func (n *editNotif) applyChatContext(ctx NotifContext) {
	if ctx.IsDirectChat {
		return
	}
	n.ChatName = ctx.ChatName
	if ctx.Sender != ctx.ChatName {
		n.Sender = ctx.Sender
	}
}

func WriteEditNotification(ctx NotifContext, targetMessageID, oldText, newText string) error {
	n := editNotif{
		Source:          "whatsapp",
		Type:            "edit",
		Instance:        ctx.Instance,
		ContactName:     ctx.ContactName,
		ContactPhone:    ctx.ContactPhone,
		OldText:         oldText,
		Message:         newText,
		Timestamp:       time.Now().Format(time.RFC3339),
		TargetMessageID: targetMessageID,
		ContactUnknown:  !ctx.ContactSaved,
		ReplyHint:       "they changed a message you may have already answered; reply with `whatsapp send` only if the change asks something new",
	}
	n.applyChatContext(ctx)
	return writeNotificationFile(ctx.NotifDir, n, "edit")
}

func WriteRevokeNotification(ctx NotifContext, targetMessageID, oldText string) error {
	n := editNotif{
		Source:          "whatsapp",
		Type:            "revoke",
		Instance:        ctx.Instance,
		ContactName:     ctx.ContactName,
		ContactPhone:    ctx.ContactPhone,
		OldText:         oldText,
		Timestamp:       time.Now().Format(time.RFC3339),
		TargetMessageID: targetMessageID,
		ContactUnknown:  !ctx.ContactSaved,
		ReplyHint:       "they deleted this message, so treat it as unsaid and do not quote it back to them",
	}
	n.applyChatContext(ctx)
	return writeNotificationFile(ctx.NotifDir, n, "revoke")
}

func writeCallNotification(notifDir, instance string, n callNotif) error {
	n.Source = "whatsapp"
	n.Instance = instance
	n.Timestamp = time.Now().Format(time.RFC3339)
	return writeNotificationFile(notifDir, n, n.Type)
}

// managedParadigm reports whether this box runs a managed (pooled) WhatsApp number,
// mirroring the resolution runConnect and chooseLinker use: env creds first, filled
// from persisted state so an env scrub still resolves the managed path. The auth
// notifications read it because they run without a *WhatsAppClient (so without the
// constructed linker) yet must still tell a managed agent to reauth autonomously.
func managedParadigm() bool {
	cfg := loadManagedConfig()
	if cfg.directURL == "" || cfg.directKey == "" {
		st := loadStateFromDisk(stateDataDir())
		if cfg.directURL == "" {
			cfg.directURL = st.DirectURL
		}
		if cfg.directKey == "" {
			cfg.directKey = st.DirectKey
		}
	}
	return newManagedAuth(cfg).isHosted()
}

// WriteUnpairedNotification tells the agent the WhatsApp daemon came up without a
// device session and needs re-pairing. Called once per unpaired daemon boot. A
// managed number reclaims itself autonomously (no user step), so only self-hosted QR
// linking, which needs the human to scan, is gated on the user being ready.
func WriteUnpairedNotification(notifDir, instance string) error {
	message := "WhatsApp daemon started without a paired device session. Run `whatsapp connect` to link (when the user is ready)."
	if managedParadigm() {
		message = "WhatsApp daemon started without a paired device session. Run `whatsapp connect` now to re-link your managed number; it reclaims the number autonomously and needs no user step."
	}
	n := authNotif{
		Source:    "whatsapp",
		Type:      "unpaired",
		Instance:  instance,
		Message:   message,
		Timestamp: time.Now().Format(time.RFC3339),
	}
	return writeNotificationFile(notifDir, n, "unpaired")
}

// WriteLoggedOutNotification tells the agent WhatsApp logged this device out.
// Re-linking is deliberate (`whatsapp connect`), never an automatic loop, so
// this notifies once and stops rather than re-pairing.
func WriteLoggedOutNotification(notifDir, instance, reason string) error {
	message := "WhatsApp logged this device out"
	if reason != "" {
		message += " (" + reason + ")"
	}
	if managedParadigm() {
		message += ". This is NOT re-linked automatically, but a managed number reauthorizes autonomously: run `whatsapp connect` now to re-link the SAME number, no user step needed. Do not retry-loop pairing."
	} else {
		message += ". This is NOT re-linked automatically. When the user is ready, run `whatsapp connect` to re-link. Do not retry-loop pairing."
	}
	n := authNotif{
		Source:    "whatsapp",
		Type:      "logged_out",
		Instance:  instance,
		Message:   message,
		Timestamp: time.Now().Format(time.RFC3339),
	}
	return writeNotificationFile(notifDir, n, "logged_out")
}
