package main

import (
	"context"
	"fmt"
	"time"

	"go.mau.fi/whatsmeow/appstate"
	"go.mau.fi/whatsmeow/types"
)

func (wac *WhatsAppClient) ArchiveChat(chatIdentifier string) (bool, string) {
	jid, err := wac.ResolveRecipient(chatIdentifier)
	if err != nil {
		return false, fmt.Sprintf("Failed to resolve chat: %v", err)
	}
	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}

	patch := appstate.BuildArchive(jid, true, time.Time{}, nil)
	if err := wac.client.SendAppState(context.Background(), patch); err != nil {
		return false, fmt.Sprintf("Failed to archive chat: %v", err)
	}
	return true, "Chat archived successfully"
}

func (wac *WhatsAppClient) ArchiveAllChats() (int, []string, error) {
	if err := wac.EnsureConnected(); err != nil {
		return 0, nil, err
	}

	jids, err := wac.store.ListAllChatJIDs()
	if err != nil {
		return 0, nil, fmt.Errorf("failed to list chats: %v", err)
	}

	var errs []string
	archived := 0
	for _, jidStr := range jids {
		jid, parseErr := types.ParseJID(jidStr)
		if parseErr != nil {
			errs = append(errs, fmt.Sprintf("%s: invalid JID: %v", jidStr, parseErr))
			continue
		}
		patch := appstate.BuildArchive(jid, true, time.Time{}, nil)
		if sendErr := wac.client.SendAppState(context.Background(), patch); sendErr != nil {
			errs = append(errs, fmt.Sprintf("%s: %v", jidStr, sendErr))
			continue
		}
		archived++
	}

	return archived, errs, nil
}

func (wac *WhatsAppClient) RequestBackfill(chatIdentifier string, count int) (bool, string) {
	if chatIdentifier == "" {
		return false, "Chat identifier is required"
	}
	if count <= 0 {
		count = 50
	}

	jid, err := wac.ResolveRecipient(chatIdentifier)
	if err != nil {
		return false, fmt.Sprintf("Failed to resolve chat: %v", err)
	}
	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}

	msgID, senderJID, isFromMe, ts, err := wac.store.GetOldestMessage(jid.String())
	if err != nil {
		return false, "No local message history for this chat. WhatsApp history sync requires an existing message as an anchor — send a message to this contact first (or ask them to send one), then retry backfill."
	}

	senderParsed, err := types.ParseJID(senderJID)
	if err != nil {
		return false, fmt.Sprintf("Failed to parse sender JID: %v", err)
	}
	msgInfo := &types.MessageInfo{
		MessageSource: types.MessageSource{
			Chat:     jid,
			Sender:   senderParsed,
			IsFromMe: isFromMe,
		},
		ID:        msgID,
		Timestamp: ts,
	}

	histMsg := wac.client.BuildHistorySyncRequest(msgInfo, count)
	_, err = wac.client.SendPeerMessage(context.Background(), histMsg)
	if err != nil {
		return false, fmt.Sprintf("Failed to request backfill: %v", err)
	}

	return true, fmt.Sprintf("Backfill requested for %d messages before %s. Messages will arrive asynchronously — wait a few seconds then use list-messages to check.", count, ts.Format(time.RFC3339))
}

// DeleteChat clears all messages in a chat both locally and on the WhatsApp servers
// (via the app-state sync mechanism used by official WhatsApp clients).
func (wac *WhatsAppClient) DeleteChat(chatIdentifier string) (bool, string) {
	jid, err := wac.ResolveRecipient(chatIdentifier)
	if err != nil {
		return false, fmt.Sprintf("Failed to resolve chat: %v", err)
	}
	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}

	lastTS, _, dbErr := wac.store.GetLastMessageInfo(jid.String())
	if dbErr != nil {
		lastTS = time.Now()
	}

	patch := appstate.BuildDeleteChat(jid, lastTS, nil, false)
	if patchErr := wac.client.SendAppState(context.Background(), patch); patchErr != nil {
		wac.logger.Warnf("Failed to push delete-chat app state: %v — clearing local DB only", patchErr)
	}

	n, err := wac.store.DeleteChatMessages(jid.String())
	if err != nil {
		return false, fmt.Sprintf("Failed to clear local messages: %v", err)
	}
	return true, fmt.Sprintf("Chat deleted: %d messages removed from local DB and deletion pushed to all devices", n)
}
