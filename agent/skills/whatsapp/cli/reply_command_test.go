package main

import "testing"

func TestNotificationReplyCommand(t *testing.T) {
	cases := []struct {
		name string
		ctx  NotifContext
		want string
	}{
		{
			name: "saved contact is addressed by name",
			ctx:  savedCtx(""),
			want: "whatsapp send --instance 'personal' --to 'Ana' --message '<reply>'",
		},
		{
			// A phone number resolves on its own, so an unsaved sender still gets addressed.
			name: "unsaved sender is addressed by phone number",
			ctx:  unsavedCtx(""),
			want: "whatsapp send --instance 'personal' --to '+15559998888' --message '<reply>'",
		},
		{
			name: "group is addressed by chat name, shell-quoted",
			ctx:  NotifContext{ChatName: "Bob's Crew"},
			want: "whatsapp send --to 'Bob'\"'\"'s Crew' --message '<reply>'",
		},
		{
			name: "an unnamed group falls back to the bare command",
			ctx:  NotifContext{ChatName: ""},
			want: "whatsapp send",
		},
		{
			name: "an unsaved sender with no number falls back to the bare command",
			ctx:  NotifContext{IsDirectChat: true, ContactName: "Ana"},
			want: "whatsapp send",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := notificationReplyCommand(tc.ctx); got != tc.want {
				t.Fatalf("got %q, want %q", got, tc.want)
			}
		})
	}
}
