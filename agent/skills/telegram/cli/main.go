package main

import (
	"fmt"
	"io"
	"os"
	"strings"
)

func isHelpArg(arg string) bool {
	return arg == "--help" || arg == "-h" || arg == "help"
}

func printUsage(w io.Writer) {
	fmt.Fprintln(w, "Usage: telegram <command> [args] [flags]")
	fmt.Fprintln(w, "Lifecycle:")
	fmt.Fprintln(w, "  daemon <start|stop|restart|status>   manage the background daemon (idempotent start; stop/restart also handle the watchdog)")
	fmt.Fprintln(w, "  serve                                run the daemon in the foreground")
	fmt.Fprintln(w, "  authenticate                         save the bot token / print auth status")
	fmt.Fprintln(w, "Commands (short aliases in parentheses):")
	fmt.Fprintln(w, "  send-message (send) [to] [message]   send-file (file) [to] [path]")
	fmt.Fprintln(w, "    send-message flags: --buttons 'L1=d1,L2=d2;L3=d3'  --reply-to <id>  --message-file <path>")
	fmt.Fprintln(w, "  edit-message [to] [message-id] [message] (--buttons)  delete-message (del) [to] [message-id]")
	fmt.Fprintln(w, "  answer-callback [callback-id] (--text --alert)   send-voice [to] [file-path]")
	fmt.Fprintln(w, "  send-chat-action [to] [action]       pin-message [to] [message-id]   unpin-message [to] [message-id]")
	fmt.Fprintln(w, "  send-reaction (react) [to] [id] [emoji]")
	fmt.Fprintln(w, "  list-messages (messages) [to]        list-chats (chats)")
	fmt.Fprintln(w, "  list-contacts (contacts)             list-groups (groups)")
	fmt.Fprintln(w, "  add-contact [name] [chat-id]         remove-contact [identifier]")
}

func main() {
	if len(os.Args) < 2 || isHelpArg(os.Args[1]) {
		printUsage(os.Stdout)
		os.Exit(0)
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
		"edit":     "edit-message",
		"del":      "delete-message",
		"voice":    "send-voice",
		"action":   "send-chat-action",
		"pin":      "pin-message",
		"unpin":    "unpin-message",
	}
	if canon, ok := aliases[command]; ok {
		command = canon
	}

	for i := range os.Args {
		os.Args[i] = strings.ReplaceAll(os.Args[i], `\!`, `!`)
	}

	positionalSpecs := map[string][]string{
		"send-message":     {"to", "message"},
		"list-messages":    {"to"},
		"send-file":        {"to", "file-path"},
		"send-reaction":    {"to", "message-id", "emoji"},
		"edit-message":     {"to", "message-id", "message"},
		"delete-message":   {"to", "message-id"},
		"answer-callback":  {"callback-id"},
		"send-voice":       {"to", "file-path"},
		"send-chat-action": {"to", "action"},
		"pin-message":      {"to", "message-id"},
		"unpin-message":    {"to", "message-id"},
		"add-contact":      {"name", "chat-id"},
		"remove-contact":   {"identifier"},
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
	case "daemon":
		runDaemon()
	default:
		runOneShot(command)
	}
}
