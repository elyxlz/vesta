package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	waLog "go.mau.fi/whatsmeow/util/log"
)

func isHelpArg(arg string) bool {
	return arg == "--help" || arg == "-h" || arg == "help"
}

func printUsage(w io.Writer) {
	fmt.Fprintln(w, "Usage: whatsapp <command> [args] [flags]")
	fmt.Fprintln(w, "Lifecycle:")
	fmt.Fprintln(w, "  daemon <start|stop|restart|status>   manage the background daemon")
	fmt.Fprintln(w, "  link [--phone +E.164]                link a WhatsApp account (QR page, or pairing code with --phone)")
	fmt.Fprintln(w, "  serve                                run the daemon in the foreground")
	fmt.Fprintln(w, "  authenticate                         print auth status")
	fmt.Fprintln(w, "Commands (short aliases in parentheses):")
	fmt.Fprintln(w, "  send-message (send) [to] [message]   send-file (file) [to] [path]")
	fmt.Fprintln(w, "  list-messages (messages) [to]        send-reaction (react) [to] [id] [emoji]")
	fmt.Fprintln(w, "  list-chats (chats)                   list-contacts (contacts)")
	fmt.Fprintln(w, "  list-groups (groups)                 add-contact [name] [phone]")
	fmt.Fprintln(w, "  remove-contact [identifier]          leave-group [group]")
	fmt.Fprintln(w, "  backfill [to]                        rename-group (rename) [group] [name]")
	fmt.Fprintln(w, "  check-delivery (delivery) [msg-id]   download-media [msg-id]")
	fmt.Fprintln(w, "  delete-chat [to]                     archive-chat [to]")
	fmt.Fprintln(w, "  clear-all-chats                      update-group-participants")
	fmt.Fprintln(w, "  serve  authenticate  create-group    search-contacts")
	fmt.Fprintln(w, "  update-group-participants            set-group-description [group] [desc]")
}

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
	if len(os.Args) < 2 || isHelpArg(os.Args[1]) {
		printUsage(os.Stdout)
		os.Exit(0)
	}

	command := os.Args[1]
	// Remove the subcommand from os.Args so flag parsing works on remaining args
	os.Args = append(os.Args[:1], os.Args[2:]...)

	// The bash execution environment escapes special chars — undo in all args
	for i := range os.Args {
		os.Args[i] = shellEscapeReplacer.Replace(os.Args[i])
	}

	// Resolve the alias to its canonical name and rewrite the command's leading
	// positional args into flags, both driven by the command registry.
	if cmd, ok := lookupCommand(command); ok {
		command = cmd.name
		remaining := os.Args[1:]
		var positionals []string
		i := 0
		for i < len(remaining) && i < len(cmd.positionals) && !strings.HasPrefix(remaining[i], "-") {
			positionals = append(positionals, remaining[i])
			i++
		}
		if len(positionals) > 0 {
			var injected []string
			for j, val := range positionals {
				injected = append(injected, "--"+cmd.positionals[j], val)
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
