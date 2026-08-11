package main

import (
	"strings"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/types"
)

func TestNotificationReplyCommandIsCompleteAndUnambiguous(t *testing.T) {
	// The chat JID is what ResolveRecipient matches first and needs no saved contact, so the same
	// command shape works for a saved contact, a stranger, and a group alike.
	ctx := NotifContext{Instance: "personal", ChatJID: "4477000111@s.whatsapp.net"}
	got := notificationReplyCommand(ctx)
	want := "whatsapp send --instance 'personal' --to '4477000111@s.whatsapp.net' --message -"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}

	single := notificationReplyCommand(NotifContext{ChatJID: "123@g.us"})
	if strings.Contains(single, "--instance") {
		t.Fatalf("a single account should omit --instance: %q", single)
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

// A saved contact in a direct chat is addressed by name: the same word the user uses, and the name
// resolves to the peer's stored phone JID, the address that carries delivery and read receipts.
func TestNotificationReplyCommandNamesASavedDirectContact(t *testing.T) {
	ctx := NotifContext{
		ContactSaved: true, IsDirectChat: true,
		ContactName: "Emmy", ChatJID: "99988877766655@lid",
	}
	got := notificationReplyCommand(ctx)
	want := "whatsapp send --to 'Emmy' --message -"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

// An unsaved contact has no confirmed name to resolve, so the reply keeps the chat JID.
func TestNotificationReplyCommandKeepsTheJIDForAnUnsavedContact(t *testing.T) {
	ctx := NotifContext{IsDirectChat: true, ChatJID: "15551234567@s.whatsapp.net"}
	got := notificationReplyCommand(ctx)
	if !strings.Contains(got, "--to '15551234567@s.whatsapp.net'") {
		t.Fatalf("an unsaved contact must keep the chat JID, got %q", got)
	}
}

// A group is addressed by the chat, never by a contact name, so its reply keeps the chat JID.
func TestNotificationReplyCommandKeepsTheJIDForAGroup(t *testing.T) {
	ctx := NotifContext{ContactSaved: true, IsDirectChat: false, ContactName: "Alice", ChatJID: "123@g.us"}
	got := notificationReplyCommand(ctx)
	if !strings.Contains(got, "--to '123@g.us'") {
		t.Fatalf("a group must keep the chat JID, got %q", got)
	}
}

// A contact name with an apostrophe stays one shell argument.
func TestNotificationReplyCommandQuotesAName(t *testing.T) {
	ctx := NotifContext{ContactSaved: true, IsDirectChat: true, ContactName: "O'Brien", ChatJID: "x@s.whatsapp.net"}
	got := notificationReplyCommand(ctx)
	want := `whatsapp send --to 'O'"'"'Brien' --message -`
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

// The name a reply names must resolve back to the peer's deliverable phone JID, so addressing by
// name reaches the same person the chat JID would, on the receipt-bearing address (see #1961).
func TestReplyNameRoundTripsToTheDeliverablePhoneJID(t *testing.T) {
	wac := newOutgoingTestClient(t)
	phone, err := types.ParseJID(outgoingPhoneJID)
	if err != nil {
		t.Fatalf("failed to parse phone jid: %v", err)
	}
	if _, err := wac.AddContact("Emmy", "+"+phone.User); err != nil {
		t.Fatalf("failed to save contact: %v", err)
	}

	ctx := NotifContext{ContactSaved: true, IsDirectChat: true, ContactName: "Emmy", ChatJID: outgoingPhoneJID}
	if got := notificationReplyCommand(ctx); !strings.Contains(got, "--to 'Emmy'") {
		t.Fatalf("a saved direct contact must be addressed by name, got %q", got)
	}

	resolved, err := wac.ResolveRecipient("Emmy")
	if err != nil {
		t.Fatalf("the emitted name must resolve, got %v", err)
	}
	if resolved.String() != outgoingPhoneJID {
		t.Errorf("name must resolve to the deliverable phone JID %q, got %q", outgoingPhoneJID, resolved)
	}
	if resolved.Server != types.DefaultUserServer {
		t.Errorf("name must resolve to a phone-server JID, got %v", resolved.Server)
	}
}

// When a group shares the saved contact's name, the reply keeps the chat JID, so it can never
// resolve to the group by that ambiguous name.
func TestNotificationReplyCommandKeepsTheJIDWhenAGroupSharesTheName(t *testing.T) {
	ctx := NotifContext{
		ContactSaved: true, IsDirectChat: true, ContactName: "Book Club",
		NameSharedWithGroup: true, ChatJID: "15551110000@s.whatsapp.net",
	}
	got := notificationReplyCommand(ctx)
	if !strings.Contains(got, "--to '15551110000@s.whatsapp.net'") {
		t.Fatalf("a name shared with a group must fall back to the chat JID, got %q", got)
	}
}

// buildNotifContext flags a saved direct contact whose name a group also holds, and leaves a name no
// group holds unflagged, so the reply command names the contact only when that name is unambiguous.
func TestBuildNotifContextFlagsANameAGroupShares(t *testing.T) {
	wac := newOutgoingTestClient(t)
	if err := wac.store.StoreChat("120363021234567890@g.us", "Book Club", time.Now()); err != nil {
		t.Fatalf("failed to seed group: %v", err)
	}

	shared := wac.buildNotifContext("15551110000@s.whatsapp.net", "Book Club", "Book Club", "Book Club", "+15551110000", true, true)
	if !shared.NameSharedWithGroup {
		t.Errorf("a saved contact name a group also holds must be flagged")
	}

	distinct := wac.buildNotifContext("15551110000@s.whatsapp.net", "Alice", "Alice", "Alice", "+15551110000", true, true)
	if distinct.NameSharedWithGroup {
		t.Errorf("a name no group holds must not be flagged")
	}
}
