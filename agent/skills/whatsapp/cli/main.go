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

// printUsage lists every command in the registry, so a command cannot ship without appearing here.
func printUsage(w io.Writer) {
	fmt.Fprintln(w, "Usage: whatsapp <command> [args] [flags]")
	// The lifecycle commands run in the client, not the daemon, so they are not in the registry.
	fmt.Fprintln(w, "Lifecycle:")
	fmt.Fprintln(w, "  daemon <start|stop|restart|status>   manage the background daemon")
	fmt.Fprintln(w, "  link [--phone +E.164]                link a WhatsApp account (QR page, or pairing code with --phone)")
	fmt.Fprintln(w, "  serve                                run the daemon in the foreground")
	fmt.Fprintln(w, "  authenticate                         print auth status")
	fmt.Fprintln(w, "Commands (short aliases in parentheses; `whatsapp <command> --help` for its flags):")
	for _, cmd := range commands {
		if cmd.hidden {
			continue
		}
		fmt.Fprintln(w, "  "+commandSignature(cmd))
	}
}

// printCommandUsage answers `whatsapp <command> --help` from the command's own flags. Every
// handler declares its FlagSet and parses before it touches the client, so passing no client
// reports the flags without a daemon, without the socket, and without reaching any command body.
func printCommandUsage(w io.Writer, name string) {
	cmd, ok := lookupCommand(name)
	if !ok {
		// A lifecycle command (serve, link, daemon, authenticate): the general usage documents it.
		printUsage(w)
		return
	}
	_, err := cmd.run([]string{"--help"}, nil)
	fmt.Fprintln(w, err)
}

// commandSignature renders one registry entry as `name (alias) <positional>`.
func commandSignature(cmd command) string {
	var sig strings.Builder
	sig.WriteString(cmd.name)
	if len(cmd.aliases) > 0 {
		sig.WriteString(" (" + strings.Join(cmd.aliases, ", ") + ")")
	}
	for _, positional := range cmd.positionals {
		sig.WriteString(" <" + positional + ">")
	}
	return sig.String()
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

	// Answer it here so no daemon, no socket, and no command body is involved, which is what keeps
	// `clear-all-chats --help` from running clear-all-chats. Only the first argument is read as
	// help, so `send <to> -h` still sends the text `-h`.
	if len(os.Args) > 1 && isHelpArg(os.Args[1]) {
		printCommandUsage(os.Stdout, command)
		os.Exit(0)
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
	case "daemon":
		runDaemon()
	case "link":
		runLink()
	default:
		runOneShot(command)
	}
}
