package main

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"math/rand"
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

type WhatsAppClient struct {
	client           *whatsmeow.Client
	store            *MessageStore
	logger           waLog.Logger
	dataDir          string
	notificationsDir string
	messageSenders   map[string]string
	sendersMutex     sync.RWMutex
	authStatus       AuthStatus
	authMutex        sync.RWMutex
	qrPath           string
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
	}
}

func (wac *WhatsAppClient) handleMessage(evt *events.Message) {
	msg := evt.Message
	info := evt.Info

	// Extract message content
	content := extractTextContent(msg)
	isForwarded := isMessageForwarded(msg)
	mediaType, filename, _, _, _, _, _ := extractMediaInfo(msg)

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
		"", nil, nil, nil, 0,
	)

	// Write notification
	if wac.notificationsDir != "" && !info.IsFromMe {
		WriteNotification(
			wac.notificationsDir,
			info.ID,
			info.Chat.String(),
			chatName,
			info.Sender.String(),
			content,
			mediaType,
			isForwarded,
		)
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
		WriteReactionNotification(
			wac.notificationsDir,
			targetID,
			evt.Info.Chat.String(),
			chatName,
			evt.Info.Sender.String(),
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

func (wac *WhatsAppClient) SendMessage(recipient, message string) (bool, string) {
	if recipient == "" || message == "" {
		return false, "Recipient and message are required. Provide recipient (contact name, phone number, or JID) and message text"
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
		return false, "Recipient and file path are required. Provide recipient (contact name, phone number, or JID) and file path"
	}

	// Check file exists
	if _, err := os.Stat(filePath); err != nil {
		return false, fmt.Sprintf("File not found: %s", filePath)
	}

	// Resolve recipient to JID
	jid, err := wac.ResolveRecipient(recipient)
	if err != nil {
		return false, err.Error()
	}

	// Read file
	data, err := os.ReadFile(filePath)
	if err != nil {
		return false, fmt.Sprintf("Failed to read file: %v", err)
	}

	// Upload file
	uploaded, err := wac.client.Upload(context.Background(), data, whatsmeow.MediaDocument)
	if err != nil {
		return false, fmt.Sprintf("Failed to upload file: %v", err)
	}

	// Create message
	msg := &waProto.Message{
		DocumentMessage: &waProto.DocumentMessage{
			URL:           proto.String(uploaded.URL),
			DirectPath:    proto.String(uploaded.DirectPath),
			MediaKey:      uploaded.MediaKey,
			FileEncSHA256: uploaded.FileEncSHA256,
			FileSHA256:    uploaded.FileSHA256,
			FileLength:    proto.Uint64(uploaded.FileLength),
			FileName:      proto.String(filepath.Base(filePath)),
		},
	}

	if caption != "" {
		msg.DocumentMessage.Caption = proto.String(caption)
	}

	resp, err := wac.client.SendMessage(context.Background(), jid, msg)
	if err != nil {
		return false, fmt.Sprintf("Failed to send file: %v", err)
	}

	return true, fmt.Sprintf("File sent successfully (ID: %s)", resp.ID)
}

func (wac *WhatsAppClient) SendAudioMessage(recipient, filePath string) (bool, string) {
	if recipient == "" || filePath == "" {
		return false, "Recipient and file path are required. Provide recipient (contact name, phone number, or JID) and audio file path"
	}

	// Resolve recipient to JID
	jid, err := wac.ResolveRecipient(recipient)
	if err != nil {
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

func (wac *WhatsAppClient) DownloadMedia(messageID, chatIdentifier string) (string, error) {
	// Resolve chat identifier to JID
	_, err := wac.ResolveRecipient(chatIdentifier)
	if err != nil {
		return "", fmt.Errorf("failed to resolve chat: %v", err)
	}

	// This would need implementation to download media from stored message info
	// For now, return placeholder
	return "", fmt.Errorf("media download not yet implemented")
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
				return false, fmt.Sprintf("Invalid sender JID: %v", err)
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

func (wac *WhatsAppClient) CreateGroup(name string, participants []string) (bool, string, string) {
	if name == "" || len(participants) == 0 {
		return false, "", "Group name and participants are required"
	}

	jids, err := parseParticipantJIDs(participants)
	if err != nil {
		return false, "", err.Error()
	}

	resp, err := wac.client.CreateGroup(context.Background(), whatsmeow.ReqCreateGroup{
		Name:         name,
		Participants: jids,
	})
	if err != nil {
		return false, "", fmt.Sprintf("Failed to create group: %v", err)
	}
	return true, resp.JID.String(), fmt.Sprintf("Group '%s' created successfully", name)
}

func (wac *WhatsAppClient) LeaveGroup(groupJID string) (bool, string) {
	jid, err := types.ParseJID(groupJID)
	if err != nil {
		return false, fmt.Sprintf("Invalid group JID: %v", err)
	}

	err = wac.client.LeaveGroup(jid)
	if err != nil {
		return false, fmt.Sprintf("Failed to leave group: %v", err)
	}

	return true, "Successfully left the group"
}

func (wac *WhatsAppClient) GetGroupInviteLink(groupJID string) (bool, string, string) {
	jid, err := types.ParseJID(groupJID)
	if err != nil {
		return false, "", fmt.Sprintf("Invalid group JID: %v", err)
	}

	link, err := wac.client.GetGroupInviteLink(jid, false)
	if err != nil {
		return false, "", fmt.Sprintf("Failed to get invite link: %v", err)
	}

	return true, link, "Invite link retrieved successfully"
}

func (wac *WhatsAppClient) ResolveRecipient(identifier string) (types.JID, error) {
	if identifier == "" {
		return types.JID{}, fmt.Errorf("recipient identifier cannot be empty")
	}

	// 1. If contains "@", parse as JID directly
	if strings.Contains(identifier, "@") {
		jid, err := types.ParseJID(identifier)
		if err != nil {
			return types.JID{}, fmt.Errorf("invalid JID format '%s': %v. Use phone (+1234567890), contact name, or valid JID", identifier, err)
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

	if len(contacts) == 1 {
		jid, err := types.ParseJID(contacts[0].JID)
		if err != nil {
			return types.JID{}, fmt.Errorf("invalid contact JID: %v", err)
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
			return types.JID{}, fmt.Errorf("invalid group JID: %v", err)
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
	return types.JID{}, fmt.Errorf("multiple groups match '%s': %s. Please use full group name or JID",
		identifier, strings.Join(names, ", "))
}

func isNumeric(s string) bool {
	_, err := strconv.ParseUint(s, 10, 64)
	return err == nil && len(s) > 0
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

func (wac *WhatsAppClient) UpdateGroupParticipants(groupJID, action string, participants []string) (bool, string) {
	jid, err := types.ParseJID(groupJID)
	if err != nil {
		return false, fmt.Sprintf("Invalid group JID: %v", err)
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
	rand.Seed(int64(duration))
	for i := range waveform {
		pos := float64(i) / 64.0
		val := 35.0 * math.Sin(pos*math.Pi*8)
		val += (rand.Float64() - 0.5) * 15
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