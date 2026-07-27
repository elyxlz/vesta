package main

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
	"time"

	waLog "go.mau.fi/whatsmeow/util/log"
)

// startTestSocket puts a command on the real path: client -> unix socket -> executeCommand -> response.
func startTestSocket(t *testing.T, store *MessageStore) string {
	t.Helper()
	sockPath := filepath.Join(t.TempDir(), "whatsapp.sock")
	listener, err := startSocketServer(sockPath, &WhatsAppClient{store: store, logger: waLog.Noop})
	if err != nil {
		t.Fatalf("failed to start socket server: %v", err)
	}
	t.Cleanup(func() { stopSocketServer(listener, sockPath) })
	return sockPath
}

func runTestCommand(t *testing.T, sockPath, command string, args ...string) (map[string]any, int) {
	t.Helper()
	output, exitCode, connected := trySocketCommand(sockPath, command, args)
	if !connected {
		t.Fatalf("test socket did not answer %q", command)
	}
	var body map[string]any
	if err := json.Unmarshal(output, &body); err != nil {
		t.Fatalf("command %q produced unparseable output %q: %v", command, output, err)
	}
	return body, exitCode
}

// runAsyncTestCommand drives the second decoder of SocketResponse, the one behind the pairing
// commands, so both decoders are held to the same body-and-exit-code rule.
func runAsyncTestCommand(t *testing.T, sockPath, command string, args ...string) (map[string]any, int) {
	t.Helper()
	result, stopWaiting, connected := startSocketCommand(sockPath, command, args)
	if !connected {
		t.Fatalf("test socket did not answer %q", command)
	}
	defer stopWaiting()
	res := <-result
	if !res.connected {
		t.Fatalf("test socket dropped %q before answering", command)
	}
	var body map[string]any
	if err := json.Unmarshal(res.output, &body); err != nil {
		t.Fatalf("command %q produced unparseable output %q: %v", command, res.output, err)
	}
	return body, res.exitCode
}

func TestAsyncFailedWriteKeepsItsResultBody(t *testing.T) {
	body, exitCode := runAsyncTestCommand(t, startTestSocket(t, newTestStore(t)), "archive-chat", "--to", "Nobody Saved")
	if exitCode == 0 {
		t.Errorf("a failed write must exit nonzero, got exit 0 with body %v", body)
	}
	if body["success"] != false {
		t.Errorf("the failure body must stay the command's own result, got %v", body)
	}
}

func TestAsyncFailureWithoutResultReportsError(t *testing.T) {
	body, exitCode := runAsyncTestCommand(t, startTestSocket(t, newTestStore(t)), "send-message", "--to", "+15551234567")
	if exitCode == 0 {
		t.Errorf("a validation failure must exit nonzero, got exit 0 with body %v", body)
	}
	if _, ok := body["error"].(string); !ok {
		t.Errorf("a failure that produced no result must report its reason under error, got %v", body)
	}
}

func TestFailedWriteExitsNonZero(t *testing.T) {
	body, exitCode := runTestCommand(t, startTestSocket(t, newTestStore(t)), "archive-chat", "--to", "Nobody Saved")
	if exitCode == 0 {
		t.Errorf("a failed write must exit nonzero, got exit 0 with body %v", body)
	}
	if body["success"] != false {
		t.Errorf("the failure body must keep success:false, got %v", body)
	}
	message, ok := body["message"].(string)
	if !ok || !strings.Contains(message, "Nobody Saved") {
		t.Errorf("the failure body must keep the reason under message, got %v", body)
	}
}

func TestRejectedSendExitsNonZero(t *testing.T) {
	body, exitCode := runTestCommand(t, startTestSocket(t, newTestStore(t)), "send-message", "--to", "+15551234567", "--message", "hey. ok")
	if exitCode == 0 {
		t.Errorf("a send rejected by the bubble lint must exit nonzero, got exit 0 with body %v", body)
	}
	if _, ok := body["error"].(string); !ok {
		t.Errorf("a rejected command must report its reason under error, got %v", body)
	}
}

func TestSucceededWriteExitsZero(t *testing.T) {
	store := newTestStore(t)
	if _, err := store.SaveManualContact("Alice", "+15551234567"); err != nil {
		t.Fatalf("failed to seed a contact: %v", err)
	}
	body, exitCode := runTestCommand(t, startTestSocket(t, store), "remove-contact", "--identifier", "Alice")
	if exitCode != 0 {
		t.Errorf("a write reporting success:true must exit 0, got %d with body %v", exitCode, body)
	}
}

// A wipe that cleared nothing must not look like a clean sweep at the shell. The chats are seeded
// under identifiers that no longer resolve, which is what fails every delete in the loop.
func TestBulkSweepThatClearedNothingExitsNonZero(t *testing.T) {
	store := newTestStore(t)
	for _, jid := range []string{"vanished chat one", "vanished chat two"} {
		if err := store.StoreChat(jid, "Gone", time.Now()); err != nil {
			t.Fatalf("failed to seed a chat: %v", err)
		}
	}
	body, exitCode := runTestCommand(t, startTestSocket(t, store), "clear-all-chats")
	if exitCode == 0 {
		t.Errorf("a sweep that cleared none of two chats must exit nonzero, got exit 0 with body %v", body)
	}
	if body["deleted"] != float64(0) || body["failed"] != float64(2) || body["total"] != float64(2) {
		t.Errorf("the failing sweep must keep reporting its counts, got %v", body)
	}
	if errs, ok := body["errors"].([]any); !ok || len(errs) != 2 {
		t.Errorf("the failing sweep must keep one error per chat, got %v", body)
	}
}

func TestBulkSweepWithNothingToClearExitsZero(t *testing.T) {
	body, exitCode := runTestCommand(t, startTestSocket(t, newTestStore(t)), "clear-all-chats")
	if exitCode != 0 {
		t.Errorf("a sweep with no chats to clear must exit 0, got %d with body %v", exitCode, body)
	}
	if body["total"] != float64(0) {
		t.Errorf("an empty sweep must report that it had nothing to do, got %v", body)
	}
}

// The verdict the exit code above is wired to. archive-all-chats reports the same way, from
// counts it can only produce over a live WhatsApp connection.
func TestABulkSweepFailsOnlyWhenItCompletedNothing(t *testing.T) {
	for _, tc := range []struct {
		name      string
		succeeded int
		failed    int
		want      bool
	}{
		{"nothing to sweep", 0, 0, true},
		{"every item failed", 0, 3, false},
		{"one of three failed", 2, 1, true},
		{"every item succeeded", 3, 0, true},
	} {
		if got := sweptSuccessfully(tc.succeeded, tc.failed); got != tc.want {
			t.Errorf("%s: sweptSuccessfully(%d, %d) = %v, want %v", tc.name, tc.succeeded, tc.failed, got, tc.want)
		}
	}
}

func TestCommandWithoutVerdictExitsZero(t *testing.T) {
	body, exitCode := runTestCommand(t, startTestSocket(t, newTestStore(t)), "list-contacts")
	if exitCode != 0 {
		t.Errorf("a command carrying no success field must exit 0, got %d with body %v", exitCode, body)
	}
	if _, ok := body["contacts"]; !ok {
		t.Errorf("a successful command must return its own result body, got %v", body)
	}
}
