package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

const (
	MaxFileSizeBytes = 50 * 1024 * 1024 // 50 MB (Telegram bot limit)
	MaxMessageLength = 4096
)

type TelegramClient struct {
	bot              *tgbotapi.BotAPI
	store            *MessageStore
	dataDir          string
	notificationsDir string
	instance         string
	readOnly         bool
	skipSenders      map[string]bool
	botUserID        int64
	token            string
	mu               sync.RWMutex
}

func NewTelegramClient(dataDir, notificationsDir, instance string, readOnly bool, skipSenders map[string]bool) (*TelegramClient, error) {
	store, err := NewMessageStore(dataDir)
	if err != nil {
		return nil, fmt.Errorf("failed to initialize message store: %v", err)
	}

	tokenPath := filepath.Join(dataDir, "bot-token")
	tokenBytes, err := os.ReadFile(tokenPath)
	if err != nil {
		store.Close()
		return nil, fmt.Errorf("bot token not found at %s — run 'telegram authenticate' first", tokenPath)
	}
	token := strings.TrimSpace(string(tokenBytes))
	if token == "" {
		store.Close()
		return nil, fmt.Errorf("bot token is empty — run 'telegram authenticate' to set it")
	}

	bot, err := tgbotapi.NewBotAPI(token)
	if err != nil {
		store.Close()
		return nil, fmt.Errorf("failed to authenticate with Telegram: %v", err)
	}

	tc := &TelegramClient{
		bot:              bot,
		store:            store,
		dataDir:          dataDir,
		notificationsDir: notificationsDir,
		instance:         instance,
		readOnly:         readOnly,
		skipSenders:      skipSenders,
		botUserID:        int64(bot.Self.ID),
		token:            token,
	}

	return tc, nil
}

func (tc *TelegramClient) StartPolling() {
	updateConfig := tgbotapi.NewUpdate(0)
	updateConfig.Timeout = 30
	// Note: message_reaction requires Bot API 7.0+; the library will pass it through
	// even if it doesn't have native struct support
	updateConfig.AllowedUpdates = []string{"message"}

	updates := tc.bot.GetUpdatesChan(updateConfig)

	log.Printf("Bot @%s started polling for updates", tc.bot.Self.UserName)

	for update := range updates {
		if update.Message != nil {
			tc.handleMessage(update.Message)
		}
	}
}

func (tc *TelegramClient) Stop() {
	tc.bot.StopReceivingUpdates()
	tc.store.Close()
}

func (tc *TelegramClient) handleMessage(msg *tgbotapi.Message) {
	content := msg.Text
	if content == "" {
		content = msg.Caption
	}

	mediaType := ""
	filename := ""
	fileID := ""

	if msg.Photo != nil && len(msg.Photo) > 0 {
		mediaType = "photo"
		fileID = msg.Photo[len(msg.Photo)-1].FileID
	} else if msg.Document != nil {
		mediaType = "document"
		filename = msg.Document.FileName
		fileID = msg.Document.FileID
	} else if msg.Audio != nil {
		mediaType = "audio"
		filename = msg.Audio.FileName
		fileID = msg.Audio.FileID
	} else if msg.Voice != nil {
		mediaType = "voice"
		fileID = msg.Voice.FileID
	} else if msg.Video != nil {
		mediaType = "video"
		filename = msg.Video.FileName
		fileID = msg.Video.FileID
	} else if msg.VideoNote != nil {
		mediaType = "video_note"
		fileID = msg.VideoNote.FileID
	} else if msg.Sticker != nil {
		mediaType = "sticker"
		fileID = msg.Sticker.FileID
		if content == "" {
			content = msg.Sticker.Emoji
		}
	} else if msg.Location != nil {
		mediaType = "location"
		content = fmt.Sprintf("Location: %.6f, %.6f", msg.Location.Latitude, msg.Location.Longitude)
	} else if msg.Contact != nil {
		mediaType = "contact"
		content = fmt.Sprintf("Contact: %s %s (%s)", msg.Contact.FirstName, msg.Contact.LastName, msg.Contact.PhoneNumber)
	}

	// Store file ID for later download
	_ = fileID

	if content == "" && mediaType == "" {
		return
	}

	senderName := formatSenderName(msg.From)
	username := ""
	if msg.From != nil {
		username = msg.From.UserName
	}

	chatName := msg.Chat.Title
	if chatName == "" && msg.Chat.FirstName != "" {
		chatName = strings.TrimSpace(msg.Chat.FirstName + " " + msg.Chat.LastName)
	}

	chatType := string(msg.Chat.Type)
	isFromMe := msg.From != nil && int64(msg.From.ID) == tc.botUserID
	isDirectChat := msg.Chat.Type == "private"
	timestamp := msg.Time()

	var replyToID int64
	if msg.ReplyToMessage != nil {
		replyToID = int64(msg.ReplyToMessage.MessageID)
	}

	// Store chat
	if err := tc.store.StoreChat(msg.Chat.ID, chatName, chatType, timestamp); err != nil {
		log.Printf("Failed to store chat: %v", err)
	}

	// Store message
	if err := tc.store.StoreMessage(
		int64(msg.MessageID), msg.Chat.ID, senderName, content,
		timestamp, isFromMe, mediaType, filename, fileID, replyToID,
	); err != nil {
		log.Printf("Failed to store message: %v", err)
	}

	// Write notification for incoming messages
	if tc.notificationsDir != "" && !isFromMe {
		contactName := ""
		contactSaved := false
		if contact, _ := tc.store.GetManualContact(msg.Chat.ID); contact != nil {
			contactName = contact.Name
			contactSaved = true
		}
		if contactName == "" {
			contactName = senderName
		}

		senderPhone := ""
		if msg.From != nil {
			senderPhone = strconv.FormatInt(int64(msg.From.ID), 10)
		}

		if !tc.skipSenders[senderPhone] && !tc.skipSenders[username] {
			WriteNotification(
				tc.notificationsDir,
				int64(msg.MessageID),
				chatName,
				contactName,
				username,
				tc.instance,
				contactSaved,
				isDirectChat,
				senderName,
				content,
				mediaType,
				replyToID,
			)
		}
	}
}

func (tc *TelegramClient) SendMessage(recipientID int64, text string) (int64, error) {
	// Split long messages
	if len(text) > MaxMessageLength {
		chunks := splitMessage(text, MaxMessageLength)
		var lastID int64
		for i, chunk := range chunks {
			prefix := ""
			if len(chunks) > 1 {
				prefix = fmt.Sprintf("(%d/%d) ", i+1, len(chunks))
			}
			msg := tgbotapi.NewMessage(recipientID, prefix+chunk)
			msg.ParseMode = "Markdown"
			sent, err := tc.bot.Send(msg)
			if err != nil {
				// Retry without parse mode
				msg.ParseMode = ""
				sent, err = tc.bot.Send(msg)
				if err != nil {
					return 0, fmt.Errorf("failed to send message: %v", err)
				}
			}
			lastID = int64(sent.MessageID)

			// Record outgoing
			chatName, _ := tc.store.GetChatName(recipientID)
			tc.store.StoreChat(recipientID, chatName, "private", time.Now())
			tc.store.StoreMessage(lastID, recipientID, tc.bot.Self.UserName, prefix+chunk, time.Now(), true, "", "", "", 0)
		}
		return lastID, nil
	}

	msg := tgbotapi.NewMessage(recipientID, text)
	msg.ParseMode = "Markdown"
	sent, err := tc.bot.Send(msg)
	if err != nil {
		// Retry without parse mode
		msg.ParseMode = ""
		sent, err = tc.bot.Send(msg)
		if err != nil {
			return 0, fmt.Errorf("failed to send message: %v", err)
		}
	}

	msgID := int64(sent.MessageID)
	chatName, _ := tc.store.GetChatName(recipientID)
	tc.store.StoreChat(recipientID, chatName, "private", time.Now())
	tc.store.StoreMessage(msgID, recipientID, tc.bot.Self.UserName, text, time.Now(), true, "", "", "", 0)

	return msgID, nil
}

func (tc *TelegramClient) SendFile(recipientID int64, filePath, caption string) (int64, error) {
	fileInfo, err := os.Stat(filePath)
	if err != nil {
		return 0, fmt.Errorf("file not found: %s", filePath)
	}
	if fileInfo.Size() > MaxFileSizeBytes {
		return 0, fmt.Errorf("file too large: %d MB (max %d MB)",
			fileInfo.Size()/(1024*1024), MaxFileSizeBytes/(1024*1024))
	}

	file := tgbotapi.FilePath(filePath)
	doc := tgbotapi.NewDocument(recipientID, file)
	if caption != "" {
		doc.Caption = caption
	}

	sent, err := tc.bot.Send(doc)
	if err != nil {
		return 0, fmt.Errorf("failed to send file: %v", err)
	}

	msgID := int64(sent.MessageID)
	chatName, _ := tc.store.GetChatName(recipientID)
	tc.store.StoreChat(recipientID, chatName, "private", time.Now())
	tc.store.StoreMessage(msgID, recipientID, tc.bot.Self.UserName, caption, time.Now(), true, "document", filepath.Base(filePath), "", 0)

	return msgID, nil
}

// SendReaction sends an emoji reaction to a message via raw Bot API call.
func (tc *TelegramClient) SendReaction(chatID int64, messageID int, emoji string) error {
	payload := map[string]interface{}{
		"chat_id":    chatID,
		"message_id": messageID,
		"reaction": []map[string]string{
			{"type": "emoji", "emoji": emoji},
		},
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal reaction: %v", err)
	}

	url := fmt.Sprintf("https://api.telegram.org/bot%s/setMessageReaction", tc.token)
	resp, err := http.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("failed to send reaction: %v", err)
	}
	defer resp.Body.Close()

	var result struct {
		OK          bool   `json:"ok"`
		Description string `json:"description"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return fmt.Errorf("failed to decode response: %v", err)
	}
	if !result.OK {
		return fmt.Errorf("telegram API error: %s", result.Description)
	}
	return nil
}

// DownloadFile downloads a file from Telegram by its file_id.
func (tc *TelegramClient) DownloadFile(fileID, downloadPath string) (string, error) {
	file, err := tc.bot.GetFile(tgbotapi.FileConfig{FileID: fileID})
	if err != nil {
		return "", fmt.Errorf("failed to get file info: %v", err)
	}

	link := file.Link(tc.token)

	if downloadPath == "" {
		downloadPath = filepath.Join(os.TempDir(), filepath.Base(file.FilePath))
	}

	resp, err := http.Get(link)
	if err != nil {
		return "", fmt.Errorf("failed to download file: %v", err)
	}
	defer resp.Body.Close()

	outFile, err := os.Create(downloadPath)
	if err != nil {
		return "", fmt.Errorf("failed to create output file: %v", err)
	}
	defer outFile.Close()

	if _, err := io.Copy(outFile, resp.Body); err != nil {
		return "", fmt.Errorf("failed to write file: %v", err)
	}

	return downloadPath, nil
}

func (tc *TelegramClient) writeAuthStatusFile(data map[string]string) {
	b, err := json.Marshal(data)
	if err != nil {
		log.Printf("Failed to marshal auth status: %v", err)
		return
	}
	if err := os.WriteFile(filepath.Join(tc.dataDir, "auth-status.json"), b, 0644); err != nil {
		log.Printf("Failed to write auth status file: %v", err)
	}
}

func formatSenderName(user *tgbotapi.User) string {
	if user == nil {
		return "Unknown"
	}
	name := strings.TrimSpace(user.FirstName + " " + user.LastName)
	if name == "" {
		if user.UserName != "" {
			return "@" + user.UserName
		}
		return "Unknown"
	}
	return name
}

func splitMessage(text string, maxLen int) []string {
	if len(text) <= maxLen {
		return []string{text}
	}

	var chunks []string
	for len(text) > 0 {
		if len(text) <= maxLen {
			chunks = append(chunks, text)
			break
		}
		// Try to split at newline
		splitAt := strings.LastIndex(text[:maxLen], "\n")
		if splitAt < maxLen/2 {
			// Try space
			splitAt = strings.LastIndex(text[:maxLen], " ")
		}
		if splitAt < maxLen/4 {
			splitAt = maxLen
		}
		chunks = append(chunks, text[:splitAt])
		text = text[splitAt:]
	}
	return chunks
}
