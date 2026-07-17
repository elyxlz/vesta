package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
)

const (
	testChatJID  = "15551234567@s.whatsapp.net"
	testTargetID = "MSG-ORIGINAL"
)

// newEditTestClient builds a client wired to a real store and notifications dir, with no
// whatsmeow connection: readOnly keeps handleMessage from reaching for the socket, and a
// direct-chat, non-LID JID keeps sender resolution store-local. The chat is pre-stored
// because getChatName falls back to the connection for a chat it has never seen, which by
// the time any message arrives is never the case in production.
func newEditTestClient(t *testing.T) (*WhatsAppClient, string) {
	t.Helper()
	store, err := NewMessageStore(t.TempDir())
	if err != nil {
		t.Fatalf("failed to open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	if err := store.StoreChat(testChatJID, "Ana", time.Now()); err != nil {
		t.Fatalf("failed to store chat: %v", err)
	}

	notifDir := t.TempDir()
	return &WhatsAppClient{
		store:            store,
		logger:           waLog.Noop,
		notificationsDir: notifDir,
		instance:         "personal",
		readOnly:         true,
		skipSenders:      map[string]bool{},
		messageSenders:   map[string]string{},
	}, notifDir
}

func storeOriginal(t *testing.T, wac *WhatsAppClient, content string) {
	t.Helper()
	if err := wac.store.StoreMessage(StoreMessageParams{
		ID: testTargetID, ChatJID: testChatJID, Sender: "Ana", Content: content,
		Timestamp: time.Now(),
	}); err != nil {
		t.Fatalf("failed to store message: %v", err)
	}
}

func inboundEvent(msg *waProto.Message) *events.Message {
	chat, _ := types.ParseJID(testChatJID)
	return &events.Message{
		Info: types.MessageInfo{
			ID:        "MSG-PROTOCOL",
			Timestamp: time.Now(),
			MessageSource: types.MessageSource{
				Chat:     chat,
				Sender:   chat,
				IsFromMe: false,
			},
		},
		Message: msg,
	}
}

func editEvent(newText string) *events.Message {
	return inboundEvent(&waProto.Message{
		ProtocolMessage: &waProto.ProtocolMessage{
			Type:          waProto.ProtocolMessage_MESSAGE_EDIT.Enum(),
			Key:           &waProto.MessageKey{ID: proto.String(testTargetID)},
			EditedMessage: &waProto.Message{Conversation: proto.String(newText)},
		},
	})
}

func revokeEvent() *events.Message {
	return inboundEvent(&waProto.Message{
		ProtocolMessage: &waProto.ProtocolMessage{
			Type: waProto.ProtocolMessage_REVOKE.Enum(),
			Key:  &waProto.MessageKey{ID: proto.String(testTargetID)},
		},
	})
}

// readNotifs returns every notification written to dir, decoded into the edit shape.
func readNotifs(t *testing.T, dir string) []editNotif {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("failed to read notifications dir: %v", err)
	}
	notifs := make([]editNotif, 0, len(entries))
	for _, entry := range entries {
		raw, err := os.ReadFile(filepath.Join(dir, entry.Name()))
		if err != nil {
			t.Fatalf("failed to read notification: %v", err)
		}
		var n editNotif
		if err := json.Unmarshal(raw, &n); err != nil {
			t.Fatalf("notification is not valid json: %v", err)
		}
		notifs = append(notifs, n)
	}
	return notifs
}

func soleNotif(t *testing.T, dir string) editNotif {
	t.Helper()
	notifs := readNotifs(t, dir)
	if len(notifs) != 1 {
		t.Fatalf("expected exactly one notification, got %d: %+v", len(notifs), notifs)
	}
	return notifs[0]
}

func TestEditNotifiesWithBothTheOldAndTheNewText(t *testing.T) {
	wac, notifDir := newEditTestClient(t)
	storeOriginal(t, wac, "let's meet at 6")

	wac.eventHandler(editEvent("let's meet at 9"))

	got := soleNotif(t, notifDir)
	if got.Source != "whatsapp" || got.Type != "edit" {
		t.Errorf("source/type = %q/%q, want whatsapp/edit", got.Source, got.Type)
	}
	if got.OldText != "let's meet at 6" {
		t.Errorf("old_text = %q, want the pre-edit text", got.OldText)
	}
	if got.Message != "let's meet at 9" {
		t.Errorf("message = %q, want the replacement text", got.Message)
	}
	if got.TargetMessageID != testTargetID {
		t.Errorf("target_message_id = %q, want the edited message's id, not the protocol stanza's", got.TargetMessageID)
	}
	if got.Timestamp == "" {
		t.Error("timestamp is empty")
	}
}

func TestEditRewritesStoredContentWithoutClobberingDeliveryStatus(t *testing.T) {
	wac, _ := newEditTestClient(t)
	storeOriginal(t, wac, "let's meet at 6")
	if err := wac.store.UpdateDeliveryStatus(testTargetID, testChatJID, DeliveryStatusRead, time.Now()); err != nil {
		t.Fatalf("failed to seed delivery status: %v", err)
	}

	wac.eventHandler(editEvent("let's meet at 9"))

	content, err := wac.store.GetMessageContent(testTargetID)
	if err != nil {
		t.Fatalf("failed to read content: %v", err)
	}
	if content != "let's meet at 9" {
		t.Errorf("stored content = %q, want the edit applied", content)
	}
	status, _, err := wac.store.GetDeliveryStatus(testTargetID, testChatJID)
	if err != nil {
		t.Fatalf("failed to read delivery status: %v", err)
	}
	if status != DeliveryStatusRead {
		t.Errorf("delivery_status = %q, want it preserved as %q across an edit", status, DeliveryStatusRead)
	}
}

func TestEditKeepsFullTextSearchInSyncWithTheNewText(t *testing.T) {
	wac, _ := newEditTestClient(t)
	storeOriginal(t, wac, "let's meet at the harbour")

	wac.eventHandler(editEvent("let's meet at the airport"))

	if ids := searchIDs(t, wac, "airport"); len(ids) != 1 || ids[0] != testTargetID {
		t.Errorf("searching the new text returned %v, want the edited message", ids)
	}
	if ids := searchIDs(t, wac, "harbour"); len(ids) != 0 {
		t.Errorf("searching the pre-edit text returned %v, want nothing (the index must not hold stale text)", ids)
	}
}

func searchIDs(t *testing.T, wac *WhatsAppClient, query string) []string {
	t.Helper()
	rows, err := wac.store.db.Query(`
		SELECT m.id FROM messages m
		JOIN messages_fts ON messages_fts.rowid = m.rowid
		WHERE messages_fts MATCH ?
	`, query)
	if err != nil {
		t.Fatalf("fts query failed: %v", err)
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			t.Fatalf("scan failed: %v", err)
		}
		ids = append(ids, id)
	}
	return ids
}

func TestRevokeNotifiesWithTheDeletedText(t *testing.T) {
	wac, notifDir := newEditTestClient(t)
	storeOriginal(t, wac, "forget i said that")

	wac.eventHandler(revokeEvent())

	got := soleNotif(t, notifDir)
	if got.Type != "revoke" {
		t.Errorf("type = %q, want revoke", got.Type)
	}
	if got.OldText != "forget i said that" {
		t.Errorf("old_text = %q, want the deleted text", got.OldText)
	}
	if got.Message != "" {
		t.Errorf("message = %q, want empty (a deleted message has no replacement)", got.Message)
	}
	if got.TargetMessageID != testTargetID {
		t.Errorf("target_message_id = %q, want the deleted message's id", got.TargetMessageID)
	}
}

// A nil ProtocolMessage reports type REVOKE (it is the zero value), so an ordinary message
// must be routed on the presence of the protocol part, never on its type.
func TestOrdinaryMessageIsNotMistakenForARevoke(t *testing.T) {
	wac, notifDir := newEditTestClient(t)

	wac.eventHandler(inboundEvent(&waProto.Message{Conversation: proto.String("hello")}))

	got := soleNotif(t, notifDir)
	if got.Type != "message" {
		t.Fatalf("type = %q, want message", got.Type)
	}
}

func TestEditOfAMessageWeNeverStoredStillReportsTheNewText(t *testing.T) {
	wac, notifDir := newEditTestClient(t)

	wac.eventHandler(editEvent("let's meet at 9"))

	got := soleNotif(t, notifDir)
	if got.Message != "let's meet at 9" {
		t.Errorf("message = %q, want the replacement text", got.Message)
	}
	if got.OldText != "" {
		t.Errorf("old_text = %q, want empty when the original was never stored", got.OldText)
	}
}

func TestRevokeOfAMessageWeNeverStoredIsSilent(t *testing.T) {
	wac, notifDir := newEditTestClient(t)

	wac.eventHandler(revokeEvent())

	if notifs := readNotifs(t, notifDir); len(notifs) != 0 {
		t.Errorf("wrote %d notifications, want none: a deletion we have no text for tells the agent nothing", len(notifs))
	}
}

func TestOwnEditIsNotNotified(t *testing.T) {
	wac, notifDir := newEditTestClient(t)
	storeOriginal(t, wac, "let's meet at 6")

	evt := editEvent("let's meet at 9")
	evt.Info.IsFromMe = true
	wac.eventHandler(evt)

	if notifs := readNotifs(t, notifDir); len(notifs) != 0 {
		t.Errorf("wrote %d notifications, want none for our own edit", len(notifs))
	}
}

func TestEditToIdenticalTextIsNotNotified(t *testing.T) {
	wac, notifDir := newEditTestClient(t)
	storeOriginal(t, wac, "let's meet at 6")

	wac.eventHandler(editEvent("let's meet at 6"))

	if notifs := readNotifs(t, notifDir); len(notifs) != 0 {
		t.Errorf("wrote %d notifications, want none when the text did not actually change", len(notifs))
	}
}

func TestSkippedSenderGetsNoEditNotification(t *testing.T) {
	wac, notifDir := newEditTestClient(t)
	storeOriginal(t, wac, "let's meet at 6")
	// SaveManualContact derives the JID from the phone, so this contact is the test chat.
	contact, err := wac.store.SaveManualContact("Ana", "+15551234567")
	if err != nil {
		t.Fatalf("failed to save contact: %v", err)
	}
	wac.skipSenders[contact.PhoneNumber] = true

	wac.eventHandler(editEvent("let's meet at 9"))

	if notifs := readNotifs(t, notifDir); len(notifs) != 0 {
		t.Errorf("wrote %d notifications, want none for a skipped sender", len(notifs))
	}
}
