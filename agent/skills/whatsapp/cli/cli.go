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

// These parse os.Args directly rather than using flag.FlagSet because they are
// global flags that must be read before command dispatch (the per-command FlagSet
// only sees the remaining args after the subcommand).

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

func successResult(success bool, msg string) map[string]any {
	return map[string]any{"success": success, "message": msg}
}

func printJSON(v any) {
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
		printJSON(map[string]any{"error": "daemon not running — start with: screen -dmS whatsapp whatsapp serve"})
		os.Exit(1)
	}
	fmt.Println(string(output))
	os.Exit(exitCode)
}

// writeCommands lists commands that are blocked in read-only mode.
var writeCommands = map[string]bool{
	"send-message": true, "send-file": true, "send-reaction": true,
	"send-audio": true, "add-contact": true, "remove-contact": true,
	"leave-group": true, "create-group": true, "rename-group": true,
	"update-group-participants": true, "set-group-photo": true, "set-group-description": true,
	"revoke-message": true, "archive-chat": true, "archive-all-chats": true,
	"delete-chat": true, "clear-all-chats": true,
}

func executeCommand(command string, args []string, wac *WhatsAppClient) (any, error) {
	if wac.readOnly && writeCommands[command] {
		return nil, fmt.Errorf("command %q blocked: instance is read-only", command)
	}

	switch command {
	case "list-contacts":
		return cmdListContacts(args, wac)
	case "add-contact":
		return cmdAddContact(args, wac)
	case "remove-contact":
		return cmdRemoveContact(args, wac)
	case "list-messages":
		return cmdListMessages(args, wac)
	case "list-chats":
		return cmdListChats(args, wac)
	case "send-message":
		return cmdSendMessage(args, wac)
	case "send-file":
		return cmdSendFile(args, wac)
	case "send-audio":
		return cmdSendAudio(args, wac)
	case "download-media":
		return cmdDownloadMedia(args, wac)
	case "send-reaction":
		return cmdSendReaction(args, wac)
	case "revoke-message":
		return cmdRevokeMessage(args, wac)
	case "create-group":
		return cmdCreateGroup(args, wac)
	case "leave-group":
		return cmdLeaveGroup(args, wac)
	case "list-groups":
		return cmdListGroups(args, wac)
	case "update-group-participants":
		return cmdUpdateGroupParticipants(args, wac)
	case "backfill":
		return cmdBackfill(args, wac)
	case "rename-group":
		return cmdRenameGroup(args, wac)
	case "set-group-photo":
		return cmdSetGroupPhoto(args, wac)
	case "set-group-description":
		return cmdSetGroupDescription(args, wac)
	case "get-group-invite-link":
		return cmdGetGroupInviteLink(args, wac)
	case "check-delivery":
		return cmdCheckDelivery(args, wac)
	case "pair-phone":
		return cmdPairPhone(args, wac)
	case "list-received-contacts":
		return cmdListReceivedContacts(args, wac)
	case "archive-chat":
		return cmdArchiveChat(args, wac)
	case "archive-all-chats":
		return cmdArchiveAllChats(wac)
	case "delete-chat":
		return cmdDeleteChat(args, wac)
	case "clear-all-chats":
		return cmdClearAllChats(wac)
	default:
		return nil, fmt.Errorf("unknown command: %s", command)
	}
}

func cmdListContacts(args []string, wac *WhatsAppClient) (any, error) {
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
	return map[string]any{"contacts": contacts}, nil
}

func cmdAddContact(args []string, wac *WhatsAppClient) (any, error) {
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
	return map[string]any{"contact": contact}, nil
}

func cmdRemoveContact(args []string, wac *WhatsAppClient) (any, error) {
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
	return map[string]any{"success": true, "message": "Contact removed"}, nil
}

func cmdListMessages(args []string, wac *WhatsAppClient) (any, error) {
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

	messages, err := wac.store.ListMessages(afterTime, beforeTime, senderPhone, chatJID, query, limit, page*limit)
	if err != nil {
		return nil, err
	}
	return map[string]any{"messages": messages}, nil
}

func cmdListChats(args []string, wac *WhatsAppClient) (any, error) {
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
	return map[string]any{"chats": chats}, nil
}

func cmdSendMessage(args []string, wac *WhatsAppClient) (any, error) {
	var to, message string
	fs := flag.NewFlagSet("send-message", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Recipient")
	fs.StringVar(&message, "message", "", "Message text")
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	if to == "" || message == "" {
		return nil, fmt.Errorf("--to and --message are required")
	}
	success, msg := wac.SendMessageWithPresence(to, message)
	return successResult(success, msg), nil
}

func cmdSendFile(args []string, wac *WhatsAppClient) (any, error) {
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
	return successResult(success, msg), nil
}

func cmdSendAudio(args []string, wac *WhatsAppClient) (any, error) {
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
	return successResult(success, msg), nil
}

func cmdDownloadMedia(args []string, wac *WhatsAppClient) (any, error) {
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
		return map[string]any{"success": false, "message": err.Error()}, nil
	}
	return map[string]any{"success": true, "file_path": path, "message": "Media downloaded"}, nil
}

func cmdSendReaction(args []string, wac *WhatsAppClient) (any, error) {
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
	return successResult(success, msg), nil
}

func cmdRevokeMessage(args []string, wac *WhatsAppClient) (any, error) {
	var messageID, to string
	fs := flag.NewFlagSet("revoke-message", flag.ContinueOnError)
	fs.StringVar(&messageID, "message-id", "", "Message ID to revoke")
	fs.StringVar(&to, "to", "", "Chat")
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	if messageID == "" || to == "" {
		return nil, fmt.Errorf("--message-id and --to are required")
	}
	success, msg := wac.RevokeMessage(messageID, to)
	return successResult(success, msg), nil
}

func cmdCreateGroup(args []string, wac *WhatsAppClient) (any, error) {
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
	return map[string]any{"success": success, "group_name": groupName, "message": msg}, nil
}

func cmdLeaveGroup(args []string, wac *WhatsAppClient) (any, error) {
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
	return successResult(success, msg), nil
}

func cmdListGroups(args []string, wac *WhatsAppClient) (any, error) {
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
	return map[string]any{"groups": groups}, nil
}

func cmdUpdateGroupParticipants(args []string, wac *WhatsAppClient) (any, error) {
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
	return successResult(success, msg), nil
}

func cmdBackfill(args []string, wac *WhatsAppClient) (any, error) {
	var to string
	var count int
	fs := flag.NewFlagSet("backfill", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Chat to backfill")
	fs.IntVar(&count, "count", 50, "Number of messages")
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	if to == "" {
		return nil, fmt.Errorf("--to is required")
	}
	success, msg := wac.RequestBackfill(to, count)
	return successResult(success, msg), nil
}

func cmdRenameGroup(args []string, wac *WhatsAppClient) (any, error) {
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
	return successResult(success, msg), nil
}

func cmdSetGroupPhoto(args []string, wac *WhatsAppClient) (any, error) {
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
	return successResult(success, msg), nil
}

func cmdSetGroupDescription(args []string, wac *WhatsAppClient) (any, error) {
	var group, description string
	fs := flag.NewFlagSet("set-group-description", flag.ContinueOnError)
	fs.StringVar(&group, "group", "", "Group name or JID")
	fs.StringVar(&description, "description", "", "New group description")
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	if group == "" || description == "" {
		return nil, fmt.Errorf("--group and --description are required")
	}
	success, msg := wac.SetGroupDescription(group, description)
	return successResult(success, msg), nil
}

func cmdGetGroupInviteLink(args []string, wac *WhatsAppClient) (any, error) {
	var group string
	fs := flag.NewFlagSet("get-group-invite-link", flag.ContinueOnError)
	fs.StringVar(&group, "group", "", "Group name or JID")
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	if group == "" {
		return nil, fmt.Errorf("--group is required")
	}
	success, link, msg := wac.GetGroupInviteLink(group)
	return map[string]any{"success": success, "link": link, "message": msg}, nil
}

func cmdCheckDelivery(args []string, wac *WhatsAppClient) (any, error) {
	var messageID, to string
	var limit int
	var recent bool
	fs := flag.NewFlagSet("check-delivery", flag.ContinueOnError)
	fs.StringVar(&messageID, "message-id", "", "Message ID to check")
	fs.StringVar(&to, "to", "", "Chat filter")
	fs.IntVar(&limit, "limit", 10, "Recent messages to show")
	fs.BoolVar(&recent, "recent", false, "Show recent outgoing statuses")
	if err := fs.Parse(args); err != nil {
		return nil, err
	}

	var chatJID string
	if to != "" {
		jid, err := wac.ResolveRecipient(to)
		if err != nil {
			return nil, fmt.Errorf("failed to resolve chat: %v", err)
		}
		chatJID = jid.String()
	}

	if recent || messageID == "" {
		results, err := wac.store.GetRecentOutgoingStatus(chatJID, limit)
		if err != nil {
			return nil, err
		}
		return map[string]any{"messages": results}, nil
	}

	status, ts, err := wac.store.GetDeliveryStatus(messageID, chatJID)
	if err != nil {
		return nil, fmt.Errorf("message not found: %v", err)
	}
	result := map[string]any{
		"message_id":      messageID,
		"delivery_status": status,
	}
	if ts != nil {
		result["delivery_timestamp"] = ts.Format(time.RFC3339)
	}
	return result, nil
}

func cmdPairPhone(args []string, wac *WhatsAppClient) (any, error) {
	var phone string
	fs := flag.NewFlagSet("pair-phone", flag.ContinueOnError)
	fs.StringVar(&phone, "phone", "", "Phone number (E.164 format)")
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
	return map[string]any{
		"pairing_code": code,
		"phone":        phone,
		"instructions": "Enter this code in WhatsApp > Linked Devices > Link a Device > Link with phone number",
	}, nil
}

func cmdListReceivedContacts(args []string, wac *WhatsAppClient) (any, error) {
	var to string
	var limit int
	fs := flag.NewFlagSet("list-received-contacts", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Filter by chat")
	fs.IntVar(&limit, "limit", 50, "Max results")
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	var chatJID string
	if to != "" {
		jid, err := wac.ResolveRecipient(to)
		if err != nil {
			return nil, fmt.Errorf("failed to resolve chat: %v", err)
		}
		chatJID = jid.String()
	}
	messages, err := wac.store.ListMessages(nil, nil, "", chatJID, "[Contact:", limit, 0)
	if err != nil {
		return nil, err
	}
	return map[string]any{"contacts": messages}, nil
}

func cmdArchiveChat(args []string, wac *WhatsAppClient) (any, error) {
	var to string
	fs := flag.NewFlagSet("archive-chat", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Chat to archive (contact name, phone, group, or JID)")
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	if to == "" && len(fs.Args()) > 0 {
		to = fs.Args()[0]
	}
	if to == "" {
		return nil, fmt.Errorf("--to is required (contact name, phone number, group name, or JID)")
	}
	success, msg := wac.ArchiveChat(to)
	return successResult(success, msg), nil
}

func cmdArchiveAllChats(wac *WhatsAppClient) (any, error) {
	archived, errs, err := wac.ArchiveAllChats()
	if err != nil {
		return nil, err
	}
	result := map[string]any{"archived": archived}
	if len(errs) > 0 {
		result["errors"] = errs
	}
	return result, nil
}

func cmdDeleteChat(args []string, wac *WhatsAppClient) (any, error) {
	var to string
	fs := flag.NewFlagSet("delete-chat", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Chat to delete")
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	if to == "" && len(fs.Args()) > 0 {
		to = fs.Args()[0]
	}
	if to == "" {
		return nil, fmt.Errorf("--to is required (contact name, phone number, group name, or JID)")
	}
	success, msg := wac.DeleteChat(to)
	return successResult(success, msg), nil
}

func cmdClearAllChats(wac *WhatsAppClient) (any, error) {
	jids, err := wac.store.ListAllChatJIDs()
	if err != nil {
		return nil, fmt.Errorf("failed to list chats: %v", err)
	}
	var deleted, failed int
	var errs []string
	for _, jid := range jids {
		ok, msg := wac.DeleteChat(jid)
		if ok {
			deleted++
		} else {
			failed++
			errs = append(errs, fmt.Sprintf("%s: %s", jid, msg))
		}
	}
	result := map[string]any{
		"deleted": deleted,
		"failed":  failed,
		"total":   len(jids),
	}
	if len(errs) > 0 {
		result["errors"] = errs
	}
	return result, nil
}
