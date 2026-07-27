package main

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"

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

func TestCommandWithoutVerdictExitsZero(t *testing.T) {
	body, exitCode := runTestCommand(t, startTestSocket(t, newTestStore(t)), "list-contacts")
	if exitCode != 0 {
		t.Errorf("a command carrying no success field must exit 0, got %d with body %v", exitCode, body)
	}
	if _, ok := body["contacts"]; !ok {
		t.Errorf("a successful command must return its own result body, got %v", body)
	}
}
