package main

import (
	"context"
	"fmt"
	"math"
	"math/rand/v2"
	"os"
	"path/filepath"
	"strings"
	"time"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/types"
	"google.golang.org/protobuf/proto"
)

func (wac *WhatsAppClient) DownloadMedia(messageID, chatIdentifier, downloadPath string) (string, error) {
	if messageID == "" {
		return "", fmt.Errorf("message ID cannot be empty")
	}

	jid, err := wac.ResolveRecipient(chatIdentifier)
	if err != nil {
		return "", fmt.Errorf("failed to resolve chat: %v", err)
	}

	mediaInfo, err := wac.store.GetMessageMediaInfo(messageID, jid.String())
	if err != nil {
		return "", err
	}

	var downloadable whatsmeow.DownloadableMessage
	switch mediaInfo.MediaType {
	case MediaTypeImage:
		downloadable = &waProto.ImageMessage{
			URL: proto.String(mediaInfo.URL), MediaKey: mediaInfo.MediaKey,
			FileSHA256: mediaInfo.FileSHA256, FileEncSHA256: mediaInfo.FileEncSHA256,
			FileLength: proto.Uint64(mediaInfo.FileLength),
		}
	case MediaTypeVideo:
		downloadable = &waProto.VideoMessage{
			URL: proto.String(mediaInfo.URL), MediaKey: mediaInfo.MediaKey,
			FileSHA256: mediaInfo.FileSHA256, FileEncSHA256: mediaInfo.FileEncSHA256,
			FileLength: proto.Uint64(mediaInfo.FileLength),
		}
	case MediaTypeAudio:
		downloadable = &waProto.AudioMessage{
			URL: proto.String(mediaInfo.URL), MediaKey: mediaInfo.MediaKey,
			FileSHA256: mediaInfo.FileSHA256, FileEncSHA256: mediaInfo.FileEncSHA256,
			FileLength: proto.Uint64(mediaInfo.FileLength),
		}
	case MediaTypeDocument:
		downloadable = &waProto.DocumentMessage{
			URL: proto.String(mediaInfo.URL), MediaKey: mediaInfo.MediaKey,
			FileSHA256: mediaInfo.FileSHA256, FileEncSHA256: mediaInfo.FileEncSHA256,
			FileLength: proto.Uint64(mediaInfo.FileLength),
		}
	default:
		return "", fmt.Errorf("unsupported media type: %s", mediaInfo.MediaType)
	}

	data, err := wac.client.Download(context.Background(), downloadable)
	if err != nil {
		return "", fmt.Errorf("failed to download media: %v", err)
	}

	savePath := downloadPath
	if savePath == "" {
		downloadsDir := filepath.Join(wac.dataDir, "downloads")
		if err := os.MkdirAll(downloadsDir, 0755); err != nil {
			return "", fmt.Errorf("failed to create downloads directory: %v", err)
		}
		filename := mediaInfo.Filename
		if filename == "" {
			ext := getExtensionForMediaType(mediaInfo.MediaType)
			filename = fmt.Sprintf("%s_%s%s", messageID, time.Now().Format("20060102_150405"), ext)
		}
		savePath = filepath.Join(downloadsDir, filename)
	} else {
		if err := validateFilePath(downloadPath); err != nil {
			return "", fmt.Errorf("invalid download path: %v", err)
		}
	}

	if err := os.MkdirAll(filepath.Dir(savePath), 0755); err != nil {
		return "", fmt.Errorf("failed to create directory: %v", err)
	}
	if err := os.WriteFile(savePath, data, 0644); err != nil {
		return "", fmt.Errorf("failed to save file: %v", err)
	}

	return savePath, nil
}

func (wac *WhatsAppClient) SendReaction(messageID, emoji, chatIdentifier string) (bool, string) {
	jid, err := wac.ResolveRecipient(chatIdentifier)
	if err != nil {
		return false, fmt.Sprintf("Failed to resolve chat: %v", err)
	}

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

func (wac *WhatsAppClient) RevokeMessage(messageID, chatIdentifier string) (bool, string) {
	jid, err := wac.ResolveRecipient(chatIdentifier)
	if err != nil {
		return false, fmt.Sprintf("Failed to resolve chat: %v", err)
	}
	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}

	resp, err := wac.client.RevokeMessage(context.Background(), jid, types.MessageID(messageID))
	if err != nil {
		return false, fmt.Sprintf("Failed to revoke message: %v", err)
	}
	return true, fmt.Sprintf("Message revoked successfully (revocation ID: %s)", resp.ID)
}

// --- Media type helpers ---

func mediaTypeToString(mt whatsmeow.MediaType) string {
	switch mt {
	case whatsmeow.MediaImage:
		return MediaTypeImage
	case whatsmeow.MediaVideo:
		return MediaTypeVideo
	case whatsmeow.MediaAudio:
		return MediaTypeAudio
	case whatsmeow.MediaDocument:
		return MediaTypeDocument
	default:
		return ""
	}
}

func getExtensionForMediaType(mediaType string) string {
	switch mediaType {
	case MediaTypeImage:
		return ".jpg"
	case MediaTypeVideo:
		return ".mp4"
	case MediaTypeAudio:
		return ".ogg"
	default:
		return ".bin"
	}
}

func detectMediaType(filePath string) (whatsmeow.MediaType, string) {
	ext := strings.ToLower(filepath.Ext(filePath))
	switch ext {
	case ".jpg", ".jpeg":
		return whatsmeow.MediaImage, "image/jpeg"
	case ".png":
		return whatsmeow.MediaImage, "image/png"
	case ".gif":
		return whatsmeow.MediaImage, "image/gif"
	case ".webp":
		return whatsmeow.MediaImage, "image/webp"
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
	case ".mp3":
		return whatsmeow.MediaAudio, "audio/mpeg"
	case ".ogg":
		return whatsmeow.MediaAudio, "audio/ogg"
	case ".m4a":
		return whatsmeow.MediaAudio, "audio/mp4"
	case ".wav":
		return whatsmeow.MediaAudio, "audio/wav"
	default:
		return whatsmeow.MediaDocument, "application/octet-stream"
	}
}

func validateFilePath(path string) error {
	if path == "" {
		return fmt.Errorf("file path cannot be empty")
	}
	cleanPath := filepath.Clean(path)
	absPath, err := filepath.Abs(cleanPath)
	if err != nil {
		return fmt.Errorf("invalid file path: %v", err)
	}
	if strings.Contains(absPath, "..") {
		return fmt.Errorf("path traversal detected in file path")
	}
	return nil
}

// --- Message content extraction ---

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
	if contact := msg.GetContactMessage(); contact != nil {
		return formatContactCard(contact.GetDisplayName(), contact.GetVcard())
	}
	return ""
}

func formatContactCard(displayName, vcard string) string {
	if displayName == "" && vcard == "" {
		return ""
	}
	phone := extractVCardPhone(vcard)
	if phone != "" {
		return fmt.Sprintf("[Contact: %s — %s]", displayName, phone)
	}
	return fmt.Sprintf("[Contact: %s]", displayName)
}

func extractVCardPhone(vcard string) string {
	for _, line := range strings.Split(vcard, "\n") {
		line = strings.TrimSpace(line)
		upper := strings.ToUpper(line)
		if strings.HasPrefix(upper, "TEL") {
			if idx := strings.Index(line, ":"); idx >= 0 {
				phone := strings.TrimSpace(line[idx+1:])
				if phone != "" {
					return phone
				}
			}
		}
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

func extractQuoteContext(msg *waProto.Message) (quotedMessageID, quotedText string) {
	if msg == nil {
		return "", ""
	}

	var ci *waProto.ContextInfo
	switch {
	case msg.GetExtendedTextMessage() != nil:
		ci = msg.GetExtendedTextMessage().GetContextInfo()
	case msg.GetImageMessage() != nil:
		ci = msg.GetImageMessage().GetContextInfo()
	case msg.GetVideoMessage() != nil:
		ci = msg.GetVideoMessage().GetContextInfo()
	case msg.GetDocumentMessage() != nil:
		ci = msg.GetDocumentMessage().GetContextInfo()
	}

	if ci == nil {
		return "", ""
	}

	quotedMessageID = ci.GetStanzaID()
	if qm := ci.GetQuotedMessage(); qm != nil {
		quotedText = extractTextContent(qm)
	}
	return quotedMessageID, quotedText
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
		return MediaTypeImage, "", img.GetURL(),
			img.GetMediaKey(), img.GetFileSHA256(), img.GetFileEncSHA256(), img.GetFileLength()
	}
	if vid := msg.GetVideoMessage(); vid != nil {
		return MediaTypeVideo, "", vid.GetURL(),
			vid.GetMediaKey(), vid.GetFileSHA256(), vid.GetFileEncSHA256(), vid.GetFileLength()
	}
	if aud := msg.GetAudioMessage(); aud != nil {
		return MediaTypeAudio, "", aud.GetURL(),
			aud.GetMediaKey(), aud.GetFileSHA256(), aud.GetFileEncSHA256(), aud.GetFileLength()
	}
	if doc := msg.GetDocumentMessage(); doc != nil {
		return MediaTypeDocument, doc.GetFileName(), doc.GetURL(),
			doc.GetMediaKey(), doc.GetFileSHA256(), doc.GetFileEncSHA256(), doc.GetFileLength()
	}
	return
}

func analyzeOpusOgg(data []byte) (uint32, []byte) {
	duration := uint32(len(data) / 2000)
	if duration < 1 {
		duration = 1
	} else if duration > 300 {
		duration = 300
	}

	waveform := make([]byte, 64)
	rng := rand.New(rand.NewPCG(uint64(duration), uint64(duration)))
	for i := range waveform {
		pos := float64(i) / 64.0
		val := 35.0*math.Sin(pos*math.Pi*8) + (rng.Float64()-0.5)*15 + 50
		waveform[i] = byte(max(0, min(100, int(val))))
	}

	return duration, waveform
}
