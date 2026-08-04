package main

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// One peer addressed two ways: sends target the LID, replies land under the phone JID.
const (
	outgoingLIDJID   = "18812345678901@lid"
	outgoingPhoneJID = "15559876543@s.whatsapp.net"
)

// newOutgoingTestClient builds a store-backed client over a real whatsmeow device store seeded
// with the outgoingLIDJID<->outgoingPhoneJID mapping, so canonicalChatKey resolves the LID to
// the phone JID instead of degrading to the raw JID. That makes the canonical key DIFFER from
// the send target, which is what these tests are about.
func newOutgoingTestClient(t *testing.T) *WhatsAppClient {
	t.Helper()
	ctx := context.Background()
	container, err := sqlstore.New(ctx, "sqlite3", "file:"+filepath.Join(t.TempDir(), "whatsmeow.db")+"?_foreign_keys=on", nil)
	if err != nil {
		t.Fatalf("failed to open whatsmeow store: %v", err)
	}
	t.Cleanup(func() { container.Close() })

	device := container.NewDevice()
	device.LIDs = container.LIDMap
	lid, err := types.ParseJID(outgoingLIDJID)
	if err != nil {
		t.Fatalf("failed to parse lid: %v", err)
	}
	phone, err := types.ParseJID(outgoingPhoneJID)
	if err != nil {
		t.Fatalf("failed to parse phone jid: %v", err)
	}
	if err := device.LIDs.PutLIDMapping(ctx, lid, phone); err != nil {
		t.Fatalf("failed to seed LID mapping: %v", err)
	}

	return &WhatsAppClient{
		store:  newTestStore(t),
		logger: waLog.Noop,
		client: whatsmeow.NewClient(device, waLog.Noop),
	}
}

// TestOutgoingMessageStoredUnderCanonicalChatKey pins that a message sent to a peer's LID is
// filed under their phone JID, the same key inbound storage resolves to, so one conversation
// stays one chat row.
func TestOutgoingMessageStoredUnderCanonicalChatKey(t *testing.T) {
	wac := newOutgoingTestClient(t)

	lid, err := types.ParseJID(outgoingLIDJID)
	if err != nil {
		t.Fatalf("failed to parse lid: %v", err)
	}
	if err := wac.store.StoreChat(outgoingLIDJID, "Ana", time.Now()); err != nil {
		t.Fatalf("failed to store chat: %v", err)
	}

	wac.recordOutgoingMessage(lid, StoreMessageParams{ID: "MSG-OUT", Content: "hello"})

	msgs, err := wac.store.ListMessages(nil, nil, "", []string{outgoingPhoneJID}, "", 10, 0)
	if err != nil {
		t.Fatalf("failed to list messages: %v", err)
	}
	if len(msgs) != 1 {
		t.Fatalf("expected 1 message under canonical key %q, got %d", outgoingPhoneJID, len(msgs))
	}
	if !msgs[0].IsFromMe {
		t.Errorf("stored outgoing message is not marked IsFromMe")
	}
}

// TestOutgoingAndIncomingShareOneChatKey pins the threading guarantee: a reply from the same peer
// lands in the same chat row as what we sent to their LID, so the conversation reads as one thread
// and "did they answer?" can be resolved by reading that row.
func TestOutgoingAndIncomingShareOneChatKey(t *testing.T) {
	wac := newOutgoingTestClient(t)

	lid, err := types.ParseJID(outgoingLIDJID)
	if err != nil {
		t.Fatalf("failed to parse lid: %v", err)
	}
	if err := wac.store.StoreChat(outgoingLIDJID, "Ana", time.Now()); err != nil {
		t.Fatalf("failed to store chat: %v", err)
	}

	wac.recordOutgoingMessage(lid, StoreMessageParams{ID: "MSG-OUT", Content: "ping"})
	if err := wac.store.StoreMessage(StoreMessageParams{
		ID: "MSG-IN", ChatJID: outgoingPhoneJID, Sender: "Ana", Content: "pong", Timestamp: time.Now(),
	}); err != nil {
		t.Fatalf("failed to store inbound message: %v", err)
	}

	msgs, err := wac.store.ListMessages(nil, nil, "", []string{outgoingPhoneJID}, "", 10, 0)
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
		t.Errorf("chat %q is one-sided: outgoing=%v incoming=%v", outgoingPhoneJID, sawOutgoing, sawIncoming)
	}
}
