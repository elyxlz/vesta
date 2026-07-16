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
	"regexp"
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
			tc.handleEditedMessage(update.EditedMessage)
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

// notifContext is who an inbound message is from, resolved identically for a new message and
// for an edit of one.
type notifContext struct {
	chatName     string
	contactName  string
	username     string
	sender       string
	contactSaved bool
	isDirectChat bool
}

func chatNameOf(msg *tgbotapi.Message) string {
	if msg.Chat.Title != "" {
		return msg.Chat.Title
	}
	if msg.Chat.FirstName != "" {
		return strings.TrimSpace(msg.Chat.FirstName + " " + msg.Chat.LastName)
	}
	return ""
}

// notifContextFor resolves who to name in a notification about msg, and reports false when
// nothing should be written for it at all: our own message, notifications off, or a skipped
// sender. Shared so an edit stays exactly as quiet as the message it refers to.
func (tc *TelegramClient) notifContextFor(msg *tgbotapi.Message) (notifContext, bool) {
	isFromMe := msg.From != nil && int64(msg.From.ID) == tc.botUserID
	if tc.notificationsDir == "" || isFromMe {
		return notifContext{}, false
	}

	username := ""
	senderID := ""
	if msg.From != nil {
		username = msg.From.UserName
		senderID = strconv.FormatInt(int64(msg.From.ID), 10)
	}
	if tc.skipSenders[senderID] || tc.skipSenders[username] {
		return notifContext{}, false
	}

	senderName := formatSenderName(msg.From)
	contactName := ""
	contactSaved := false
	if contact, _ := tc.store.GetManualContact(msg.Chat.ID); contact != nil {
		contactName = contact.Name
		contactSaved = true
	}
	if contactName == "" {
		contactName = senderName
	}

	return notifContext{
		chatName:     chatNameOf(msg),
		contactName:  contactName,
		username:     username,
		sender:       senderName,
		contactSaved: contactSaved,
		isDirectChat: msg.Chat.Type == "private",
	}, true
}

// handleEditedMessage reports that a message the agent already read now says something else.
// Telegram delivers the edit as a whole message carrying the new text under the original's ID,
// so routing it through handleMessage would store it correctly but announce it as a brand new
// message, and the agent would answer the same question twice.
func (tc *TelegramClient) handleEditedMessage(msg *tgbotapi.Message) {
	newText := msg.Text
	if newText == "" {
		newText = msg.Caption
	}
	if newText == "" {
		return
	}

	// Read the old text before the update overwrites it: it is the whole point of the
	// notification, and an edit to a message we never stored just reads as empty.
	oldText, err := tc.store.GetMessageContent(int64(msg.MessageID))
	if err != nil {
		log.Printf("Failed to look up edited message %d: %v", msg.MessageID, err)
	}
	if err := tc.store.UpdateMessageContent(int64(msg.MessageID), msg.Chat.ID, newText); err != nil {
		log.Printf("Failed to apply edit to message %d: %v", msg.MessageID, err)
	}
	if oldText == newText {
		return
	}

	if ctx, ok := tc.notifContextFor(msg); ok {
		if err := WriteEditNotification(
			tc.notificationsDir, int64(msg.MessageID), ctx.chatName, ctx.contactName,
			ctx.username, tc.instance, ctx.contactSaved, ctx.isDirectChat,
			ctx.sender, oldText, newText,
		); err != nil {
			log.Printf("Failed to write edit notification for %d: %v", msg.MessageID, err)
		}
	}
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
	chatName := chatNameOf(msg)
	chatType := string(msg.Chat.Type)
	isFromMe := msg.From != nil && int64(msg.From.ID) == tc.botUserID
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
	if ctx, ok := tc.notifContextFor(msg); ok {
		WriteNotification(
			tc.notificationsDir,
			int64(msg.MessageID),
			ctx.chatName,
			ctx.contactName,
			ctx.username,
			tc.instance,
			ctx.contactSaved,
			ctx.isDirectChat,
			ctx.sender,
			content,
			mediaType,
			replyToID,
		)
	}
}

// --- Telegram MarkdownV2 rendering -----------------------------------------
//
// Outbound messages are sent as MarkdownV2. Telegram's legacy "Markdown" mode
// silently drops the underscores in a matched pair like `cs_live_...` (it reads
// them as italics), which corrupted the Stripe Checkout links handed to users
// -> a dead pay page. MarkdownV2 has the same hazard, so we ESCAPE every
// reserved character in literal text. Explicit `[label](url)` links are kept
// intact (label escaped; url only needs `)`/`\` escaped) so the onboard skill
// can hand out a real, clickable pay link whose Stripe session id survives
// byte-for-byte. Text that isn't a recognised link is still escaped, so a bare
// URL survives verbatim (Telegram auto-links it) -- worst case a link renders
// unlabelled, never corrupted.

// mdV2Escaper backslash-escapes every MarkdownV2 reserved character in a run of
// literal text. Backslash is listed first so we never double-escape our own
// escapes.
var mdV2Escaper = strings.NewReplacer(
	"\\", "\\\\",
	"_", "\\_", "*", "\\*", "[", "\\[", "]", "\\]",
	"(", "\\(", ")", "\\)", "~", "\\~", "`", "\\`",
	">", "\\>", "#", "\\#", "+", "\\+", "-", "\\-",
	"=", "\\=", "|", "\\|", "{", "\\{", "}", "\\}",
	".", "\\.", "!", "\\!",
)

// mdV2LinkURLEscaper escapes the only two characters reserved inside a
// MarkdownV2 `(...)` link destination.
var mdV2LinkURLEscaper = strings.NewReplacer("\\", "\\\\", ")", "\\)")

// mdLinkRe matches a Markdown inline link `[label](http(s)://url)` with a plain
// label and a whitespace/paren-free URL -- the shape the skills emit.
var mdLinkRe = regexp.MustCompile(`\[([^\[\]]*)\]\((https?://[^\s)]+)\)`)

// toMarkdownV2 renders an agent message as safe Telegram MarkdownV2: literal
// text is fully escaped (so a URL's underscores can never parse as italics)
// while explicit [label](url) links are preserved with their URL byte-for-byte.
func toMarkdownV2(text string) string {
	var b strings.Builder
	last := 0
	for _, m := range mdLinkRe.FindAllStringSubmatchIndex(text, -1) {
		b.WriteString(mdV2Escaper.Replace(text[last:m[0]]))
		b.WriteString("[")
		b.WriteString(mdV2Escaper.Replace(text[m[2]:m[3]]))
		b.WriteString("](")
		b.WriteString(mdV2LinkURLEscaper.Replace(text[m[4]:m[5]]))
		b.WriteString(")")
		last = m[1]
	}
	b.WriteString(mdV2Escaper.Replace(text[last:]))
	return b.String()
}

// requireManualContact blocks sending to an individual user unless they are a
// saved contact, mirroring the WhatsApp guard. Individual users have positive
// chat IDs; groups and channels have non-positive IDs and are exempt. Stops the
// agent from messaging strangers it was never told to contact.
func (tc *TelegramClient) requireManualContact(chatID int64) error {
	if chatID <= 0 {
		return nil
	}
	contact, err := tc.store.GetManualContact(chatID)
	if err != nil {
		return fmt.Errorf("failed to verify saved contacts: %v", err)
	}
	if contact == nil {
		return fmt.Errorf("no saved contact found for chat %d. Ask the user who this is, then run add-contact --name <name> --chat-id %d", chatID, chatID)
	}
	return nil
}

func (tc *TelegramClient) SendMessage(recipientID int64, text string) (int64, error) {
	if err := tc.requireManualContact(recipientID); err != nil {
		return 0, err
	}
	// Split long messages
	if len(text) > MaxMessageLength {
		chunks := splitMessage(text, MaxMessageLength)
		var lastID int64
		for i, chunk := range chunks {
			prefix := ""
			if len(chunks) > 1 {
				prefix = fmt.Sprintf("(%d/%d) ", i+1, len(chunks))
			}
			msg := tgbotapi.NewMessage(recipientID, toMarkdownV2(prefix+chunk))
			msg.ParseMode = "MarkdownV2"
			sent, err := tc.bot.Send(msg)
			if err != nil {
				// Retry as plain text (the unescaped original) if MarkdownV2 is rejected.
				msg.Text = prefix + chunk
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

	msg := tgbotapi.NewMessage(recipientID, toMarkdownV2(text))
	msg.ParseMode = "MarkdownV2"
	sent, err := tc.bot.Send(msg)
	if err != nil {
		// Retry as plain text (the unescaped original) if MarkdownV2 is rejected.
		msg.Text = text
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
	if err := tc.requireManualContact(recipientID); err != nil {
		return 0, err
	}
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
	if err := tc.requireManualContact(recipientID); err != nil {
		return 0, err
	}
	if buttons == "" && replyTo == 0 {
		return tc.SendMessage(recipientID, text)
	}
	if len(text) > MaxMessageLength {
		return 0, fmt.Errorf("message too long: %d chars (max %d for a message with buttons/reply)", len(text), MaxMessageLength)
	}
	msg := tgbotapi.NewMessage(recipientID, toMarkdownV2(text))
	msg.ParseMode = "MarkdownV2"
	if replyTo != 0 {
		msg.ReplyToMessageID = int(replyTo)
	}
	if kb, ok := parseInlineKeyboard(buttons); ok {
		msg.ReplyMarkup = kb
	}
	sent, err := tc.bot.Send(msg)
	if err != nil {
		msg.Text = text
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
		edit := tgbotapi.NewEditMessageTextAndMarkup(chatID, int(messageID), toMarkdownV2(text), kb)
		edit.ParseMode = "MarkdownV2"
		if _, err := tc.bot.Send(edit); err != nil {
			edit.Text = text
			edit.ParseMode = ""
			if _, err = tc.bot.Send(edit); err != nil {
				return fmt.Errorf("failed to edit message: %v", err)
			}
		}
	} else {
		edit := tgbotapi.NewEditMessageText(chatID, int(messageID), toMarkdownV2(text))
		edit.ParseMode = "MarkdownV2"
		if _, err := tc.bot.Send(edit); err != nil {
			edit.Text = text
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
	if err := tc.requireManualContact(recipientID); err != nil {
		return 0, err
	}
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
