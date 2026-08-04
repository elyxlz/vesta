package main

import (
	"testing"

	"go.mau.fi/whatsmeow/types"
)

// A LID chat is a direct chat: `send` accepts one, so `react` must too. Before this, the reaction
// path only knew s.whatsapp.net and g.us and rejected a @lid chat with "Unsupported chat type: lid",
// even though the same conversation reacted fine when addressed by its +E.164 number.
func TestReactionSenderJIDAcceptsDirectChats(t *testing.T) {
	wac := &WhatsAppClient{}
	for _, server := range []string{types.DefaultUserServer, types.HiddenUserServer, types.HostedLIDServer} {
		chat := types.JID{User: "123456", Server: server}
		sender, failure := wac.reactionSenderJID(chat, "MSGID")
		if failure != "" {
			t.Fatalf("server %q: unexpected failure %q", server, failure)
		}
		if sender != chat {
			t.Fatalf("server %q: sender = %v, want the chat itself %v", server, sender, chat)
		}
	}
}

func TestReactionSenderJIDUsesStoredSenderForGroups(t *testing.T) {
	wac := &WhatsAppClient{messageSenders: map[string]string{"MSGID": "49999@s.whatsapp.net"}}
	chat := types.JID{User: "120363", Server: types.GroupServer}

	sender, failure := wac.reactionSenderJID(chat, "MSGID")
	if failure != "" {
		t.Fatalf("unexpected failure %q", failure)
	}
	if sender.User != "49999" {
		t.Fatalf("sender = %v, want the stored per-message sender", sender)
	}

	if _, failure = wac.reactionSenderJID(chat, "UNKNOWN"); failure != "Message sender not found for group reaction" {
		t.Fatalf("missing stored sender: got %q", failure)
	}
}

func TestReactionSenderJIDRejectsUnsupportedChatTypes(t *testing.T) {
	wac := &WhatsAppClient{}
	chat := types.JID{User: "status", Server: types.BroadcastServer}
	if _, failure := wac.reactionSenderJID(chat, "MSGID"); failure != "Unsupported chat type: broadcast" {
		t.Fatalf("got %q, want the unsupported-chat-type failure", failure)
	}
}
