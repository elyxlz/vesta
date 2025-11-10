package main

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"math/rand/v2"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/skip2/go-qrcode"
	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
)

type AuthStatus string

const (
	AuthStatusNotAuthenticated AuthStatus = "not_authenticated"
	AuthStatusQRReady          AuthStatus = "qr_ready"
	AuthStatusAuthenticated    AuthStatus = "authenticated"
)

const (
	MaxFileSizeBytes  = 100 * 1024 * 1024 // 100 MB
	MaxAudioSizeBytes = 16 * 1024 * 1024  // 16 MB (WhatsApp limit for audio)
)

type WhatsAppClient struct {
	client            *whatsmeow.Client
	store             *MessageStore
	logger            waLog.Logger
	dataDir           string
	notificationsDir  string
	messageSenders    map[string]string
	sendersMutex      sync.RWMutex
	authStatus        AuthStatus
	authMutex         sync.RWMutex
	qrPath            string
	presenceActive    bool
	presenceMutex     sync.RWMutex
	lastMessageSentAt time.Time
}

func NewWhatsAppClient(dataDir, notificationsDir string, logger waLog.Logger) (*WhatsAppClient, error) {
	// Create message store
	store, err := NewMessageStore(dataDir)
	if err != nil {
		return nil, fmt.Errorf("failed to initialize message store: %v", err)
	}

	// Create WhatsApp database
	dbLog := waLog.Stdout("Database", "INFO", true)
	whatsappDBPath := filepath.Join(dataDir, "whatsapp.db")

	ctx := context.Background()
	container, err := sqlstore.New(ctx, "sqlite3", fmt.Sprintf("file:%s?_foreign_keys=on", whatsappDBPath), dbLog)
	if err != nil {
		store.Close()
		return nil, fmt.Errorf("failed to connect to whatsapp database: %v", err)
	}

	// Get or create device
	deviceStore, err := container.GetFirstDevice(ctx)
	if err != nil {
		if err == sql.ErrNoRows {
			deviceStore = container.NewDevice()
			logger.Infof("Created new device")
		} else {
			store.Close()
			return nil, fmt.Errorf("failed to get device: %v", err)
		}
	}

	// Create WhatsApp client
	client := whatsmeow.NewClient(deviceStore, logger)
	if client == nil {
		store.Close()
		return nil, fmt.Errorf("failed to create WhatsApp client")
	}

	wac := &WhatsAppClient{
		client:           client,
		store:            store,
		logger:           logger,
		dataDir:          dataDir,
		notificationsDir: notificationsDir,
		messageSenders:   make(map[string]string),
		authStatus:       AuthStatusNotAuthenticated,
	}

	// Add event handlers
	client.AddEventHandler(wac.eventHandler)

	return wac, nil
}

func (wac *WhatsAppClient) Connect() error {
	if wac.client.Store.ID == nil {
		// New client, need QR code
		wac.setAuthStatus(AuthStatusNotAuthenticated)

		// Start connection in background
		go wac.handleQRAuthentication()
		return nil
	} else {
		// Already logged in
		wac.logger.Infof("Device already authenticated, connecting...")
		err := wac.client.Connect()
		if err != nil {
			return fmt.Errorf("failed to connect: %v", err)
		}

		// Wait for connection with retries
		for i := 0; i < 10; i++ {
			time.Sleep(1 * time.Second)
			if wac.client.IsConnected() {
				wac.setAuthStatus(AuthStatusAuthenticated)
				wac.logger.Infof("Connected to WhatsApp after %d seconds", i+1)

				// Set online status
				if err := wac.EnsureOnline(); err != nil {
					wac.logger.Warnf("Failed to set online status: %v", err)
				}
				break
			}
		}

		if !wac.client.IsConnected() {
			wac.logger.Warnf("WhatsApp connection not established after 10 seconds")
		}
	}

	return nil
}

func (wac *WhatsAppClient) handleQRAuthentication() {
	qrChan, _ := wac.client.GetQRChannel(context.Background())
	err := wac.client.Connect()
	if err != nil {
		wac.logger.Errorf("Failed to connect for QR: %v", err)
		return
	}

	for evt := range qrChan {
		if evt.Event == "code" {
			// Save QR code as image
			qrPath := filepath.Join(wac.dataDir, "qr-code.png")
			err := qrcode.WriteFile(evt.Code, qrcode.Medium, 256, qrPath)
			if err != nil {
				wac.logger.Errorf("Failed to save QR code: %v", err)
				continue
			}

			wac.authMutex.Lock()
			wac.qrPath = qrPath
			wac.authStatus = AuthStatusQRReady
			wac.authMutex.Unlock()

			wac.logger.Infof("QR code saved to %s", qrPath)
		} else if evt.Event == "success" {
			wac.setAuthStatus(AuthStatusAuthenticated)
			wac.logger.Infof("Successfully authenticated!")

			// Set online status
			if err := wac.EnsureOnline(); err != nil {
				wac.logger.Warnf("Failed to set online status: %v", err)
			}

			// Remove QR code file
			wac.authMutex.Lock()
			if wac.qrPath != "" {
				os.Remove(wac.qrPath)
				wac.qrPath = ""
			}
			wac.authMutex.Unlock()
			break
		}
	}
}

func (wac *WhatsAppClient) setAuthStatus(status AuthStatus) {
	wac.authMutex.Lock()
	wac.authStatus = status
	wac.authMutex.Unlock()
}

func (wac *WhatsAppClient) GetAuthStatus() (AuthStatus, string) {
	wac.authMutex.RLock()
	defer wac.authMutex.RUnlock()
	return wac.authStatus, wac.qrPath
}

func (wac *WhatsAppClient) IsAuthenticated() bool {
	status, _ := wac.GetAuthStatus()
	return status == AuthStatusAuthenticated
}

func (wac *WhatsAppClient) Disconnect() {
	wac.presenceMutex.Lock()
	wac.presenceActive = false
	wac.presenceMutex.Unlock()

	wac.client.Disconnect()
	wac.store.Close()
}

func (wac *WhatsAppClient) eventHandler(evt interface{}) {
	switch v := evt.(type) {
	case *events.Message:
		if v.Message.GetReactionMessage() != nil {
			wac.handleReaction(v)
		} else {
			wac.handleMessage(v)
		}
	case *events.HistorySync:
		wac.handleHistorySync(v)
	case *events.Connected:
		wac.logger.Infof("Connected to WhatsApp")
	case *events.LoggedOut:
		wac.logger.Warnf("Device logged out")
		wac.presenceMutex.Lock()
		wac.presenceActive = false
		wac.presenceMutex.Unlock()
	}
}

func (wac *WhatsAppClient) handleMessage(evt *events.Message) {
	msg := evt.Message
	info := evt.Info

	// Extract message content
	content := extractTextContent(msg)
	isForwarded := isMessageForwarded(msg)
	mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength := extractMediaInfo(msg)

	// Skip empty messages
	if content == "" && mediaType == "" {
		return
	}

	// Get chat name
	chatName := wac.getChatName(info.Chat, info.Sender.String())

	// Store message sender for reactions
	wac.sendersMutex.Lock()
	wac.messageSenders[info.ID] = info.Sender.String()
	wac.sendersMutex.Unlock()

	// Store in database
	wac.store.StoreChat(info.Chat.String(), chatName, info.Timestamp)
	wac.store.StoreMessage(
		info.ID,
		info.Chat.String(),
		info.Sender.String(),
		content,
		info.Timestamp,
		info.IsFromMe,
		isForwarded,
		mediaType,
		filename,
		url,
		mediaKey,
		fileSHA256,
		fileEncSHA256,
		fileLength,
	)

	// Write notification
	if wac.notificationsDir != "" && !info.IsFromMe {
		contactName, contactPhone, contactSaved := wac.notificationContactInfo(info.Chat, chatName)
		senderDisplay := info.Sender.String()
		if contactSaved && contactName != "" {
			if contactPhone != "" {
				senderDisplay = fmt.Sprintf("%s (%s)", contactName, contactPhone)
			} else {
				senderDisplay = contactName
			}
		}
		WriteNotification(
			wac.notificationsDir,
			info.ID,
			chatName,
			contactName,
			contactPhone,
			contactSaved,
			info.Chat.Server == types.DefaultUserServer,
			senderDisplay,
			content,
			mediaType,
			isForwarded,
		)
	}

	// Send read receipt if not from me
	if !info.IsFromMe && wac.client.IsConnected() {
		// Copy fields to avoid race condition with event data
		msgID := info.ID
		chatJID := info.Chat
		senderJID := info.Sender
		go wac.sendReadReceiptDelayed(msgID, chatJID, senderJID, content)
	}
}

func (wac *WhatsAppClient) sendReadReceiptDelayed(msgID string, chatJID, senderJID types.JID, content string) {

	// Calculate reading delay based on content length
	// Base: 2 seconds, +50ms per character, cap at 10 seconds
	readDelay := time.Duration(2000+len(content)*50) * time.Millisecond
	if readDelay > 10*time.Second {
		readDelay = 10 * time.Second
	}

	// Add random variance (±20%)
	variance := int(float64(readDelay.Milliseconds()) * 0.2)
	if variance > 0 {
		readDelay += time.Duration(rand.IntN(variance*2)-variance) * time.Millisecond
	}

	time.Sleep(readDelay)

	// Ensure we're online before sending receipt
	if err := wac.EnsureOnline(); err != nil {
		wac.logger.Warnf("Failed to set online status for read receipt: %v", err)
		return
	}

	// Mark as read
	err := wac.client.MarkRead(
		[]types.MessageID{msgID},
		time.Now(),
		chatJID,
		senderJID,
		types.ReceiptTypeRead,
	)

	if err != nil {
		wac.logger.Warnf("Failed to send read receipt: %v", err)
	} else {
		wac.logger.Debugf("Sent read receipt for message %s after %v delay", msgID, readDelay)
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

	// Get chat name
	chatName := wac.getChatName(evt.Info.Chat, evt.Info.Sender.String())

	// Write notification
	if wac.notificationsDir != "" {
		contactName, contactPhone, contactSaved := wac.notificationContactInfo(evt.Info.Chat, chatName)
		senderDisplay := evt.Info.Sender.String()
		if contactSaved && contactName != "" {
			if contactPhone != "" {
				senderDisplay = fmt.Sprintf("%s (%s)", contactName, contactPhone)
			} else {
				senderDisplay = contactName
			}
		}
		WriteReactionNotification(
			wac.notificationsDir,
			targetID,
			chatName,
			contactName,
			contactPhone,
			contactSaved,
			evt.Info.Chat.Server == types.DefaultUserServer,
			senderDisplay,
			emoji,
			isRemoved,
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

		// Get chat name
		name := wac.getChatNameFromConversation(jid, conversation)

		// Process messages
		for _, msg := range conversation.Messages {
			if msg == nil || msg.Message == nil {
				continue
			}

			// Extract content
			content := extractTextContent(msg.Message.Message)
			isForwarded := msg.Message.Message != nil && isMessageForwarded(msg.Message.Message)
			mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength := extractMediaInfo(msg.Message.Message)

			if content == "" && mediaType == "" {
				continue
			}

			// Get timestamp
			timestamp := time.Unix(int64(msg.Message.GetMessageTimestamp()), 0)

			// Determine sender
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

			// Store message
			msgID := ""
			if msg.Message.Key != nil && msg.Message.Key.ID != nil {
				msgID = *msg.Message.Key.ID
			}

			wac.store.StoreMessage(
				msgID, chatJID, sender, content,
				timestamp, isFromMe, isForwarded,
				mediaType, filename, url,
				mediaKey, fileSHA256, fileEncSHA256, fileLength,
			)
		}

		// Update chat
		if len(conversation.Messages) > 0 {
			latestMsg := conversation.Messages[0]
			if latestMsg != nil && latestMsg.Message != nil {
				timestamp := time.Unix(int64(latestMsg.Message.GetMessageTimestamp()), 0)
				wac.store.StoreChat(chatJID, name, timestamp)
			}
		}
	}
}

func (wac *WhatsAppClient) getChatName(jid types.JID, sender string) string {
	if contact, err := wac.store.GetManualContact(jid.String()); err == nil && contact != nil && contact.Name != "" {
		return contact.Name
	}

	// Try database first
	if name, err := wac.store.GetChatName(jid.String()); err == nil && name != "" {
		return name
	}

	// For groups
	if jid.Server == types.GroupServer {
		if groupInfo, err := wac.client.GetGroupInfo(jid); err == nil {
			return groupInfo.Name
		}
		return fmt.Sprintf("Group %s", jid.User)
	}

	// For contacts
	ctx := context.Background()
	if contact, err := wac.client.Store.Contacts.GetContact(ctx, jid); err == nil && contact.FullName != "" {
		return contact.FullName
	}

	return jid.User
}

func (wac *WhatsAppClient) getChatNameFromConversation(jid types.JID, conversation interface{}) string {
	// Implementation would extract name from conversation object
	// For now, use getChatName
	return wac.getChatName(jid, "")
}

func (wac *WhatsAppClient) notificationContactInfo(jid types.JID, chatName string) (string, string, bool) {
	if jid.Server != types.DefaultUserServer {
		return "", "", false
	}

	contactName := chatName
	contactPhone := ""
	if jid.User != "" {
		contactPhone = "+" + jid.User
	}

	if contact, err := wac.store.GetManualContact(jid.String()); err == nil && contact != nil {
		if contact.Name != "" {
			contactName = contact.Name
		}
		if contact.PhoneNumber != "" {
			contactPhone = contact.PhoneNumber
		}
		return contactName, contactPhone, true
	}

	return contactName, contactPhone, false
}

func (wac *WhatsAppClient) SendMessageWithPresence(recipient, message string) (bool, string) {
	if recipient == "" || message == "" {
		return false, "Recipient and message are required. Provide a contact name, phone number, or group name plus the message text"
	}

	// Check if connected
	if !wac.client.IsConnected() {
		return false, "WhatsApp is not connected. Ensure WhatsApp is authenticated and connected"
	}

	// Resolve recipient to JID
	jid, err := wac.ResolveRecipient(recipient)
	if err != nil {
		return false, err.Error()
	}

	if err := wac.requireManualContact(jid); err != nil {
		return false, err.Error()
	}

	// Ensure we're online
	if err := wac.EnsureOnline(); err != nil {
		wac.logger.Warnf("Failed to set online status: %v", err)
	}

	// Check if this is a rapid message (< 3 seconds since last message)
	wac.presenceMutex.RLock()
	timeSinceLastMessage := time.Since(wac.lastMessageSentAt)
	wac.presenceMutex.RUnlock()

	isRapidMessage := timeSinceLastMessage < 3*time.Second

	// Skip all delays for rapid messages
	if !isRapidMessage {
		// Human reaction delay (0.5-1s)
		reactionDelay := time.Duration(500+rand.IntN(500)) * time.Millisecond
		time.Sleep(reactionDelay)

		// Start typing indicator
		err = wac.client.SendChatPresence(
			jid,
			types.ChatPresenceComposing,
			types.ChatPresenceMediaText,
		)
		if err != nil {
			wac.logger.Warnf("Failed to send typing indicator: %v", err)
		}

		// Calculate typing duration (30ms per character, min 2s, max 8s)
		typingDuration := time.Duration(2000+len(message)*30) * time.Millisecond
		if typingDuration > 8*time.Second {
			typingDuration = 8 * time.Second
		}
		// Add randomness (±20%)
		variance := int(float64(typingDuration.Milliseconds()) * 0.2)
		if variance > 0 {
			typingDuration += time.Duration(rand.IntN(variance*2)-variance) * time.Millisecond
		}

		time.Sleep(typingDuration)

		// Stop typing
		err = wac.client.SendChatPresence(
			jid,
			types.ChatPresencePaused,
			types.ChatPresenceMediaText,
		)
		if err != nil {
			wac.logger.Debugf("Failed to stop typing indicator: %v", err)
		}

		// Small delay before sending (0.3-0.5s)
		sendDelay := time.Duration(300+rand.IntN(200)) * time.Millisecond
		time.Sleep(sendDelay)
	}

	// Actually send the message
	msg := &waProto.Message{
		Conversation: proto.String(message),
	}

	resp, err := wac.client.SendMessage(context.Background(), jid, msg)
	if err != nil {
		return false, fmt.Sprintf("Failed to send message: %v", err)
	}

	// Update last message sent time
	wac.presenceMutex.Lock()
	wac.lastMessageSentAt = time.Now()
	wac.presenceMutex.Unlock()

	return true, fmt.Sprintf("Message sent successfully (ID: %s)", resp.ID)
}

func (wac *WhatsAppClient) SendMessage(recipient, message string) (bool, string) {
	if recipient == "" || message == "" {
		return false, "Recipient and message are required. Provide a contact name, phone number, or group name plus the message text"
	}

	// Check if connected
	if !wac.client.IsConnected() {
		return false, "WhatsApp is not connected. Ensure WhatsApp is authenticated and connected"
	}

	// Resolve recipient to JID
	jid, err := wac.ResolveRecipient(recipient)
	if err != nil {
		return false, err.Error()
	}

	if err := wac.requireManualContact(jid); err != nil {
		return false, err.Error()
	}

	// Send message
	msg := &waProto.Message{
		Conversation: proto.String(message),
	}

	resp, err := wac.client.SendMessage(context.Background(), jid, msg)
	if err != nil {
		return false, fmt.Sprintf("Failed to send message: %v", err)
	}

	return true, fmt.Sprintf("Message sent successfully (ID: %s)", resp.ID)
}

func (wac *WhatsAppClient) SendFile(recipient, filePath, caption string) (bool, string) {
	if recipient == "" || filePath == "" {
		return false, "Recipient and file path are required. Provide a contact name, phone number, or group name and the file path"
	}

	// Validate file path for security
	if err := validateFilePath(filePath); err != nil {
		return false, fmt.Sprintf("Invalid file path: %v", err)
	}

	// Check file exists and get size
	fileInfo, err := os.Stat(filePath)
	if err != nil {
		return false, fmt.Sprintf("File not found: %s", filePath)
	}

	// Check file size
	if fileInfo.Size() > MaxFileSizeBytes {
		return false, fmt.Sprintf("File too large: %d MB (max %d MB)",
			fileInfo.Size()/(1024*1024), MaxFileSizeBytes/(1024*1024))
	}

	// Resolve recipient to JID
	jid, err := wac.ResolveRecipient(recipient)
	if err != nil {
		return false, err.Error()
	}

	if err := wac.requireManualContact(jid); err != nil {
		return false, err.Error()
	}

	// Read file
	data, err := os.ReadFile(filePath)
	if err != nil {
		return false, fmt.Sprintf("Failed to read file: %v", err)
	}

	// Detect media type
	mediaType, mimeType := detectMediaType(filePath)

	// Upload file with appropriate media type
	uploaded, err := wac.client.Upload(context.Background(), data, mediaType)
	if err != nil {
		return false, fmt.Sprintf("Failed to upload file: %v", err)
	}

	// Create message based on media type
	msg := &waProto.Message{}
	switch mediaType {
	case whatsmeow.MediaImage:
		msg.ImageMessage = &waProto.ImageMessage{
			URL:           proto.String(uploaded.URL),
			DirectPath:    proto.String(uploaded.DirectPath),
			MediaKey:      uploaded.MediaKey,
			FileEncSHA256: uploaded.FileEncSHA256,
			FileSHA256:    uploaded.FileSHA256,
			FileLength:    proto.Uint64(uploaded.FileLength),
			Mimetype:      proto.String(mimeType),
		}
		if caption != "" {
			msg.ImageMessage.Caption = proto.String(caption)
		}

	case whatsmeow.MediaVideo:
		msg.VideoMessage = &waProto.VideoMessage{
			URL:           proto.String(uploaded.URL),
			DirectPath:    proto.String(uploaded.DirectPath),
			MediaKey:      uploaded.MediaKey,
			FileEncSHA256: uploaded.FileEncSHA256,
			FileSHA256:    uploaded.FileSHA256,
			FileLength:    proto.Uint64(uploaded.FileLength),
			Mimetype:      proto.String(mimeType),
		}
		if caption != "" {
			msg.VideoMessage.Caption = proto.String(caption)
		}

	default: // MediaDocument
		msg.DocumentMessage = &waProto.DocumentMessage{
			URL:           proto.String(uploaded.URL),
			DirectPath:    proto.String(uploaded.DirectPath),
			MediaKey:      uploaded.MediaKey,
			FileEncSHA256: uploaded.FileEncSHA256,
			FileSHA256:    uploaded.FileSHA256,
			FileLength:    proto.Uint64(uploaded.FileLength),
			FileName:      proto.String(filepath.Base(filePath)),
			Mimetype:      proto.String(mimeType),
		}
		if caption != "" {
			msg.DocumentMessage.Caption = proto.String(caption)
		}
	}

	resp, err := wac.client.SendMessage(context.Background(), jid, msg)
	if err != nil {
		return false, fmt.Sprintf("Failed to send file: %v", err)
	}

	return true, fmt.Sprintf("File sent successfully (ID: %s)", resp.ID)
}

func (wac *WhatsAppClient) SendAudioMessageWithPresence(recipient, filePath string) (bool, string) {
	if recipient == "" || filePath == "" {
		return false, "Recipient and file path are required. Provide a contact name, phone number, or group name and the audio file path"
	}

	// Validate file path for security
	if err := validateFilePath(filePath); err != nil {
		return false, fmt.Sprintf("Invalid file path: %v", err)
	}

	// Resolve recipient to JID
	jid, err := wac.ResolveRecipient(recipient)
	if err != nil {
		return false, err.Error()
	}

	if err := wac.requireManualContact(jid); err != nil {
		return false, err.Error()
	}

	// Ensure we're online
	if err := wac.EnsureOnline(); err != nil {
		wac.logger.Warnf("Failed to set online status: %v", err)
	}

	// Human reaction delay (0.5-1s)
	reactionDelay := time.Duration(500+rand.IntN(500)) * time.Millisecond
	time.Sleep(reactionDelay)

	// Start recording indicator
	err = wac.client.SendChatPresence(
		jid,
		types.ChatPresenceComposing,
		types.ChatPresenceMediaAudio,
	)
	if err != nil {
		wac.logger.Warnf("Failed to send recording indicator: %v", err)
	}

	// Convert to opus if needed (happens during "recording" indicator)
	if !strings.HasSuffix(filePath, ".ogg") {
		converted, err := ConvertToOpusOggTemp(filePath, "32k", 24000)
		if err != nil {
			// Stop recording indicator on error
			if stopErr := wac.client.SendChatPresence(jid, types.ChatPresencePaused, types.ChatPresenceMediaAudio); stopErr != nil {
				wac.logger.Debugf("Failed to stop recording indicator: %v", stopErr)
			}
			return false, fmt.Sprintf("Failed to convert audio: %v", err)
		}
		filePath = converted
		defer os.Remove(converted)
	}

	// Check file size
	fileInfo, err := os.Stat(filePath)
	if err != nil {
		if stopErr := wac.client.SendChatPresence(jid, types.ChatPresencePaused, types.ChatPresenceMediaAudio); stopErr != nil {
			wac.logger.Debugf("Failed to stop recording indicator: %v", stopErr)
		}
		return false, fmt.Sprintf("Audio file not found: %v", err)
	}
	if fileInfo.Size() > MaxAudioSizeBytes {
		if stopErr := wac.client.SendChatPresence(jid, types.ChatPresencePaused, types.ChatPresenceMediaAudio); stopErr != nil {
			wac.logger.Debugf("Failed to stop recording indicator: %v", stopErr)
		}
		return false, fmt.Sprintf("Audio file too large: %d MB (max %d MB)",
			fileInfo.Size()/(1024*1024), MaxAudioSizeBytes/(1024*1024))
	}

	// Read file
	data, err := os.ReadFile(filePath)
	if err != nil {
		if stopErr := wac.client.SendChatPresence(jid, types.ChatPresencePaused, types.ChatPresenceMediaAudio); stopErr != nil {
			wac.logger.Debugf("Failed to stop recording indicator: %v", stopErr)
		}
		return false, fmt.Sprintf("Failed to read audio file: %v", err)
	}

	// Calculate duration and waveform
	duration, waveform := analyzeOpusOgg(data)

	// Upload audio (still "recording")
	uploaded, err := wac.client.Upload(context.Background(), data, whatsmeow.MediaAudio)
	if err != nil {
		if stopErr := wac.client.SendChatPresence(jid, types.ChatPresencePaused, types.ChatPresenceMediaAudio); stopErr != nil {
			wac.logger.Debugf("Failed to stop recording indicator: %v", stopErr)
		}
		return false, fmt.Sprintf("Failed to upload audio: %v", err)
	}

	// Stop recording indicator
	err = wac.client.SendChatPresence(
		jid,
		types.ChatPresencePaused,
		types.ChatPresenceMediaAudio,
	)
	if err != nil {
		wac.logger.Debugf("Failed to stop recording indicator: %v", err)
	}

	// Small delay before sending (0.3-0.5s)
	sendDelay := time.Duration(300+rand.IntN(200)) * time.Millisecond
	time.Sleep(sendDelay)

	// Create audio message
	msg := &waProto.Message{
		AudioMessage: &waProto.AudioMessage{
			URL:           proto.String(uploaded.URL),
			DirectPath:    proto.String(uploaded.DirectPath),
			MediaKey:      uploaded.MediaKey,
			FileEncSHA256: uploaded.FileEncSHA256,
			FileSHA256:    uploaded.FileSHA256,
			FileLength:    proto.Uint64(uploaded.FileLength),
			Mimetype:      proto.String("audio/ogg; codecs=opus"),
			Seconds:       proto.Uint32(duration),
			PTT:           proto.Bool(true),
			Waveform:      waveform,
		},
	}

	resp, err := wac.client.SendMessage(context.Background(), jid, msg)
	if err != nil {
		return false, fmt.Sprintf("Failed to send audio message: %v", err)
	}

	return true, fmt.Sprintf("Audio message sent successfully (ID: %s)", resp.ID)
}

func (wac *WhatsAppClient) SendAudioMessage(recipient, filePath string) (bool, string) {
	if recipient == "" || filePath == "" {
		return false, "Recipient and file path are required. Provide a contact name, phone number, or group name and the audio file path"
	}

	// Validate file path for security
	if err := validateFilePath(filePath); err != nil {
		return false, fmt.Sprintf("Invalid file path: %v", err)
	}

	// Resolve recipient to JID
	jid, err := wac.ResolveRecipient(recipient)
	if err != nil {
		return false, err.Error()
	}

	if err := wac.requireManualContact(jid); err != nil {
		return false, err.Error()
	}

	// Convert to opus if needed
	if !strings.HasSuffix(filePath, ".ogg") {
		converted, err := ConvertToOpusOggTemp(filePath, "32k", 24000)
		if err != nil {
			return false, fmt.Sprintf("Failed to convert audio: %v", err)
		}
		filePath = converted
		defer os.Remove(converted)
	}

	// Check file size
	fileInfo, err := os.Stat(filePath)
	if err != nil {
		return false, fmt.Sprintf("Audio file not found: %v", err)
	}
	if fileInfo.Size() > MaxAudioSizeBytes {
		return false, fmt.Sprintf("Audio file too large: %d MB (max %d MB)",
			fileInfo.Size()/(1024*1024), MaxAudioSizeBytes/(1024*1024))
	}

	// Read file
	data, err := os.ReadFile(filePath)
	if err != nil {
		return false, fmt.Sprintf("Failed to read audio file: %v", err)
	}

	// Calculate duration and waveform
	duration, waveform := analyzeOpusOgg(data)

	// Upload audio
	uploaded, err := wac.client.Upload(context.Background(), data, whatsmeow.MediaAudio)
	if err != nil {
		return false, fmt.Sprintf("Failed to upload audio: %v", err)
	}

	// Create audio message
	msg := &waProto.Message{
		AudioMessage: &waProto.AudioMessage{
			URL:           proto.String(uploaded.URL),
			DirectPath:    proto.String(uploaded.DirectPath),
			MediaKey:      uploaded.MediaKey,
			FileEncSHA256: uploaded.FileEncSHA256,
			FileSHA256:    uploaded.FileSHA256,
			FileLength:    proto.Uint64(uploaded.FileLength),
			Mimetype:      proto.String("audio/ogg; codecs=opus"),
			Seconds:       proto.Uint32(duration),
			PTT:           proto.Bool(true),
			Waveform:      waveform,
		},
	}

	resp, err := wac.client.SendMessage(context.Background(), jid, msg)
	if err != nil {
		return false, fmt.Sprintf("Failed to send audio message: %v", err)
	}

	return true, fmt.Sprintf("Audio message sent successfully (ID: %s)", resp.ID)
}

func (wac *WhatsAppClient) DownloadMedia(messageID, chatIdentifier, downloadPath string) (string, error) {
	if messageID == "" {
		return "", fmt.Errorf("message ID cannot be empty")
	}

	// Resolve chat identifier to JID
	jid, err := wac.ResolveRecipient(chatIdentifier)
	if err != nil {
		return "", fmt.Errorf("failed to resolve chat: %v", err)
	}

	// Get media info from database
	mediaInfo, err := wac.store.GetMessageMediaInfo(messageID, jid.String())
	if err != nil {
		return "", err
	}

	// Create downloadable message based on media type
	var downloadable whatsmeow.DownloadableMessage
	switch mediaInfo.MediaType {
	case "image":
		downloadable = &waProto.ImageMessage{
			URL:           proto.String(mediaInfo.URL),
			MediaKey:      mediaInfo.MediaKey,
			FileSHA256:    mediaInfo.FileSHA256,
			FileEncSHA256: mediaInfo.FileEncSHA256,
			FileLength:    proto.Uint64(mediaInfo.FileLength),
		}
	case "video":
		downloadable = &waProto.VideoMessage{
			URL:           proto.String(mediaInfo.URL),
			MediaKey:      mediaInfo.MediaKey,
			FileSHA256:    mediaInfo.FileSHA256,
			FileEncSHA256: mediaInfo.FileEncSHA256,
			FileLength:    proto.Uint64(mediaInfo.FileLength),
		}
	case "audio":
		downloadable = &waProto.AudioMessage{
			URL:           proto.String(mediaInfo.URL),
			MediaKey:      mediaInfo.MediaKey,
			FileSHA256:    mediaInfo.FileSHA256,
			FileEncSHA256: mediaInfo.FileEncSHA256,
			FileLength:    proto.Uint64(mediaInfo.FileLength),
		}
	case "document":
		downloadable = &waProto.DocumentMessage{
			URL:           proto.String(mediaInfo.URL),
			MediaKey:      mediaInfo.MediaKey,
			FileSHA256:    mediaInfo.FileSHA256,
			FileEncSHA256: mediaInfo.FileEncSHA256,
			FileLength:    proto.Uint64(mediaInfo.FileLength),
		}
	default:
		return "", fmt.Errorf("unsupported media type: %s", mediaInfo.MediaType)
	}

	// Download media from WhatsApp servers
	data, err := wac.client.Download(context.Background(), downloadable)
	if err != nil {
		return "", fmt.Errorf("failed to download media: %v", err)
	}

	// Determine save path
	savePath := downloadPath
	if savePath == "" {
		// Default to downloads directory
		downloadsDir := filepath.Join(wac.dataDir, "downloads")
		if err := os.MkdirAll(downloadsDir, 0755); err != nil {
			return "", fmt.Errorf("failed to create downloads directory: %v", err)
		}

		// Use filename if available, otherwise generate one
		filename := mediaInfo.Filename
		if filename == "" {
			ext := getExtensionForMediaType(mediaInfo.MediaType)
			filename = fmt.Sprintf("%s_%s%s", messageID, time.Now().Format("20060102_150405"), ext)
		}
		savePath = filepath.Join(downloadsDir, filename)
	} else {
		// Validate user-provided download path
		if err := validateFilePath(downloadPath); err != nil {
			return "", fmt.Errorf("invalid download path: %v", err)
		}
	}

	// Ensure parent directory exists
	if err := os.MkdirAll(filepath.Dir(savePath), 0755); err != nil {
		return "", fmt.Errorf("failed to create directory: %v", err)
	}

	// Write to file
	if err := os.WriteFile(savePath, data, 0644); err != nil {
		return "", fmt.Errorf("failed to save file: %v", err)
	}

	return savePath, nil
}

func getExtensionForMediaType(mediaType string) string {
	switch mediaType {
	case "image":
		return ".jpg"
	case "video":
		return ".mp4"
	case "audio":
		return ".ogg"
	case "document":
		return ".bin"
	default:
		return ".bin"
	}
}

func detectMediaType(filePath string) (mediaType whatsmeow.MediaType, mimeType string) {
	ext := strings.ToLower(filepath.Ext(filePath))

	// Image types
	switch ext {
	case ".jpg", ".jpeg":
		return whatsmeow.MediaImage, "image/jpeg"
	case ".png":
		return whatsmeow.MediaImage, "image/png"
	case ".gif":
		return whatsmeow.MediaImage, "image/gif"
	case ".webp":
		return whatsmeow.MediaImage, "image/webp"
	}

	// Video types
	switch ext {
	case ".mp4":
		return whatsmeow.MediaVideo, "video/mp4"
	case ".mov":
		return whatsmeow.MediaVideo, "video/quicktime"
	case ".avi":
		return whatsmeow.MediaVideo, "video/x-msvideo"
	case ".mkv":
		return whatsmeow.MediaVideo, "video/x-matroska"
	case ".webm":
		return whatsmeow.MediaVideo, "video/webm"
	}

	// Audio types
	switch ext {
	case ".mp3":
		return whatsmeow.MediaAudio, "audio/mpeg"
	case ".ogg":
		return whatsmeow.MediaAudio, "audio/ogg"
	case ".m4a":
		return whatsmeow.MediaAudio, "audio/mp4"
	case ".wav":
		return whatsmeow.MediaAudio, "audio/wav"
	}

	// Default to document
	return whatsmeow.MediaDocument, "application/octet-stream"
}

func (wac *WhatsAppClient) SendReaction(messageID, emoji, chatIdentifier string) (bool, string) {
	// Resolve chat identifier to JID
	jid, err := wac.ResolveRecipient(chatIdentifier)
	if err != nil {
		return false, fmt.Sprintf("Failed to resolve chat: %v", err)
	}

	// Determine sender JID
	var senderJID types.JID
	if jid.Server == types.DefaultUserServer {
		senderJID = jid
	} else if jid.Server == types.GroupServer {
		wac.sendersMutex.RLock()
		storedSender := wac.messageSenders[messageID]
		wac.sendersMutex.RUnlock()

		if storedSender != "" {
			senderJID, err = types.ParseJID(storedSender)
			if err != nil {
				return false, fmt.Sprintf("Could not resolve the original sender for this message: %v", err)
			}
		} else {
			return false, "Message sender not found for group reaction"
		}
	} else {
		return false, fmt.Sprintf("Unsupported chat type: %s", jid.Server)
	}

	reactionMsg := wac.client.BuildReaction(jid, senderJID, messageID, emoji)

	_, err = wac.client.SendMessage(context.Background(), jid, reactionMsg)
	if err != nil {
		return false, fmt.Sprintf("Failed to send reaction: %v", err)
	}

	action := "sent"
	if emoji == "" {
		action = "removed"
	}

	return true, fmt.Sprintf("Reaction %s successfully", action)
}

func (wac *WhatsAppClient) CreateGroup(name string, participants []string) (bool, string) {
	if name == "" || len(participants) == 0 {
		return false, "Group name and participants are required"
	}

	jids, err := parseParticipantJIDs(participants)
	if err != nil {
		return false, err.Error()
	}

	resp, err := wac.client.CreateGroup(context.Background(), whatsmeow.ReqCreateGroup{
		Name:         name,
		Participants: jids,
	})
	if err != nil {
		return false, fmt.Sprintf("Failed to create group: %v", err)
	}
	if resp.JID.String() != "" {
		wac.store.StoreChat(resp.JID.String(), name, time.Now())
	}
	return true, fmt.Sprintf("Group '%s' created successfully", name)
}

func (wac *WhatsAppClient) LeaveGroup(groupIdentifier string) (bool, string) {
	if groupIdentifier == "" {
		return false, "Group name is required"
	}

	jid, err := wac.ResolveRecipient(groupIdentifier)
	if err != nil {
		return false, fmt.Sprintf("Failed to resolve group: %v", err)
	}
	if jid.Server != types.GroupServer {
		return false, "The specified identifier is not a WhatsApp group"
	}

	err = wac.client.LeaveGroup(jid)
	if err != nil {
		return false, fmt.Sprintf("Failed to leave group: %v", err)
	}

	return true, "Successfully left the group"
}

func (wac *WhatsAppClient) GetGroupInviteLink(groupIdentifier string) (bool, string, string) {
	jid, err := wac.ResolveRecipient(groupIdentifier)
	if err != nil {
		return false, "", fmt.Sprintf("Failed to resolve group: %v", err)
	}
	if jid.Server != types.GroupServer {
		return false, "", "The specified identifier is not a WhatsApp group"
	}

	link, err := wac.client.GetGroupInviteLink(jid, false)
	if err != nil {
		return false, "", fmt.Sprintf("Failed to get invite link: %v", err)
	}

	return true, link, "Invite link retrieved successfully"
}

func (wac *WhatsAppClient) EnsureOnline() error {
	wac.presenceMutex.Lock()
	defer wac.presenceMutex.Unlock()

	if !wac.presenceActive {
		err := wac.client.SendPresence(types.PresenceAvailable)
		if err != nil {
			return fmt.Errorf("failed to set online status: %v", err)
		}
		wac.presenceActive = true
		wac.logger.Debugf("Set online status")
	}
	return nil
}

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

	// 1. If contains "@", parse as JID directly
	if strings.Contains(identifier, "@") {
		jid, err := types.ParseJID(identifier)
		if err != nil {
			return types.JID{}, fmt.Errorf("invalid WhatsApp address '%s': %v. Use a phone number (+1234567890) or saved contact/group name instead", identifier, err)
		}
		return jid, nil
	}

	// 2. If starts with "+", treat as phone number
	if strings.HasPrefix(identifier, "+") {
		phone := strings.TrimPrefix(identifier, "+")
		if !isNumeric(phone) {
			return types.JID{}, fmt.Errorf("invalid phone number '%s': must contain only digits after '+'", identifier)
		}
		return types.NewJID(phone, types.DefaultUserServer), nil
	}

	// 3. If all digits, treat as phone number without "+"
	if isNumeric(identifier) {
		return types.NewJID(identifier, types.DefaultUserServer), nil
	}

	// 4. Search contacts by name
	contacts, err := wac.store.SearchContacts(identifier, 50)
	if err == nil {
		if jid, err := resolveFromContacts(contacts, identifier); err != nil || jid.User != "" {
			return jid, err
		}
	}

	// 5. Search groups by name
	groups, err := wac.store.ListGroups(50, 0)
	if err == nil {
		if jid, err := resolveFromGroups(groups, identifier); err != nil || jid.User != "" {
			return jid, err
		}
	}

	// 6. No matches found
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

	// Multiple matches - build suggestions
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
	// Filter matches
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

	// Multiple matches - build suggestions
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

func validateFilePath(path string) error {
	if path == "" {
		return fmt.Errorf("file path cannot be empty")
	}

	// Clean the path to resolve any .. or .
	cleanPath := filepath.Clean(path)

	// Convert to absolute path
	absPath, err := filepath.Abs(cleanPath)
	if err != nil {
		return fmt.Errorf("invalid file path: %v", err)
	}

	// Check for path traversal attempts
	if strings.Contains(absPath, "..") {
		return fmt.Errorf("path traversal detected in file path")
	}

	return nil
}

func parseParticipantJIDs(participants []string) ([]types.JID, error) {
	jids := make([]types.JID, 0, len(participants))
	for _, p := range participants {
		var jid types.JID
		var err error
		if strings.Contains(p, "@") {
			jid, err = types.ParseJID(p)
		} else {
			jid = types.NewJID(p, types.DefaultUserServer)
		}
		if err != nil {
			return nil, fmt.Errorf("invalid participant: %s", p)
		}
		jids = append(jids, jid)
	}
	return jids, nil
}

func (wac *WhatsAppClient) UpdateGroupParticipants(groupIdentifier, action string, participants []string) (bool, string) {
	if groupIdentifier == "" {
		return false, "group is required"
	}

	jid, err := wac.ResolveRecipient(groupIdentifier)
	if err != nil {
		return false, fmt.Sprintf("Failed to resolve group: %v", err)
	}
	if jid.Server != types.GroupServer {
		return false, "The specified identifier is not a WhatsApp group"
	}

	participantJIDs, err := parseParticipantJIDs(participants)
	if err != nil {
		return false, err.Error()
	}

	changeType, ok := map[string]whatsmeow.ParticipantChange{
		"add":    whatsmeow.ParticipantChangeAdd,
		"remove": whatsmeow.ParticipantChangeRemove,
	}[action]

	if !ok {
		return false, "Invalid action: must be 'add' or 'remove'"
	}

	_, err = wac.client.UpdateGroupParticipants(jid, participantJIDs, changeType)
	if err != nil {
		return false, fmt.Sprintf("Failed to update participants: %v", err)
	}
	return true, fmt.Sprintf("Successfully %sed participants", action)
}

// Helper functions

func extractTextContent(msg *waProto.Message) string {
	if msg == nil {
		return ""
	}
	if msg.GetConversation() != "" {
		return msg.GetConversation()
	}
	if ext := msg.GetExtendedTextMessage(); ext != nil {
		return ext.GetText()
	}
	if img := msg.GetImageMessage(); img != nil && img.GetCaption() != "" {
		return img.GetCaption()
	}
	if vid := msg.GetVideoMessage(); vid != nil && vid.GetCaption() != "" {
		return vid.GetCaption()
	}
	if doc := msg.GetDocumentMessage(); doc != nil && doc.GetCaption() != "" {
		return doc.GetCaption()
	}
	return ""
}

func isMessageForwarded(msg *waProto.Message) bool {
	if msg == nil {
		return false
	}
	if msg.GetExtendedTextMessage() != nil {
		return msg.GetExtendedTextMessage().GetContextInfo().GetIsForwarded()
	}
	if msg.GetImageMessage() != nil {
		return msg.GetImageMessage().GetContextInfo().GetIsForwarded()
	}
	if msg.GetVideoMessage() != nil {
		return msg.GetVideoMessage().GetContextInfo().GetIsForwarded()
	}
	if msg.GetDocumentMessage() != nil {
		return msg.GetDocumentMessage().GetContextInfo().GetIsForwarded()
	}
	return false
}

func extractMediaInfo(msg *waProto.Message) (
	mediaType, filename, url string,
	mediaKey, fileSHA256, fileEncSHA256 []byte,
	fileLength uint64,
) {
	if msg == nil {
		return
	}

	if img := msg.GetImageMessage(); img != nil {
		return "image", "", img.GetURL(),
			img.GetMediaKey(), img.GetFileSHA256(), img.GetFileEncSHA256(),
			img.GetFileLength()
	}
	if vid := msg.GetVideoMessage(); vid != nil {
		return "video", "", vid.GetURL(),
			vid.GetMediaKey(), vid.GetFileSHA256(), vid.GetFileEncSHA256(),
			vid.GetFileLength()
	}
	if aud := msg.GetAudioMessage(); aud != nil {
		return "audio", "", aud.GetURL(),
			aud.GetMediaKey(), aud.GetFileSHA256(), aud.GetFileEncSHA256(),
			aud.GetFileLength()
	}
	if doc := msg.GetDocumentMessage(); doc != nil {
		return "document", doc.GetFileName(), doc.GetURL(),
			doc.GetMediaKey(), doc.GetFileSHA256(), doc.GetFileEncSHA256(),
			doc.GetFileLength()
	}

	return
}

func analyzeOpusOgg(data []byte) (uint32, []byte) {
	// Simplified analysis - would need full implementation
	duration := uint32(len(data) / 2000) // Rough estimate
	if duration < 1 {
		duration = 1
	} else if duration > 300 {
		duration = 300
	}

	// Generate placeholder waveform
	waveform := make([]byte, 64)
	rng := rand.New(rand.NewPCG(uint64(duration), uint64(duration)))
	for i := range waveform {
		pos := float64(i) / 64.0
		val := 35.0 * math.Sin(pos*math.Pi*8)
		val += (rng.Float64() - 0.5) * 15
		val += 50
		if val < 0 {
			val = 0
		} else if val > 100 {
			val = 100
		}
		waveform[i] = byte(val)
	}

	return duration, waveform
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
