package main

import (
	"fmt"
	"os"
	"strings"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "Usage: telegram <command> [args] [flags]")
		fmt.Fprintln(os.Stderr, "Commands (short aliases in parentheses):")
		fmt.Fprintln(os.Stderr, "  send-message (send) [to] [message]   send-file (file) [to] [path]")
		fmt.Fprintln(os.Stderr, "  list-messages (messages) [to]        send-reaction (react) [to] [id] [emoji]")
		fmt.Fprintln(os.Stderr, "  list-chats (chats)                   list-contacts (contacts)")
		fmt.Fprintln(os.Stderr, "  list-groups (groups)                 add-contact [name] [chat-id]")
		fmt.Fprintln(os.Stderr, "  remove-contact [identifier]")
		fmt.Fprintln(os.Stderr, "  serve  authenticate")
		os.Exit(1)
	}

	command := os.Args[1]
	os.Args = append(os.Args[:1], os.Args[2:]...)

	aliases := map[string]string{
		"send":     "send-message",
		"messages": "list-messages",
		"chats":    "list-chats",
		"contacts": "list-contacts",
		"groups":   "list-groups",
		"file":     "send-file",
		"react":    "send-reaction",
	}
	if canon, ok := aliases[command]; ok {
		command = canon
	}

	for i := range os.Args {
		os.Args[i] = strings.ReplaceAll(os.Args[i], `\!`, `!`)
	}

	positionalSpecs := map[string][]string{
		"send-message":   {"to", "message"},
		"list-messages":  {"to"},
		"send-file":      {"to", "file-path"},
		"send-reaction":  {"to", "message-id", "emoji"},
		"add-contact":    {"name", "chat-id"},
		"remove-contact": {"identifier"},
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

	switch command {
	case "serve":
		runServe()
	case "authenticate":
		runAuthenticate()
	default:
		runOneShot(command)
	}
}
