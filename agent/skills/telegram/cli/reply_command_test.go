package main

import "testing"

// chatName and contactName are deliberately different in every case: they are adjacent string
// parameters, so identical values would let a transposition pass.
func TestNotificationReplyCommand(t *testing.T) {
	cases := []struct {
		name         string
		chatName     string
		contactName  string
		instance     string
		isDirectChat bool
		contactSaved bool
		want         string
	}{
		{
			name:         "saved contact is addressed by the name send resolves",
			chatName:     "Ana Ruiz",
			contactName:  "Ana",
			instance:     "personal",
			isDirectChat: true,
			contactSaved: true,
			want:         "telegram send --instance 'personal' --to 'Ana' --message '<reply>'",
		},
		{
			// ResolveRecipient looks an @username up in contacts, the very table an unsaved
			// sender is missing from, so any addressed command would fail to resolve.
			name:         "unsaved sender falls back to the bare command",
			chatName:     "Bob Stone",
			contactName:  "Bob Stone",
			instance:     "personal",
			isDirectChat: true,
			contactSaved: false,
			want:         "telegram send",
		},
		{
			name:        "group is addressed by chat name, shell-quoted",
			chatName:    "Bob's Crew",
			contactName: "Bob",
			want:        "telegram send --to 'Bob'\"'\"'s Crew' --message '<reply>'",
		},
		{
			name:        "an unnamed chat falls back to the bare command",
			chatName:    "",
			contactName: "Bob",
			want:        "telegram send",
		},
		{
			name:        "a single account omits the instance flag",
			chatName:    "Team",
			contactName: "Bob",
			instance:    "",
			want:        "telegram send --to 'Team' --message '<reply>'",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := notificationReplyCommand(tc.chatName, tc.contactName, tc.instance, tc.isDirectChat, tc.contactSaved)
			if got != tc.want {
				t.Fatalf("got %q, want %q", got, tc.want)
			}
		})
	}
}
