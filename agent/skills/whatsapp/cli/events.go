package main

import (
	"context"
	"time"

	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

func (wac *WhatsAppClient) eventHandler(evt interface{}) {
	switch v := evt.(type) {
	case *events.Message:
		if v.Message.GetReactionMessage() != nil {
			wac.handleReaction(v)
		} else {
			wac.handleMessage(v)
		}
	case *events.Receipt:
		wac.handleReceipt(v)
	case *events.HistorySync:
		wac.handleHistorySync(v)
	case *events.Connected:
		wac.logger.Infof("Connected to WhatsApp")
		wac.presenceMutex.Lock()
		wac.presenceActive = false
		wac.presenceMutex.Unlock()
	case *events.Disconnected:
		wac.logger.Warnf("Disconnected from WhatsApp")
		wac.presenceMutex.Lock()
		wac.presenceActive = false
		wac.presenceMutex.Unlock()
	case *events.KeepAliveTimeout:
		wac.logger.Warnf("WhatsApp keep-alive timeout: error_count=%d, last_success=%s", v.ErrorCount, v.LastSuccess.Format(time.RFC3339))
	case *events.StreamReplaced:
		wac.logger.Warnf("WhatsApp stream replaced — another connection took over this session")
	case *events.StreamError:
		wac.logger.Errorf("WhatsApp stream error: code=%s", v.Code)
	case *events.LoggedOut:
		wac.logger.Warnf("Device logged out from WhatsApp - initiating re-authentication")
		wac.initiateReauth()
	}
}

func (wac *WhatsAppClient) handleReceipt(evt *events.Receipt) {
	if wac.store == nil {
		return
	}

	var status string
	switch evt.Type {
	case types.ReceiptTypeDelivered:
		status = DeliveryStatusDelivered
	case types.ReceiptTypeRead:
		status = DeliveryStatusRead
	case types.ReceiptTypePlayed:
		status = DeliveryStatusPlayed
	default:
		if evt.Type == types.ReceiptTypeSender || evt.Type == "" {
			status = DeliveryStatusDelivered
		} else {
			return
		}
	}

	chatJID := evt.Chat.String()
	for _, msgID := range evt.MessageIDs {
		if err := wac.store.UpdateDeliveryStatus(string(msgID), chatJID, status, evt.Timestamp); err != nil {
			wac.logger.Warnf("Failed to update delivery status for %s: %v", msgID, err)
		}
	}
}

func (wac *WhatsAppClient) handleMessage(evt *events.Message) {
	msg := evt.Message
	info := evt.Info

	content := extractTextContent(msg)
	isForwarded := isMessageForwarded(msg)
	quotedMessageID, quotedText := extractQuoteContext(msg)
	mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength := extractMediaInfo(msg)

	if content == "" && mediaType == "" {
		return
	}

	resolvedSender, senderDisplay, contactName, contactPhone, contactSaved, isDirectChat := wac.prepareNotificationInfo(info.MessageSource)
	chatName := wac.getChatName(info.Chat)

	// Track message sender for reaction routing
	wac.sendersMutex.Lock()
	wac.messageSenders[info.ID] = resolvedSender.String()
	wac.senderOrder = append(wac.senderOrder, info.ID)
	if len(wac.senderOrder) > MaxSenderCacheSize {
		evict := wac.senderOrder[:len(wac.senderOrder)-MaxSenderCacheSize]
		for _, id := range evict {
			delete(wac.messageSenders, id)
		}
		wac.senderOrder = wac.senderOrder[len(wac.senderOrder)-MaxSenderCacheSize:]
	}
	wac.sendersMutex.Unlock()

	if err := wac.store.StoreChat(info.Chat.String(), chatName, info.Timestamp); err != nil {
		wac.logger.Warnf("Failed to store chat: %v", err)
	}
	if err := wac.store.StoreMessage(
		info.ID, info.Chat.String(), senderDisplay, content,
		info.Timestamp, info.IsFromMe, isForwarded,
		mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength,
	); err != nil {
		wac.logger.Warnf("Failed to store message: %v", err)
	}

	// Auto-transcribe audio messages
	if mediaType == MediaTypeAudio && !info.IsFromMe {
		if transcription := wac.transcribeAudioMessage(info.ID, info.Chat.String()); transcription != "" {
			content = transcription
		}
	}

	// Write notification for incoming messages
	if wac.notificationsDir != "" && !info.IsFromMe && !wac.skipSenders[contactPhone] {
		WriteNotification(
			wac.notificationsDir, info.ID, chatName,
			contactName, contactPhone, wac.instance,
			contactSaved, isDirectChat, senderDisplay,
			content, mediaType, isForwarded,
			quotedMessageID, quotedText,
		)
	}

	// Delayed read receipt
	if !info.IsFromMe && !wac.readOnly && wac.client.IsConnected() {
		msgID := info.ID
		chatJID := info.Chat
		senderJID := info.Sender
		go wac.sendReadReceiptDelayed(msgID, chatJID, senderJID, content)
	}
}

func (wac *WhatsAppClient) sendReadReceiptDelayed(msgID string, chatJID, senderJID types.JID, content string) {
	time.Sleep(humanDelay(ReadDelayBase, ReadDelayPerChar, len(content), ReadDelayMax))

	if err := wac.EnsureOnline(); err != nil {
		wac.logger.Warnf("Failed to set online status for read receipt: %v", err)
		return
	}

	err := wac.client.MarkRead(
		context.Background(),
		[]types.MessageID{msgID},
		time.Now(),
		chatJID,
		senderJID,
		types.ReceiptTypeRead,
	)
	if err != nil {
		wac.logger.Warnf("Failed to send read receipt: %v", err)
	}
}

func (wac *WhatsAppClient) handleReaction(evt *events.Message) {
	reaction := evt.Message.GetReactionMessage()
	if reaction == nil {
		return
	}

	targetID := reaction.GetKey().GetID()
	emoji := reaction.GetText()
	isRemoved := emoji == ""

	chatName := wac.getChatName(evt.Info.Chat)

	if wac.notificationsDir != "" {
		_, senderDisplay, contactName, contactPhone, contactSaved, isDirectChat := wac.prepareNotificationInfo(evt.Info.MessageSource)
		WriteReactionNotification(
			wac.notificationsDir, targetID, chatName,
			contactName, contactPhone, wac.instance,
			contactSaved, isDirectChat, senderDisplay,
			emoji, isRemoved,
		)
	}
}

func (wac *WhatsAppClient) handleHistorySync(evt *events.HistorySync) {
	wac.logger.Infof("Processing history sync with %d conversations", len(evt.Data.Conversations))

	for _, conversation := range evt.Data.Conversations {
		if conversation.ID == nil {
			continue
		}

		chatJID := *conversation.ID
		jid, err := types.ParseJID(chatJID)
		if err != nil {
			continue
		}

		name := wac.getChatName(jid)

		for _, msg := range conversation.Messages {
			if msg == nil || msg.Message == nil {
				continue
			}

			content := extractTextContent(msg.Message.Message)
			isForwarded := msg.Message.Message != nil && isMessageForwarded(msg.Message.Message)
			mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength := extractMediaInfo(msg.Message.Message)

			if content == "" && mediaType == "" {
				continue
			}

			timestamp := time.Unix(int64(msg.Message.GetMessageTimestamp()), 0)

			var sender string
			isFromMe := false
			if msg.Message.Key != nil {
				if msg.Message.Key.FromMe != nil {
					isFromMe = *msg.Message.Key.FromMe
				}
				if !isFromMe && msg.Message.Key.Participant != nil {
					sender = *msg.Message.Key.Participant
				} else if isFromMe {
					sender = wac.client.Store.ID.User
				} else {
					sender = jid.User
				}
			}

			msgID := ""
			if msg.Message.Key != nil && msg.Message.Key.ID != nil {
				msgID = *msg.Message.Key.ID
			}

			if err := wac.store.StoreMessage(
				msgID, chatJID, sender, content,
				timestamp, isFromMe, isForwarded,
				mediaType, filename, url,
				mediaKey, fileSHA256, fileEncSHA256, fileLength,
			); err != nil {
				wac.logger.Warnf("Failed to store history message: %v", err)
			}
		}

		if len(conversation.Messages) > 0 {
			latestMsg := conversation.Messages[0]
			if latestMsg != nil && latestMsg.Message != nil {
				timestamp := time.Unix(int64(latestMsg.Message.GetMessageTimestamp()), 0)
				if err := wac.store.StoreChat(chatJID, name, timestamp); err != nil {
					wac.logger.Warnf("Failed to store history chat: %v", err)
				}
			}
		}
	}
}
