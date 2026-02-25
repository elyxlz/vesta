package main

import (
	"fmt"
	"os"
	"path/filepath"

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
		fmt.Fprintln(os.Stderr, "Usage: whatsapp <command> [flags]")
		fmt.Fprintln(os.Stderr, "Commands: serve, authenticate, search-contacts, list-contacts, add-contact,")
		fmt.Fprintln(os.Stderr, "  remove-contact, list-messages, list-chats, send-message, send-file,")
		fmt.Fprintln(os.Stderr, "  download-media, send-reaction, create-group, leave-group, list-groups,")
		fmt.Fprintln(os.Stderr, "  update-group-participants")
		os.Exit(1)
	}

	command := os.Args[1]
	// Remove the subcommand from os.Args so flag parsing works on remaining args
	os.Args = append(os.Args[:1], os.Args[2:]...)

	logger := waLog.Stdout("WhatsApp", "WARN", true)

	switch command {
	case "serve":
		runServe(logger)
	case "authenticate":
		runAuthenticate()
	default:
		runOneShot(command, logger)
	}
}
