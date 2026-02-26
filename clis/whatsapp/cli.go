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

func parseStateDir() (dataDir, logDir, notifDir string) {
	var stateDir string
	flag.StringVar(&stateDir, "state-dir", defaultStateDir, "State directory (default: ~/.vesta)")
	flag.Parse()

	dataDir = filepath.Join(stateDir, "data", "whatsapp")
	logDir = filepath.Join(stateDir, "logs", "whatsapp")
	notifDir = filepath.Join(stateDir, "notifications")
	return
}

func getSocketPath() string {
	stateDir := defaultStateDir
	for i, arg := range os.Args {
		if arg == "--state-dir" && i+1 < len(os.Args) {
			stateDir = os.Args[i+1]
			break
		}
		if strings.HasPrefix(arg, "--state-dir=") {
			stateDir = strings.TrimPrefix(arg, "--state-dir=")
			break
		}
	}
	return filepath.Join(stateDir, "data", "whatsapp", "whatsapp.sock")
}

func initClient(logger waLog.Logger) (*WhatsAppClient, string, string, string) {
	dataDir, logDir, notifDir := parseStateDir()

	var err error
	dataDir, err = resolveDir(dataDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	logDir, err = resolveDir(logDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	notifDir, err = resolveDir(notifDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	wac, err := NewWhatsAppClient(dataDir, notifDir, logger)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to initialize WhatsApp client: %v\n", err)
		os.Exit(1)
	}

	if err := wac.Connect(); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to connect: %v\n", err)
		os.Exit(1)
	}

	// Wait briefly for authentication to settle
	time.Sleep(2 * time.Second)

	return wac, dataDir, logDir, notifDir
}

func printJSON(v interface{}) {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "JSON encoding error: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(string(data))
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
	dataDir, _, _ := parseStateDir()
	var err error
	dataDir, err = resolveDir(dataDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	printJSON(readAuthStatus(dataDir))
}

func runServe(logger waLog.Logger) {
	dataDir, _, notifDir := parseStateDir()

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

	wac, err := NewWhatsAppClient(dataDir, notifDir, logger)
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

	fmt.Fprintf(os.Stderr, "WhatsApp client initialized. Data: %s\n", dataDir)
	fmt.Fprintf(os.Stderr, "Notifications: %s\n", notifDir)

	if !wac.IsAuthenticated() {
		fmt.Fprintln(os.Stderr, "Not authenticated. Use 'whatsapp authenticate' to get QR code.")
	}

	printJSON(map[string]string{"status": "serving"})

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	<-sigChan

	fmt.Fprintln(os.Stderr, "Shutting down...")
	if listener != nil {
		stopSocketServer(listener, sockPath)
	}
	wac.Disconnect()
}

func runOneShot(command string, logger waLog.Logger) {
	sockPath := getSocketPath()
	if output, exitCode, connected := trySocketCommand(sockPath, command, os.Args[1:]); connected {
		fmt.Println(string(output))
		os.Exit(exitCode)
	}

	wac, _, _, _ := initClient(logger)
	defer wac.Disconnect()

	result, err := executeCommand(command, os.Args[1:], wac)
	if err != nil {
		printJSON(map[string]interface{}{"error": err.Error()})
		os.Exit(1)
	}
	if result != nil {
		printJSON(result)
	}
}

func executeCommand(command string, args []string, wac *WhatsAppClient) (interface{}, error) {
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

	default:
		return nil, fmt.Errorf("unknown command: %s", command)
	}
}
