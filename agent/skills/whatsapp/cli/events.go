package main

import (
	"context"
	"fmt"
	"time"

	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

func (wac *WhatsAppClient) eventHandler(evt any) {
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
		if v.ErrorCount >= KeepAliveRestartThreshold {
			go wac.recoverOrRestart(fmt.Sprintf("keepalive_timeout:error_count=%d", v.ErrorCount))
		}
	case *events.StreamReplaced:
		wac.logger.Warnf("WhatsApp stream replaced; another connection took over this session")
		go wac.recoverOrRestart("stream_replaced")
	case *events.StreamError:
		wac.logger.Errorf("WhatsApp stream error: code=%s", v.Code)
		go wac.recoverOrRestart("stream_error:" + v.Code)
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
	if len(wac.senderOrder) > MaxSenderCacheSize+SenderCacheEvictBatch {
		evict := wac.senderOrder[:SenderCacheEvictBatch]
		for _, id := range evict {
			delete(wac.messageSenders, id)
		}
		// Copy into a new slice so the old backing array can be GC'd
		remaining := wac.senderOrder[SenderCacheEvictBatch:]
		wac.senderOrder = make([]string, len(remaining))
		copy(wac.senderOrder, remaining)
	}
	wac.sendersMutex.Unlock()

	if err := wac.store.StoreChat(info.Chat.String(), chatName, info.Timestamp); err != nil {
		wac.logger.Warnf("Failed to store chat: %v", err)
	}
	if err := wac.store.StoreMessage(StoreMessageParams{
		ID: info.ID, ChatJID: info.Chat.String(), Sender: senderDisplay, Content: content,
		Timestamp: info.Timestamp, IsFromMe: info.IsFromMe, IsForwarded: isForwarded,
		MediaType: mediaType, Filename: filename, URL: url,
		MediaKey: mediaKey, FileSHA256: fileSHA256, FileEncSHA256: fileEncSHA256, FileLength: fileLength,
	}); err != nil {
		wac.logger.Warnf("Failed to store message: %v", err)
	}

	// If we receive a message from someone in a direct chat, it implies they
	// saw the conversation, so upgrade any "sent" outgoing messages to
	// "delivered". This prevents false-positive stale-message alerts for
	// contacts who have delivery receipts turned off.
	if !info.IsFromMe && isDirectChat && wac.store != nil {
		if n, err := wac.store.UpgradeSentToDelivered(info.Chat.String(), info.Timestamp); err != nil {
			wac.logger.Warnf("Failed to upgrade sent→delivered for %s: %v", info.Chat, err)
		} else if n > 0 {
			wac.logger.Infof("Upgraded %d sent→delivered for %s (contact replied)", n, info.Chat)
		}
	}

	// Build notification context (shared by sync and async paths)
	shouldNotify := wac.notificationsDir != "" && !wac.noNotify && !info.IsFromMe && !wac.skipSenders[contactPhone]
	var notifCtx NotifContext
	if shouldNotify {
		interrupt, interruptExplicit := wac.shouldInterrupt(contactPhone)
		notifCtx = NotifContext{
			NotifDir: wac.notificationsDir, ChatName: chatName,
			ContactName: contactName, ContactPhone: contactPhone,
			Instance: wac.instance, ContactSaved: contactSaved,
			IsDirectChat: isDirectChat, Sender: senderDisplay,
			Interrupt: interrupt, InterruptExplicit: interruptExplicit,
		}
	}

	// Audio messages: transcribe asynchronously, then send notification
	if mediaType == MediaTypeAudio && !info.IsFromMe {
		msgID := info.ID
		chatJIDStr := info.Chat.String()
		go func() {
			wac.transcribeSem <- struct{}{} // acquire
			defer func() { <-wac.transcribeSem }()

			notifContent := content
			if transcription, err := wac.transcribeAudioMessage(msgID, chatJIDStr); err != nil {
				notifContent = fmt.Sprintf("⚠️ Audio message received but transcription failed: %s", err)
			} else if transcription != "" {
				notifContent = transcription
			}
			if shouldNotify {
				WriteNotification(notifCtx, msgID, notifContent, mediaType, isForwarded, quotedMessageID, quotedText)
			}
		}()
	} else if shouldNotify {
		WriteNotification(notifCtx, info.ID, content, mediaType, isForwarded, quotedMessageID, quotedText)
	}

	// Delayed read receipt, coalesced per chat+sender so receipts never go out
	// of order (see enqueueReadReceipt).
	if !info.IsFromMe && !wac.readOnly && wac.client.IsConnected() {
		wac.enqueueReadReceipt(info.ID, info.Chat, info.Sender, content)
	}
}

// chatReadBatch accumulates the unread messages from one sender in one chat
// that are waiting for their human-delayed read receipt.
type chatReadBatch struct {
	chatJID types.JID
	sender  types.JID
	msgIDs  []types.MessageID
	maxLen  int // longest content in the batch, drives the human read delay
	timer   *time.Timer
}

// enqueueReadReceipt schedules a read receipt for an inbound message. Receipts
// are coalesced per (chat, sender): all messages that arrive before the timer
// fires are marked read together, in arrival order, in a single MarkRead. This
// makes it impossible to mark a later message read before an earlier one (the
// old per-message goroutine raced because each had an independent random
// delay), and means a daemon crash leaves the whole batch unread rather than
// acking some messages but not earlier ones.
func (wac *WhatsAppClient) enqueueReadReceipt(msgID string, chatJID, senderJID types.JID, content string) {
	key := chatJID.String() + "|" + senderJID.String()

	wac.readQueueMu.Lock()
	defer wac.readQueueMu.Unlock()

	batch, ok := wac.readQueue[key]
	if !ok {
		batch = &chatReadBatch{chatJID: chatJID, sender: senderJID}
		wac.readQueue[key] = batch
	}
	batch.msgIDs = append(batch.msgIDs, types.MessageID(msgID))
	if len(content) > batch.maxLen {
		batch.maxLen = len(content)
	}
	if batch.timer == nil {
		delay := humanDelay(ReadDelayBase, ReadDelayPerChar, batch.maxLen, ReadDelayMax)
		batch.timer = time.AfterFunc(delay, func() { wac.flushReadReceipt(key) })
	}
}

func (wac *WhatsAppClient) flushReadReceipt(key string) {
	wac.readQueueMu.Lock()
	batch := wac.readQueue[key]
	delete(wac.readQueue, key)
	wac.readQueueMu.Unlock()
	if batch == nil || len(batch.msgIDs) == 0 {
		return
	}

	if err := wac.EnsureOnline(); err != nil {
		wac.logger.Warnf("Failed to set online status for read receipt: %v", err)
		return
	}

	if err := wac.client.MarkRead(
		context.Background(),
		batch.msgIDs,
		time.Now(),
		batch.chatJID,
		batch.sender,
		types.ReceiptTypeRead,
	); err != nil {
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
		interrupt, interruptExplicit := wac.shouldInterrupt(contactPhone)
		ctx := NotifContext{
			NotifDir: wac.notificationsDir, ChatName: chatName,
			ContactName: contactName, ContactPhone: contactPhone,
			Instance: wac.instance, ContactSaved: contactSaved,
			IsDirectChat: isDirectChat, Sender: senderDisplay,
			Interrupt: interrupt, InterruptExplicit: interruptExplicit,
		}
		WriteReactionNotification(ctx, targetID, emoji, isRemoved)
	}
}

func (wac *WhatsAppClient) handleHistorySync(evt *events.HistorySync) {
	wac.logger.Infof("Processing history sync with %d conversations", len(evt.Data.Conversations))

	// Commit one transaction per conversation so the writer lock releases between
	// conversations, allowing other writes (add-contact, live events) to make
	// progress during large first-pair backfills.
	for _, conversation := range evt.Data.Conversations {
		if conversation.ID == nil {
			continue
		}

		chatJID := *conversation.ID
		jid, err := types.ParseJID(chatJID)
		if err != nil {
			continue
		}

		err = func() error {
			tx, err := wac.store.Begin()
			if err != nil {
				return err
			}
			defer tx.Rollback()

			name := wac.getChatName(jid)

			// Store chat FIRST so the FTS AFTER INSERT trigger can look up chat name.
			// Chats with no messages in this sync batch must still be recorded.
			chatTimestamp := time.Now()
			if len(conversation.Messages) > 0 {
				if m0 := conversation.Messages[0]; m0 != nil && m0.Message != nil {
					chatTimestamp = time.Unix(int64(m0.Message.GetMessageTimestamp()), 0)
				}
			}
			if err := wac.store.StoreChatTx(tx, chatJID, name, chatTimestamp); err != nil {
				wac.logger.Warnf("Failed to store history chat: %v", err)
			}

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

				if err := wac.store.StoreMessageTx(tx, StoreMessageParams{
					ID: msgID, ChatJID: chatJID, Sender: sender, Content: content,
					Timestamp: timestamp, IsFromMe: isFromMe, IsForwarded: isForwarded,
					MediaType: mediaType, Filename: filename, URL: url,
					MediaKey: mediaKey, FileSHA256: fileSHA256, FileEncSHA256: fileEncSHA256, FileLength: fileLength,
				}); err != nil {
					wac.logger.Warnf("Failed to store history message: %v", err)
				}
			}

			return tx.Commit()
		}()
		if err != nil {
			wac.logger.Warnf("Failed to store history conversation %s: %v", chatJID, err)
		}
	}
}
