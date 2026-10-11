package main

import (
	"testing"
	"time"

	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/proto/waHistorySync"
	"go.mau.fi/whatsmeow/proto/waWeb"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/proto"
)

const historySyncDeadline = 5 * time.Second

// TestHistorySyncConversationIsStoredWithoutBlocking pins that a history batch carrying a
// conversation commits against the real one-connection store. A store read issued on the pool
// while the conversation's transaction holds the only connection waits forever, which leaves
// every later reader of messages.db (live notifications, list-messages) hung.
func TestHistorySyncConversationIsStoredWithoutBlocking(t *testing.T) {
	wac := newOutgoingTestClient(t)
	wac.state = newStateStore(t.TempDir())

	evt := &events.HistorySync{Data: &waHistorySync.HistorySync{
		Conversations: []*waHistorySync.Conversation{{
			ID: proto.String(outgoingPhoneJID),
			Messages: []*waHistorySync.HistorySyncMsg{{
				Message: &waWeb.WebMessageInfo{
					Key: &waCommon.MessageKey{
						RemoteJID: proto.String(outgoingPhoneJID),
						FromMe:    proto.Bool(false),
						ID:        proto.String("HIST-1"),
					},
					Message:          &waE2E.Message{Conversation: proto.String("hi from history")},
					MessageTimestamp: proto.Uint64(uint64(time.Now().Unix())),
				},
			}},
		}},
	}}

	done := make(chan struct{})
	go func() {
		wac.handleHistorySync(evt)
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(historySyncDeadline):
		t.Fatalf("handleHistorySync did not return within %s: the store is deadlocked", historySyncDeadline)
	}

	msgs, err := wac.store.ListMessages(nil, nil, "", []string{outgoingPhoneJID}, "", 10, 0)
	if err != nil {
		t.Fatalf("failed to list messages: %v", err)
	}
	if len(msgs) != 1 || msgs[0].Content != "hi from history" {
		t.Fatalf("expected the history message stored under %q, got %+v", outgoingPhoneJID, msgs)
	}
}
