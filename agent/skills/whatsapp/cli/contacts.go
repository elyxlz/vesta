package main

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	"go.mau.fi/whatsmeow/types"
)

func (wac *WhatsAppClient) AddContact(name, phone string) (Contact, error) {
	if digits, _, err := normalizePhoneInput(phone); err == nil {
		peer := wac.canonicalChatJID(types.NewJID(digits, types.DefaultUserServer))
		if err := wac.rejectDuplicateContactName(name, peer); err != nil {
			return Contact{}, err
		}
	}
	return wac.store.SaveManualContact(name, phone)
}

// rejectDuplicateContactName keeps every saved name pointing at one person, so `whatsapp send --to
// '<name>'` and the reply command that emits a name are never ambiguous. The peer's own rows are
// excluded: one person holds a row under each of their key forms (phone JID and LID), so re-saving
// or renaming the same person is an update, never a clash. The match is case-insensitive and trimmed
// so a near-copy cannot reintroduce the ambiguity.
func (wac *WhatsAppClient) rejectDuplicateContactName(name string, peer types.JID) error {
	trimmed := strings.TrimSpace(name)
	if trimmed == "" {
		return nil
	}
	existing, err := wac.store.ManualContactsByName(trimmed)
	if err != nil {
		return fmt.Errorf("failed to check for a duplicate contact name: %v", err)
	}
	own := make(map[string]struct{})
	for _, key := range wac.contactKeys(peer) {
		own[key] = struct{}{}
	}
	for _, contact := range existing {
		if _, mine := own[contact.JID]; mine {
			continue
		}
		return fmt.Errorf(
			"a contact named '%s' already exists (%s); choose a distinct name like '%s R' so a reply names one person",
			trimmed, contactLabel(contact), trimmed,
		)
	}
	return nil
}

// contactLabel names the peer already holding a name, its number when known, otherwise its chat id.
func contactLabel(contact Contact) string {
	if contact.PhoneNumber != "" {
		return contact.PhoneNumber
	}
	return contact.JID
}

// AddContactByChat saves a contact for a chat given by its own id, the form for a peer WhatsApp
// addresses only by a LID: there is no phone number to save them under. The key is the same
// canonical identity requireManualContact checks, so a LID that does map to a phone saves under
// the phone JID and stays one contact with one number.
func (wac *WhatsAppClient) AddContactByChat(name, chat string) (Contact, error) {
	jid, err := types.ParseJID(strings.TrimSpace(chat))
	if err != nil {
		return Contact{}, fmt.Errorf("invalid chat id '%s': %v", chat, err)
	}
	// A token with no '@' parses into a JID whose user part is empty rather than failing, so it
	// has to be refused here; left to the group check below it would be reported as a group, the
	// one answer that stops a caller from retrying with a corrected id.
	if jid.User == "" {
		return Contact{}, fmt.Errorf(
			"'%s' is not a chat id: a chat id is a user part and a server, like 12345@lid or 15551234567@s.whatsapp.net. To save someone by phone number, use --phone +15551234567",
			chat,
		)
	}
	if !isDirectChatJID(jid) {
		return Contact{}, fmt.Errorf("'%s' is a group, not a person; only people need a saved contact", chat)
	}
	peer := wac.canonicalChatJID(jid)
	if err := wac.rejectDuplicateContactName(name, peer); err != nil {
		return Contact{}, err
	}
	if peer.Server == types.DefaultUserServer {
		return wac.store.SaveManualContact(name, "+"+peer.User)
	}
	return wac.store.SaveManualContactByChatJID(name, peer.String())
}

// RemoveContact revokes a user-confirmed contact, named by contact name, phone number, or chat id.
// Whichever form names them, the revoke clears every key form the peers behind it can be filed
// under, because the send gate passes on any one of them and a row left behind would keep sending
// to someone the user just revoked. A name reaches its peers through the rows carrying it, since
// the user is asked to confirm a peer once per key form and the two rows can carry different names.
func (wac *WhatsAppClient) RemoveContact(identifier string) error {
	named, err := wac.store.ManualContactJIDsByName(identifier)
	if err != nil {
		return err
	}

	keys := wac.contactKeysOf(named)
	if len(keys) == 0 {
		jid, parseErr := contactIdentifierJID(identifier)
		if parseErr != nil {
			return fmt.Errorf("contact not found: %s", identifier)
		}
		keys = wac.contactKeys(jid)
	}

	removed, err := wac.store.DeleteManualContactsByJID(keys)
	if err != nil {
		return err
	}
	if !removed {
		return fmt.Errorf("contact not found: %s", identifier)
	}
	return nil
}

// contactKeysOf unions the key forms of the peers behind the given contact rows. Each row's own key
// is kept as well, so a row whose peer no longer resolves to it is still cleared.
func (wac *WhatsAppClient) contactKeysOf(rowJIDs []string) []string {
	keys := make([]string, 0, len(rowJIDs)*2)
	for _, raw := range rowJIDs {
		keys = append(keys, raw)
		if jid, err := types.ParseJID(raw); err == nil {
			keys = append(keys, wac.contactKeys(jid)...)
		}
	}
	return keys
}

// contactIdentifierJID reads the address forms remove-contact accepts: a chat id as itself, and a
// phone number as its phone JID.
func contactIdentifierJID(identifier string) (types.JID, error) {
	trimmed := strings.TrimSpace(identifier)
	if strings.Contains(trimmed, "@") {
		return types.ParseJID(trimmed)
	}
	digits, _, err := normalizePhoneInput(trimmed)
	if err != nil {
		return types.JID{}, err
	}
	return types.NewJID(digits, types.DefaultUserServer), nil
}

// MaxPhoneDigits is the E.164 ceiling on phone-number length. A WhatsApp
// group ID renders as a longer all-digit string; sending to one as a user JID
// makes the server log the device out and destroys the pairing (#1169).
const MaxPhoneDigits = 15

func errIfGroupIDDigits(digits string) error {
	if len(digits) <= MaxPhoneDigits {
		return nil
	}
	return fmt.Errorf(
		"'%s' looks like a WhatsApp group ID, not a phone number (%d digits; phone numbers have at most %d). To message a group, use its group name: send --to '<Group Name>'",
		digits, len(digits), MaxPhoneDigits,
	)
}

// contactKeys returns every key one peer's saved contact can be filed under: their canonical
// identity plus its LID<->PN counterpart. WhatsApp addresses one person both by phone JID and by
// LID, and a contact is saved under whichever key was known when the user confirmed them, so this
// is the one owner of "which rows are this peer's contact": the send gate, the inbound
// notification, and a revoke all resolve a peer through here and therefore cannot disagree about
// who is saved. A group has no counterpart and yields a single key.
func (wac *WhatsAppClient) contactKeys(chat types.JID) []string {
	peer := wac.canonicalChatJID(chat)
	return storageKeys(peer, wac.mappedJID(peer))
}

// lookupManualContact loads a peer's saved contact under any of their key forms, nil when the user
// has confirmed nobody at that identity.
func (wac *WhatsAppClient) lookupManualContact(chat types.JID) (*Contact, error) {
	for _, key := range wac.contactKeys(chat) {
		contact, err := wac.store.GetManualContact(key)
		if err != nil {
			return nil, err
		}
		if contact != nil {
			return contact, nil
		}
	}
	return nil, nil
}

// requireManualContact is the saved-contact half of the ban gate: every person the device
// messages must have been confirmed by the user first. It covers a direct chat addressed
// either way, since a peer confirmed by chat id while they had no phone mapping is saved under
// their LID, and once whatsmeow learns the mapping the canonical key becomes their phone JID, so
// checking one key alone would ask the user to confirm the same person twice. A LID with no phone
// mapping is a peer with no number, so the refusal asks for it to be saved by chat id. Groups
// carry no such requirement.
func (wac *WhatsAppClient) requireManualContact(jid types.JID) error {
	if !isDirectChatJID(jid) {
		return nil
	}

	contact, err := wac.lookupManualContact(jid)
	if err != nil {
		return fmt.Errorf("failed to verify saved contacts: %v", err)
	}
	if contact != nil {
		return nil
	}

	peer := wac.canonicalChatJID(jid)
	who, target := "this chat", "--chat "+peer.String()
	if peer.Server == types.DefaultUserServer && peer.User != "" {
		who, target = "+"+peer.User, "--phone +"+peer.User
	}
	return fmt.Errorf(
		"No saved contact found for %s. Ask the user who this is, then run add-contact --name <name> %s.",
		who, target,
	)
}

func (wac *WhatsAppClient) ResolveRecipient(identifier string) (types.JID, error) {
	jid, err := wac.resolveRecipientJID(identifier)
	if err != nil {
		return types.JID{}, err
	}
	if jid.Server == types.DefaultUserServer {
		if err := errIfGroupIDDigits(jid.User); err != nil {
			return types.JID{}, err
		}
	}
	return jid, nil
}

func (wac *WhatsAppClient) resolveRecipientJID(identifier string) (types.JID, error) {
	if identifier == "" {
		return types.JID{}, fmt.Errorf("recipient identifier cannot be empty")
	}

	if strings.Contains(identifier, "@") {
		jid, err := types.ParseJID(identifier)
		if err != nil {
			return types.JID{}, fmt.Errorf("invalid WhatsApp address '%s': %v. Use a phone number (+1234567890) or saved contact/group name instead", identifier, err)
		}
		return jid, nil
	}

	if strings.HasPrefix(identifier, "+") {
		phone := strings.TrimPrefix(identifier, "+")
		if !isNumeric(phone) {
			return types.JID{}, fmt.Errorf("invalid phone number '%s': must contain only digits after '+'", identifier)
		}
		return types.NewJID(phone, types.DefaultUserServer), nil
	}

	if isNumeric(identifier) {
		return types.NewJID(identifier, types.DefaultUserServer), nil
	}

	// Both are searched with the same name-filtered query, cheap enough to run together so a name
	// that reaches both a contact and a group can be caught before either resolves.
	contacts, contactsErr := wac.store.SearchContacts(identifier, 50)
	groups, groupsErr := wac.store.SearchGroups(identifier, 50)

	// A bare name that exactly matches both a saved contact and a group is ambiguous: refuse it so a
	// message never goes silently to the wrong one. The contact is the one name the caller controls,
	// so the remedy renames it; the contact stays reachable meanwhile by their phone number.
	if contactsErr == nil && groupsErr == nil && hasExactName(contactNames(contacts), identifier) && hasExactName(groupNames(groups), identifier) {
		return types.JID{}, fmt.Errorf(
			"'%s' is both a saved contact and a group; give the contact a different name so the name reaches one recipient, or address them by their phone number",
			identifier,
		)
	}

	if contactsErr == nil {
		if jid, err := wac.resolveFromContacts(contacts, identifier); err != nil || jid.User != "" {
			return jid, err
		}
	}

	if groupsErr == nil {
		if jid, err := resolveFromGroups(groups, identifier); err != nil || jid.User != "" {
			return jid, err
		}
	}

	return types.JID{}, fmt.Errorf("no contact or group found matching '%s'. Use search_contacts or list_groups to find available recipients", identifier)
}

// nameEquals is the one owner of "these two names are the same recipient name": non-empty, equal
// once trimmed, ignoring case. Contact and group matching both go through it so they cannot drift.
func nameEquals(candidate, target string) bool {
	return candidate != "" && strings.EqualFold(strings.TrimSpace(candidate), strings.TrimSpace(target))
}

func hasExactName(candidates []string, target string) bool {
	for _, candidate := range candidates {
		if nameEquals(candidate, target) {
			return true
		}
	}
	return false
}

func contactNames(contacts []Contact) []string {
	names := make([]string, len(contacts))
	for i, c := range contacts {
		names[i] = c.Name
	}
	return names
}

func groupNames(groups []Chat) []string {
	names := make([]string, len(groups))
	for i, g := range groups {
		names[i] = g.Name
	}
	return names
}

// nameSharedWithGroup reports whether a group holds the exact name, used to keep a reply on the chat
// JID when a saved contact's name would otherwise resolve ambiguously.
func (wac *WhatsAppClient) nameSharedWithGroup(name string) bool {
	if wac.store == nil {
		return false
	}
	groups, err := wac.store.SearchGroups(name, 50)
	if err != nil {
		return false
	}
	return hasExactName(groupNames(groups), name)
}

func (wac *WhatsAppClient) resolveFromContacts(contacts []Contact, identifier string) (types.JID, error) {
	if len(contacts) == 0 {
		return types.JID{}, nil
	}

	if jid, handled, err := wac.preferExactContactMatch(contacts, identifier); handled {
		return jid, err
	}

	if len(contacts) == 1 {
		jid, err := types.ParseJID(contacts[0].JID)
		if err != nil {
			return types.JID{}, fmt.Errorf("could not read the saved contact identifier: %v", err)
		}
		return jid, nil
	}

	var names []string
	for i, c := range contacts {
		if i >= 5 {
			names = append(names, "...")
			break
		}
		displayName := c.Name
		if displayName == "" {
			displayName = c.PhoneNumber
		}
		names = append(names, fmt.Sprintf("%s (%s)", displayName, c.PhoneNumber))
	}
	return types.JID{}, fmt.Errorf("multiple contacts match '%s': %s. Please use full name or phone number",
		identifier, strings.Join(names, ", "))
}

func (wac *WhatsAppClient) preferExactContactMatch(contacts []Contact, identifier string) (types.JID, bool, error) {
	trimmed := strings.TrimSpace(identifier)
	if trimmed == "" {
		return types.JID{}, false, nil
	}

	var matches []Contact
	for _, c := range contacts {
		if nameEquals(c.Name, trimmed) {
			matches = append(matches, c)
		}
	}

	if len(matches) > 1 {
		return wac.collapseSamePeerMatches(matches, identifier)
	}

	if len(matches) == 1 {
		jid, err := types.ParseJID(matches[0].JID)
		return jid, true, err
	}

	digits := digitsOnly(trimmed)
	if digits == "" {
		return types.JID{}, false, nil
	}

	// At most one row can hold a given non-empty phone number: the jid is the primary key and is
	// derived from those digits, so a repeat save upserts the same row rather than adding a second.
	var phoneMatch *Contact
	for i := range contacts {
		if digitsOnly(contacts[i].PhoneNumber) == digits {
			phoneMatch = &contacts[i]
		}
	}

	if phoneMatch == nil {
		return types.JID{}, false, nil
	}

	jid, err := types.ParseJID(phoneMatch.JID)
	return jid, true, err
}

// collapseSamePeerMatches folds exact-name matches that resolve to one peer into that peer's
// deliverable phone JID: one person holds a row under each key form (phone JID and LID), so a name
// held under both is not ambiguous. It reuses canonicalChatJID, the one owner of peer identity, so
// the collapse cannot disagree with the send gate about who two rows are. canonicalChatJID resolves
// a LID to its phone JID, so the returned identity is the deliverable phone form. The name stays
// ambiguous only when the matches are genuinely different peers.
func (wac *WhatsAppClient) collapseSamePeerMatches(matches []Contact, identifier string) (types.JID, bool, error) {
	var peer types.JID
	seen := make(map[string]struct{})
	var labels []string
	for _, c := range matches {
		jid, err := types.ParseJID(c.JID)
		if err != nil {
			return types.JID{}, true, err
		}
		canonical := wac.canonicalChatJID(jid)
		if _, known := seen[canonical.String()]; known {
			continue
		}
		seen[canonical.String()] = struct{}{}
		labels = append(labels, contactLabel(c))
		if peer.IsEmpty() {
			peer = canonical
		}
	}
	if len(seen) > 1 {
		return types.JID{}, true, fmt.Errorf(
			"multiple contacts share the exact name '%s' (%s); address one by their exact phone number, or give one a different name",
			identifier, strings.Join(labels, ", "),
		)
	}
	return peer, true, nil
}

func resolveFromGroups(groups []Chat, identifier string) (types.JID, error) {
	var matches []Chat
	lowerIdentifier := strings.ToLower(identifier)
	for _, g := range groups {
		if strings.Contains(strings.ToLower(g.Name), lowerIdentifier) {
			matches = append(matches, g)
		}
	}

	if len(matches) == 0 {
		return types.JID{}, nil
	}

	if len(matches) == 1 {
		jid, err := types.ParseJID(matches[0].JID)
		if err != nil {
			return types.JID{}, fmt.Errorf("could not read the saved group identifier: %v", err)
		}
		return jid, nil
	}

	var names []string
	for i, g := range matches {
		if i >= 5 {
			names = append(names, "...")
			break
		}
		names = append(names, g.Name)
	}
	return types.JID{}, fmt.Errorf("multiple groups match '%s': %s. Please provide the full group name",
		identifier, strings.Join(names, ", "))
}

func isNumeric(s string) bool {
	_, err := strconv.ParseUint(s, 10, 64)
	return err == nil && len(s) > 0
}

// getChatName returns the name shown for a chat: a saved contact's name, a group's name, or, for a
// person with no saved contact, their phone number. A direct chat never takes the peer's WhatsApp
// profile name (pushname), so a name in the chats table is always a saved contact or a number. Two
// different people cannot then share a chat name, which keeps a saved name pointing at one person
// for name-based sends and replies.
func (wac *WhatsAppClient) getChatName(jid types.JID) string {
	if contact, err := wac.store.GetManualContact(jid.String()); err == nil && contact != nil && contact.Name != "" {
		return contact.Name
	}
	if name, err := wac.store.GetChatName(jid.String()); err == nil && name != "" {
		return name
	}
	if jid.Server == types.GroupServer {
		if groupInfo, err := wac.client.GetGroupInfo(context.Background(), jid); err == nil {
			return groupInfo.Name
		}
		return fmt.Sprintf("Group %s", jid.User)
	}
	if jid.Server == types.DefaultUserServer && jid.User != "" {
		return "+" + jid.User
	}
	if jid.User != "" {
		return jid.User
	}
	return "Unknown"
}

// isLIDServer checks if a server string indicates a LID (Linked ID) server.
func isLIDServer(server string) bool {
	return server == types.HiddenUserServer || server == types.HostedLIDServer
}

// isDirectChatJID checks if a JID represents a direct chat (not a group).
func isDirectChatJID(jid types.JID) bool {
	return jid.Server == types.DefaultUserServer || isLIDServer(jid.Server)
}

// resolveSenderJID resolves a LID JID to its phone number JID if possible.
func (wac *WhatsAppClient) resolveSenderJID(sender, senderAlt types.JID) types.JID {
	if !isLIDServer(sender.Server) {
		return sender
	}
	if !senderAlt.IsEmpty() && senderAlt.Server == types.DefaultUserServer {
		return senderAlt
	}
	if pn, err := wac.client.Store.LIDs.GetPNForLID(context.Background(), sender); err == nil && !pn.IsEmpty() {
		return pn
	}
	return sender
}

// canonicalChatJID returns the one JID that identifies a chat. WhatsApp addresses a direct chat
// by the peer's LID (a privacy id), but a saved contact and any reply resolve to the peer's phone
// JID; treating the raw LID as its own identity splits one person into two chats, which breaks
// reply-first, read-receipt targeting, threading, and the saved-contact gate. Resolving the LID to
// its phone JID here (a group JID is left unchanged) makes one person one identity everywhere.
func (wac *WhatsAppClient) canonicalChatJID(chat types.JID) types.JID {
	if wac.client == nil {
		return chat
	}
	return wac.resolveSenderJID(chat, types.JID{})
}

// canonicalChatKey is the storage-key form of canonicalChatJID, used everywhere messages and
// chats are stored or looked up.
func (wac *WhatsAppClient) canonicalChatKey(chat types.JID) string {
	return wac.canonicalChatJID(chat).String()
}

// formatSenderForDisplay returns a user-friendly sender display string.
func (wac *WhatsAppClient) formatSenderForDisplay(jid types.JID) string {
	if contact, err := wac.store.GetManualContact(jid.String()); err == nil && contact != nil && contact.Name != "" {
		return contact.Name
	}
	if jid.Server == types.DefaultUserServer && jid.User != "" {
		return "+" + jid.User
	}
	if jid.User != "" {
		return jid.User
	}
	return "Unknown"
}

// prepareNotificationInfo prepares all the data needed for a notification.
func (wac *WhatsAppClient) prepareNotificationInfo(info types.MessageSource) (
	resolvedSender types.JID,
	senderDisplay string,
	contactPhone string,
	contactSaved, isDirectChat bool,
) {
	resolvedSender = wac.resolveSenderJID(info.Sender, info.SenderAlt)
	var contactName string

	// resolvedChat is the peer's number for display, read through the alt address the message
	// itself carries, which the LID store need not hold. It never decides which rows are the
	// peer's contact: contactKeys owns that, and unions both key forms rather than picking one.
	resolvedChat := info.Chat
	if isLIDServer(info.Chat.Server) {
		resolvedChat = wac.resolveSenderJID(info.Chat, info.SenderAlt)
	}

	// Each address the message carries is expanded through contactKeys, the same resolution the
	// send gate uses: a peer is saved under whichever key form was known when the user confirmed
	// them, so reading one key alone reports a confirmed peer as unknown and gets them saved a
	// second time. The chat comes first because in a direct chat it is the peer; a group chat
	// holds no contact of its own, so it falls through to whoever sent the message.
	for _, addressed := range []types.JID{info.Chat, info.Sender, info.SenderAlt} {
		if addressed.IsEmpty() {
			continue
		}
		if contact, err := wac.lookupManualContact(addressed); err == nil && contact != nil {
			contactName, contactPhone, contactSaved = contact.Name, contact.PhoneNumber, true
			break
		}
	}

	// Fall back to a JID's user part as the phone, but only when that JID is a real
	// phone-server JID — never for a group ID or an unresolved LID/hidden JID, whose
	// user part is an internal numeric that would render as a bogus "+120363..." phone.
	// In a direct chat the meaningful number is the peer's (resolvedChat); in a group
	// it is the sender's (resolvedSender). Either way, if it didn't resolve to a real
	// phone JID, leave contact_phone empty rather than lie.
	if contactPhone == "" {
		if isDirectChatJID(info.Chat) {
			if resolvedChat.Server == types.DefaultUserServer && resolvedChat.User != "" {
				contactPhone = "+" + resolvedChat.User
			}
		} else if resolvedSender.Server == types.DefaultUserServer && resolvedSender.User != "" {
			contactPhone = "+" + resolvedSender.User
		}
	}

	if !contactSaved && contactPhone != "" {
		if contact, err := wac.store.GetManualContactByPhone(contactPhone); err == nil && contact != nil {
			contactName = contact.Name
			contactSaved = true
		}
	}

	if contactSaved && contactName != "" {
		senderDisplay = contactName
	} else {
		senderDisplay = wac.formatSenderForDisplay(resolvedSender)
	}
	isDirectChat = isDirectChatJID(info.Chat)

	return
}
