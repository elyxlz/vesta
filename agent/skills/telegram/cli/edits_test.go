package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

const (
	testChatID    = int64(4242)
	testMessageID = 77
	testBotUserID = int64(999)
	testSenderID  = 4242
)

// newEditTestClient builds a client wired to a real store and notifications dir. The bot
// handle stays nil: the edit path never calls Telegram, it only reads the update it was
// handed.
func newEditTestClient(t *testing.T) (*TelegramClient, string) {
	t.Helper()
	store, err := NewMessageStore(t.TempDir())
	if err != nil {
		t.Fatalf("failed to open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	if err := store.StoreChat(testChatID, "Ana", "private", time.Now()); err != nil {
		t.Fatalf("failed to store chat: %v", err)
	}

	notifDir := t.TempDir()
	return &TelegramClient{
		store:            store,
		notificationsDir: notifDir,
		instance:         "personal",
		skipSenders:      map[string]bool{},
		botUserID:        testBotUserID,
	}, notifDir
}

func storeOriginal(t *testing.T, tc *TelegramClient, content string) {
	t.Helper()
	if err := tc.store.StoreMessage(
		testMessageID, testChatID, "Ana", content, time.Now(), false, "", "", "", 0,
	); err != nil {
		t.Fatalf("failed to store message: %v", err)
	}
}

func editedMessage(newText string) *tgbotapi.Message {
	return &tgbotapi.Message{
		MessageID: testMessageID,
		From:      &tgbotapi.User{ID: testSenderID, FirstName: "Ana", UserName: "ana"},
		Chat:      &tgbotapi.Chat{ID: testChatID, Type: "private", FirstName: "Ana"},
		Text:      newText,
		Date:      int(time.Now().Unix()),
	}
}

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
	tc, notifDir := newEditTestClient(t)
	storeOriginal(t, tc, "let's meet at 6")

	tc.handleEditedMessage(editedMessage("let's meet at 9"))

	got := soleNotif(t, notifDir)
	if got.Source != "telegram" || got.Type != "edit" {
		t.Errorf("source/type = %q/%q, want telegram/edit (not a plain message)", got.Source, got.Type)
	}
	if got.OldText != "let's meet at 6" {
		t.Errorf("old_text = %q, want the pre-edit text", got.OldText)
	}
	if got.Message != "let's meet at 9" {
		t.Errorf("message = %q, want the replacement text", got.Message)
	}
	if got.TargetMessageID != testMessageID {
		t.Errorf("target_message_id = %d, want the edited message's id", got.TargetMessageID)
	}
	if got.Timestamp == "" {
		t.Error("timestamp is empty")
	}
}

func TestEditRewritesStoredContent(t *testing.T) {
	tc, _ := newEditTestClient(t)
	storeOriginal(t, tc, "let's meet at 6")

	tc.handleEditedMessage(editedMessage("let's meet at 9"))

	content, err := tc.store.GetMessageContent(testMessageID)
	if err != nil {
		t.Fatalf("failed to read content: %v", err)
	}
	if content != "let's meet at 9" {
		t.Errorf("stored content = %q, want the edit applied", content)
	}
}

func TestEditKeepsFullTextSearchInSyncWithTheNewText(t *testing.T) {
	tc, _ := newEditTestClient(t)
	storeOriginal(t, tc, "let's meet at the harbour")

	tc.handleEditedMessage(editedMessage("let's meet at the airport"))

	if ids := searchIDs(t, tc, "airport"); len(ids) != 1 || ids[0] != testMessageID {
		t.Errorf("searching the new text returned %v, want exactly the edited message", ids)
	}
	if ids := searchIDs(t, tc, "harbour"); len(ids) != 0 {
		t.Errorf("searching the pre-edit text returned %v, want nothing (the index must not hold stale text)", ids)
	}
}

func searchIDs(t *testing.T, tc *TelegramClient, query string) []int64 {
	t.Helper()
	rows, err := tc.store.db.Query(`
		SELECT m.id FROM messages m
		JOIN messages_fts ON messages_fts.rowid = m.rowid
		WHERE messages_fts MATCH ?
	`, query)
	if err != nil {
		t.Fatalf("fts query failed: %v", err)
	}
	defer rows.Close()
	var ids []int64
	for rows.Next() {
		var id int64
		if err := rows.Scan(&id); err != nil {
			t.Fatalf("scan failed: %v", err)
		}
		ids = append(ids, id)
	}
	return ids
}

func TestEditOfAMessageWeNeverStoredStillReportsTheNewText(t *testing.T) {
	tc, notifDir := newEditTestClient(t)

	tc.handleEditedMessage(editedMessage("let's meet at 9"))

	got := soleNotif(t, notifDir)
	if got.Message != "let's meet at 9" {
		t.Errorf("message = %q, want the replacement text", got.Message)
	}
	if got.OldText != "" {
		t.Errorf("old_text = %q, want empty when the original was never stored", got.OldText)
	}
}

func TestEditToIdenticalTextIsNotNotified(t *testing.T) {
	tc, notifDir := newEditTestClient(t)
	storeOriginal(t, tc, "let's meet at 6")

	tc.handleEditedMessage(editedMessage("let's meet at 6"))

	if notifs := readNotifs(t, notifDir); len(notifs) != 0 {
		t.Errorf("wrote %d notifications, want none when the text did not actually change", len(notifs))
	}
}

func TestOwnEditIsNotNotified(t *testing.T) {
	tc, notifDir := newEditTestClient(t)
	storeOriginal(t, tc, "let's meet at 6")

	msg := editedMessage("let's meet at 9")
	msg.From.ID = int64(testBotUserID)
	tc.handleEditedMessage(msg)

	if notifs := readNotifs(t, notifDir); len(notifs) != 0 {
		t.Errorf("wrote %d notifications, want none for our own edit", len(notifs))
	}
}

func TestSkippedSenderGetsNoEditNotification(t *testing.T) {
	tc, notifDir := newEditTestClient(t)
	storeOriginal(t, tc, "let's meet at 6")
	tc.skipSenders["ana"] = true

	tc.handleEditedMessage(editedMessage("let's meet at 9"))

	if notifs := readNotifs(t, notifDir); len(notifs) != 0 {
		t.Errorf("wrote %d notifications, want none for a skipped sender", len(notifs))
	}
}

// An edited caption carries its text in Caption, not Text.
func TestEditOfAMediaCaptionIsReported(t *testing.T) {
	tc, notifDir := newEditTestClient(t)
	storeOriginal(t, tc, "old caption")

	msg := editedMessage("")
	msg.Caption = "new caption"
	tc.handleEditedMessage(msg)

	got := soleNotif(t, notifDir)
	if got.Message != "new caption" || got.OldText != "old caption" {
		t.Errorf("caption edit not reported: old=%q new=%q", got.OldText, got.Message)
	}
}
