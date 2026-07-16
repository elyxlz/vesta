package main

import (
	"bytes"
	"strings"
	"testing"
	"time"

	waLog "go.mau.fi/whatsmeow/util/log"
)

func helpFor(t *testing.T, name string) string {
	t.Helper()
	var out bytes.Buffer
	printCommandUsage(&out, name)
	return strings.TrimSpace(out.String())
}

// Help is answered from the command's own flags with no client at all, which is what keeps it
// working with the daemon down and keeps it away from every command body. Driving the real
// registry means a command cannot be added without inheriting that.
func TestEveryCommandReportsItsFlagsWithoutAClient(t *testing.T) {
	for _, cmd := range commands {
		func() {
			defer func() {
				if r := recover(); r != nil {
					t.Errorf("%s --help panicked, so it reaches for the client before parsing: %v", cmd.name, r)
				}
			}()
			if usage := helpFor(t, cmd.name); usage == "" {
				t.Errorf("%s --help printed nothing, want its usage", cmd.name)
			}
		}()
	}
}

// Discovering what a command takes must never destroy anything: clear-all-chats deletes every
// chat, so its help path must not reach the body.
func TestHelpNeverReachesADestructiveBody(t *testing.T) {
	store, err := NewMessageStore(t.TempDir())
	if err != nil {
		t.Fatalf("failed to open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	const chatJID = "15551234567@s.whatsapp.net"
	if err := store.StoreChat(chatJID, "Ana", time.Now()); err != nil {
		t.Fatalf("failed to store chat: %v", err)
	}
	if err := store.StoreMessage(StoreMessageParams{
		ID: "MSG1", ChatJID: chatJID, Sender: "Ana", Content: "keep me", Timestamp: time.Now(),
	}); err != nil {
		t.Fatalf("failed to store message: %v", err)
	}

	// printCommandUsage passes no client, so a body that ran would panic rather than pass quietly.
	if usage := helpFor(t, "clear-all-chats"); usage == "" {
		t.Fatal("clear-all-chats --help printed nothing")
	}

	content, err := store.GetMessageContent("MSG1")
	if err != nil {
		t.Fatalf("failed to read content: %v", err)
	}
	if content != "keep me" {
		t.Error("the message is gone after clear-all-chats --help; asking for help wiped the database")
	}
}

// main routes `--help`, `-h` and a bare `help` to the usage path, so every spelling the CLI
// accepts stops short of the command body rather than only the two flag-shaped ones.
func TestEveryHelpSpellingIsRecognised(t *testing.T) {
	for _, spelling := range []string{"--help", "-h", "help"} {
		if !isHelpArg(spelling) {
			t.Errorf("isHelpArg(%q) = false; that spelling would reach the command body", spelling)
		}
	}
}

func TestHelpListsTheFlagsACommandActuallyTakes(t *testing.T) {
	for _, tc := range []struct{ command, flag string }{
		{"call", "-to"},
		{"say", "-text"},
		{"send-message", "-to"},
		{"list-messages", "-limit"},
	} {
		if usage := helpFor(t, tc.command); !strings.Contains(usage, tc.flag) {
			t.Errorf("%s --help does not mention %s:\n%s", tc.command, tc.flag, usage)
		}
	}
}

// A bare "Usage of hangup:" with nothing under it reads like the answer went missing.
func TestCommandsThatTakeNoFlagsSaySo(t *testing.T) {
	for _, name := range []string{"hangup", "call-status", "clear-all-chats", "archive-all-chats"} {
		if usage := helpFor(t, name); !strings.Contains(usage, "takes no flags") {
			t.Errorf("%s --help = %q, want it to say it takes no flags", name, usage)
		}
	}
}

// A lifecycle command is dispatched outside the registry, so without its own help path
// `whatsapp link --help` would start a real, rate-limited pairing attempt.
func TestLifecycleCommandsAnswerHelpRatherThanRunning(t *testing.T) {
	for _, name := range []string{"link", "serve", "daemon", "authenticate"} {
		usage := helpFor(t, name)
		if !strings.Contains(usage, "Usage: whatsapp") {
			t.Errorf("%s --help = %q, want the usage text", name, usage)
		}
	}
}

// An argument whose own text is `-h` is not a question. It must fail loudly: reporting usage and
// succeeding would tell the agent a message was sent when nothing was.
func TestAnArgumentThatLooksLikeHelpIsNotTreatedAsHelp(t *testing.T) {
	wac := &WhatsAppClient{logger: waLog.Noop, skipSenders: map[string]bool{}}
	result, err := executeCommand("send-message", []string{"--to", "Bob", "-h"}, wac)
	if err == nil {
		t.Fatalf("send-message --to Bob -h returned %#v with no error; the message was never sent", result)
	}
}

// A command declaring no flags must still reject one it does not know, rather than ignore its
// arguments and run regardless.
func TestAnUnknownFlagIsRejectedRatherThanIgnored(t *testing.T) {
	wac := &WhatsAppClient{logger: waLog.Noop, skipSenders: map[string]bool{}}
	for _, name := range []string{"hangup", "clear-all-chats", "archive-all-chats"} {
		if _, err := executeCommand(name, []string{"--bogus"}, wac); err == nil {
			t.Errorf("%s --bogus was accepted, want an error rather than the command running", name)
		}
	}
}

// A rejected flag is answered by the list of flags the command does take.
func TestARejectedFlagReportsWhatTheCommandAccepts(t *testing.T) {
	wac := &WhatsAppClient{logger: waLog.Noop, skipSenders: map[string]bool{}}
	_, err := executeCommand("call", []string{"--nonexistent-flag", "x"}, wac)
	if err == nil {
		t.Fatal("call --nonexistent-flag was accepted, want an error")
	}
	if !strings.Contains(err.Error(), "-to") {
		t.Errorf("the rejection does not list the flags call takes: %v", err)
	}
}

// The usage list is generated from the registry, so a command cannot ship undiscoverable.
func TestUsageListsEveryCommandOfferedToTheAgent(t *testing.T) {
	var usage bytes.Buffer
	printUsage(&usage)
	for _, cmd := range commands {
		if cmd.internal {
			continue
		}
		if !strings.Contains(usage.String(), cmd.name) {
			t.Errorf("`whatsapp --help` does not list %q, so there is no way to discover it", cmd.name)
		}
	}
}

// The link-* and daemon-status commands are for the `link` and `daemon` wrappers to drive:
// offering them directly routes around the rate-limit and QR-page handling those wrappers own.
func TestUsageDoesNotOfferWrapperDrivenCommands(t *testing.T) {
	var usage bytes.Buffer
	printUsage(&usage)
	for _, name := range []string{"link-start", "link-status", "link-stop", "daemon-status"} {
		for _, line := range strings.Split(usage.String(), "\n") {
			if strings.TrimSpace(line) == name || strings.HasPrefix(strings.TrimSpace(line), name+" ") {
				t.Errorf("`whatsapp --help` offers %q, which the wrappers own", name)
			}
		}
	}
}

func TestUsageShowsAliasesAndPositionals(t *testing.T) {
	var usage bytes.Buffer
	printUsage(&usage)
	for _, want := range []string{
		"send-message (send) <to> <message>",
		"call <to>",
		"say <text>",
		"hangup",
		"list-contacts (contacts, search-contacts)",
	} {
		if !strings.Contains(usage.String(), want) {
			t.Errorf("`whatsapp --help` is missing %q:\n%s", want, usage.String())
		}
	}
}
