package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	waLog "go.mau.fi/whatsmeow/util/log"
)

func extractFlag(name string) string {
	flag := "--" + name
	prefix := flag + "="
	for i, arg := range os.Args {
		if arg == flag && i+1 < len(os.Args) {
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
		for _, phone := range strings.Split(val, ",") {
			phone = strings.TrimSpace(phone)
			if phone != "" {
				result[phone] = true
			}
		}
	}
	return result
}

func parseStateDir() (dataDir, logDir string) {
	instance := extractInstance()
	if instance != "" {
		dataDir = filepath.Join(os.Getenv("HOME"), ".whatsapp", instance)
		logDir = filepath.Join(os.Getenv("HOME"), ".whatsapp", instance, "logs")
	} else {
		dataDir = filepath.Join(os.Getenv("HOME"), ".whatsapp")
		logDir = filepath.Join(os.Getenv("HOME"), ".whatsapp", "logs")
	}
	return
}

func getSocketPath() string {
	instance := extractInstance()
	if instance != "" {
		return filepath.Join(os.Getenv("HOME"), ".whatsapp", instance, "whatsapp.sock")
	}
	return filepath.Join(os.Getenv("HOME"), ".whatsapp", "whatsapp.sock")
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
		"source":    "whatsapp",
		"type":      "daemon_died",
		"signal":    sig,
	}
	data, err := json.Marshal(notif)
	if err != nil {
		return
	}
	filename := fmt.Sprintf("%d-whatsapp-daemon_died.json", time.Now().UnixMicro())
	os.MkdirAll(notifDir, 0755)
	os.WriteFile(filepath.Join(notifDir, filename), data, 0644)
}

func readAuthStatus(dataDir string) map[string]string {
	statusPath := filepath.Join(dataDir, "auth-status.json")
	data, err := os.ReadFile(statusPath)
	if err != nil {
		return map[string]string{"status": "not_started"}
	}
	var status map[string]string
	if err := json.Unmarshal(data, &status); err != nil {
		return map[string]string{"status": "not_started"}
	}
	if status["status"] == string(AuthStatusQRReady) {
		status["qr_image"] = "file://" + filepath.Join(dataDir, "qr-code.png")
	}
	return status
}

func runAuthenticate() {
	dataDir, _ := parseStateDir()
	var err error
	dataDir, err = resolveDir(dataDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	printJSON(readAuthStatus(dataDir))
}

func runServe(logger waLog.Logger) {
	dataDir, _ := parseStateDir()

	notifDir := extractNotificationsDir()
	if notifDir == "" {
		fmt.Fprintln(os.Stderr, "error: --notifications-dir is required for serve")
		os.Exit(1)
	}

	var err error
	dataDir, err = resolveDir(dataDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	notifDir, err = resolveDir(notifDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	wac, err := NewWhatsAppClient(dataDir, notifDir, extractInstance(), isReadOnly(), extractSkipSenders(), logger)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to initialize WhatsApp client: %v\n", err)
		os.Exit(1)
	}

	if err := wac.Connect(); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to connect: %v\n", err)
		os.Exit(1)
	}

	sockPath := filepath.Join(dataDir, "whatsapp.sock")
	listener, err := startSocketServer(sockPath, wac)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Warning: failed to start socket server: %v\n", err)
	}

	instance := extractInstance()
	if instance != "" {
		fmt.Fprintf(os.Stderr, "WhatsApp client initialized (instance: %s). Data: %s\n", instance, dataDir)
	} else {
		fmt.Fprintf(os.Stderr, "WhatsApp client initialized. Data: %s\n", dataDir)
	}
	fmt.Fprintf(os.Stderr, "Notifications: %s\n", notifDir)
	if isReadOnly() {
		fmt.Fprintln(os.Stderr, "Running in READ-ONLY mode (no sending, no read receipts)")
	}

	if !wac.IsAuthenticated() {
		fmt.Fprintln(os.Stderr, "Not authenticated. Use 'whatsapp authenticate' to get QR code.")
	}

	printJSON(map[string]string{"status": "serving"})

	signal.Ignore(syscall.SIGHUP)

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigChan

	fmt.Fprintf(os.Stderr, "Shutting down (signal: %v)...\n", sig)
	writeDeathNotification(notifDir, sig.String())
	if listener != nil {
		stopSocketServer(listener, sockPath)
	}
	wac.Disconnect()
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
		printJSON(map[string]interface{}{"error": "daemon not running — start with: screen -dmS whatsapp whatsapp serve"})
		os.Exit(1)
	}
	fmt.Println(string(output))
	os.Exit(exitCode)
}

func executeCommand(command string, args []string, wac *WhatsAppClient) (interface{}, error) {
	// Block write commands on read-only instances
	if wac.readOnly {
		writeCommands := map[string]bool{
			"send-message": true, "send-file": true, "send-reaction": true,
			"send-audio": true, "add-contact": true, "remove-contact": true,
			"leave-group": true, "create-group": true, "rename-group": true,
			"update-group-participants": true, "set-group-photo": true,
			"revoke-message": true,
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
		contacts, err := wac.store.SearchContacts(query, limit)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"contacts": contacts}, nil

	case "add-contact":
		var name, phone string
		fs := flag.NewFlagSet("add-contact", flag.ContinueOnError)
		fs.StringVar(&name, "name", "", "Contact name")
		fs.StringVar(&phone, "phone", "", "Phone number (E.164)")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if name == "" || phone == "" {
			return nil, fmt.Errorf("--name and --phone are required")
		}
		contact, err := wac.AddContact(name, phone)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"contact": contact}, nil

	case "remove-contact":
		var identifier string
		fs := flag.NewFlagSet("remove-contact", flag.ContinueOnError)
		fs.StringVar(&identifier, "identifier", "", "Contact name or phone")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if identifier == "" {
			return nil, fmt.Errorf("--identifier is required")
		}
		if err := wac.store.DeleteManualContact(identifier); err != nil {
			return nil, err
		}
		return map[string]interface{}{"success": true, "message": "Contact removed"}, nil

	case "list-messages":
		var to, after, before, senderPhone, query string
		var limit, page int
		fs := flag.NewFlagSet("list-messages", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Chat filter (contact name, phone, or group)")
		fs.StringVar(&after, "after", "", "ISO-8601 datetime")
		fs.StringVar(&before, "before", "", "ISO-8601 datetime")
		fs.StringVar(&senderPhone, "sender-phone", "", "Filter by sender")
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

		var chatJID string
		if to != "" {
			jid, err := wac.ResolveRecipient(to)
			if err != nil {
				return nil, fmt.Errorf("failed to resolve chat: %v", err)
			}
			chatJID = jid.String()
		}

		messages, err := wac.store.ListMessages(
			afterTime, beforeTime,
			senderPhone, chatJID, query,
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
		chats, err := wac.store.ListChats(query, limit, page*limit, includeLastMessage, sortBy)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"chats": chats}, nil

	case "send-message":
		var to, message string
		fs := flag.NewFlagSet("send-message", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Recipient (name, phone, or group)")
		fs.StringVar(&message, "message", "", "Message text")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" || message == "" {
			return nil, fmt.Errorf("--to and --message are required")
		}
		success, msg := wac.SendMessageWithPresence(to, message)
		return map[string]interface{}{"success": success, "message": msg}, nil

	case "send-file":
		var to, filePath, caption, displayName string
		fs := flag.NewFlagSet("send-file", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Recipient")
		fs.StringVar(&filePath, "file-path", "", "Path to file")
		fs.StringVar(&caption, "caption", "", "Optional caption")
		fs.StringVar(&displayName, "display-name", "", "Override filename shown to recipient")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" || filePath == "" {
			return nil, fmt.Errorf("--to and --file-path are required")
		}
		success, msg := wac.SendFile(to, filePath, caption, displayName)
		return map[string]interface{}{"success": success, "message": msg}, nil

	case "send-audio":
		var to, filePath string
		fs := flag.NewFlagSet("send-audio", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Recipient")
		fs.StringVar(&filePath, "file-path", "", "Path to audio file")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" || filePath == "" {
			return nil, fmt.Errorf("--to and --file-path are required")
		}
		success, msg := wac.SendAudioMessage(to, filePath)
		return map[string]interface{}{"success": success, "message": msg}, nil

	case "download-media":
		var messageID, to, downloadPath string
		fs := flag.NewFlagSet("download-media", flag.ContinueOnError)
		fs.StringVar(&messageID, "message-id", "", "Message ID")
		fs.StringVar(&to, "to", "", "Chat")
		fs.StringVar(&downloadPath, "download-path", "", "Save path")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if messageID == "" {
			return nil, fmt.Errorf("--message-id is required")
		}
		path, err := wac.DownloadMedia(messageID, to, downloadPath)
		if err != nil {
			return map[string]interface{}{"success": false, "message": err.Error()}, nil
		}
		return map[string]interface{}{"success": true, "file_path": path, "message": "Media downloaded"}, nil

	case "send-reaction":
		var messageID, emoji, to string
		fs := flag.NewFlagSet("send-reaction", flag.ContinueOnError)
		fs.StringVar(&messageID, "message-id", "", "Message ID")
		fs.StringVar(&emoji, "emoji", "", "Emoji")
		fs.StringVar(&to, "to", "", "Chat")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if messageID == "" || emoji == "" || to == "" {
			return nil, fmt.Errorf("--message-id, --emoji, and --to are required")
		}
		success, msg := wac.SendReaction(messageID, emoji, to)
		return map[string]interface{}{"success": success, "message": msg}, nil

	case "revoke-message":
		var messageID, to string
		fs := flag.NewFlagSet("revoke-message", flag.ContinueOnError)
		fs.StringVar(&messageID, "message-id", "", "Message ID to revoke/delete for everyone")
		fs.StringVar(&to, "to", "", "Chat (contact name, phone, or group)")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if messageID == "" || to == "" {
			return nil, fmt.Errorf("--message-id and --to are required")
		}
		success, msg := wac.RevokeMessage(messageID, to)
		return map[string]interface{}{"success": success, "message": msg}, nil

	case "create-group":
		var groupName string
		fs := flag.NewFlagSet("create-group", flag.ContinueOnError)
		fs.StringVar(&groupName, "name", "", "Group name")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		participants := fs.Args()
		if groupName == "" || len(participants) == 0 {
			return nil, fmt.Errorf("--name and participant phone numbers are required")
		}
		success, msg := wac.CreateGroup(groupName, participants)
		return map[string]interface{}{"success": success, "group_name": groupName, "message": msg}, nil

	case "leave-group":
		var group string
		fs := flag.NewFlagSet("leave-group", flag.ContinueOnError)
		fs.StringVar(&group, "group", "", "Group name")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if group == "" {
			return nil, fmt.Errorf("--group is required")
		}
		success, msg := wac.LeaveGroup(group)
		return map[string]interface{}{"success": success, "message": msg}, nil

	case "list-groups":
		var limit, page int
		fs := flag.NewFlagSet("list-groups", flag.ContinueOnError)
		fs.IntVar(&limit, "limit", 50, "Max results")
		fs.IntVar(&page, "page", 0, "Page number")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		groups, err := wac.store.ListGroups(limit, page*limit)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"groups": groups}, nil

	case "update-group-participants":
		var group, action string
		fs := flag.NewFlagSet("update-group-participants", flag.ContinueOnError)
		fs.StringVar(&group, "group", "", "Group name")
		fs.StringVar(&action, "action", "", "add or remove")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		participants := fs.Args()
		if group == "" || action == "" || len(participants) == 0 {
			return nil, fmt.Errorf("--group, --action, and participant phone numbers are required")
		}
		success, msg := wac.UpdateGroupParticipants(group, action, participants)
		return map[string]interface{}{"success": success, "message": msg}, nil

	case "backfill":
		var to string
		var count int
		fs := flag.NewFlagSet("backfill", flag.ContinueOnError)
		fs.StringVar(&to, "to", "", "Chat to backfill")
		fs.IntVar(&count, "count", 50, "Number of messages to request")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if to == "" {
			return nil, fmt.Errorf("--to is required")
		}
		success, msg := wac.RequestBackfill(to, count)
		return map[string]interface{}{"success": success, "message": msg}, nil

	case "rename-group":
		var group, name string
		fs := flag.NewFlagSet("rename-group", flag.ContinueOnError)
		fs.StringVar(&group, "group", "", "Group name or JID")
		fs.StringVar(&name, "name", "", "New group name")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if group == "" || name == "" {
			return nil, fmt.Errorf("--group and --name are required")
		}
		success, msg := wac.RenameGroup(group, name)
		return map[string]interface{}{"success": success, "message": msg}, nil

	case "set-group-photo":
		var group, filePath string
		fs := flag.NewFlagSet("set-group-photo", flag.ContinueOnError)
		fs.StringVar(&group, "group", "", "Group name or JID")
		fs.StringVar(&filePath, "file-path", "", "Path to image file")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if group == "" || filePath == "" {
			return nil, fmt.Errorf("--group and --file-path are required")
		}
		success, msg := wac.SetGroupPhoto(group, filePath)
		return map[string]interface{}{"success": success, "message": msg}, nil

	case "check-delivery":
		var messageID, to string
		var limit int
		var recent bool
		fs := flag.NewFlagSet("check-delivery", flag.ContinueOnError)
		fs.StringVar(&messageID, "message-id", "", "Message ID to check")
		fs.StringVar(&to, "to", "", "Chat filter (contact name, phone, or group)")
		fs.IntVar(&limit, "limit", 10, "Number of recent messages to show")
		fs.BoolVar(&recent, "recent", false, "Show recent outgoing message statuses")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}

		if recent || messageID == "" {
			// Show recent outgoing messages with delivery status
			var chatJID string
			if to != "" {
				jid, err := wac.ResolveRecipient(to)
				if err != nil {
					return nil, fmt.Errorf("failed to resolve chat: %v", err)
				}
				chatJID = jid.String()
			}
			results, err := wac.store.GetRecentOutgoingStatus(chatJID, limit)
			if err != nil {
				return nil, err
			}
			return map[string]interface{}{"messages": results}, nil
		}

		// Check specific message
		var chatJID string
		if to != "" {
			jid, err := wac.ResolveRecipient(to)
			if err != nil {
				return nil, fmt.Errorf("failed to resolve chat: %v", err)
			}
			chatJID = jid.String()
		}
		status, ts, err := wac.store.GetDeliveryStatus(messageID, chatJID)
		if err != nil {
			return nil, fmt.Errorf("message not found: %v", err)
		}
		result := map[string]interface{}{
			"message_id":      messageID,
			"delivery_status": status,
		}
		if ts != nil {
			result["delivery_timestamp"] = ts.Format(time.RFC3339)
		}
		return result, nil

	case "pair-phone":
		var phone string
		fs := flag.NewFlagSet("pair-phone", flag.ContinueOnError)
		fs.StringVar(&phone, "phone", "", "Phone number to pair with (E.164 format, e.g. +393481234567)")
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if phone == "" {
			return nil, fmt.Errorf("--phone is required (E.164 format, e.g. +393481234567)")
		}
		code, err := wac.PairPhone(phone)
		if err != nil {
			return nil, fmt.Errorf("failed to generate pairing code: %v", err)
		}
		return map[string]interface{}{"pairing_code": code, "phone": phone, "instructions": "Enter this code in WhatsApp > Linked Devices > Link a Device > Link with phone number"}, nil

	default:
		return nil, fmt.Errorf("unknown command: %s", command)
	}
}
