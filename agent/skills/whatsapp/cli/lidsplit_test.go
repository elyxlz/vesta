package main

import (
	"testing"
	"time"

	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// A direct chat is stored under two keys: the peer's phone JID and their LID. Messages
// received before the LID<->PN mapping was known sit under the LID, everything else under
// the phone JID, so reading one key returns a one-sided transcript.
const (
	splitPhoneJID = "15557654321@s.whatsapp.net"
	splitLIDJID   = "11085528756332@lid"
)

// storeSplitConversation writes one outbound under the phone JID and one inbound under the
// LID, i.e. the same human's conversation as it actually lands on disk.
func storeSplitConversation(t *testing.T, store *MessageStore) {
	t.Helper()
	now := time.Now()
	for _, chat := range []struct{ jid, name string }{
		{splitPhoneJID, "Peer"},
		{splitLIDJID, "11085528756332"},
	} {
		if err := store.StoreChat(chat.jid, chat.name, now); err != nil {
			t.Fatalf("failed to store chat %s: %v", chat.jid, err)
		}
	}
	if err := store.StoreMessage(StoreMessageParams{
		ID: "OUT-1", ChatJID: splitPhoneJID, Sender: "me", Content: "mine",
		Timestamp: now.Add(-time.Minute), IsFromMe: true,
	}); err != nil {
		t.Fatalf("failed to store outbound: %v", err)
	}
	if err := store.StoreMessage(StoreMessageParams{
		ID: "IN-1", ChatJID: splitLIDJID, Sender: "Peer", Content: "theirs",
		Timestamp: now,
	}); err != nil {
		t.Fatalf("failed to store inbound: %v", err)
	}
}

// TestListMessagesReadsEveryStorageKeyOfOneChat is the regression guard for the read path.
// Filtering on the resolved phone JID alone hides everything stored under the peer's LID,
// which reads as "they never replied" rather than as missing data.
func TestListMessagesReadsEveryStorageKeyOfOneChat(t *testing.T) {
	store := newTestStore(t)
	storeSplitConversation(t, store)

	oneKey, err := store.ListMessages(nil, nil, "", []string{splitPhoneJID}, "", 50, 0)
	if err != nil {
		t.Fatalf("listing one key failed: %v", err)
	}
	if len(oneKey) != 1 {
		t.Fatalf("expected the phone JID alone to yield 1 message, got %d", len(oneKey))
	}

	bothKeys, err := store.ListMessages(nil, nil, "", []string{splitPhoneJID, splitLIDJID}, "", 50, 0)
	if err != nil {
		t.Fatalf("listing both keys failed: %v", err)
	}
	if len(bothKeys) != 2 {
		t.Fatalf("expected both storage keys to yield the whole conversation (2 messages), got %d", len(bothKeys))
	}

	var mine, theirs int
	for _, m := range bothKeys {
		if m.IsFromMe {
			mine++
		} else {
			theirs++
		}
	}
	if mine != 1 || theirs != 1 {
		t.Errorf("expected a two-sided transcript (1 sent, 1 received), got %d sent and %d received", mine, theirs)
	}
}

// TestListMessagesWithNoChatFilterIsUnfiltered proves the nil case still means "every chat",
// so dropping --to did not silently become "no results".
func TestListMessagesWithNoChatFilterIsUnfiltered(t *testing.T) {
	store := newTestStore(t)
	storeSplitConversation(t, store)

	all, err := store.ListMessages(nil, nil, "", nil, "", 50, 0)
	if err != nil {
		t.Fatalf("listing without a chat filter failed: %v", err)
	}
	if len(all) != 2 {
		t.Fatalf("expected no chat filter to return every message (2), got %d", len(all))
	}
}

// TestStorageKeysUnionsTheCounterpart guards the union itself, which is the point of the change.
// Without it the LID counterpart could be dropped and every other test here would still pass.
func TestStorageKeysUnionsTheCounterpart(t *testing.T) {
	phone := types.NewJID("15557654321", types.DefaultUserServer)
	lid := types.NewJID("11085528756332", types.HiddenUserServer)

	both := storageKeys(phone, lid)
	if len(both) != 2 {
		t.Fatalf("a peer with a LID counterpart must yield both storage keys, got %v", both)
	}
	if both[0] != splitPhoneJID || both[1] != splitLIDJID {
		t.Errorf("expected [%s %s], got %v", splitPhoneJID, splitLIDJID, both)
	}

	// A group, or a peer with no mapping yet, has no counterpart.
	if only := storageKeys(phone, types.JID{}); len(only) != 1 || only[0] != splitPhoneJID {
		t.Errorf("an empty counterpart must yield the primary key alone, got %v", only)
	}

	// Defensive: a counterpart equal to the primary must not produce a self-union.
	if same := storageKeys(phone, phone); len(same) != 1 {
		t.Errorf("a counterpart equal to the primary must not be repeated, got %v", same)
	}
}

// TestChatStorageKeysDegradesWithoutAClient proves the resolver is safe offline: with no
// whatsmeow client there is no LID mapping to consult, so it yields the resolved JID alone
// rather than erroring or returning nothing.
func TestChatStorageKeysDegradesWithoutAClient(t *testing.T) {
	wac := &WhatsAppClient{store: newTestStore(t), logger: waLog.Noop}

	none, err := wac.chatStorageKeys("")
	if err != nil {
		t.Fatalf("an empty target must not error: %v", err)
	}
	if none != nil {
		t.Errorf("an empty target must mean no chat filter, got %v", none)
	}

	keys, err := wac.chatStorageKeys("+15557654321")
	if err != nil {
		t.Fatalf("resolving a phone must succeed: %v", err)
	}
	if len(keys) != 1 || keys[0] != splitPhoneJID {
		t.Errorf("expected the resolved phone JID alone, got %v", keys)
	}
}

// TestListMessagesDoesNotShowOneMessageTwice covers the composite primary key (id, chat_jid):
// the same message re-stored under a chat's other key is two rows, and a union across both keys
// would otherwise return it twice, with each copy spending the caller's --limit.
func TestListMessagesDoesNotShowOneMessageTwice(t *testing.T) {
	store := newTestStore(t)
	storeSplitConversation(t, store)

	// The same message id under both storage keys, as backfill re-storing under the
	// canonical key would leave it.
	now := time.Now()
	for _, jid := range []string{splitPhoneJID, splitLIDJID} {
		if err := store.StoreMessage(StoreMessageParams{
			ID: "DUP-1", ChatJID: jid, Sender: "Peer", Content: "said once",
			Timestamp: now.Add(time.Minute),
		}); err != nil {
			t.Fatalf("failed to store duplicate under %s: %v", jid, err)
		}
	}

	got, err := store.ListMessages(nil, nil, "", []string{splitPhoneJID, splitLIDJID}, "", 50, 0)
	if err != nil {
		t.Fatalf("listing both keys failed: %v", err)
	}

	var dupCount int
	for _, m := range got {
		if m.ID == "DUP-1" {
			dupCount++
		}
	}
	if dupCount != 1 {
		t.Errorf("a message stored under both keys must appear once, appeared %d times", dupCount)
	}
	if len(got) != 3 {
		t.Errorf("expected 3 distinct messages, got %d", len(got))
	}
}
