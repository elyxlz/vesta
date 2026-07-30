package main

import (
	"strings"
	"testing"
)

func TestNotificationReplyCommandUsesUniqueSavedContactName(t *testing.T) {
	got := notificationReplyCommand(42, "Ana", "personal", true, true)
	want := "telegram send --instance 'personal' --to 'Ana' --message -"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestNotificationReplyCommandFallsBackToChatIDForAmbiguousName(t *testing.T) {
	got := notificationReplyCommand(42, "Ana", "", true, false)
	want := "telegram send --to '42' --message -"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
	if strings.Contains(got, "--instance") {
		t.Fatalf("a single account should omit --instance: %q", got)
	}
}

func TestContactNameUniquenessDetectsDuplicateSavedNames(t *testing.T) {
	store, err := NewMessageStore(t.TempDir())
	if err != nil {
		t.Fatalf("failed to open store: %v", err)
	}
	defer store.Close()

	if _, err := store.SaveManualContact("Ana", 42, "ana_one"); err != nil {
		t.Fatalf("failed to save first contact: %v", err)
	}
	if !store.ContactNameUniquelyIdentifies("Ana", 42) {
		t.Fatal("one saved contact should be uniquely identified by its name")
	}
	if _, err := store.SaveManualContact("Ana", 84, "ana_two"); err != nil {
		t.Fatalf("failed to save duplicate-name contact: %v", err)
	}
	if store.ContactNameUniquelyIdentifies("Ana", 42) {
		t.Fatal("duplicate saved contact names must be treated as ambiguous")
	}
}

// The command hands the body to stdin rather than inlining it, so the reply text never reaches the
// shell. An inline --message would break on the first apostrophe and could evaluate a $(...).
func TestNotificationReplyCommandBodyIsShellInert(t *testing.T) {
	got := notificationReplyCommand(42, "", "", false, false)
	if !strings.HasSuffix(got, "--message -") {
		t.Fatalf("reply command must end at --message -, leaving the body to stdin: %q", got)
	}
	if strings.Contains(got, "--message '") {
		t.Fatalf("reply command must not inline the body: %q", got)
	}
	// A heredoc here would reach the agent as &lt;&lt; and &#10; entities: the notification is
	// rendered as an XML attribute. SKILL.md carries the heredoc shape instead.
	if strings.ContainsAny(got, "<\n") {
		t.Fatalf("reply command must survive XML attribute rendering unescaped: %q", got)
	}
}
