package main

import (
	"encoding/json"
)

// runStatus is the agent's one WhatsApp health command. It ensures the
// background daemon is up (idempotent, the agent never manages it), reads the
// live connection, and prints a simple self-explanatory verdict:
//
//	linked:    {"linked":true,"number":"+44...","connected":true}
//	not linked:{"linked":false,"connected":false,"next":"run: whatsapp connect","reason":"..."}
func runStatus() {
	dataDir := stateDataDir()
	resolved, err := resolveDir(dataDir)
	if err != nil {
		failJSON("%s", err.Error())
	}
	if err := startDaemonProcess(linkServeArgs()); err != nil {
		printJSON(notLinkedStatus(resolved, err.Error()))
		return
	}
	output, exitCode, connected := trySocketCommand(getSocketPath(), "daemon-status", nil)
	if connected && exitCode == 0 {
		var live map[string]any
		if err := json.Unmarshal(output, &live); err == nil {
			printJSON(simpleStatus(live, resolved))
			return
		}
	}
	printJSON(notLinkedStatus(resolved, ""))
}

// simpleStatus reduces a daemon-status response to the agent-facing verdict.
func simpleStatus(live map[string]any, dataDir string) map[string]any {
	loggedIn, _ := live["logged_in"].(bool)
	if !loggedIn {
		return notLinkedStatus(dataDir, "")
	}
	connected, _ := live["connected"].(bool)
	result := map[string]any{"linked": true, "connected": connected}
	if number, ok := live["number"].(string); ok && number != "" {
		result["number"] = number
	}
	return result
}

// notLinkedStatus is the not-linked verdict, carrying the last logout/conflict
// reason (or a daemon-start error) so the agent sees why it is not linked.
func notLinkedStatus(dataDir, startErr string) map[string]any {
	result := map[string]any{
		"linked":    false,
		"connected": false,
		"next":      "run: whatsapp connect",
	}
	// A live daemon-start error is the real, current failure, so it wins over the
	// last-exit reason (which a successful connect clears anyway).
	if startErr != "" {
		result["reason"] = startErr
	} else if exit := loadStateFromDisk(dataDir); exit.ExitReason != "" {
		result["reason"] = exit.ExitReason
	}
	return result
}
