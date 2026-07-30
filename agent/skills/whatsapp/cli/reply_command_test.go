package main

import (
	"strings"
	"testing"
)

func TestNotificationReplyCommandUsesUniqueSavedContactName(t *testing.T) {
	ctx := NotifContext{
		Instance: "personal", ChatJID: "4477000111@s.whatsapp.net",
		ContactName: "Ana", ContactSaved: true, ContactNameUnique: true,
	}
	got := notificationReplyCommand(ctx)
	want := "whatsapp send --instance 'personal' --to 'Ana' --message -"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestNotificationReplyCommandFallsBackToJIDForAmbiguousContactName(t *testing.T) {
	ctx := NotifContext{
		ChatJID:     "4477000111@s.whatsapp.net",
		ContactName: "Ana", ContactSaved: true, ContactNameUnique: false,
	}
	got := notificationReplyCommand(ctx)
	want := "whatsapp send --to '4477000111@s.whatsapp.net' --message -"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
	if strings.Contains(got, "--instance") {
		t.Fatalf("a single account should omit --instance: %q", got)
	}
}

// The command hands the body to stdin rather than inlining it, so the reply text never reaches the
// shell. An inline --message would break on the first apostrophe and could evaluate a $(...).
func TestNotificationReplyCommandBodyIsShellInert(t *testing.T) {
	got := notificationReplyCommand(NotifContext{ChatJID: "123@g.us"})
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
