package main

import "testing"

func TestNotificationReplyCommandRoutesAndQuotes(t *testing.T) {
	got := notificationReplyCommand("Ana", "Ana", "ana", "personal", true, true)
	want := "telegram send --instance 'personal' --to 'Ana' --message '<reply>'"
	if got != want {
		t.Fatalf("saved contact: got %q, want %q", got, want)
	}
	got = notificationReplyCommand("Bob's Crew", "Bob", "bob", "", false, false)
	want = "telegram send --to 'Bob'\"'\"'s Crew' --message '<reply>'"
	if got != want {
		t.Fatalf("group: got %q, want %q", got, want)
	}
}
