package main

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"

	waLog "go.mau.fi/whatsmeow/util/log"
)

// startTestSocket serves a store-backed client on a temp socket, the same path a
// real command takes: client -> unix socket -> executeCommand -> response.
func startTestSocket(t *testing.T) string {
	t.Helper()
	wac := &WhatsAppClient{store: newTestStore(t), logger: waLog.Noop}
	sockPath := filepath.Join(t.TempDir(), "whatsapp.sock")
	listener, err := startSocketServer(sockPath, wac)
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

// TestFailedWriteExitsNonZero proves a write that did not happen fails at the shell,
// instead of looking identical to one that did, and that its structured body still
// carries the reason.
func TestFailedWriteExitsNonZero(t *testing.T) {
	body, exitCode := runTestCommand(t, startTestSocket(t), "archive-chat", "--to", "Nobody Saved")
	if exitCode == 0 {
		t.Errorf("a failed write must exit nonzero, got exit 0 with body %v", body)
	}
	if body["success"] != false {
		t.Errorf("the failure body must keep success:false, got %v", body)
	}
	message, ok := body["message"].(string)
	if !ok || !strings.Contains(message, "Nobody Saved") {
		t.Errorf("the failure body must keep the reason, got %v", body)
	}
}

// TestRejectedSendExitsNonZero pins the bubble lint's exit code, the behavior a failed
// write now matches: both failures of the same command exit the same way.
func TestRejectedSendExitsNonZero(t *testing.T) {
	body, exitCode := runTestCommand(t, startTestSocket(t), "send-message", "--to", "+15551234567", "--message", "hey. ok")
	if exitCode == 0 {
		t.Errorf("a send rejected by the bubble lint must exit nonzero, got exit 0 with body %v", body)
	}
	if _, ok := body["error"].(string); !ok {
		t.Errorf("a rejected command must report its reason under error, got %v", body)
	}
}

// TestSuccessfulCommandExitsZero pins the unchanged success path: exit 0 and the
// command's own result body.
func TestSuccessfulCommandExitsZero(t *testing.T) {
	body, exitCode := runTestCommand(t, startTestSocket(t), "list-contacts")
	if exitCode != 0 {
		t.Errorf("a successful command must exit 0, got %d with body %v", exitCode, body)
	}
	if _, ok := body["contacts"]; !ok {
		t.Errorf("a successful command must return its own result body, got %v", body)
	}
}
