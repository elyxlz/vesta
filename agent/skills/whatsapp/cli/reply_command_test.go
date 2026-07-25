package main

import "testing"

func TestNotificationReplyCommandRoutesAndQuotes(t *testing.T) {
	got := notificationReplyCommand(savedCtx(""))
	want := "whatsapp send --instance 'personal' --to 'Ana' --message '<reply>'"
	if got != want {
		t.Fatalf("saved contact: got %q, want %q", got, want)
	}
	got = notificationReplyCommand(NotifContext{ChatName: "Bob's Crew"})
	want = "whatsapp send --to 'Bob'\"'\"'s Crew' --message '<reply>'"
	if got != want {
		t.Fatalf("group: got %q, want %q", got, want)
	}
}
