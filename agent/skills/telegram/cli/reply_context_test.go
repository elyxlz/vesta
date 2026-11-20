package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

// A reply notification carries the quoted text, not just the id it points at: a one-word reply
// says nothing on its own about which message it answers.

const replyTargetID = 4100

func newReplyTestClient(t *testing.T) (*TelegramClient, string) {
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

func replyTo(targetID int, text string) *tgbotapi.Message {
	return &tgbotapi.Message{
		MessageID: 9001,
		From:      &tgbotapi.User{ID: testSenderID, FirstName: "Ana", UserName: "ana"},
		Chat:      &tgbotapi.Chat{ID: testChatID, Type: "private", FirstName: "Ana"},
		Text:      text,
		Date:      int(time.Now().Unix()),
		ReplyToMessage: &tgbotapi.Message{
			MessageID: targetID,
			Chat:      &tgbotapi.Chat{ID: testChatID, Type: "private"},
		},
	}
}

func soleMessageNotif(t *testing.T, dir string) messageNotif {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("failed to read notifications dir: %v", err)
	}
	var out []messageNotif
	for _, e := range entries {
		raw, err := os.ReadFile(filepath.Join(dir, e.Name()))
		if err != nil {
			t.Fatalf("failed to read notification: %v", err)
		}
		var n messageNotif
		if err := json.Unmarshal(raw, &n); err != nil {
			t.Fatalf("notification is not valid json: %v", err)
		}
		out = append(out, n)
	}
	if len(out) != 1 {
		t.Fatalf("expected exactly one notification, got %d: %+v", len(out), out)
	}
	return out[0]
}

func TestReplyNotificationCarriesTheQuotedText(t *testing.T) {
	tc, notifDir := newReplyTestClient(t)
	if err := tc.store.StoreMessage(
		replyTargetID, testChatID, "vesta",
		"the 15:40 train is the one with no changes", time.Now(), true, "", "", "", 0,
	); err != nil {
		t.Fatalf("failed to store the quoted message: %v", err)
	}

	tc.handleMessage(replyTo(replyTargetID, "?"))

	got := soleMessageNotif(t, notifDir)
	if got.ReplyToID != replyTargetID {
		t.Errorf("reply_to_id = %d, want %d", got.ReplyToID, replyTargetID)
	}
	if got.ReplyToText != "the 15:40 train is the one with no changes" {
		t.Errorf("reply_to_text = %q, want the quoted message's text", got.ReplyToText)
	}
	if got.Message != "?" {
		t.Errorf("message = %q, want the bare reply", got.Message)
	}
}

// The POSITIVE CONTROL for the test above: with the quoted message absent from the store there is
// nothing to resolve, so reply_to_text must be EMPTY while reply_to_id still arrives. Without this,
// a bug that hardcoded some non-empty string would pass the first test and never be noticed.
func TestReplyToTextIsEmptyWhenTheQuotedMessageIsNotInTheStore(t *testing.T) {
	tc, notifDir := newReplyTestClient(t)

	tc.handleMessage(replyTo(424242, "?"))

	got := soleMessageNotif(t, notifDir)
	if got.ReplyToID != 424242 {
		t.Errorf("reply_to_id = %d, want the pointer to survive even unresolved", got.ReplyToID)
	}
	if got.ReplyToText != "" {
		t.Errorf("reply_to_text = %q, want empty for a message this store has never seen", got.ReplyToText)
	}
}

// A message that is not a reply must carry neither field, so the common case stays terse.
func TestPlainMessageCarriesNoReplyFields(t *testing.T) {
	tc, notifDir := newReplyTestClient(t)

	msg := replyTo(replyTargetID, "hey")
	msg.ReplyToMessage = nil
	tc.handleMessage(msg)

	got := soleMessageNotif(t, notifDir)
	if got.ReplyToID != 0 || got.ReplyToText != "" {
		t.Errorf("reply fields = %d/%q, want both empty on a non-reply", got.ReplyToID, got.ReplyToText)
	}
}
