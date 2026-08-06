package main

import (
	"strings"
	"testing"

	"go.mau.fi/whatsmeow/types"
)

// groupIDDigits is a WhatsApp group ID rendered numerically: all digits, but
// longer than any E.164 phone number.
const groupIDDigits = "120363419527129553"

func newTestStore(t *testing.T) *MessageStore {
	t.Helper()
	store, err := NewMessageStore(t.TempDir())
	if err != nil {
		t.Fatalf("failed to create message store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	return store
}

func TestSaveManualContactRejectsGroupIDAsPhone(t *testing.T) {
	store := newTestStore(t)
	_, err := store.SaveManualContact("Test Group", "+"+groupIDDigits)
	if err == nil || !strings.Contains(err.Error(), "group ID") {
		t.Errorf("saving a group ID as a phone must fail with a group-ID error, got %v", err)
	}
}

func TestSaveManualContactAcceptsPhone(t *testing.T) {
	store := newTestStore(t)
	contact, err := store.SaveManualContact("Alice", "+15551234567")
	if err != nil {
		t.Fatalf("saving a valid phone must succeed, got %v", err)
	}
	if contact.PhoneNumber != "+15551234567" {
		t.Errorf("expected phone +15551234567, got %q", contact.PhoneNumber)
	}
}

func TestResolveRecipientRejectsGroupIDAsPhone(t *testing.T) {
	wac := &WhatsAppClient{}
	for _, identifier := range []string{
		"+" + groupIDDigits,
		groupIDDigits,
		groupIDDigits + "@s.whatsapp.net",
	} {
		_, err := wac.ResolveRecipient(identifier)
		if err == nil || !strings.Contains(err.Error(), "group ID") {
			t.Errorf("ResolveRecipient(%q) must fail with a group-ID error, got %v", identifier, err)
		}
	}
}

func TestResolveRecipientAllowsMaxLengthPhone(t *testing.T) {
	wac := &WhatsAppClient{}
	jid, err := wac.ResolveRecipient("+123456789012345")
	if err != nil {
		t.Fatalf("a 15-digit phone must resolve, got %v", err)
	}
	if jid.User != "123456789012345" || jid.Server != types.DefaultUserServer {
		t.Errorf("expected user JID for 15-digit phone, got %v", jid)
	}
}

func TestResolveRecipientAllowsGroupJID(t *testing.T) {
	wac := &WhatsAppClient{}
	jid, err := wac.ResolveRecipient(groupIDDigits + "@" + types.GroupServer)
	if err != nil {
		t.Fatalf("an explicit group JID must resolve, got %v", err)
	}
	if jid.Server != types.GroupServer {
		t.Errorf("expected group JID, got %v", jid)
	}
}

func TestResolveRecipientRejectsSavedGroupIDContact(t *testing.T) {
	store := newTestStore(t)
	jid := groupIDDigits + "@" + types.DefaultUserServer
	if _, err := store.db.Exec(
		`INSERT INTO contacts (jid, phone_number, name, added_at, updated_at)
		 VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)`,
		jid, "+"+groupIDDigits, "Legacy Bad Contact",
	); err != nil {
		t.Fatalf("failed to seed legacy contact: %v", err)
	}

	wac := &WhatsAppClient{store: store}
	_, err := wac.ResolveRecipient("Legacy Bad Contact")
	if err == nil || !strings.Contains(err.Error(), "group ID") {
		t.Errorf("a previously saved group-ID contact must not resolve to a user JID, got %v", err)
	}
}

// A peer addressed by their LID passes the same saved-contact gate as the same peer addressed by
// their phone JID. Both forms are valid send targets, so gating only the phone form would let an
// outbound reach a person the user never confirmed, which is the ban risk the gate exists for.
func TestRequireManualContactGatesALIDLikeThePhoneJID(t *testing.T) {
	wac := newOutgoingTestClient(t)
	lid, err := types.ParseJID(outgoingLIDJID)
	if err != nil {
		t.Fatalf("failed to parse lid: %v", err)
	}
	phone, err := types.ParseJID(outgoingPhoneJID)
	if err != nil {
		t.Fatalf("failed to parse phone jid: %v", err)
	}
	// The phone the harness maps the LID to: the one number both forms must be gated by.
	peerPhone := "+" + phone.User

	for _, jid := range []types.JID{lid, phone} {
		err := wac.requireManualContact(jid)
		if err == nil || !strings.Contains(err.Error(), "No saved contact found for "+peerPhone) {
			t.Errorf("unsaved peer %s must be refused naming %s, got %v", jid, peerPhone, err)
		}
	}

	if _, err := wac.store.SaveManualContact("Ana", peerPhone); err != nil {
		t.Fatalf("failed to save contact: %v", err)
	}

	for _, jid := range []types.JID{lid, phone} {
		if err := wac.requireManualContact(jid); err != nil {
			t.Errorf("saved peer %s must pass the gate, got %v", jid, err)
		}
	}
}

// A LID with no phone mapping resolves to nobody, so it cannot have been confirmed and is refused.
// Its user part is an internal id, never a phone, so the refusal must not render it as one.
func TestRequireManualContactRefusesAnUnmappedLID(t *testing.T) {
	wac := newOutgoingTestClient(t)
	unmapped := types.NewJID("99988877766655", types.HiddenUserServer)

	err := wac.requireManualContact(unmapped)
	if err == nil || !strings.Contains(err.Error(), "No saved contact found") {
		t.Fatalf("an unmapped LID must be refused, got %v", err)
	}
	if strings.Contains(err.Error(), "+99988877766655") {
		t.Errorf("refusal must not render a LID as a phone number, got %v", err)
	}
}

// The refusal for an unmapped LID must name a remedy that works: a peer with no phone number
// cannot be saved by number, so the gate would otherwise refuse that chat forever and every reply
// to it, since a reply targets the raw chat JID. This follows the printed command literally.
func TestUnmappedLIDPassesTheGateAfterTheRefusalsOwnCommand(t *testing.T) {
	wac := newOutgoingTestClient(t)
	unmapped := types.NewJID("99988877766655", types.HiddenUserServer)

	err := wac.requireManualContact(unmapped)
	wanted := "run add-contact --name <name> --chat " + unmapped.String()
	if err == nil || !strings.Contains(err.Error(), wanted) {
		t.Fatalf("refusal must name %q, got %v", wanted, err)
	}

	if _, err := cmdAddContact([]string{"--name", "Ana", "--chat", unmapped.String()}, wac); err != nil {
		t.Fatalf("the command the refusal names must work, got %v", err)
	}

	if err := wac.requireManualContact(unmapped); err != nil {
		t.Errorf("a peer confirmed by chat id must pass the gate, got %v", err)
	}
}

// Saving by chat id is confirmation of one identity, not a second one: a LID that does map to a
// phone saves under the phone JID, so the peer stays one contact addressable either way.
func TestAddContactByChatSavesAMappedLIDUnderItsPhoneJID(t *testing.T) {
	wac := newOutgoingTestClient(t)

	contact, err := wac.AddContactByChat("Ana", outgoingLIDJID)
	if err != nil {
		t.Fatalf("failed to save contact by chat id: %v", err)
	}
	if contact.JID != outgoingPhoneJID {
		t.Errorf("expected the contact keyed by %q, got %q", outgoingPhoneJID, contact.JID)
	}

	for _, raw := range []string{outgoingLIDJID, outgoingPhoneJID} {
		jid, err := types.ParseJID(raw)
		if err != nil {
			t.Fatalf("failed to parse %q: %v", raw, err)
		}
		if err := wac.requireManualContact(jid); err != nil {
			t.Errorf("peer addressed as %s must pass the gate, got %v", raw, err)
		}
	}
}

// The gate still refuses an unmapped LID nobody confirmed, and a group id is not a person to save.
func TestAddContactByChatRefusesAGroup(t *testing.T) {
	wac := newOutgoingTestClient(t)

	if _, err := wac.AddContactByChat("Team", types.NewJID(groupIDDigits, types.GroupServer).String()); err == nil {
		t.Error("a group must not be saveable as a contact")
	}
	if err := wac.requireManualContact(types.NewJID("12312312312312", types.HiddenUserServer)); err == nil {
		t.Error("an unconfirmed LID must stay refused")
	}
}

// Groups carry no saved-contact requirement; only people do.
func TestRequireManualContactLeavesGroupsUngated(t *testing.T) {
	wac := newOutgoingTestClient(t)

	if err := wac.requireManualContact(types.NewJID(groupIDDigits, types.GroupServer)); err != nil {
		t.Errorf("a group must not require a saved contact, got %v", err)
	}
}
