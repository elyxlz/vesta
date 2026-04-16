package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
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

func extractInstance() string        { return extractFlag("instance") }
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

func printJSON(v interface{}) {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "JSON encoding error: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(string(data))
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

func readAuthStatus(dataDir string) map[string]string {
	tokenPath := filepath.Join(dataDir, "bot-token")
	if _, err := os.Stat(tokenPath); err != nil {
		return map[string]string{"status": "not_authenticated", "instructions": "Set your bot token with: telegram authenticate --token <BOT_TOKEN>"}
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

		// Write auth status
		statusData, _ := json.Marshal(map[string]string{"status": "authenticated"})
		os.WriteFile(filepath.Join(dataDir, "auth-status.json"), statusData, 0644)

		printJSON(map[string]string{"status": "authenticated", "message": "Bot token saved successfully"})
		return
	}

	printJSON(readAuthStatus(dataDir))
}

func runServe() {
	dataDir, _ := parseStateDir()

	notifDir := extractNotificationsDir()
	if notifDir == "" {
		fmt.Fprintln(os.Stderr, "error: --notifications-dir is required for serve")
		os.Exit(1)
	}

	var err error
	if err = os.MkdirAll(dataDir, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	if err = os.MkdirAll(notifDir, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	tc, err := NewTelegramClient(dataDir, notifDir, extractInstance(), isReadOnly(), extractSkipSenders())
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to initialize Telegram client: %v\n", err)
		os.Exit(1)
	}

	sockPath := filepath.Join(dataDir, "telegram.sock")
	listener, err := startSocketServer(sockPath, tc)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Warning: failed to start socket server: %v\n", err)
	}

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

	tc.writeAuthStatusFile(map[string]string{"status": "authenticated"})

	printJSON(map[string]string{"status": "serving", "bot": "@" + tc.bot.Self.UserName})

	// Start polling in background
	go tc.StartPolling()

	signal.Ignore(syscall.SIGHUP)

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigChan

	fmt.Fprintf(os.Stderr, "Shutting down (signal: %v)...\n", sig)
	writeDeathNotification(notifDir, sig.String())
	if listener != nil {
		stopSocketServer(listener, sockPath)
	}
	tc.Stop()
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

func runOneShot(command string) {
	sockPath := getSocketPath()
	output, exitCode, connected := trySocketCommand(sockPath, command, stripGlobalFlags(os.Args[1:]))
	if !connected {
		printJSON(map[string]interface{}{"error": "daemon not running — start with: screen -dmS telegram telegram serve --notifications-dir ~/agent/notifications"})
		os.Exit(1)
	}
	fmt.Println(string(output))
	os.Exit(exitCode)
}

func executeCommand(command string, args []string, tc *TelegramClient) (interface{}, error) {
	if tc.readOnly {
		writeCommands := map[string]bool{
			"send-message": true, "send-file": true, "send-reaction": true,
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
		var to, message string
		fs := flag.NewFlagSet("send-message", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Recipient (name, username, or chat ID)")
		fs.StringVar(&message, "message", "", "Message text")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" || message == "" {
			return nil, fmt.Errorf("--to and --message are required")
		}

		chatID, err := tc.store.ResolveRecipient(to)
		if err != nil {
			return nil, err
		}

		msgID, err := tc.SendMessage(chatID, message)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message_id": msgID, "message": "Message sent successfully"}, nil

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
