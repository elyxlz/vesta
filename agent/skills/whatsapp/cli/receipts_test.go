package main

import (
	"errors"
	"testing"
	"time"
)

func TestForceActiveDeliveryReceipts(t *testing.T) {
	if !forceActiveDeliveryReceipts(false) {
		t.Fatal("writable companion must emit visible delivery receipts")
	}
	if forceActiveDeliveryReceipts(true) {
		t.Fatal("read-only companion must not force active delivery receipts")
	}
}

func TestReadReceiptSurvivesPresenceFailure(t *testing.T) {
	presenceFailure := errors.New("no push name")
	marked := false
	presenceErr, receiptErr := sendReadAfterPresence(
		func() error { return presenceFailure },
		func() error { marked = true; return nil },
	)
	if !errors.Is(presenceErr, presenceFailure) {
		t.Fatalf("presence error = %v, want %v", presenceErr, presenceFailure)
	}
	if receiptErr != nil {
		t.Fatalf("read receipt error = %v", receiptErr)
	}
	if !marked {
		t.Fatal("read receipt was skipped after presence failure")
	}
}

// The store has recorded delivery_status and delivery_timestamp for every outbound message since
// the LID split was fixed, and ListMessages never selected either column. Nothing surfaced them, so
// a reader of this CLI could not tell an unread message from one the user opened three hours ago,
// and read that gap as "they have not seen it". This is the regression guard for the read path.
func TestListMessagesSurfacesDeliveryReceipts(t *testing.T) {
	store := newTestStore(t)
	const chat = "15557654321@s.whatsapp.net"
	now := time.Now().Truncate(time.Second)

	if err := store.StoreChat(chat, "Peer", now); err != nil {
		t.Fatalf("failed to store chat: %v", err)
	}
	// One outbound that gets read, one that does not, and one inbound. The unread pair is what
	// makes this test able to fail in both directions: a stub that always reported "read" would
	// pass a single-message version of it.
	for _, m := range []struct {
		id      string
		content string
		fromMe  bool
	}{
		{"OUT-READ", "opened", true},
		{"OUT-UNREAD", "not opened", true},
		{"IN-1", "theirs", false},
	} {
		if err := store.StoreMessage(StoreMessageParams{
			ID: m.id, ChatJID: chat, Sender: "s", Content: m.content,
			Timestamp: now, IsFromMe: m.fromMe,
		}); err != nil {
			t.Fatalf("failed to store %s: %v", m.id, err)
		}
	}
	readAt := now.Add(3 * time.Hour)
	if err := store.UpdateDeliveryStatus("OUT-READ", chat, DeliveryStatusRead, readAt); err != nil {
		t.Fatalf("failed to set delivery status: %v", err)
	}

	msgs, err := store.ListMessages(nil, nil, "", []string{chat}, "", 50, 0)
	if err != nil {
		t.Fatalf("ListMessages failed: %v", err)
	}
	seen := map[string]Message{}
	for _, m := range msgs {
		seen[m.ID] = m
	}
	if len(seen) != 3 {
		t.Fatalf("got %d messages, want 3", len(seen))
	}

	got := seen["OUT-READ"]
	if got.DeliveryStatus != DeliveryStatusRead {
		t.Errorf("read message: delivery_status = %q, want %q", got.DeliveryStatus, DeliveryStatusRead)
	}
	if got.DeliveryTimestamp == nil {
		t.Fatal("read message: delivery_timestamp is nil, so the receipt cannot be dated and " +
			"the latency between sending and opening is unrecoverable")
	}
	if !got.DeliveryTimestamp.Equal(readAt) {
		t.Errorf("read message: delivery_timestamp = %v, want %v", *got.DeliveryTimestamp, readAt)
	}

	// An outbound with no read receipt must be DISTINGUISHABLE from one that has been opened,
	// which is the whole point. StoreMessage stamps outbound as "sent" (storage.go), so the
	// assertion is on the ladder sent < delivered < read, not on emptiness: the first version of
	// this test asserted empty, and the store proved that wrong.
	if s := seen["OUT-UNREAD"].DeliveryStatus; s != DeliveryStatusSent {
		t.Errorf("unread message: delivery_status = %q, want %q", s, DeliveryStatusSent)
	}
	if s := seen["OUT-UNREAD"].DeliveryStatus; s == DeliveryStatusRead {
		t.Error("unread message reports as read, so an unopened message is indistinguishable " +
			"from an opened one and the receipt carries no information")
	}
	// Inbound messages carry no receipt of ours, so the field is omitted rather than guessed.
	if s := seen["IN-1"].DeliveryStatus; s != "" {
		t.Errorf("inbound message: delivery_status = %q, want empty", s)
	}
}
