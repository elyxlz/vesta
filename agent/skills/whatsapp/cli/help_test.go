package main

import (
	"strings"
	"testing"
	"time"

	waLog "go.mau.fi/whatsmeow/util/log"
)

// newHelpTestClient builds a client with a real store and no whatsmeow connection. Answering
// `--help` must never reach the connection, so a nil client here is the point: any command that
// runs its body instead of reporting its flags fails loudly rather than quietly passing.
func newHelpTestClient(t *testing.T) *WhatsAppClient {
	t.Helper()
	store, err := NewMessageStore(t.TempDir())
	if err != nil {
		t.Fatalf("failed to open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	return &WhatsAppClient{
		store:          store,
		logger:         waLog.Noop,
		skipSenders:    map[string]bool{},
		messageSenders: map[string]string{},
	}
}

func helpFor(t *testing.T, wac *WhatsAppClient, name string) string {
	t.Helper()
	result, err := executeCommand(name, []string{"--help"}, wac)
	if err != nil {
		t.Fatalf("%s --help returned error %v, want its usage", name, err)
	}
	usage, ok := result.(map[string]string)
	if !ok {
		t.Fatalf("%s --help returned %#v, want a usage map", name, result)
	}
	return usage["usage"]
}

// The whole point of the fix: asking any command what it takes is answered, not executed and not
// turned into "flag: help requested". Driving the real registry means a new command cannot be
// added without inheriting this.
func TestEveryCommandAnswersHelpRatherThanRunning(t *testing.T) {
	wac := newHelpTestClient(t)
	for _, cmd := range commands {
		result, err := executeCommand(cmd.name, []string{"--help"}, wac)
		if err != nil {
			t.Errorf("%s --help returned error %v, want its usage", cmd.name, err)
			continue
		}
		usage, ok := result.(map[string]string)
		if !ok || strings.TrimSpace(usage["usage"]) == "" {
			t.Errorf("%s --help returned %#v, want a non-empty usage string", cmd.name, result)
		}
	}
}

// clear-all-chats ignored its args, so `--help` fell straight through to the body and deleted
// every chat. Discovering what a command takes must never destroy anything.
func TestHelpOnClearAllChatsLeavesTheMessagesAlone(t *testing.T) {
	wac := newHelpTestClient(t)
	const chatJID = "15551234567@s.whatsapp.net"
	if err := wac.store.StoreChat(chatJID, "Ana", time.Now()); err != nil {
		t.Fatalf("failed to store chat: %v", err)
	}
	if err := wac.store.StoreMessage(StoreMessageParams{
		ID: "MSG1", ChatJID: chatJID, Sender: "Ana", Content: "keep me", Timestamp: time.Now(),
	}); err != nil {
		t.Fatalf("failed to store message: %v", err)
	}

	if usage := helpFor(t, wac, "clear-all-chats"); usage == "" {
		t.Fatal("clear-all-chats --help gave no usage")
	}

	content, err := wac.store.GetMessageContent("MSG1")
	if err != nil {
		t.Fatalf("failed to read content: %v", err)
	}
	if content != "keep me" {
		t.Errorf("the message is gone after clear-all-chats --help; asking for help wiped the database")
	}
}

func TestHelpListsTheFlagsACommandActuallyTakes(t *testing.T) {
	wac := newHelpTestClient(t)
	for _, tc := range []struct{ command, flag string }{
		{"call", "-to"},
		{"say", "-text"},
		{"send-message", "-to"},
		{"list-messages", "-limit"},
	} {
		if usage := helpFor(t, wac, tc.command); !strings.Contains(usage, tc.flag) {
			t.Errorf("%s --help does not mention %s:\n%s", tc.command, tc.flag, usage)
		}
	}
}

// A bare "Usage of hangup:" with nothing under it reads like the answer went missing.
func TestCommandsThatTakeNoFlagsSaySo(t *testing.T) {
	wac := newHelpTestClient(t)
	for _, name := range []string{"hangup", "call-status", "clear-all-chats", "archive-all-chats", "daemon-status"} {
		usage := helpFor(t, wac, name)
		if !strings.Contains(usage, "takes no flags") {
			t.Errorf("%s --help = %q, want it to say it takes no flags", name, usage)
		}
	}
}

// These commands used to ignore their args entirely, so a typo'd flag ran the command anyway.
func TestAnUnknownFlagIsRejectedRatherThanIgnored(t *testing.T) {
	wac := newHelpTestClient(t)
	for _, name := range []string{"hangup", "clear-all-chats", "archive-all-chats"} {
		if _, err := executeCommand(name, []string{"--bogus"}, wac); err == nil {
			t.Errorf("%s --bogus was accepted, want an error rather than the command running", name)
		}
	}
}

// A real mistake still reads as a failure, not as help.
func TestAGenuineParseErrorIsStillAnError(t *testing.T) {
	wac := newHelpTestClient(t)
	result, err := executeCommand("call", []string{"--nonexistent-flag", "x"}, wac)
	if err == nil {
		t.Fatalf("call --nonexistent-flag returned %#v, want an error", result)
	}
	if strings.Contains(err.Error(), "takes no flags") {
		t.Errorf("a parse error was reported as help: %v", err)
	}
}
