package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/types"
	"google.golang.org/protobuf/proto"
)

// mentionPattern matches @word patterns in message text.
var mentionPattern = regexp.MustCompile(`@(\+?\w+)`)

// WhatsApp spam filters silently drop messages containing user@IP patterns.
var userAtIPPattern = regexp.MustCompile(`\w+@\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}`)

func (wac *WhatsAppClient) SendMessageWithPresence(recipient, message string, quotedMessageID string) (bool, string) {
	if recipient == "" || message == "" {
		return false, "Recipient and message are required. Provide a contact name, phone number, or group name plus the message text"
	}

	message = shellEscapeReplacer.Replace(message)

	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}

	jid, err := wac.ResolveRecipient(recipient)
	if err != nil {
		return false, err.Error()
	}

	if err := wac.requireManualContact(jid); err != nil {
		return false, err.Error()
	}

	if err := wac.EnsureOnline(); err != nil {
		wac.logger.Warnf("Failed to set online status: %v", err)
	}

	// Skip presence simulation for rapid successive messages
	wac.presenceMutex.RLock()
	timeSinceLastMessage := time.Since(wac.lastMessageSentAt)
	wac.presenceMutex.RUnlock()

	if timeSinceLastMessage >= RapidMessageThreshold {
		time.Sleep(randomDelay(ReactionDelayMin, ReactionDelayMax))

		err = wac.client.SendChatPresence(context.Background(), jid, types.ChatPresenceComposing, types.ChatPresenceMediaText)
		if err != nil {
			wac.logger.Warnf("Failed to send typing indicator: %v", err)
		}

		time.Sleep(humanDelay(TypingDelayMin, TypingDelayPerChar, len(message), TypingDelayMax))

		err = wac.client.SendChatPresence(context.Background(), jid, types.ChatPresencePaused, types.ChatPresenceMediaText)
		if err != nil {
			wac.logger.Debugf("Failed to stop typing indicator: %v", err)
		}

		time.Sleep(randomDelay(PreSendDelayMin, PreSendDelayMax))
	}

	resolvedText, mentionedJIDs := wac.parseMentions(message)

	// Look up the sender of the quoted message if reply-to is set.
	var quotedParticipant, quotedContent string
	if quotedMessageID != "" && wac.store != nil {
		if sender, err := wac.store.GetMessageSender(quotedMessageID); err == nil && sender != "" {
			quotedParticipant = sender
		}
		if content, err := wac.store.GetMessageContent(quotedMessageID); err == nil && content != "" {
			quotedContent = content
		}
	}

	msg := buildMessage(resolvedText, mentionedJIDs, quotedMessageID, quotedParticipant, quotedContent)

	resp, err := wac.client.SendMessage(context.Background(), jid, msg)
	if err != nil {
		return false, fmt.Sprintf("Failed to send message: %v", err)
	}

	wac.recordOutgoingMessage(jid, StoreMessageParams{ID: resp.ID, Content: message})

	wac.presenceMutex.Lock()
	wac.lastMessageSentAt = time.Now()
	wac.presenceMutex.Unlock()

	return true, fmt.Sprintf("Message sent successfully (ID: %s)", resp.ID)
}

func (wac *WhatsAppClient) SendFile(recipient, filePath, caption, displayName string) (bool, string) {
	if recipient == "" || filePath == "" {
		return false, "Recipient and file path are required. Provide a contact name, phone number, or group name and the file path"
	}

	if err := validateFilePath(filePath); err != nil {
		return false, fmt.Sprintf("Invalid file path: %v", err)
	}

	fileInfo, err := os.Stat(filePath)
	if err != nil {
		return false, fmt.Sprintf("File not found: %s", filePath)
	}
	if fileInfo.Size() > MaxFileSizeBytes {
		return false, fmt.Sprintf("File too large: %d MB (max %d MB)",
			fileInfo.Size()/(1024*1024), MaxFileSizeBytes/(1024*1024))
	}

	jid, err := wac.ResolveRecipient(recipient)
	if err != nil {
		return false, err.Error()
	}
	if err := wac.requireManualContact(jid); err != nil {
		return false, err.Error()
	}
	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}

	data, err := os.ReadFile(filePath)
	if err != nil {
		return false, fmt.Sprintf("Failed to read file: %v", err)
	}

	mediaType, mimeType := detectMediaType(filePath)

	uploaded, err := wac.client.Upload(context.Background(), data, mediaType)
	if err != nil {
		return false, fmt.Sprintf("Failed to upload file: %v", err)
	}

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
	default:
		docName := filepath.Base(filePath)
		if displayName != "" {
			docName = displayName
		}
		msg.DocumentMessage = &waProto.DocumentMessage{
			URL:           proto.String(uploaded.URL),
			DirectPath:    proto.String(uploaded.DirectPath),
			MediaKey:      uploaded.MediaKey,
			FileEncSHA256: uploaded.FileEncSHA256,
			FileSHA256:    uploaded.FileSHA256,
			FileLength:    proto.Uint64(uploaded.FileLength),
			FileName:      proto.String(docName),
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

	var filename string
	if msg.DocumentMessage != nil && msg.DocumentMessage.FileName != nil {
		filename = msg.DocumentMessage.GetFileName()
	}

	wac.recordOutgoingMessage(jid, StoreMessageParams{
		ID: resp.ID, Content: caption, MediaType: mediaTypeToString(mediaType), Filename: filename,
		URL: uploaded.URL, MediaKey: uploaded.MediaKey, FileSHA256: uploaded.FileSHA256,
		FileEncSHA256: uploaded.FileEncSHA256, FileLength: uploaded.FileLength,
	})

	return true, fmt.Sprintf("File sent successfully (ID: %s)", resp.ID)
}

func (wac *WhatsAppClient) SendAudioMessage(recipient, filePath string) (bool, string) {
	if recipient == "" || filePath == "" {
		return false, "Recipient and file path are required. Provide a contact name, phone number, or group name and the audio file path"
	}

	if err := validateFilePath(filePath); err != nil {
		return false, fmt.Sprintf("Invalid file path: %v", err)
	}

	jid, err := wac.ResolveRecipient(recipient)
	if err != nil {
		return false, err.Error()
	}
	if err := wac.requireManualContact(jid); err != nil {
		return false, err.Error()
	}
	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}

	if !strings.HasSuffix(filePath, ".ogg") {
		converted, err := ConvertToOpusOggTemp(filePath, "32k", 24000)
		if err != nil {
			return false, fmt.Sprintf("Failed to convert audio: %v", err)
		}
		filePath = converted
		defer os.Remove(converted)
	}

	fileInfo, err := os.Stat(filePath)
	if err != nil {
		return false, fmt.Sprintf("Audio file not found: %v", err)
	}
	if fileInfo.Size() > MaxAudioSizeBytes {
		return false, fmt.Sprintf("Audio file too large: %d MB (max %d MB)",
			fileInfo.Size()/(1024*1024), MaxAudioSizeBytes/(1024*1024))
	}

	data, err := os.ReadFile(filePath)
	if err != nil {
		return false, fmt.Sprintf("Failed to read audio file: %v", err)
	}

	duration, waveform := analyzeOpusOgg(data)

	uploaded, err := wac.client.Upload(context.Background(), data, whatsmeow.MediaAudio)
	if err != nil {
		return false, fmt.Sprintf("Failed to upload audio: %v", err)
	}

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

	wac.recordOutgoingMessage(jid, StoreMessageParams{
		ID: resp.ID, MediaType: MediaTypeAudio,
		URL: uploaded.URL, MediaKey: uploaded.MediaKey, FileSHA256: uploaded.FileSHA256,
		FileEncSHA256: uploaded.FileEncSHA256, FileLength: uploaded.FileLength,
	})

	return true, fmt.Sprintf("Audio message sent successfully (ID: %s)", resp.ID)
}

// parseMentions finds @mention patterns in text, resolves them to JIDs,
// and returns the modified text (with @phone format) and list of mentioned JIDs.
func (wac *WhatsAppClient) parseMentions(text string) (string, []string) {
	matches := mentionPattern.FindAllStringSubmatchIndex(text, -1)
	if len(matches) == 0 {
		return text, nil
	}

	var mentionedJIDs []string
	seen := map[string]bool{}
	for i := len(matches) - 1; i >= 0; i-- {
		fullStart, fullEnd := matches[i][0], matches[i][1]
		captureStart, captureEnd := matches[i][2], matches[i][3]
		identifier := text[captureStart:captureEnd]

		jid, err := wac.ResolveRecipient(identifier)
		if err != nil {
			continue
		}
		if jid.Server != types.DefaultUserServer {
			continue
		}

		jidStr := jid.String()
		if !seen[jidStr] {
			mentionedJIDs = append(mentionedJIDs, jidStr)
			seen[jidStr] = true
		}
		text = text[:fullStart] + "@" + jid.User + text[fullEnd:]
	}

	return text, mentionedJIDs
}

// buildMessage creates a waProto.Message, using ExtendedTextMessage with
// ContextInfo if mentions are present or a quoted message ID is set,
// or simple Conversation otherwise.
func buildMessage(text string, mentionedJIDs []string, quotedMessageID, quotedParticipant, quotedContent string) *waProto.Message {
	if len(mentionedJIDs) > 0 || quotedMessageID != "" {
		ctx := &waProto.ContextInfo{
			MentionedJID: mentionedJIDs,
		}
		if quotedMessageID != "" {
			ctx.StanzaID = proto.String(quotedMessageID)
			if quotedParticipant != "" {
				ctx.Participant = proto.String(quotedParticipant)
			}
			if quotedContent != "" {
				ctx.QuotedMessage = &waProto.Message{
					Conversation: proto.String(quotedContent),
				}
			}
		}
		return &waProto.Message{
			ExtendedTextMessage: &waProto.ExtendedTextMessage{
				Text:        proto.String(text),
				ContextInfo: ctx,
			},
		}
	}
	return &waProto.Message{
		Conversation: proto.String(text),
	}
}

func (wac *WhatsAppClient) recordOutgoingMessage(jid types.JID, p StoreMessageParams) {
	if wac.store == nil || (jid.User == "" && jid.Server == "") {
		return
	}

	if p.ID == "" {
		p.ID = fmt.Sprintf("local-%d", time.Now().UnixNano())
	}

	p.ChatJID = jid.String()
	p.Timestamp = time.Now()
	p.IsFromMe = true

	if err := wac.store.StoreChat(jid.String(), wac.getChatName(jid), p.Timestamp); err != nil {
		wac.logger.Warnf("Failed to store outgoing chat metadata: %v", err)
	}

	if wac.client != nil && wac.client.Store != nil && wac.client.Store.ID != nil {
		p.Sender = wac.client.Store.ID.String()
	}

	if err := wac.store.StoreMessage(p); err != nil {
		wac.logger.Warnf("Failed to record outgoing message: %v", err)
	}
}
