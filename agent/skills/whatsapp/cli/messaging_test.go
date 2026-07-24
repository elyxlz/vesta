package main

import (
	"strings"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// gateTestPhone/gateTestJID are a saved-contact peer, so the reply-first gate is the
// only thing left to decide once requireManualContact passes.
const (
	gateTestPhone = "+15557654321"
	gateTestJID   = "15557654321@s.whatsapp.net"
)

// newGateTestClient builds a store-backed client in the given paradigm with the peer
// already saved as a contact, isolating the reply-first gate under test.
func newGateTestClient(t *testing.T, managed bool) *WhatsAppClient {
	t.Helper()
	store, err := NewMessageStore(t.TempDir())
	if err != nil {
		t.Fatalf("failed to open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	if _, err := store.SaveManualContact("Peer", gateTestPhone); err != nil {
		t.Fatalf("failed to save contact: %v", err)
	}
	var link linker = qrLinker{}
	if managed {
		link = &managedLinker{}
	}
	return &WhatsAppClient{store: store, logger: waLog.Noop, linker: link}
}

// storeInbound records a received (is_from_me=0) message from the peer, the reply-first
// precondition. The chat row is stored first for the messages foreign key.
func storeInbound(t *testing.T, wac *WhatsAppClient) {
	t.Helper()
	if err := wac.store.StoreChat(gateTestJID, "Peer", time.Now()); err != nil {
		t.Fatalf("failed to store chat: %v", err)
	}
	if err := wac.store.StoreMessage(StoreMessageParams{
		ID: "IN-1", ChatJID: gateTestJID, Sender: "Peer", Content: "hi", Timestamp: time.Now(),
	}); err != nil {
		t.Fatalf("failed to store inbound message: %v", err)
	}
}

// TestManagedNumberCannotColdInitiate proves a managed (pooled) number is blocked from
// sending to a saved contact that has never messaged first, and is allowed once an
// inbound arrives (reply-first). A self-hosted number carries no such rule.
func TestManagedNumberCannotColdInitiate(t *testing.T) {
	jid := types.NewJID("15557654321", types.DefaultUserServer)

	managed := newGateTestClient(t, true)
	err := managed.requireSendAllowed(jid)
	if err == nil {
		t.Fatal("managed number must not cold-initiate to a peer that has not messaged first")
	}
	if !strings.Contains(err.Error(), "reply-first") {
		t.Errorf("block must cite reply-first, got: %v", err)
	}

	storeInbound(t, managed)
	if err := managed.requireSendAllowed(jid); err != nil {
		t.Errorf("managed number must be allowed to reply once the peer has messaged first: %v", err)
	}

	selfHosted := newGateTestClient(t, false)
	if err := selfHosted.requireSendAllowed(jid); err != nil {
		t.Errorf("self-hosted number must send to a saved contact with no reply-first rule: %v", err)
	}
}
