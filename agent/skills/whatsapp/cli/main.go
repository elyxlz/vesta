package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func isHelpArg(arg string) bool {
	return arg == "--help" || arg == "-h" || arg == "help"
}

func printUsage(w io.Writer) {
	fmt.Fprintln(w, "Usage: whatsapp <command> [args] [flags]")
	fmt.Fprintln(w, "Setup / health:")
	fmt.Fprintln(w, "  provision                            hosted box: claim + link the agent's own managed number (one blocking call)")
	fmt.Fprintln(w, "  start                                bring the daemon up (idempotent); the restart skill runs this at boot")
	fmt.Fprintln(w, "  status                               simple health check: linked, number, connected")
	fmt.Fprintln(w, "  link [--phone +E.164]                link a WhatsApp account (QR page, or pairing code with --phone)")
	fmt.Fprintln(w, "Internal (the CLI self-manages its daemon; agents never call these):")
	fmt.Fprintln(w, "  daemon <start|stop|restart|status>   manage the background daemon")
	fmt.Fprintln(w, "  serve                                run the daemon in the foreground")
	fmt.Fprintln(w, "  authenticate                         print auth status (alias of status, kept for back-compat)")
	fmt.Fprintln(w, "  update-deps                          bump the pinned whatsmeow to latest (do this deliberately, not mid-session)")
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

	switch command {
	case "serve":
		runServe()
	case "start":
		// Bring the daemon up and wait until it answers, so inbound notifications
		// are already flowing before the caller (the restart skill at boot, or the
		// agent) does anything else. Idempotent: an already-running daemon is a
		// no-op. Reuses the daemon-lifecycle start; any trailing serve flags
		// (e.g. --instance) pass through.
		daemonStart(os.Args[1:])
	case "status":
		runStatus()
	case "profile":
		runProfile()
	case "authenticate":
		runAuthenticate()
	case "daemon":
		runDaemon()
	case "link":
		runLink()
	case "provision":
		runProvision()
	default:
		runOneShot(command)
	}
}

// profileCommand maps a friendly `whatsapp profile <sub>` to the canonical
// set-profile-* socket command and the flag its value fills.
func profileCommand(sub string) (command string, flag string, ok bool) {
	switch sub {
	case "name":
		return "set-profile-name", "name", true
	case "photo":
		return "set-profile-photo", "file", true
	}
	return "", "", false
}

// runProfile is the friendly `whatsapp profile name <name>` /
// `whatsapp profile photo <file>` surface. It rewrites into the canonical
// set-profile-name / set-profile-photo socket command (both still usable
// directly), preserving any trailing flags like --instance.
func runProfile() {
	if len(os.Args) < 3 {
		failJSON("usage: whatsapp profile name <name> | whatsapp profile photo <file>")
	}
	command, flag, ok := profileCommand(os.Args[1])
	if !ok {
		failJSON("unknown profile subcommand %q (use: whatsapp profile name <name> | whatsapp profile photo <file>)", os.Args[1])
	}
	os.Args = append([]string{os.Args[0], "--" + flag, os.Args[2]}, os.Args[3:]...)
	runOneShot(command)
}
