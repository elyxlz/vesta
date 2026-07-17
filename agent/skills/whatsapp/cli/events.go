package main

import (
	"context"
	"fmt"
	"os"
	"time"

	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

func (wac *WhatsAppClient) eventHandler(evt any) {
	switch v := evt.(type) {
	case *events.Message:
		// Data-plane: offload so a slow store write never stalls whatsmeow's serial
		// node loop. The reaction/protocol/message split runs on the worker, in FIFO order.
		wac.enqueueWork(func() {
			switch {
			case v.Message.GetReactionMessage() != nil:
				wac.handleReaction(v)
			case v.Message.GetProtocolMessage() != nil:
				wac.handleProtocolMessage(v)
			default:
				wac.handleMessage(v)
			}
		})
	case *events.Receipt:
		wac.enqueueWork(func() { wac.handleReceipt(v) })
	case *events.HistorySync:
		wac.handleHistorySync(v)
	case *events.PairSuccess:
		// A phone-code pairing finished (the user entered the code). QR pairing
		// instead completes through consumeQRChannel, so this is the phone-code path.
		wac.logger.Infof("Pairing succeeded")
		wac.onLinked()
	case *events.Connected:
		wac.logger.Infof("Connected to WhatsApp")
		// A successful connect clears any stale logout/yield reason so `status` does
		// not keep reporting an old failure after the daemon has recovered.
		wac.clearExit()
		wac.presenceMutex.Lock()
		wac.presenceActive = false
		wac.presenceMutex.Unlock()
		// Refresh the last-good device snapshot (throttled) and (re)arm the
		// stability timer that clears the preserve single-retry guard once the
		// connection has held for StableConnDuration.
		wac.maybeSnapshotGoodDevice()
		wac.armStableTimer()
	case *events.KeepAliveTimeout:
		wac.logger.Warnf("WhatsApp keep-alive timeout: error_count=%d, last_success=%s", v.ErrorCount, v.LastSuccess.Format(time.RFC3339))
		if v.ErrorCount >= KeepAliveRestartThreshold {
			go wac.recoverOrRestart(fmt.Sprintf("keepalive_timeout:error_count=%d", v.ErrorCount))
		}
	case *events.StreamError:
		wac.logger.Errorf("WhatsApp stream error: code=%s", v.Code)
		go wac.recoverOrRestart("stream_error:" + v.Code)
	case *events.Disconnected:
		wac.applyConnAction(classifyConnEvent(v), "")
	case *events.StreamReplaced:
		wac.applyConnAction(classifyConnEvent(v), "another connection took over this device session")
	case *events.LoggedOut:
		wac.applyConnAction(classifyConnEvent(v), loggedOutReason(v))
	}
}

// connEventAction is what the daemon does in response to a connection-lifecycle
// event. The mapping lives in classifyConnEvent (the single owner); applyConnAction
// executes each action.
type connEventAction int

const (
	// connIgnore: a transient disconnect. whatsmeow auto-reconnects, so the
	// daemon does nothing but reset presence; it must NOT stop or re-pair.
	connIgnore connEventAction = iota
	// connYield: another connection took over this device session (the conflict
	// signal). whatsmeow has already disabled auto-reconnect; park (stay up, do not
	// reconnect, do not exit) so an auto-restarted daemon can't steal the session
	// back and ping-pong with the other holder.
	connYield
	// connNeedsProvision: a genuine logout (the phone unlinked the device). Clear
	// the dead device and exit, so the next command restarts into a fresh device
	// for a deliberate `whatsapp provision`; never re-pair automatically.
	connNeedsProvision
)

// classifyConnEvent maps a whatsmeow connection-lifecycle event to the daemon's
// response. It is the single source of truth for how a disconnect, a stream
// replacement, and a logout are treated differently.
func classifyConnEvent(evt any) connEventAction {
	switch evt.(type) {
	case *events.Disconnected:
		return connIgnore
	case *events.StreamReplaced:
		return connYield
	case *events.LoggedOut:
		return connNeedsProvision
	}
	return connIgnore
}

// loggedOutReason renders a human-readable reason for a LoggedOut event, using
// whatsmeow's connect-failure reason when the logout arrived on connect.
func loggedOutReason(evt *events.LoggedOut) string {
	if evt.OnConnect {
		return "logged out on connect: " + evt.Reason.String()
	}
	return "unlinked from the phone (stream:error logout)"
}

// recordExit persists why the device session ended, so status can surface it after
// the daemon has gone quiescent.
func (wac *WhatsAppClient) recordExit(status, reason string) {
	wac.state.update(func(s *daemonState) {
		s.ExitStatus, s.ExitReason, s.ExitTime = status, reason, time.Now().UTC()
	})
}

// clearExit drops a stale exit reason once the daemon has reconnected, so status
// stops reporting an old failure.
func (wac *WhatsAppClient) clearExit() {
	wac.state.update(func(s *daemonState) {
		s.ExitStatus, s.ExitReason, s.ExitTime = "", "", time.Time{}
	})
}

func (wac *WhatsAppClient) applyConnAction(action connEventAction, reason string) {
	// Any Disconnected/StreamReplaced/LoggedOut cancels the stability timer, so a
	// brief connect that drops before StableConnDuration keeps PreserveRetryAt fresh.
	wac.stopStableTimer()
	switch action {
	case connIgnore:
		wac.logger.Warnf("Disconnected from WhatsApp (transient); whatsmeow will auto-reconnect")
		wac.presenceMutex.Lock()
		wac.presenceActive = false
		wac.presenceMutex.Unlock()
	case connYield:
		// Another connection owns this session and whatsmeow already stopped
		// reconnecting. Park (connParked): record the reason and stay up WITHOUT
		// reconnecting or exiting. The park mode is what every reconnect path
		// (EnsureConnected, recoverOrRestart) reads to refuse reconnecting, so the
		// next auto-started daemon can't steal the session back and ping-pong.
		wac.logger.Warnf("Yielding: %s. Parking (no reconnect, no exit).", reason)
		wac.setConnMode(connParked)
		wac.recordExit("stream_replaced", reason)
		wac.presenceMutex.Lock()
		wac.presenceActive = false
		wac.presenceMutex.Unlock()
	case connNeedsProvision:
		// A device removal (mid-session or on-connect). Try device preservation
		// first (restore last-good + reconnect once); fall back to today's exact
		// clear-and-exit when preservation is not available or a retry just failed.
		wac.handleDeviceRemoved(reason)
	}
}

// handleDeviceRemoved responds to a whatsmeow device removal. When a last-good
// snapshot exists and the single-retry guard is clear, it restores the snapshot
// and reconnects once (NOT a re-pair, so no ban risk). Otherwise it falls back to
// today's exact park+provision give-up: record the logout, notify, drop the dead
// device, and exit for a deliberate `whatsapp provision`.
func (wac *WhatsAppClient) handleDeviceRemoved(reason string) {
	st := wac.state.snapshot()
	switch decidePreserve(hasGoodDevice(wac.dataDir), st.PreserveRetryAt, time.Now()) {
	case preserveReconnect:
		wac.logger.Warnf("Device removed (%s). Restoring last-good device and reconnecting once to avoid a re-pair.", reason)
		wac.state.update(func(s *daemonState) {
			s.RestorePending = true
			s.PreserveRetryAt = time.Now().UTC()
		})
		wac.reExecDaemon() // does not return
	default: // preserveGiveUp — today's exact behavior (unchanged)
		wac.logger.Warnf("Device logged out (%s). Clearing dead device and exiting; run `whatsapp provision` to re-link.", reason)
		wac.state.update(func(s *daemonState) {
			s.ExitStatus, s.ExitReason, s.ExitTime = "logged_out", reason, time.Now().UTC()
			s.AuthStatus = "logged_out"
			s.AuthNote = "WhatsApp logged this device out. Re-linking is a deliberate `whatsapp provision`, never an automatic retry loop."
			s.PreserveRetryAt = time.Time{} // episode closed
			// Keep MSISDN so the next `whatsapp provision` re-links the SAME number
			// (reauth), no re-claim.
		})
		if wac.notificationsDir != "" {
			if err := WriteLoggedOutNotification(wac.notificationsDir, wac.instance, reason); err != nil {
				wac.logger.Warnf("Failed to write logged_out notification: %v", err)
			}
		}
		// Tell the pool this managed account was logged out (a device_removed is the
		// authoritative unlink/ban signal), so it marks the account dead and self-heals
		// onto a fresh number. Best-effort and time-bounded: a dead network must not
		// delay the exit. A no-op for self-hosted (qrLinker.reportLogout returns nil).
		reported := make(chan error, 1)
		go func() { reported <- wac.linker.reportLogout() }()
		select {
		case err := <-reported:
			if err != nil {
				wac.logger.Warnf("Failed to report logout to pool: %v", err)
			}
		case <-time.After(ReportLogoutTimeout):
			wac.logger.Warnf("Reporting logout to pool timed out; exiting anyway")
		}
		wac.dropDeadDevice()
		os.Exit(0)
	}
}

// dropDeadDevice clears the logged-out device store so the next daemon start
// builds a fresh device that a deliberate `whatsapp provision` can pair. The
// caller EXITS immediately after (which closes the socket), so this does not
// Disconnect from inside the event-handler goroutine; and Store.Delete poisons the
// in-memory client (ErrDeviceDeleted), which is why this must never be used on a
// daemon that keeps running.
func (wac *WhatsAppClient) dropDeadDevice() {
	if err := wac.client.Store.Delete(context.Background()); err != nil {
		wac.logger.Warnf("Failed to clear logged-out device store: %v", err)
	}
}

// buildNotifContext assembles the NotifContext shared by message and reaction
// notifications.
func (wac *WhatsAppClient) buildNotifContext(chatName, senderDisplay, contactName, contactPhone string, contactSaved, isDirectChat bool) NotifContext {
	return NotifContext{
		NotifDir: wac.notificationsDir, ChatName: chatName,
		ContactName: contactName, ContactPhone: contactPhone,
		Instance: wac.instance, ContactSaved: contactSaved,
		IsDirectChat: isDirectChat, Sender: senderDisplay,
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
	content = wac.resolveMentionsInContent(content, msg)
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
		notifCtx = wac.buildNotifContext(chatName, senderDisplay, contactName, contactPhone, contactSaved, isDirectChat)
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
		ctx := wac.buildNotifContext(chatName, senderDisplay, contactName, contactPhone, contactSaved, isDirectChat)
		WriteReactionNotification(ctx, targetID, emoji, isRemoved)
	}
}

// handleProtocolMessage surfaces the two ways a sender changes a message after the fact:
// editing it and deleting it for everyone. Both arrive as a ProtocolMessage naming the
// original message's key, which whatsmeow's UnwrapRaw leaves wrapped, so they never carry
// text of their own and would otherwise die on handleMessage's empty-content return.
//
// Reached only when the event has a ProtocolMessage: GetType() reports REVOKE for a nil
// one, so testing the type first would read every ordinary message as a deletion.
func (wac *WhatsAppClient) handleProtocolMessage(evt *events.Message) {
	protocol := evt.Message.GetProtocolMessage()
	targetID := protocol.GetKey().GetID()
	if targetID == "" {
		return
	}

	switch protocol.GetType() {
	case waProto.ProtocolMessage_MESSAGE_EDIT:
		wac.handleEdit(evt, targetID, protocol.GetEditedMessage())
	case waProto.ProtocolMessage_REVOKE:
		wac.handleRevoke(evt, targetID)
	}
}

func (wac *WhatsAppClient) handleEdit(evt *events.Message, targetID string, edited *waProto.Message) {
	newText := wac.resolveMentionsInContent(extractTextContent(edited), edited)
	if newText == "" {
		return
	}

	// Read the old text before the update overwrites it: it is the whole point of the
	// notification, and an edit to a message we never stored just reads as empty.
	oldText := wac.storedContent(targetID)
	if wac.store != nil {
		if err := wac.store.UpdateMessageContent(targetID, evt.Info.Chat.String(), newText); err != nil {
			wac.logger.Warnf("Failed to apply edit to message %s: %v", targetID, err)
		}
	}
	if oldText == newText {
		return
	}

	if ctx, ok := wac.notifContextFor(evt); ok {
		if err := WriteEditNotification(ctx, targetID, oldText, newText); err != nil {
			wac.logger.Warnf("Failed to write edit notification for %s: %v", targetID, err)
		}
	}
}

func (wac *WhatsAppClient) handleRevoke(evt *events.Message, targetID string) {
	oldText := wac.storedContent(targetID)
	if oldText == "" {
		return
	}

	if ctx, ok := wac.notifContextFor(evt); ok {
		if err := WriteRevokeNotification(ctx, targetID, oldText); err != nil {
			wac.logger.Warnf("Failed to write revoke notification for %s: %v", targetID, err)
		}
	}
}

func (wac *WhatsAppClient) storedContent(messageID string) string {
	if wac.store == nil {
		return ""
	}
	content, err := wac.store.GetMessageContent(messageID)
	if err != nil {
		wac.logger.Warnf("Failed to look up message %s: %v", messageID, err)
		return ""
	}
	return content
}

// notifContextFor applies the same suppressions handleMessage uses, so an edit or a
// deletion stays as quiet as the message it refers to would have been.
func (wac *WhatsAppClient) notifContextFor(evt *events.Message) (NotifContext, bool) {
	if wac.notificationsDir == "" || wac.noNotify || evt.Info.IsFromMe {
		return NotifContext{}, false
	}
	_, senderDisplay, contactName, contactPhone, contactSaved, isDirectChat := wac.prepareNotificationInfo(evt.Info.MessageSource)
	if wac.skipSenders[contactPhone] {
		return NotifContext{}, false
	}
	return wac.buildNotifContext(wac.getChatName(evt.Info.Chat), senderDisplay, contactName, contactPhone, contactSaved, isDirectChat), true
}

func (wac *WhatsAppClient) handleHistorySync(evt *events.HistorySync) {
	// History backfill can outlast the fixed post-link window; slide the window
	// while batches are still arriving so stop/restart stay refused mid-sync.
	// An expired window is never re-armed: routine syncs outside it are ignored.
	if syncWindowRemaining(wac.state.snapshot().LinkedAt, time.Now()) > 0 {
		wac.markLinkedNow()
	}

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
