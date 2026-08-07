package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

// ConnectRetryInterval paces the wait for a bot token (and for Telegram itself) in a daemon
// that is up but not connected yet.
const (
	ConnectRetryInterval = 15 * time.Second
	authStatusFile       = "auth-status.json"
)

func extractFlag(name string) string {
	f := "--" + name
	prefix := f + "="
	for i, arg := range os.Args {
		if arg == f && i+1 < len(os.Args) {
			return os.Args[i+1]
		}
		if strings.HasPrefix(arg, prefix) {
			return strings.TrimPrefix(arg, prefix)
		}
	}
	return ""
}

func extractInstance() string         { return extractFlag("instance") }
func extractNotificationsDir() string { return extractFlag("notifications-dir") }

func isReadOnly() bool {
	for _, arg := range os.Args {
		if arg == "--read-only" {
			return true
		}
	}
	return false
}

func extractSkipSenders() map[string]bool {
	val := extractFlag("skip-senders")
	result := make(map[string]bool)
	if val != "" {
		for _, id := range strings.Split(val, ",") {
			id = strings.TrimSpace(id)
			if id != "" {
				result[id] = true
			}
		}
	}
	return result
}

func parseStateDir() (dataDir, logDir string) {
	instance := extractInstance()
	if instance != "" {
		dataDir = filepath.Join(os.Getenv("HOME"), ".telegram", instance)
		logDir = filepath.Join(os.Getenv("HOME"), ".telegram", instance, "logs")
	} else {
		dataDir = filepath.Join(os.Getenv("HOME"), ".telegram")
		logDir = filepath.Join(os.Getenv("HOME"), ".telegram", "logs")
	}
	return
}

func getSocketPath() string {
	instance := extractInstance()
	if instance != "" {
		return filepath.Join(os.Getenv("HOME"), ".telegram", instance, "telegram.sock")
	}
	return filepath.Join(os.Getenv("HOME"), ".telegram", "telegram.sock")
}

// emit is the one owner of which stream a command's answer takes: stdout
// carries only success output, and anything paired with a non-zero exit prints
// to stderr, so a filter piped onto stdout can never swallow a failure or its
// explanation.
func emit(data []byte, exitCode int) {
	if exitCode == 0 {
		fmt.Println(string(data))
	} else {
		fmt.Fprintln(os.Stderr, string(data))
	}
}

func emitAndExit(data []byte, exitCode int) {
	emit(data, exitCode)
	os.Exit(exitCode)
}

// printJSON prints a success result; failures go through failJSON or failDaemon.
func printJSON(v interface{}) {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "JSON encoding error: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(string(data))
}

// failJSON prints an {"error": ...} object on stderr and exits nonzero.
func failJSON(format string, args ...interface{}) {
	data, _ := json.MarshalIndent(map[string]interface{}{"error": fmt.Sprintf(format, args...)}, "", "  ")
	emitAndExit(data, 1)
}

func writeDeathNotification(notifDir string, sig string) {
	notif := map[string]string{
		"timestamp": time.Now().UTC().Format(time.RFC3339),
		"source":    "telegram",
		"type":      "daemon_died",
		"signal":    sig,
	}
	data, err := json.Marshal(notif)
	if err != nil {
		return
	}
	filename := fmt.Sprintf("%d-telegram-daemon_died.json", time.Now().UnixMicro())
	os.MkdirAll(notifDir, 0755)
	os.WriteFile(filepath.Join(notifDir, filename), data, 0644)
}

// writeAuthStatus records what the daemon last learned about the token. One writer, because this
// is the only place a caller can see that a token on disk is not a token Telegram accepts.
func writeAuthStatus(dataDir string, status map[string]string) {
	data, err := json.Marshal(status)
	if err != nil {
		fmt.Fprintf(os.Stderr, "warning: could not marshal the auth status: %v\n", err)
		return
	}
	if err := os.WriteFile(filepath.Join(dataDir, authStatusFile), data, 0644); err != nil {
		fmt.Fprintf(os.Stderr, "warning: could not write %s: %v\n", authStatusFile, err)
	}
}

// authOutcome classifies a connect that failed. Telegram answering 401 is a verdict on the token
// itself, so it reads as rejected; anything else (the store, the network, Telegram being down) is
// the service out of reach, and calling that a rejection sends the user off to mint a new token
// for a token that is fine.
func authOutcome(err error) map[string]string {
	var apiErr *tgbotapi.Error
	if errors.As(err, &apiErr) && apiErr.Code == http.StatusUnauthorized {
		return map[string]string{"status": "rejected", "error": err.Error()}
	}
	return map[string]string{"status": "unreachable", "error": err.Error()}
}

// readAuthStatus answers with the recorded outcome of the last connect, so a token Telegram
// rejects reads as rejected and one it never got to try reads as unreachable, rather than either
// reading as authenticated. No token on disk outranks it: whatever an older run recorded is about
// a token that is gone.
func readAuthStatus(dataDir string) map[string]string {
	tokenPath := filepath.Join(dataDir, "bot-token")
	if _, err := os.Stat(tokenPath); err != nil {
		return map[string]string{"status": "not_authenticated", "instructions": "Set your bot token with: telegram authenticate --token <BOT_TOKEN>"}
	}
	var recorded map[string]string
	data, err := os.ReadFile(filepath.Join(dataDir, authStatusFile))
	if err == nil && json.Unmarshal(data, &recorded) == nil && recorded["status"] != "" {
		return recorded
	}
	return map[string]string{"status": "authenticated"}
}

func runAuthenticate() {
	dataDir, _ := parseStateDir()

	if err := os.MkdirAll(dataDir, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	token := extractFlag("token")

	if token == "" {
		// Check if reading from stdin pipe
		stat, _ := os.Stdin.Stat()
		if (stat.Mode() & os.ModeCharDevice) == 0 {
			scanner := bufio.NewScanner(os.Stdin)
			if scanner.Scan() {
				token = strings.TrimSpace(scanner.Text())
			}
		}
	}

	if token != "" {
		tokenPath := filepath.Join(dataDir, "bot-token")
		if err := os.WriteFile(tokenPath, []byte(token), 0600); err != nil {
			fmt.Fprintf(os.Stderr, "Error saving token: %v\n", err)
			os.Exit(1)
		}
		writeAuthStatus(dataDir, map[string]string{"status": "authenticated"})
		printJSON(map[string]string{"status": "authenticated", "message": "Bot token saved successfully"})
		return
	}

	printJSON(readAuthStatus(dataDir))
}

func runServe() {
	dataDir, _ := parseStateDir()

	notifDir := extractNotificationsDir()
	if notifDir == "" {
		notifDir = defaultNotificationsDir()
	}

	if err := os.MkdirAll(dataDir, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	writeDaemonInfo(dataDir, os.Args[1:])
	if err := os.MkdirAll(notifDir, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	// The handlers come before the socket and the connect loop, so an exit asked for during
	// startup is the deliberate one rather than a death the agent has to investigate.
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)

	var client atomic.Pointer[TelegramClient]
	sockPath := filepath.Join(dataDir, "telegram.sock")
	listener, err := startSocketServer(sockPath, &client)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Warning: failed to start socket server: %v\n", err)
	}

	tc, sig := connectClient(dataDir, notifDir, signals)
	if tc == nil {
		finishServe(sig, notifDir, listener, sockPath, nil)
		return
	}
	client.Store(tc)

	instance := extractInstance()
	if instance != "" {
		fmt.Fprintf(os.Stderr, "Telegram bot initialized (instance: %s). Data: %s\n", instance, dataDir)
	} else {
		fmt.Fprintf(os.Stderr, "Telegram bot initialized. Data: %s\n", dataDir)
	}
	fmt.Fprintf(os.Stderr, "Notifications: %s\n", notifDir)
	if isReadOnly() {
		fmt.Fprintln(os.Stderr, "Running in READ-ONLY mode (no sending)")
	}

	writeAuthStatus(dataDir, map[string]string{"status": "authenticated"})

	printJSON(map[string]string{"status": "serving", "bot": "@" + tc.bot.Self.UserName})

	// Start polling in background
	go tc.StartPolling()

	finishServe(<-signals, notifDir, listener, sockPath, tc)
}

// connectClient brings the Telegram client up, retrying until it does: a daemon started before
// the bot token is saved, or while Telegram is unreachable, idles and says so on its socket
// instead of exiting and leaving the agent with a channel that is quietly gone. Returns a nil
// client when a signal ends the wait instead.
func connectClient(dataDir, notifDir string, signals <-chan os.Signal) (*TelegramClient, os.Signal) {
	reported := ""
	for {
		tc, err := NewTelegramClient(dataDir, notifDir, extractInstance(), isReadOnly(), extractSkipSenders())
		if err == nil {
			return tc, nil
		}
		// One write and one log line per distinct reason, not one per retry: the same failure
		// every 15 seconds buries the log it is written to and rewrites a status nothing learned
		// from.
		if err.Error() != reported {
			reported = err.Error()
			writeAuthStatus(dataDir, authOutcome(err))
			fmt.Fprintf(os.Stderr, "Not serving yet: %v\n", err)
		}
		select {
		case sig := <-signals:
			return nil, sig
		case <-time.After(ConnectRetryInterval):
		}
	}
}

func finishServe(sig os.Signal, notifDir string, listener net.Listener, sockPath string, tc *TelegramClient) {
	fmt.Fprintf(os.Stderr, "Shutting down (signal: %v)...\n", sig)
	if deathIsNews(sig) {
		writeDeathNotification(notifDir, sig.String())
	}
	if listener != nil {
		stopSocketServer(listener, sockPath)
	}
	if tc != nil {
		tc.Stop()
	}
}

func stripGlobalFlags(args []string) []string {
	var filtered []string
	skip := false
	for _, arg := range args {
		if skip {
			skip = false
			continue
		}
		if arg == "--instance" || arg == "--notifications-dir" || arg == "--skip-senders" {
			skip = true
			continue
		}
		if strings.HasPrefix(arg, "--instance=") || strings.HasPrefix(arg, "--notifications-dir=") || arg == "--read-only" || strings.HasPrefix(arg, "--skip-senders=") {
			continue
		}
		filtered = append(filtered, arg)
	}
	return filtered
}

// resolveStdinArgs replaces a `-` body value with this process's stdin, before the command is
// forwarded to the daemon. executeCommand runs inside the daemon, whose stdin is not ours, so a `-`
// that reached it would read EOF and the send would fail as an empty body. Accepts both `--flag -`
// and `--flag=-`, the two forms the flag package itself accepts; a command carries one body, so the
// first match is the only one.
func resolveStdinArgs(args []string, bodyFlags ...string) ([]string, error) {
	out := slices.Clone(args)
	for i, arg := range out {
		name, value, inline := strings.Cut(arg, "=")
		if !strings.HasPrefix(name, "-") || !slices.Contains(bodyFlags, strings.TrimLeft(name, "-")) {
			continue
		}
		at := i
		if !inline {
			at, value = i+1, ""
			if at < len(out) {
				value = out[at]
			}
		}
		if value != "-" {
			continue
		}
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			return nil, err
		}
		body := strings.TrimRight(string(data), "\r\n")
		if inline {
			body = name + "=" + body
		}
		out[at] = body
		return out, nil
	}
	return out, nil
}

func runOneShot(command string) {
	sockPath := getSocketPath()
	args, err := resolveStdinArgs(stripGlobalFlags(os.Args[1:]), "message")
	if err != nil {
		failJSON("could not read the body from stdin: %v", err)
	}
	output, exitCode, connected := trySocketCommand(sockPath, command, args)
	if !connected {
		failJSON("daemon not running; start with: telegram daemon start")
	}
	emitAndExit(output, exitCode)
}

func executeCommand(command string, args []string, tc *TelegramClient) (interface{}, error) {
	if tc.readOnly {
		writeCommands := map[string]bool{
			"send-message": true, "send-file": true, "send-reaction": true,
			"send-voice": true, "edit-message": true, "delete-message": true,
			"answer-callback": true, "send-chat-action": true,
			"pin-message": true, "unpin-message": true,
		}
		if writeCommands[command] {
			return nil, fmt.Errorf("command %q blocked: instance is read-only", command)
		}
	}

	switch command {
	case "list-contacts":
		var query string
		var limit int
		fs := flag.NewFlagSet("list-contacts", flag.ContinueOnError)
		fs.StringVar(&query, "query", "", "Optional search query")
		fs.IntVar(&limit, "limit", 50, "Max results")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		contacts, err := tc.store.SearchContacts(query, limit)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"contacts": contacts}, nil

	case "add-contact":
		var name, chatIDStr, username string
		fs := flag.NewFlagSet("add-contact", flag.ContinueOnError)
		fs.StringVar(&name, "name", "", "Contact name")
		fs.StringVar(&chatIDStr, "chat-id", "", "Telegram chat ID")
		fs.StringVar(&username, "username", "", "Telegram @username (optional)")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if name == "" || chatIDStr == "" {
			return nil, fmt.Errorf("--name and --chat-id are required")
		}
		chatID, err := strconv.ParseInt(chatIDStr, 10, 64)
		if err != nil {
			return nil, fmt.Errorf("invalid chat ID: %s", chatIDStr)
		}
		contact, err := tc.store.SaveManualContact(name, chatID, username)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"contact": contact}, nil

	case "remove-contact":
		var identifier string
		fs := flag.NewFlagSet("remove-contact", flag.ContinueOnError)
		fs.StringVar(&identifier, "identifier", "", "Contact name or username")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if identifier == "" {
			return nil, fmt.Errorf("--identifier is required")
		}
		if err := tc.store.DeleteManualContact(identifier); err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message": "Contact removed"}, nil

	case "list-messages":
		var to, after, before, sender, query string
		var limit, page int
		fs := flag.NewFlagSet("list-messages", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Chat filter (contact name, username, or chat ID)")
		fs.StringVar(&after, "after", "", "ISO-8601 datetime")
		fs.StringVar(&before, "before", "", "ISO-8601 datetime")
		fs.StringVar(&sender, "sender", "", "Filter by sender name")
		fs.StringVar(&query, "query", "", "Search query")
		fs.IntVar(&limit, "limit", 50, "Max results")
		fs.IntVar(&page, "page", 0, "Page number")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}

		var afterTime, beforeTime *time.Time
		if after != "" {
			t, err := time.Parse(time.RFC3339, after)
			if err != nil {
				return nil, fmt.Errorf("invalid --after timestamp (expected RFC3339): %v", err)
			}
			afterTime = &t
		}
		if before != "" {
			t, err := time.Parse(time.RFC3339, before)
			if err != nil {
				return nil, fmt.Errorf("invalid --before timestamp (expected RFC3339): %v", err)
			}
			beforeTime = &t
		}

		var chatID int64
		if to != "" {
			resolved, err := tc.store.ResolveRecipient(to)
			if err != nil {
				return nil, fmt.Errorf("failed to resolve chat: %v", err)
			}
			chatID = resolved
		}

		messages, err := tc.store.ListMessages(
			afterTime, beforeTime,
			sender, chatID, query,
			limit, page*limit,
		)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"messages": messages}, nil

	case "list-chats":
		var query, sortBy string
		var limit, page int
		var includeLastMessage bool
		fs := flag.NewFlagSet("list-chats", flag.ContinueOnError)
		fs.StringVar(&query, "query", "", "Search query")
		fs.IntVar(&limit, "limit", 50, "Max results")
		fs.IntVar(&page, "page", 0, "Page number")
		fs.BoolVar(&includeLastMessage, "include-last-message", false, "Include last message")
		fs.StringVar(&sortBy, "sort-by", "last_active", "Sort by (last_active or name)")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		chats, err := tc.store.ListChats(query, limit, page*limit, includeLastMessage, sortBy)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"chats": chats}, nil

	case "send-message":
		var to, message, buttons, replyToStr string
		var longform bool
		fs := flag.NewFlagSet("send-message", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Recipient (name, username, or chat ID)")
		fs.StringVar(&message, "message", "", "Message text, or '-' to read the body from stdin (use a <<'MSG' heredoc for anything with apostrophes, quotes, backticks or newlines)")
		fs.StringVar(&buttons, "buttons", "", "Inline keyboard: rows by ';', buttons by ',', each 'Label=callback_data' (or 'Label=url:https://...')")
		fs.StringVar(&replyToStr, "reply-to", "", "Quote/reply to this message ID")
		fs.BoolVar(&longform, "longform", false, "Bypass the short-bubble lint for genuine reference material (a brief, a code block, a list they asked for).")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" {
			return nil, fmt.Errorf("--to is required")
		}
		// resolveStdinArgs swapped a `-` for the real body in the client process; still seeing one
		// here means nothing was piped in.
		if message == "" || message == "-" {
			return nil, fmt.Errorf("--message is required (pass '-' and a <<'MSG' heredoc to read the body from stdin)")
		}
		if !longform {
			if reason := bubbleLintReason(message); reason != "" {
				return nil, fmt.Errorf("%s", reason)
			}
		}
		var replyTo int64
		if replyToStr != "" {
			v, err := strconv.ParseInt(replyToStr, 10, 64)
			if err != nil {
				return nil, fmt.Errorf("invalid --reply-to: %s", replyToStr)
			}
			replyTo = v
		}

		chatID, err := tc.store.ResolveRecipient(to)
		if err != nil {
			return nil, err
		}

		msgID, err := tc.SendMessageWithOptions(chatID, message, buttons, replyTo)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message_id": msgID, "message": "Message sent successfully"}, nil

	case "edit-message":
		var to, messageIDStr, message, buttons string
		fs := flag.NewFlagSet("edit-message", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Chat (name, username, or chat ID)")
		fs.StringVar(&messageIDStr, "message-id", "", "ID of the message to edit")
		fs.StringVar(&message, "message", "", "New message text, or '-' to read it from stdin (use a <<'MSG' heredoc for anything with apostrophes, quotes, backticks or newlines)")
		fs.StringVar(&buttons, "buttons", "", "Replacement inline keyboard (same format as send-message; omit to clear/keep none)")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" || messageIDStr == "" {
			return nil, fmt.Errorf("--to and --message-id are required")
		}
		// resolveStdinArgs swapped a `-` for the real body in the client process; still seeing one
		// here means nothing was piped in.
		if message == "" || message == "-" {
			return nil, fmt.Errorf("--message is required (pass '-' and a <<'MSG' heredoc to read the body from stdin)")
		}
		messageID, err := strconv.ParseInt(messageIDStr, 10, 64)
		if err != nil {
			return nil, fmt.Errorf("invalid message ID: %s", messageIDStr)
		}
		chatID, err := tc.store.ResolveRecipient(to)
		if err != nil {
			return nil, err
		}
		if err := tc.EditMessage(chatID, messageID, message, buttons); err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message": "Message edited"}, nil

	case "delete-message":
		var to, messageIDStr string
		fs := flag.NewFlagSet("delete-message", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Chat")
		fs.StringVar(&messageIDStr, "message-id", "", "ID of the message to delete")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" || messageIDStr == "" {
			return nil, fmt.Errorf("--to and --message-id are required")
		}
		messageID, err := strconv.ParseInt(messageIDStr, 10, 64)
		if err != nil {
			return nil, fmt.Errorf("invalid message ID: %s", messageIDStr)
		}
		chatID, err := tc.store.ResolveRecipient(to)
		if err != nil {
			return nil, err
		}
		if err := tc.DeleteMessage(chatID, messageID); err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message": "Message deleted"}, nil

	case "answer-callback":
		var callbackID, text string
		var alert bool
		fs := flag.NewFlagSet("answer-callback", flag.ContinueOnError)
		fs.StringVar(&callbackID, "callback-id", "", "callback_id from the callback_query notification")
		fs.StringVar(&text, "text", "", "Optional toast/alert text shown to the user")
		fs.BoolVar(&alert, "alert", false, "Show as a modal alert instead of a transient toast")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if callbackID == "" {
			return nil, fmt.Errorf("--callback-id is required")
		}
		if err := tc.AnswerCallback(callbackID, text, alert); err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message": "Callback answered"}, nil

	case "send-voice":
		var to, filePath, caption string
		fs := flag.NewFlagSet("send-voice", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Recipient")
		fs.StringVar(&filePath, "file-path", "", "Path to voice file (.ogg/opus ideal)")
		fs.StringVar(&caption, "caption", "", "Optional caption")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" || filePath == "" {
			return nil, fmt.Errorf("--to and --file-path are required")
		}
		chatID, err := tc.store.ResolveRecipient(to)
		if err != nil {
			return nil, err
		}
		msgID, err := tc.SendVoice(chatID, filePath, caption)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message_id": msgID, "message": "Voice note sent"}, nil

	case "send-chat-action":
		var to, action string
		fs := flag.NewFlagSet("send-chat-action", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Chat")
		fs.StringVar(&action, "action", "typing", "typing | upload_photo | upload_document | record_voice | etc")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" {
			return nil, fmt.Errorf("--to is required")
		}
		chatID, err := tc.store.ResolveRecipient(to)
		if err != nil {
			return nil, err
		}
		if err := tc.SendChatAction(chatID, action); err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message": "Chat action sent"}, nil

	case "pin-message", "unpin-message":
		var to, messageIDStr string
		var silent bool
		fs := flag.NewFlagSet(command, flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Chat")
		fs.StringVar(&messageIDStr, "message-id", "", "Message ID (for unpin, 0/omitted unpins the latest)")
		fs.BoolVar(&silent, "silent", false, "Pin without notifying (pin-message only)")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" {
			return nil, fmt.Errorf("--to is required")
		}
		var messageID int64
		if messageIDStr != "" {
			v, err := strconv.ParseInt(messageIDStr, 10, 64)
			if err != nil {
				return nil, fmt.Errorf("invalid message ID: %s", messageIDStr)
			}
			messageID = v
		}
		chatID, err := tc.store.ResolveRecipient(to)
		if err != nil {
			return nil, err
		}
		if command == "pin-message" {
			if messageID == 0 {
				return nil, fmt.Errorf("--message-id is required for pin-message")
			}
			if err := tc.PinMessage(chatID, messageID, silent); err != nil {
				return nil, err
			}
			return map[string]interface{}{"success": true, "message": "Message pinned"}, nil
		}
		if err := tc.UnpinMessage(chatID, messageID); err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message": "Message unpinned"}, nil

	case "send-file":
		var to, filePath, caption string
		fs := flag.NewFlagSet("send-file", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Recipient")
		fs.StringVar(&filePath, "file-path", "", "Path to file")
		fs.StringVar(&caption, "caption", "", "Optional caption")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" || filePath == "" {
			return nil, fmt.Errorf("--to and --file-path are required")
		}

		chatID, err := tc.store.ResolveRecipient(to)
		if err != nil {
			return nil, err
		}

		msgID, err := tc.SendFile(chatID, filePath, caption)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message_id": msgID, "message": "File sent successfully"}, nil

	case "send-reaction":
		var to, messageIDStr, emoji string
		fs := flag.NewFlagSet("send-reaction", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Chat")
		fs.StringVar(&messageIDStr, "message-id", "", "Message ID")
		fs.StringVar(&emoji, "emoji", "", "Emoji")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" || messageIDStr == "" || emoji == "" {
			return nil, fmt.Errorf("--to, --message-id, and --emoji are required")
		}

		chatID, err := tc.store.ResolveRecipient(to)
		if err != nil {
			return nil, err
		}

		msgID, err := strconv.Atoi(messageIDStr)
		if err != nil {
			return nil, fmt.Errorf("invalid message ID: %s", messageIDStr)
		}

		if err := tc.SendReaction(chatID, msgID, emoji); err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message": "Reaction sent"}, nil

	case "download-media":
		var fileID, downloadPath string
		fs := flag.NewFlagSet("download-media", flag.ContinueOnError)
		fs.StringVar(&fileID, "file-id", "", "Telegram file ID")
		fs.StringVar(&downloadPath, "download-path", "", "Save path")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if fileID == "" {
			return nil, fmt.Errorf("--file-id is required")
		}

		path, err := tc.DownloadFile(fileID, downloadPath)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "file_path": path, "message": "File downloaded"}, nil

	case "list-groups":
		var limit, page int
		fs := flag.NewFlagSet("list-groups", flag.ContinueOnError)
		fs.IntVar(&limit, "limit", 50, "Max results")
		fs.IntVar(&page, "page", 0, "Page number")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		groups, err := tc.store.ListGroups(limit, page*limit)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"groups": groups}, nil

	default:
		return nil, fmt.Errorf("unknown command: %s", command)
	}
}
