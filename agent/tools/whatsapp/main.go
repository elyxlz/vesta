package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	waLog "go.mau.fi/whatsmeow/util/log"
)

var defaultStateDir = os.Getenv("HOME")

func resolveDir(path string) (string, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", fmt.Errorf("error resolving path: %v", err)
	}
	if err := os.MkdirAll(abs, 0755); err != nil {
		return "", fmt.Errorf("error creating directory %s: %v", abs, err)
	}
	return abs, nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "Usage: whatsapp <command> [args] [flags]")
		fmt.Fprintln(os.Stderr, "Commands (short aliases in parentheses):")
		fmt.Fprintln(os.Stderr, "  send-message (send) [to] [message]   send-file (file) [to] [path]")
		fmt.Fprintln(os.Stderr, "  list-messages (messages) [to]        send-reaction (react) [to] [id] [emoji]")
		fmt.Fprintln(os.Stderr, "  list-chats (chats)                   list-contacts (contacts)")
		fmt.Fprintln(os.Stderr, "  list-groups (groups)                 add-contact [name] [phone]")
		fmt.Fprintln(os.Stderr, "  remove-contact [identifier]          leave-group [group]")
		fmt.Fprintln(os.Stderr, "  backfill [to]                        rename-group (rename) [group] [name]")
		fmt.Fprintln(os.Stderr, "  serve  authenticate  download-media  create-group  search-contacts")
		fmt.Fprintln(os.Stderr, "  update-group-participants")
		os.Exit(1)
	}

	command := os.Args[1]
	// Remove the subcommand from os.Args so flag parsing works on remaining args
	os.Args = append(os.Args[:1], os.Args[2:]...)

	// Resolve short command aliases
	aliases := map[string]string{
		"send":     "send-message",
		"messages": "list-messages",
		"chats":    "list-chats",
		"contacts": "list-contacts",
		"groups":   "list-groups",
		"file":     "send-file",
		"react":    "send-reaction",
		"rename":          "rename-group",
		"search-contacts": "list-contacts",
	}
	if canon, ok := aliases[command]; ok {
		command = canon
	}

	// Rewrite leading positional args into flags
	positionalSpecs := map[string][]string{
		"send-message":   {"to", "message"},
		"list-messages":  {"to"},
		"send-file":      {"to", "file-path"},
		"send-reaction":  {"to", "message-id", "emoji"},
		"add-contact":    {"name", "phone"},
		"remove-contact": {"identifier"},
		"leave-group":    {"group"},
		"backfill":       {"to"},
		"rename-group":   {"group", "name"},
	}
	if spec, ok := positionalSpecs[command]; ok {
		remaining := os.Args[1:]
		var positionals []string
		i := 0
		for i < len(remaining) && i < len(spec) && !strings.HasPrefix(remaining[i], "-") {
			positionals = append(positionals, remaining[i])
			i++
		}
		if len(positionals) > 0 {
			var injected []string
			for j, val := range positionals {
				injected = append(injected, "--"+spec[j], val)
			}
			os.Args = append([]string{os.Args[0]}, append(injected, remaining[i:]...)...)
		}
	}

	logger := waLog.Stdout("WhatsApp", "WARN", true)

	switch command {
	case "serve":
		runServe(logger)
	case "authenticate":
		runAuthenticate()
	default:
		runOneShot(command)
	}
}
