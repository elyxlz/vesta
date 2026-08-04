package main

import (
	"testing"
	"time"

	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// newOutgoingTestClient builds a store-backed client with no whatsmeow connection, matching the
// pattern in edits_test.go. canonicalChatKey degrades to the raw JID when client is nil, so these
// tests pin the routing contract (outgoing storage goes through canonicalChatKey) rather than the
// LID lookup itself, which needs a live whatsmeow store.
func newOutgoingTestClient(t *testing.T) *WhatsAppClient {
	t.Helper()
	store, err := NewMessageStore(t.TempDir())
	if err != nil {
		t.Fatalf("failed to open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	return &WhatsAppClient{
		store:          store,
		logger:         waLog.Noop,
		instance:       "personal",
		readOnly:       true,
		skipSenders:    map[string]bool{},
		messageSenders: map[string]string{},
	}
}

// TestOutgoingMessageStoredUnderCanonicalChatKey pins that an outgoing message is filed under
// canonicalChatKey, the same key inbound storage uses, so one conversation stays one chat row.
func TestOutgoingMessageStoredUnderCanonicalChatKey(t *testing.T) {
	wac := newOutgoingTestClient(t)

	jid, err := types.ParseJID("15551234567@s.whatsapp.net")
	if err != nil {
		t.Fatalf("failed to parse jid: %v", err)
	}
	if err := wac.store.StoreChat(jid.String(), "Ana", time.Now()); err != nil {
		t.Fatalf("failed to store chat: %v", err)
	}

	wac.recordOutgoingMessage(jid, StoreMessageParams{ID: "MSG-OUT", Content: "hello"})

	want := wac.canonicalChatKey(jid)
	msgs, err := wac.store.ListMessages(nil, nil, "", []string{want}, "", 10, 0)
	if err != nil {
		t.Fatalf("failed to list messages: %v", err)
	}
	if len(msgs) != 1 {
		t.Fatalf("expected 1 message under canonical key %q, got %d", want, len(msgs))
	}
	if !msgs[0].IsFromMe {
		t.Errorf("stored outgoing message is not marked IsFromMe")
	}
}

// TestOutgoingAndIncomingShareOneChatKey pins the threading guarantee: a reply from the same peer
// lands in the same chat row as what we sent, so the conversation reads as one thread and
// "did they answer?" can be resolved by reading that row.
func TestOutgoingAndIncomingShareOneChatKey(t *testing.T) {
	wac := newOutgoingTestClient(t)

	jid, err := types.ParseJID("15551234567@s.whatsapp.net")
	if err != nil {
		t.Fatalf("failed to parse jid: %v", err)
	}
	key := wac.canonicalChatKey(jid)
	if err := wac.store.StoreChat(key, "Ana", time.Now()); err != nil {
		t.Fatalf("failed to store chat: %v", err)
	}

	wac.recordOutgoingMessage(jid, StoreMessageParams{ID: "MSG-OUT", Content: "ping"})
	if err := wac.store.StoreMessage(StoreMessageParams{
		ID: "MSG-IN", ChatJID: key, Sender: "Ana", Content: "pong", Timestamp: time.Now(),
	}); err != nil {
		t.Fatalf("failed to store inbound message: %v", err)
	}

	msgs, err := wac.store.ListMessages(nil, nil, "", []string{key}, "", 10, 0)
	if err != nil {
		t.Fatalf("failed to list messages: %v", err)
	}
	if len(msgs) != 2 {
		t.Fatalf("expected both directions under one chat key, got %d", len(msgs))
	}

	var sawOutgoing, sawIncoming bool
	for _, m := range msgs {
		if m.IsFromMe {
			sawOutgoing = true
		} else {
			sawIncoming = true
		}
	}
	if !sawOutgoing || !sawIncoming {
		t.Errorf("chat %q is one-sided: outgoing=%v incoming=%v", key, sawOutgoing, sawIncoming)
	}
}
