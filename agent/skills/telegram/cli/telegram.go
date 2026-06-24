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
	bot               *tgbotapi.BotAPI
	store             *MessageStore
	dataDir           string
	notificationsDir  string
	instance          string
	readOnly          bool
	skipSenders       map[string]bool
	botUserID         int64
	token             string
	mu                sync.RWMutex
	lastMessageSentAt time.Time
}

// Human-pacing constants, mirrored from the whatsapp skill so both channels feel the same.
const (
	tgTypingPerChar = 25 * time.Millisecond
	tgTypingMin     = 1500 * time.Millisecond
	tgTypingMax     = 6 * time.Second
	tgReadingBeat   = 550 * time.Millisecond // beat before typing when not a rapid follow-on
	tgPreSendDelay  = 300 * time.Millisecond
	tgRapidWindow   = 3 * time.Second // within this since last send, skip the reading beat
)

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
	// Explicitly opt into the update kinds we handle. callback_query is what powers the
	// interactive inline-keyboard UI (button taps). Telegram only delivers update types listed
	// here. (message_reaction is omitted: the v5 library has no struct for it, so it can't be
	// decoded from the poller; we can still SEND reactions via the raw setMessageReaction call.)
	updateConfig.AllowedUpdates = []string{"message", "edited_message", "callback_query"}

	updates := tc.bot.GetUpdatesChan(updateConfig)

	log.Printf("Bot @%s started polling for updates", tc.bot.Self.UserName)

	for update := range updates {
		switch {
		case update.Message != nil:
			tc.handleMessage(update.Message)
		case update.EditedMessage != nil:
			tc.handleMessage(update.EditedMessage)
		case update.CallbackQuery != nil:
			tc.handleCallbackQuery(update.CallbackQuery)
		}
	}
}

// handleCallbackQuery fires when the owner taps an inline-keyboard button. We persist nothing
// in the message store (it's a UI event, not a message) but drop a notification so the agent
// can react: answer the callback (stop the button's spinner) and/or edit the message in place.
func (tc *TelegramClient) handleCallbackQuery(cb *tgbotapi.CallbackQuery) {
	if cb == nil {
		return
	}
	var chatID, messageID int64
	if cb.Message != nil {
		chatID = cb.Message.Chat.ID
		messageID = int64(cb.Message.MessageID)
	}
	sender := formatSenderName(cb.From)
	username := ""
	if cb.From != nil {
		username = cb.From.UserName
	}
	contactName, contactSaved := sender, false
	if chatID != 0 {
		if contact, _ := tc.store.GetManualContact(chatID); contact != nil {
			contactName, contactSaved = contact.Name, true
		}
	}
	if tc.notificationsDir != "" {
		WriteCallbackNotification(tc.notificationsDir, cb.ID, cb.Data, chatID, messageID, contactName, sender, username, tc.instance, contactSaved)
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

// humanPause makes the bot feel like a person typing rather than a burst: it shows the typing
// indicator, then waits a beat scaled to message length (capped). Because the daemon blocks here
// before delivering, sequential sends are spaced automatically without the caller managing sleeps,
// and a short reply stays near-instant. action defaults to "typing".
func (tc *TelegramClient) humanPause(chatID int64, action string, textLen int) {
	if action == "" {
		action = tgbotapi.ChatTyping
	}
	// Reading beat before a fresh reply, skipped for a rapid follow-on (you don't re-read the
	// thread before continuing your own thought). Mirrors the whatsapp skill's pacing.
	tc.mu.RLock()
	rapid := time.Since(tc.lastMessageSentAt) < tgRapidWindow
	tc.mu.RUnlock()
	if !rapid {
		time.Sleep(tgReadingBeat)
	}
	tc.bot.Request(tgbotapi.NewChatAction(chatID, action))
	typing := tgTypingMin + time.Duration(textLen)*tgTypingPerChar
	if typing > tgTypingMax {
		typing = tgTypingMax
	}
	time.Sleep(typing + tgPreSendDelay)
	tc.mu.Lock()
	tc.lastMessageSentAt = time.Now()
	tc.mu.Unlock()
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
			tc.humanPause(recipientID, "", len(chunk))
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
	tc.humanPause(recipientID, "", len(text))
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

// parseInlineKeyboard turns a compact spec into an inline keyboard.
// Format: rows separated by ';', buttons within a row by ',', and each button is
// "Label=callback_data" (or just "Label", in which case data == label).
// A button whose data starts with "url:" becomes a URL button instead of a callback.
// Returns (markup, true) when at least one button parsed, else (zero, false).
func parseInlineKeyboard(spec string) (tgbotapi.InlineKeyboardMarkup, bool) {
	spec = strings.TrimSpace(spec)
	if spec == "" {
		return tgbotapi.InlineKeyboardMarkup{}, false
	}
	var rows [][]tgbotapi.InlineKeyboardButton
	for _, rowSpec := range strings.Split(spec, ";") {
		rowSpec = strings.TrimSpace(rowSpec)
		if rowSpec == "" {
			continue
		}
		var row []tgbotapi.InlineKeyboardButton
		for _, btnSpec := range strings.Split(rowSpec, ",") {
			btnSpec = strings.TrimSpace(btnSpec)
			if btnSpec == "" {
				continue
			}
			label, data := btnSpec, btnSpec
			if i := strings.Index(btnSpec, "="); i >= 0 {
				label = strings.TrimSpace(btnSpec[:i])
				data = strings.TrimSpace(btnSpec[i+1:])
			}
			if strings.HasPrefix(data, "url:") {
				row = append(row, tgbotapi.NewInlineKeyboardButtonURL(label, strings.TrimPrefix(data, "url:")))
			} else {
				row = append(row, tgbotapi.NewInlineKeyboardButtonData(label, data))
			}
		}
		if len(row) > 0 {
			rows = append(rows, row)
		}
	}
	if len(rows) == 0 {
		return tgbotapi.InlineKeyboardMarkup{}, false
	}
	return tgbotapi.NewInlineKeyboardMarkup(rows...), true
}

// SendMessageWithOptions sends a single message with optional inline-keyboard buttons and/or a
// reply-to. Used when buttons/reply are present (no chunking: a button message is a single unit).
// Plain sends with neither option still go through SendMessage so long-text chunking is preserved.
func (tc *TelegramClient) SendMessageWithOptions(recipientID int64, text, buttons string, replyTo int64) (int64, error) {
	if buttons == "" && replyTo == 0 {
		return tc.SendMessage(recipientID, text)
	}
	if len(text) > MaxMessageLength {
		return 0, fmt.Errorf("message too long: %d chars (max %d for a message with buttons/reply)", len(text), MaxMessageLength)
	}
	msg := tgbotapi.NewMessage(recipientID, text)
	msg.ParseMode = "Markdown"
	if replyTo != 0 {
		msg.ReplyToMessageID = int(replyTo)
	}
	if kb, ok := parseInlineKeyboard(buttons); ok {
		msg.ReplyMarkup = kb
	}
	tc.humanPause(recipientID, "", len(text))
	sent, err := tc.bot.Send(msg)
	if err != nil {
		msg.ParseMode = ""
		sent, err = tc.bot.Send(msg)
		if err != nil {
			return 0, fmt.Errorf("failed to send message: %v", err)
		}
	}
	msgID := int64(sent.MessageID)
	chatName, _ := tc.store.GetChatName(recipientID)
	tc.store.StoreChat(recipientID, chatName, "private", time.Now())
	tc.store.StoreMessage(msgID, recipientID, tc.bot.Self.UserName, text, time.Now(), true, "", "", "", replyTo)
	return msgID, nil
}

// EditMessage edits an existing message's text (and optionally its inline keyboard) in place.
// This is the core of the "dynamic UI": update a status line, swap a menu, mark a choice taken.
func (tc *TelegramClient) EditMessage(chatID, messageID int64, text, buttons string) error {
	if kb, ok := parseInlineKeyboard(buttons); ok {
		edit := tgbotapi.NewEditMessageTextAndMarkup(chatID, int(messageID), text, kb)
		edit.ParseMode = "Markdown"
		if _, err := tc.bot.Send(edit); err != nil {
			edit.ParseMode = ""
			if _, err = tc.bot.Send(edit); err != nil {
				return fmt.Errorf("failed to edit message: %v", err)
			}
		}
	} else {
		edit := tgbotapi.NewEditMessageText(chatID, int(messageID), text)
		edit.ParseMode = "Markdown"
		if _, err := tc.bot.Send(edit); err != nil {
			edit.ParseMode = ""
			if _, err = tc.bot.Send(edit); err != nil {
				return fmt.Errorf("failed to edit message: %v", err)
			}
		}
	}
	return nil
}

// DeleteMessage deletes a message (the bot's own, or any in a chat where it can). Telegram only
// lets a bot delete its own messages in a private chat, and recent ones (<48h for others' msgs).
func (tc *TelegramClient) DeleteMessage(chatID, messageID int64) error {
	if _, err := tc.bot.Request(tgbotapi.NewDeleteMessage(chatID, int(messageID))); err != nil {
		return fmt.Errorf("failed to delete message: %v", err)
	}
	return nil
}

// AnswerCallback acknowledges a button tap (callback_query). Always call it after handling a tap:
// it stops the button's loading spinner. With text it shows a toast; with alert it's a modal popup.
func (tc *TelegramClient) AnswerCallback(callbackID, text string, alert bool) error {
	cb := tgbotapi.NewCallback(callbackID, text)
	cb.ShowAlert = alert
	if _, err := tc.bot.Request(cb); err != nil {
		return fmt.Errorf("failed to answer callback: %v", err)
	}
	return nil
}

// SendVoice sends a voice note (best with .ogg/opus; other audio is sent as-is).
func (tc *TelegramClient) SendVoice(recipientID int64, filePath, caption string) (int64, error) {
	if _, err := os.Stat(filePath); err != nil {
		return 0, fmt.Errorf("file not found: %s", filePath)
	}
	voice := tgbotapi.NewVoice(recipientID, tgbotapi.FilePath(filePath))
	if caption != "" {
		voice.Caption = caption
	}
	sent, err := tc.bot.Send(voice)
	if err != nil {
		return 0, fmt.Errorf("failed to send voice: %v", err)
	}
	msgID := int64(sent.MessageID)
	chatName, _ := tc.store.GetChatName(recipientID)
	tc.store.StoreChat(recipientID, chatName, "private", time.Now())
	tc.store.StoreMessage(msgID, recipientID, tc.bot.Self.UserName, caption, time.Now(), true, "voice", filepath.Base(filePath), "", 0)
	return msgID, nil
}

// SendChatAction shows a transient status in the chat ("typing…", "uploading…"). Telegram clears
// it after ~5s or when the next message arrives, so call it right before a slow operation.
func (tc *TelegramClient) SendChatAction(chatID int64, action string) error {
	if action == "" {
		action = tgbotapi.ChatTyping
	}
	if _, err := tc.bot.Request(tgbotapi.NewChatAction(chatID, action)); err != nil {
		return fmt.Errorf("failed to send chat action: %v", err)
	}
	return nil
}

// PinMessage pins a message in the chat. silent=true suppresses the pin notification.
func (tc *TelegramClient) PinMessage(chatID, messageID int64, silent bool) error {
	cfg := tgbotapi.PinChatMessageConfig{ChatID: chatID, MessageID: int(messageID), DisableNotification: silent}
	if _, err := tc.bot.Request(cfg); err != nil {
		return fmt.Errorf("failed to pin message: %v", err)
	}
	return nil
}

// UnpinMessage unpins a specific message (messageID 0 unpins the most recent pinned message).
func (tc *TelegramClient) UnpinMessage(chatID, messageID int64) error {
	cfg := tgbotapi.UnpinChatMessageConfig{ChatID: chatID, MessageID: int(messageID)}
	if _, err := tc.bot.Request(cfg); err != nil {
		return fmt.Errorf("failed to unpin message: %v", err)
	}
	return nil
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
