package main

import (
	"strings"
	"testing"
)

func TestNotificationReplyCommandIsCompleteAndUnambiguous(t *testing.T) {
	// The chat ID is what ResolveRecipient matches first and needs no saved contact, so the same
	// command shape works for a saved contact, a stranger, and a group alike.
	got := notificationReplyCommand(-1001234567890, "personal")
	want := "telegram send --instance 'personal' --to '-1001234567890' --message -"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}

	single := notificationReplyCommand(42, "")
	if strings.Contains(single, "--instance") {
		t.Fatalf("a single account should omit --instance: %q", single)
	}
}

// The command hands the body to stdin rather than inlining it, so the reply text never reaches the
// shell. An inline --message would break on the first apostrophe and could evaluate a $(...).
func TestNotificationReplyCommandBodyIsShellInert(t *testing.T) {
	got := notificationReplyCommand(42, "")
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
