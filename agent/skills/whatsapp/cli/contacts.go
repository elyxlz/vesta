package main

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	"go.mau.fi/whatsmeow/types"
)

func (wac *WhatsAppClient) AddContact(name, phone string) (Contact, error) {
	return wac.store.SaveManualContact(name, phone)
}

func (wac *WhatsAppClient) requireManualContact(jid types.JID) error {
	if jid.Server != types.DefaultUserServer {
		return nil
	}

	contact, err := wac.store.GetManualContact(jid.String())
	if err != nil {
		return fmt.Errorf("failed to verify saved contacts: %v", err)
	}

	if contact == nil {
		phone := jid.User
		if phone != "" {
			phone = "+" + phone
		} else {
			phone = "this contact"
		}
		return fmt.Errorf(
			"No saved contact found for %s. Ask the user who this is and run add_contact before sending messages.",
			phone,
		)
	}

	return nil
}

func (wac *WhatsAppClient) ResolveRecipient(identifier string) (types.JID, error) {
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

	// Search contacts by name
	contacts, err := wac.store.SearchContacts(identifier, 50)
	if err == nil {
		if jid, err := resolveFromContacts(contacts, identifier); err != nil || jid.User != "" {
			return jid, err
		}
	}

	// Search groups by name (filtered query avoids loading all groups)
	groups, err := wac.store.SearchGroups(identifier, 50)
	if err == nil {
		if jid, err := resolveFromGroups(groups, identifier); err != nil || jid.User != "" {
			return jid, err
		}
	}

	return types.JID{}, fmt.Errorf("no contact or group found matching '%s'. Use search_contacts or list_groups to find available recipients", identifier)
}

func resolveFromContacts(contacts []Contact, identifier string) (types.JID, error) {
	if len(contacts) == 0 {
		return types.JID{}, nil
	}

	if jid, handled, err := preferExactContactMatch(contacts, identifier); handled {
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

func preferExactContactMatch(contacts []Contact, identifier string) (types.JID, bool, error) {
	trimmed := strings.TrimSpace(identifier)
	if trimmed == "" {
		return types.JID{}, false, nil
	}

	var matches []Contact
	for _, c := range contacts {
		if c.Name != "" && strings.EqualFold(strings.TrimSpace(c.Name), trimmed) {
			matches = append(matches, c)
		}
	}

	if len(matches) > 1 {
		return types.JID{}, true, fmt.Errorf("multiple contacts share the exact name '%s'. Please disambiguate with the precise phone number (+1234567890)", identifier)
	}

	if len(matches) == 1 {
		jid, err := types.ParseJID(matches[0].JID)
		return jid, true, err
	}

	digits := digitsOnly(trimmed)
	if digits == "" {
		return types.JID{}, false, nil
	}

	var phoneMatch *Contact
	for i := range contacts {
		if digitsOnly(contacts[i].PhoneNumber) == digits {
			if phoneMatch != nil {
				return types.JID{}, true, fmt.Errorf("multiple contacts share that phone number. Please specify the exact contact name instead")
			}
			phoneMatch = &contacts[i]
		}
	}

	if phoneMatch == nil {
		return types.JID{}, false, nil
	}

	jid, err := types.ParseJID(phoneMatch.JID)
	return jid, true, err
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

// getChatName returns a human-readable name for a chat JID.
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
	if contact, err := wac.client.Store.Contacts.GetContact(context.Background(), jid); err == nil && contact.FullName != "" {
		return contact.FullName
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
	contactName, contactPhone string,
	contactSaved, isDirectChat bool,
) {
	resolvedSender = wac.resolveSenderJID(info.Sender, info.SenderAlt)

	resolvedChat := info.Chat
	if isLIDServer(info.Chat.Server) {
		resolvedChat = wac.resolveSenderJID(info.Chat, info.SenderAlt)
	}

	if contact, err := wac.store.GetManualContact(resolvedChat.String()); err == nil && contact != nil {
		contactName = contact.Name
		contactPhone = contact.PhoneNumber
		contactSaved = true
	}

	if !contactSaved && resolvedSender.Server == types.DefaultUserServer {
		if contact, err := wac.store.GetManualContact(resolvedSender.String()); err == nil && contact != nil {
			contactName = contact.Name
			contactPhone = contact.PhoneNumber
			contactSaved = true
		}
	}

	if !contactSaved && !info.SenderAlt.IsEmpty() && info.SenderAlt.Server == types.DefaultUserServer {
		if contact, err := wac.store.GetManualContact(info.SenderAlt.String()); err == nil && contact != nil {
			contactName = contact.Name
			contactPhone = contact.PhoneNumber
			contactSaved = true
		}
	}

	if contactPhone == "" && resolvedChat.User != "" {
		contactPhone = "+" + resolvedChat.User
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
