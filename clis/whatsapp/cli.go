package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
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
		qrText, err := os.ReadFile(filepath.Join(dataDir, "qr-code.txt"))
		if err == nil {
			status["qr_terminal"] = string(qrText)
		}
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
	wac.Disconnect()
}

func runOneShot(command string, logger waLog.Logger) {
	wac, _, _, _ := initClient(logger)
	defer wac.Disconnect()

	var result interface{}
	var err error

	switch command {
	case "search-contacts":
		var query string
		var limit int
		fs := flag.NewFlagSet("search-contacts", flag.ExitOnError)
		fs.StringVar(&query, "query", "", "Search query")
		fs.IntVar(&limit, "limit", 50, "Max results")
		fs.Parse(os.Args[1:])
		contacts, e := wac.store.SearchContacts(query, limit)
		if e != nil {
			err = e
		} else {
			result = map[string]interface{}{"contacts": contacts}
		}

	case "list-contacts":
		var query string
		var limit int
		fs := flag.NewFlagSet("list-contacts", flag.ExitOnError)
		fs.StringVar(&query, "query", "", "Optional search query")
		fs.IntVar(&limit, "limit", 50, "Max results")
		fs.Parse(os.Args[1:])
		contacts, e := wac.store.SearchContacts(query, limit)
		if e != nil {
			err = e
		} else {
			result = map[string]interface{}{"contacts": contacts}
		}

	case "add-contact":
		var name, phone string
		fs := flag.NewFlagSet("add-contact", flag.ExitOnError)
		fs.StringVar(&name, "name", "", "Contact name")
		fs.StringVar(&phone, "phone", "", "Phone number (E.164)")
		fs.Parse(os.Args[1:])
		if name == "" || phone == "" {
			fmt.Fprintln(os.Stderr, "Error: --name and --phone are required")
			os.Exit(1)
		}
		contact, e := wac.AddContact(name, phone)
		if e != nil {
			err = e
		} else {
			result = map[string]interface{}{"contact": contact}
		}

	case "remove-contact":
		var identifier string
		fs := flag.NewFlagSet("remove-contact", flag.ExitOnError)
		fs.StringVar(&identifier, "identifier", "", "Contact name or phone")
		fs.Parse(os.Args[1:])
		if identifier == "" {
			fmt.Fprintln(os.Stderr, "Error: --identifier is required")
			os.Exit(1)
		}
		if e := wac.store.DeleteManualContact(identifier); e != nil {
			err = e
		} else {
			result = map[string]interface{}{"success": true, "message": "Contact removed"}
		}

	case "list-messages":
		var to, after, before, senderPhone, query, sortBy string
		var limit, page, contextBefore, contextAfter int
		var includeContext bool
		fs := flag.NewFlagSet("list-messages", flag.ExitOnError)
		fs.StringVar(&to, "to", "", "Chat filter (contact name, phone, or group)")
		fs.StringVar(&after, "after", "", "ISO-8601 datetime")
		fs.StringVar(&before, "before", "", "ISO-8601 datetime")
		fs.StringVar(&senderPhone, "sender-phone", "", "Filter by sender")
		fs.StringVar(&query, "query", "", "Search query")
		fs.IntVar(&limit, "limit", 50, "Max results")
		fs.IntVar(&page, "page", 0, "Page number")
		fs.BoolVar(&includeContext, "include-context", false, "Include surrounding messages")
		fs.IntVar(&contextBefore, "context-before", 0, "Messages before")
		fs.IntVar(&contextAfter, "context-after", 0, "Messages after")
		_ = sortBy
		fs.Parse(os.Args[1:])

		var afterTime, beforeTime *time.Time
		if after != "" {
			t, _ := time.Parse(time.RFC3339, after)
			afterTime = &t
		}
		if before != "" {
			t, _ := time.Parse(time.RFC3339, before)
			beforeTime = &t
		}

		var chatJID string
		if to != "" {
			jid, e := wac.ResolveRecipient(to)
			if e != nil {
				err = fmt.Errorf("failed to resolve chat: %v", e)
				break
			}
			chatJID = jid.String()
		}

		messages, e := wac.store.ListMessages(
			afterTime, beforeTime,
			senderPhone, chatJID, query,
			limit, page*limit,
			includeContext,
			contextBefore, contextAfter,
		)
		if e != nil {
			err = e
		} else {
			result = map[string]interface{}{"messages": messages}
		}

	case "list-chats":
		var query, sortBy string
		var limit, page int
		var includeLastMessage bool
		fs := flag.NewFlagSet("list-chats", flag.ExitOnError)
		fs.StringVar(&query, "query", "", "Search query")
		fs.IntVar(&limit, "limit", 50, "Max results")
		fs.IntVar(&page, "page", 0, "Page number")
		fs.BoolVar(&includeLastMessage, "include-last-message", false, "Include last message")
		fs.StringVar(&sortBy, "sort-by", "last_active", "Sort by (last_active or name)")
		fs.Parse(os.Args[1:])

		chats, e := wac.store.ListChats(query, limit, page*limit, includeLastMessage, sortBy)
		if e != nil {
			err = e
		} else {
			result = map[string]interface{}{"chats": chats}
		}

	case "send-message":
		var to, message string
		fs := flag.NewFlagSet("send-message", flag.ExitOnError)
		fs.StringVar(&to, "to", "", "Recipient (name, phone, or group)")
		fs.StringVar(&message, "message", "", "Message text")
		fs.Parse(os.Args[1:])
		if to == "" || message == "" {
			fmt.Fprintln(os.Stderr, "Error: --to and --message are required")
			os.Exit(1)
		}
		success, msg := wac.SendMessageWithPresence(to, message)
		result = map[string]interface{}{"success": success, "message": msg}

	case "send-file":
		var to, filePath, caption string
		fs := flag.NewFlagSet("send-file", flag.ExitOnError)
		fs.StringVar(&to, "to", "", "Recipient")
		fs.StringVar(&filePath, "file-path", "", "Path to file")
		fs.StringVar(&caption, "caption", "", "Optional caption")
		fs.Parse(os.Args[1:])
		if to == "" || filePath == "" {
			fmt.Fprintln(os.Stderr, "Error: --to and --file-path are required")
			os.Exit(1)
		}
		success, msg := wac.SendFile(to, filePath, caption)
		result = map[string]interface{}{"success": success, "message": msg}

	case "download-media":
		var messageID, to, downloadPath string
		fs := flag.NewFlagSet("download-media", flag.ExitOnError)
		fs.StringVar(&messageID, "message-id", "", "Message ID")
		fs.StringVar(&to, "to", "", "Chat")
		fs.StringVar(&downloadPath, "download-path", "", "Save path")
		fs.Parse(os.Args[1:])
		if messageID == "" {
			fmt.Fprintln(os.Stderr, "Error: --message-id is required")
			os.Exit(1)
		}
		path, e := wac.DownloadMedia(messageID, to, downloadPath)
		if e != nil {
			result = map[string]interface{}{"success": false, "message": e.Error()}
		} else {
			result = map[string]interface{}{"success": true, "file_path": path, "message": "Media downloaded"}
		}

	case "send-reaction":
		var messageID, emoji, to string
		fs := flag.NewFlagSet("send-reaction", flag.ExitOnError)
		fs.StringVar(&messageID, "message-id", "", "Message ID")
		fs.StringVar(&emoji, "emoji", "", "Emoji")
		fs.StringVar(&to, "to", "", "Chat")
		fs.Parse(os.Args[1:])
		if messageID == "" || emoji == "" || to == "" {
			fmt.Fprintln(os.Stderr, "Error: --message-id, --emoji, and --to are required")
			os.Exit(1)
		}
		success, msg := wac.SendReaction(messageID, emoji, to)
		result = map[string]interface{}{"success": success, "message": msg}

	case "create-group":
		var groupName string
		fs := flag.NewFlagSet("create-group", flag.ExitOnError)
		fs.StringVar(&groupName, "name", "", "Group name")
		fs.Parse(os.Args[1:])
		participants := fs.Args()
		if groupName == "" || len(participants) == 0 {
			fmt.Fprintln(os.Stderr, "Error: --name and participant phone numbers are required")
			os.Exit(1)
		}
		success, msg := wac.CreateGroup(groupName, participants)
		result = map[string]interface{}{"success": success, "group_name": groupName, "message": msg}

	case "leave-group":
		var group string
		fs := flag.NewFlagSet("leave-group", flag.ExitOnError)
		fs.StringVar(&group, "group", "", "Group name")
		fs.Parse(os.Args[1:])
		if group == "" {
			fmt.Fprintln(os.Stderr, "Error: --group is required")
			os.Exit(1)
		}
		success, msg := wac.LeaveGroup(group)
		result = map[string]interface{}{"success": success, "message": msg}

	case "list-groups":
		var limit, page int
		fs := flag.NewFlagSet("list-groups", flag.ExitOnError)
		fs.IntVar(&limit, "limit", 50, "Max results")
		fs.IntVar(&page, "page", 0, "Page number")
		fs.Parse(os.Args[1:])
		groups, e := wac.store.ListGroups(limit, page*limit)
		if e != nil {
			err = e
		} else {
			result = map[string]interface{}{"groups": groups}
		}

	case "update-group-participants":
		var group, action string
		fs := flag.NewFlagSet("update-group-participants", flag.ExitOnError)
		fs.StringVar(&group, "group", "", "Group name")
		fs.StringVar(&action, "action", "", "add or remove")
		fs.Parse(os.Args[1:])
		participants := fs.Args()
		if group == "" || action == "" || len(participants) == 0 {
			fmt.Fprintln(os.Stderr, "Error: --group, --action, and participant phone numbers are required")
			os.Exit(1)
		}
		success, msg := wac.UpdateGroupParticipants(group, action, participants)
		result = map[string]interface{}{"success": success, "message": msg}

	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", command)
		os.Exit(1)
	}

	if err != nil {
		printJSON(map[string]interface{}{"error": err.Error()})
		os.Exit(1)
	}

	if result != nil {
		printJSON(result)
	}
}
