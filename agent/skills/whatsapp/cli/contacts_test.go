package main

import (
	"context"
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

// A peer confirmed by chat id stays confirmed once whatsmeow learns their phone number. Learning
// the mapping moves the canonical key from the LID to the phone JID, so a gate that read only the
// canonical key would stop seeing the saved row and ask the user to confirm the same person twice.
func TestRequireManualContactSurvivesTheLIDMappingBeingLearned(t *testing.T) {
	wac := newOutgoingTestClient(t)
	lid := types.NewJID("99988877766655", types.HiddenUserServer)
	phone := types.NewJID("15551110000", types.DefaultUserServer)

	if _, err := wac.AddContactByChat("Ana", lid.String()); err != nil {
		t.Fatalf("failed to save contact by chat id: %v", err)
	}
	if err := wac.requireManualContact(lid); err != nil {
		t.Fatalf("a peer confirmed by chat id must pass the gate, got %v", err)
	}

	if err := wac.client.Store.LIDs.PutLIDMapping(context.Background(), lid, phone); err != nil {
		t.Fatalf("failed to record the learned mapping: %v", err)
	}

	for _, jid := range []types.JID{lid, phone} {
		if err := wac.requireManualContact(jid); err != nil {
			t.Errorf("peer addressed as %s must still pass the gate, got %v", jid, err)
		}
	}
}

// splitContactLID and splitContactPhone are one peer addressed both ways, confirmed under each.
const (
	splitContactLID   = "99988877766655@lid"
	splitContactPhone = "15551110000@s.whatsapp.net"
)

// saveContactUnderBothKeys reaches the split state a box gets to on its own: the peer is confirmed
// by chat id while they have no known number, whatsmeow then learns their number, and the peer is
// confirmed again by that number, leaving the same person holding one contact row under each key.
// The two names are separate because the user answers "who is this" once per key form and can
// answer differently, so the rows of one peer need not carry the same name.
func saveContactUnderBothKeys(t *testing.T, wac *WhatsAppClient, chatName, phoneName string) (lid, phone types.JID) {
	t.Helper()
	lid, phone = types.NewJID("99988877766655", types.HiddenUserServer), types.NewJID("15551110000", types.DefaultUserServer)

	if _, err := wac.AddContactByChat(chatName, lid.String()); err != nil {
		t.Fatalf("failed to save the peer by chat id: %v", err)
	}
	if err := wac.client.Store.LIDs.PutLIDMapping(context.Background(), lid, phone); err != nil {
		t.Fatalf("failed to record the learned mapping: %v", err)
	}
	if _, err := wac.AddContact(phoneName, "+"+phone.User); err != nil {
		t.Fatalf("failed to save the peer by phone: %v", err)
	}

	for _, key := range []string{splitContactLID, splitContactPhone} {
		contact, err := wac.store.GetManualContact(key)
		if err != nil || contact == nil {
			t.Fatalf("the peer must hold a row under %s for this to be the split state, got %v (%v)", key, contact, err)
		}
	}
	return lid, phone
}

// Revoking a contact must close the send gate for that peer under every form they can be addressed
// by, whichever form the revoke names. The gate passes on any one of a peer's key forms, so a row
// left behind keeps sending to someone the user just revoked, which is the ban risk the gate exists
// for. Every accepted identifier is covered because they all revoke the same one person.
func TestRemoveContactClosesTheGateUnderEveryKeyForm(t *testing.T) {
	for _, identifier := range []string{"Ana", "+15551110000", splitContactLID} {
		t.Run(identifier, func(t *testing.T) {
			wac := newOutgoingTestClient(t)
			lid, phone := saveContactUnderBothKeys(t, wac, "Ana", "Ana")

			if _, err := cmdRemoveContact([]string{"--identifier", identifier}, wac); err != nil {
				t.Fatalf("revoking by %q must succeed, got %v", identifier, err)
			}

			for _, jid := range []types.JID{phone, lid} {
				if err := wac.requireManualContact(jid); err == nil {
					t.Errorf("revoked peer addressed as %s still passes the gate", jid)
				}
			}
		})
	}
}

// A name matches on the name column alone, so in the split state it reaches only the rows carrying
// that exact name and the peer's other row survives under a different one. That surviving row keeps
// the gate open under BOTH key forms, because the gate passes on any one of them, so revoking by a
// name the peer answers to must clear every key form of the peer behind the rows it matched.
func TestRemoveContactByNameClosesTheGateWhenTheSplitRowsCarryDifferentNames(t *testing.T) {
	wac := newOutgoingTestClient(t)
	lid, phone := saveContactUnderBothKeys(t, wac, "Ana", "Ana Garcia")

	if _, err := cmdRemoveContact([]string{"--identifier", "Ana"}, wac); err != nil {
		t.Fatalf("revoking by name must succeed, got %v", err)
	}

	for _, jid := range []types.JID{phone, lid} {
		if err := wac.requireManualContact(jid); err == nil {
			t.Errorf("revoked peer addressed as %s still passes the gate", jid)
		}
	}
}

// The inbound notification and the send gate must agree about who is saved. A peer confirmed by
// chat id keeps passing the gate once whatsmeow learns their number, so a notification reading one
// key alone would report that same peer as unknown, and following that report saves the person a
// second time under their other key.
func TestNotificationNamesAPeerSavedByChatIDAfterTheMappingIsLearned(t *testing.T) {
	wac := newOutgoingTestClient(t)
	lid := types.NewJID("99988877766655", types.HiddenUserServer)
	phone := types.NewJID("15551110000", types.DefaultUserServer)

	if _, err := wac.AddContactByChat("Ana", lid.String()); err != nil {
		t.Fatalf("failed to save the peer by chat id: %v", err)
	}
	if err := wac.client.Store.LIDs.PutLIDMapping(context.Background(), lid, phone); err != nil {
		t.Fatalf("failed to record the learned mapping: %v", err)
	}

	_, senderDisplay, contactName, contactPhone, contactSaved, _ := wac.prepareNotificationInfo(
		types.MessageSource{Chat: lid, Sender: lid, SenderAlt: phone},
	)

	if !contactSaved {
		t.Errorf("a peer the gate treats as confirmed must not be reported as unknown")
	}
	if contactName != "Ana" || senderDisplay != "Ana" {
		t.Errorf("expected the saved name, got contact_name %q and sender %q", contactName, senderDisplay)
	}
	if contactPhone != "+"+phone.User {
		t.Errorf("expected the learned number %q, got %q", "+"+phone.User, contactPhone)
	}
}

// A saved contact name is the word a reply command addresses, so two different people cannot share
// one. Saving a name already held by a different number is refused with a distinct-name remedy, so
// `whatsapp send --to '<name>'` always names exactly one person.
func TestAddContactRejectsDuplicateNameForADifferentNumber(t *testing.T) {
	wac := newOutgoingTestClient(t)
	if _, err := wac.AddContact("Emmy", "+15551110000"); err != nil {
		t.Fatalf("first save must succeed, got %v", err)
	}
	_, err := wac.AddContact("Emmy", "+447700900123")
	if err == nil || !strings.Contains(err.Error(), "already exists") {
		t.Fatalf("a name already used by another number must be refused, got %v", err)
	}
}

// A duplicate name matches after trimming and ignoring case, so a near-copy cannot slip past the
// rule and reintroduce the ambiguity.
func TestAddContactDuplicateNameIgnoresCaseAndSpace(t *testing.T) {
	wac := newOutgoingTestClient(t)
	if _, err := wac.AddContact("Emmy", "+15551110000"); err != nil {
		t.Fatalf("first save must succeed, got %v", err)
	}
	_, err := wac.AddContact("  emmy ", "+447700900123")
	if err == nil || !strings.Contains(err.Error(), "already exists") {
		t.Fatalf("a name differing only by case or spacing must still collide, got %v", err)
	}
}

// Renaming or re-saving the same number is an update, never a collision with itself.
func TestAddContactAllowsRenamingAndReSavingTheSameNumber(t *testing.T) {
	wac := newOutgoingTestClient(t)
	if _, err := wac.AddContact("Emmy", "+15551110000"); err != nil {
		t.Fatalf("first save must succeed, got %v", err)
	}
	if _, err := wac.AddContact("Emmy", "+15551110000"); err != nil {
		t.Errorf("re-saving the same name and number must succeed, got %v", err)
	}
	if _, err := wac.AddContact("Emmy R", "+15551110000"); err != nil {
		t.Errorf("renaming the same number must succeed, got %v", err)
	}
}

// One peer holds a row under each key form (phone JID and LID), and those rows may carry the same
// name, so saving the phone row for a peer already saved by chat id is the same person, not a clash.
func TestAddContactAllowsTheSameNameForOnePeerUnderBothKeyForms(t *testing.T) {
	wac := newOutgoingTestClient(t)
	lid := types.NewJID("99988877766655", types.HiddenUserServer)
	phone := types.NewJID("15551110000", types.DefaultUserServer)

	if _, err := wac.AddContactByChat("Emmy", lid.String()); err != nil {
		t.Fatalf("saving by chat id must succeed, got %v", err)
	}
	if err := wac.client.Store.LIDs.PutLIDMapping(context.Background(), lid, phone); err != nil {
		t.Fatalf("failed to record the learned mapping: %v", err)
	}
	if _, err := wac.AddContact("Emmy", "+"+phone.User); err != nil {
		t.Errorf("the same peer's phone row must not collide with their own LID row, got %v", err)
	}
}

// A dual-key peer holds two rows under one name, one LID and one phone JID, so the name the reply
// command emits matches both. Both rows are the same person, so the name must resolve to that one
// peer's deliverable phone JID rather than fail as ambiguous (#1961).
func TestResolveRecipientCollapsesADualKeyPeerToItsPhoneJID(t *testing.T) {
	wac := newOutgoingTestClient(t)
	saveContactUnderBothKeys(t, wac, "Emmy", "Emmy")

	resolved, err := wac.ResolveRecipient("Emmy")
	if err != nil {
		t.Fatalf("a name held by one peer under both key forms must resolve, got %v", err)
	}
	if resolved.String() != splitContactPhone {
		t.Errorf("name must resolve to the deliverable phone JID %q, got %q", splitContactPhone, resolved)
	}
	if resolved.Server != types.DefaultUserServer {
		t.Errorf("name must resolve to a phone-server JID, got %v", resolved.Server)
	}
}

// Two genuinely different people cannot share one name a reply command emits, so a name held by
// two distinct peers stays ambiguous and is refused with the disambiguation remedy.
func TestResolveRecipientStillErrorsForDifferentPeersSharingAName(t *testing.T) {
	wac := newOutgoingTestClient(t)
	if _, err := wac.store.SaveManualContact("Emmy", "+15551110000"); err != nil {
		t.Fatalf("failed to seed first peer: %v", err)
	}
	if _, err := wac.store.SaveManualContact("Emmy", "+447700900123"); err != nil {
		t.Fatalf("failed to seed second peer: %v", err)
	}

	_, err := wac.ResolveRecipient("Emmy")
	if err == nil || !strings.Contains(err.Error(), "multiple contacts share the exact name") {
		t.Fatalf("a name held by two different peers must stay ambiguous, got %v", err)
	}
	// The error names each colliding number, so the caller can address the right one instead of guessing.
	if !strings.Contains(err.Error(), "+15551110000") || !strings.Contains(err.Error(), "+447700900123") {
		t.Errorf("the ambiguity error must name both colliding numbers, got %v", err)
	}
}

// A token that is not a chat id at all must be named as one. Reporting a mistyped id as a group
// is the one answer that stops the caller retrying, since a group genuinely needs no contact.
func TestAddContactByChatRefusesAMalformedChatID(t *testing.T) {
	wac := newOutgoingTestClient(t)

	for _, chat := range []string{"Ana", "15551234567", "+15551234567"} {
		_, err := wac.AddContactByChat("Ana", chat)
		if err == nil || !strings.Contains(err.Error(), "is not a chat id") {
			t.Errorf("AddContactByChat(%q) must be refused as a malformed chat id, got %v", chat, err)
			continue
		}
		if strings.Contains(err.Error(), "is a group") {
			t.Errorf("AddContactByChat(%q) must not be reported as a group, got %v", chat, err)
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
