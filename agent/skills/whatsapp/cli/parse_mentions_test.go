package main

import (
	"slices"
	"testing"

	"go.mau.fi/whatsmeow/types"
)

// mentionTestGroup is a group destination, the only kind of chat where mentions are parsed.
var mentionTestGroup = types.NewJID("120363000000000001", types.GroupServer)

// newMentionTestClient builds a store-backed client (the contacts_test.go pattern) with saved
// contacts whose names collide with email domain segments, so a resolvable "@ed"/"@Emi" is
// rewritten only when the guard classifies it as a real mention.
func newMentionTestClient(t *testing.T) *WhatsAppClient {
	t.Helper()
	store := newTestStore(t)
	if _, err := store.SaveManualContact("Emi", "+15551000001"); err != nil {
		t.Fatalf("failed to save contact: %v", err)
	}
	if _, err := store.SaveManualContact("Ed", "+15551000002"); err != nil {
		t.Fatalf("failed to save contact: %v", err)
	}
	return &WhatsAppClient{store: store}
}

func TestParseMentions(t *testing.T) {
	wac := newMentionTestClient(t)

	emiJID := "15551000001@s.whatsapp.net"
	cases := []struct {
		name     string
		text     string
		wantText string
		wantJIDs []string
	}{
		{
			name:     "mention at start of text",
			text:     "@Emi hello",
			wantText: "@15551000001 hello",
			wantJIDs: []string{emiJID},
		},
		{
			name:     "mention after a space",
			text:     "hello @Emi",
			wantText: "hello @15551000001",
			wantJIDs: []string{emiJID},
		},
		{
			name:     "mention after an open paren",
			text:     "(@Emi)",
			wantText: "(@15551000001)",
			wantJIDs: []string{emiJID},
		},
		{
			name:     "mention after a comma",
			text:     "ok,@Emi",
			wantText: "ok,@15551000001",
			wantJIDs: []string{emiJID},
		},
		{
			name:     "email local part with digits stays untouched",
			text:     "write to S3044936@ed.ac.uk please",
			wantText: "write to S3044936@ed.ac.uk please",
			wantJIDs: nil,
		},
		{
			name:     "email local part ending in a multibyte letter stays untouched",
			text:     "rené@ed.ac.uk",
			wantText: "rené@ed.ac.uk",
			wantJIDs: nil,
		},
		{
			name:     "email local part ending in atext punctuation stays untouched",
			text:     "foo!@ed.ac.uk",
			wantText: "foo!@ed.ac.uk",
			wantJIDs: nil,
		},
		{
			// A dot is atext, so a dot-glued "@" reads as part of an address token.
			name:     "dot-glued mention stays untouched",
			text:     "done.@Emi",
			wantText: "done.@Emi",
			wantJIDs: nil,
		},
		{
			name:     "digits around an @ produce no mention",
			text:     "5@10",
			wantText: "5@10",
			wantJIDs: nil,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			gotText, gotJIDs := wac.parseMentions(tc.text, mentionTestGroup)
			if gotText != tc.wantText {
				t.Errorf("text = %q, want %q", gotText, tc.wantText)
			}
			if !slices.Equal(gotJIDs, tc.wantJIDs) {
				t.Errorf("jids = %v, want %v", gotJIDs, tc.wantJIDs)
			}
		})
	}
}

// TestParseMentionsExactOnly pins that a mention resolves only on an exact match and only in a
// group: a token that is a mere substring of a saved name, or any mention in a 1:1 chat, leaves
// the text untouched.
func TestParseMentionsExactOnly(t *testing.T) {
	store := newTestStore(t)
	if _, err := store.SaveManualContact("Mohammed X", "+15551000003"); err != nil {
		t.Fatalf("failed to save contact: %v", err)
	}
	if _, err := store.SaveManualContact("Emi", "+15551000001"); err != nil {
		t.Fatalf("failed to save contact: %v", err)
	}
	wac := &WhatsAppClient{store: store}

	direct := types.NewJID("15551000009", types.DefaultUserServer)
	cases := []struct {
		name     string
		text     string
		dest     types.JID
		wantText string
		wantJIDs []string
	}{
		{
			name:     "substring of a contact name is not a mention",
			text:     "she @ed you",
			dest:     mentionTestGroup,
			wantText: "she @ed you",
			wantJIDs: nil,
		},
		{
			name:     "exact name match ignoring case resolves in a group",
			text:     "hi @emi",
			dest:     mentionTestGroup,
			wantText: "hi @15551000001",
			wantJIDs: []string{"15551000001@s.whatsapp.net"},
		},
		{
			name:     "phone number resolves in a group",
			text:     "hi @+15551000003",
			dest:     mentionTestGroup,
			wantText: "hi @15551000003",
			wantJIDs: []string{"15551000003@s.whatsapp.net"},
		},
		{
			name:     "exact name in a 1:1 chat is never rewritten",
			text:     "hi @Emi",
			dest:     direct,
			wantText: "hi @Emi",
			wantJIDs: nil,
		},
		{
			name:     "phone number in a 1:1 chat is never rewritten",
			text:     "hi @15551000003",
			dest:     direct,
			wantText: "hi @15551000003",
			wantJIDs: nil,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			gotText, gotJIDs := wac.parseMentions(tc.text, tc.dest)
			if gotText != tc.wantText {
				t.Errorf("text = %q, want %q", gotText, tc.wantText)
			}
			if !slices.Equal(gotJIDs, tc.wantJIDs) {
				t.Errorf("jids = %v, want %v", gotJIDs, tc.wantJIDs)
			}
		})
	}
}
