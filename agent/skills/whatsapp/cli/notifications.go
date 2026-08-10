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

// Field conventions: booleans are named so `true` is the interesting case so `,omitempty`
// drops the common-case `false` entirely, keeping notifications terse in the agent's context.
type messageNotif struct {
	Source          string `json:"source"`
	Type            string `json:"type"`
	Instance        string `json:"instance,omitempty"`
	ContactName     string `json:"contact_name,omitempty"`
	Message         string `json:"message"`
	ChatName        string `json:"chat_name,omitempty"`
	ContactPhone    string `json:"contact_phone,omitempty"`
	MediaType       string `json:"media_type,omitempty"`
	IsForwarded     bool   `json:"is_forwarded,omitempty"`
	QuotedMessageID string `json:"quoted_message_id,omitempty"`
	QuotedText      string `json:"quoted_text,omitempty"`
	Timestamp       string `json:"timestamp"`
	MessageID       string `json:"message_id,omitempty"`
	ChatJID         string `json:"chat_jid,omitempty"`
	// "group" or "direct", always set: a notification rule on chat_type and its
	// negation must both match on the field's value, never on its absence.
	ChatType       string `json:"chat_type"`
	ContactUnknown bool   `json:"contact_unknown,omitempty"`
	ReplyCommand   string `json:"reply_command,omitempty"`
	ReplyHint      string `json:"reply_hint,omitempty"`
}

type reactionNotif struct {
	Source          string `json:"source"`
	Type            string `json:"type"`
	Instance        string `json:"instance,omitempty"`
	ContactName     string `json:"contact_name,omitempty"`
	Emoji           string `json:"emoji,omitempty"`
	ChatName        string `json:"chat_name,omitempty"`
	ContactPhone    string `json:"contact_phone,omitempty"`
	IsRemoved       bool   `json:"is_removed,omitempty"`
	Timestamp       string `json:"timestamp"`
	TargetMessageID string `json:"target_message_id"`
	ChatType        string `json:"chat_type"`
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
	ChatName        string `json:"chat_name,omitempty"`
	ContactPhone    string `json:"contact_phone,omitempty"`
	OldText         string `json:"old_text,omitempty"`
	Message         string `json:"message,omitempty"`
	Timestamp       string `json:"timestamp"`
	TargetMessageID string `json:"target_message_id"`
	ChatJID         string `json:"chat_jid,omitempty"`
	ChatType        string `json:"chat_type"`
	ContactUnknown  bool   `json:"contact_unknown,omitempty"`
	ReplyCommand    string `json:"reply_command,omitempty"`
	ReplyHint       string `json:"reply_hint,omitempty"`
}

type authNotif struct {
	Source               string `json:"source"`
	Type                 string `json:"type"`
	Instance             string `json:"instance,omitempty"`
	Message              string `json:"message"`
	Recovery             string `json:"recovery,omitempty"`
	NextCommand          string `json:"next_command,omitempty"`
	RequiresUserApproval bool   `json:"requires_user_approval,omitempty"`
	Timestamp            string `json:"timestamp"`
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

func quoteReplyArg(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}

func chatType(ctx NotifContext) string {
	if ctx.IsDirectChat {
		return "direct"
	}
	return "group"
}

// replyTarget picks who a reply addresses. A saved contact in a direct chat is named, the same word
// the user uses, and that name resolves to the peer's stored phone JID, the address that carries
// delivery and read receipts. When a group holds that same name the name is ambiguous, so the reply
// keeps the chat JID. An unsaved contact and every group keep the chat JID, which always resolves.
func replyTarget(ctx NotifContext) string {
	if ctx.ContactSaved && ctx.IsDirectChat && ctx.ContactName != "" && !ctx.NameSharedWithGroup {
		return ctx.ContactName
	}
	return ctx.ChatJID
}

// Every notification carries a complete reply command. It stops at `--message -`: the notification
// is rendered as an XML attribute, so a heredoc here would reach the agent as &lt;&lt; and &#10;
// entities. `-` says the body comes from stdin and SKILL.md carries the one heredoc shape, which
// keeps the reply body out of the shell's reach.
func notificationReplyCommand(ctx NotifContext) string {
	command := "whatsapp send"
	if ctx.Instance != "" {
		command += " --instance " + quoteReplyArg(ctx.Instance)
	}
	return command + " --to " + quoteReplyArg(replyTarget(ctx)) + " --message -"
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
		ChatJID:         ctx.ChatJID,
		ChatType:        chatType(ctx),
		ContactUnknown:  !ctx.ContactSaved,
		ReplyCommand:    notificationReplyCommand(ctx),
		ReplyHint:       "think about how you can best show your personality",
	}
	if !ctx.IsDirectChat {
		n.ChatName = ctx.ChatName
		n.ReplyHint = "think about how you can best show your personality; this is a group chat, so it may not be expecting a reply from you"
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
		ChatType:        chatType(ctx),
		ContactUnknown:  !ctx.ContactSaved,
	}
	if !ctx.IsDirectChat {
		n.ChatName = ctx.ChatName
	}
	return writeNotificationFile(ctx.NotifDir, n, "reaction")
}

// applyChatContext mirrors the group-chat handling the message and reaction writers do:
// name the group in chat_name. The participant identity rides in contact_name, set for every chat.
func (n *editNotif) applyChatContext(ctx NotifContext) {
	if ctx.IsDirectChat {
		return
	}
	n.ChatName = ctx.ChatName
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
		ChatJID:         ctx.ChatJID,
		ChatType:        chatType(ctx),
		ContactUnknown:  !ctx.ContactSaved,
		ReplyCommand:    notificationReplyCommand(ctx),
		ReplyHint:       "they changed a message you may have already answered; reply only if the change asks something new",
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
		ChatType:        chatType(ctx),
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

// notificationManagedConfig mirrors runConnect's persisted-credential recovery for
// auth notifications, which run without a *WhatsAppClient. The explicit source is
// stored separately so a mixed cloud/direct environment stays unambiguous.
func notificationManagedConfig(instance string) managedConfig {
	cfg := loadManagedConfig()
	if cfg.directURL == "" || cfg.directKey == "" {
		st := loadStateFromDisk(stateDataDirFor(instance))
		if cfg.directURL == "" {
			cfg.directURL = st.DirectURL
		}
		if cfg.directKey == "" {
			cfg.directKey = st.DirectKey
		}
	}
	return cfg
}

func wasPreviouslyLinked(instance string) bool {
	st := loadStateFromDisk(stateDataDirFor(instance))
	return st.OnboardedMSISDN != "" || !st.LinkedAt.IsZero() || st.AuthStatus == "logged_out" || st.ExitStatus != ""
}

func notificationSource(instance string) (string, string) {
	st := loadStateFromDisk(stateDataDirFor(instance))
	cfg := notificationManagedConfig(instance)
	switch st.AccountSource {
	case sourceVestaCloud:
		if cfg.isManagedVM() {
			return sourceVestaCloud, ""
		}
	case sourceDoubletick:
		if cfg.isDirect() {
			return sourceDoubletick, ""
		}
	case sourceSelfManaged:
		if !cfg.isManagedVM() && !cfg.isDirect() && cfg.configError == "" {
			return sourceSelfManaged, ""
		}
	}
	// Migration fallback follows the setup decision order. A managed VM uses its
	// cloud entitlement even when stale direct credentials are also present.
	if cfg.isManagedVM() {
		return sourceVestaCloud, ""
	}
	if cfg.isDirect() {
		return sourceDoubletick, ""
	}
	if cfg.configError != "" {
		return "", cfg.configError
	}
	return sourceSelfManaged, ""
}

func connectCommand(instance string) string {
	source, _ := notificationSource(instance)
	if source == "" {
		return ""
	}
	command := "whatsapp connect --source " + source
	if instance != "" {
		command += " --instance " + quoteReplyArg(instance)
	}
	return command
}

// WriteUnpairedNotification tells the agent the WhatsApp daemon came up without a
// device session and needs re-pairing. Called once per unpaired daemon boot. A
// managed flow needs no phone or QR step, but a prior link still requires approval
// under the linking rule. A self-managed first link waits for user participation.
func WriteUnpairedNotification(notifDir, instance string) error {
	priorLink := wasPreviouslyLinked(instance)
	source, configError := notificationSource(instance)
	managed := source == sourceVestaCloud || source == sourceDoubletick
	command := connectCommand(instance)
	recovery := "first_link"
	message := "WhatsApp daemon started without a paired device session. Run the exact next_command when the user is ready."
	if managed {
		message = "WhatsApp daemon started without a paired device session. Run the exact next_command now."
	}
	if priorLink {
		recovery = "relink"
		message = "WhatsApp lost a previously linked device session. Ask the user for explicit approval before reconnecting, then run the exact next_command once."
	}
	if configError != "" {
		recovery = "configuration_error"
		message = "WhatsApp cannot choose a safe reconnect method: " + configError + ". Fix the operator-managed configuration outside chat before connecting."
		if priorLink {
			message += " After it is fixed, ask the user for explicit approval before reconnecting."
		}
	}
	if managed {
		message += " The headless flow needs no phone or QR step."
	}
	n := authNotif{
		Source:               "whatsapp",
		Type:                 "unpaired",
		Instance:             instance,
		Message:              message,
		Recovery:             recovery,
		NextCommand:          command,
		RequiresUserApproval: priorLink,
		Timestamp:            time.Now().Format(time.RFC3339),
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
	source, configError := notificationSource(instance)
	if configError != "" {
		message += ". Reconnect is blocked because " + configError + ". Fix the operator-managed configuration outside chat, then ask the user for explicit approval before reconnecting. Do not retry-loop pairing."
	} else if source == sourceVestaCloud || source == sourceDoubletick {
		message += ". Ask the user for explicit approval before reconnecting, then run the exact next_command once. The headless flow needs no phone or QR step. Do not retry-loop pairing."
	} else {
		message += ". Ask the user for explicit approval before reconnecting, then run the exact next_command once. Do not retry-loop pairing."
	}
	n := authNotif{
		Source:               "whatsapp",
		Type:                 "logged_out",
		Instance:             instance,
		Message:              message,
		Recovery:             "relink",
		NextCommand:          connectCommand(instance),
		RequiresUserApproval: true,
		Timestamp:            time.Now().Format(time.RFC3339),
	}
	return writeNotificationFile(notifDir, n, "logged_out")
}
