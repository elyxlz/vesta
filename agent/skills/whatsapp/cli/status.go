package main

import (
	"encoding/json"
)

// runStatus is the agent's one WhatsApp health command. It requires the background
// daemon to be running (it never starts one), reads the live connection, and prints
// a simple self-explanatory verdict:
//
//	daemon down:{"running":false,"next":"start the daemon: whatsapp daemon start","reason":"..."}
//	linked:    {"linked":true,"number":"+44...","connected":true}
//	not linked:{"linked":false,"connected":false,"next":"run: whatsapp connect --source <vesta-cloud|doubletick|self-managed>","reason":"..."}
func runStatus() {
	dataDir := stateDataDir()
	resolved, err := resolveDir(dataDir)
	if err != nil {
		failJSON("%s", err.Error())
	}
	if requireDaemon() != nil {
		printJSON(daemonDownStatus(resolved))
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
	printJSON(notLinkedStatus(resolved))
}

// simpleStatus reduces a daemon-status response to the agent-facing verdict.
func simpleStatus(live map[string]any, dataDir string) map[string]any {
	loggedIn, _ := live["logged_in"].(bool)
	if !loggedIn {
		if pending, _ := live["phone_pairing_pending"].(bool); pending {
			return map[string]any{
				"linked":     false,
				"connecting": true,
				"method":     "phone",
				"next":       "wait for the user to enter the active pairing code; do not run connect again",
			}
		}
		linkPort, _ := live["link_port"].(float64)
		if live["auth_status"] == string(AuthStatusQRReady) || linkPort > 0 {
			return map[string]any{
				"linked":     false,
				"connecting": true,
				"method":     "qr",
				"next":       "wait for the user to scan the active QR page; do not run connect again",
			}
		}
		return notLinkedStatus(dataDir)
	}
	connected, _ := live["connected"].(bool)
	result := map[string]any{"linked": true, "connected": connected}
	if number, ok := live["number"].(string); ok && number != "" {
		result["number"] = number
	}
	return result
}

// daemonDownStatus is the verdict when no daemon answers: the recorded exit reason, so a daemon
// that died of a logout or a device conflict says so rather than reading as a plain stopped one,
// and the one command that brings it back.
func daemonDownStatus(dataDir string) map[string]any {
	result := map[string]any{
		"running": false,
		"next":    "start the daemon: whatsapp daemon start",
		"reason":  daemonDownMessage,
	}
	if reason := loadStateFromDisk(dataDir).ExitReason; reason != "" {
		result["reason"] = reason
	}
	return result
}

// clientOutdatedNext is the one recovery for a client version the server rejects: a
// restart or a re-link hits the same 405 until the pinned whatsmeow is bumped.
const clientOutdatedNext = "whatsapp update-deps, then whatsapp daemon restart"

// notLinkedStatus is the not-linked verdict, carrying the last logout/conflict
// reason so the agent sees why it is not linked. A 405 rejection is the exception:
// the device is still linked, so the verdict points at the dependency bump instead
// of a connect that would re-pair.
func notLinkedStatus(dataDir string) map[string]any {
	st := loadStateFromDisk(dataDir)
	if st.ExitStatus == exitClientOutdated {
		return map[string]any{"linked": true, "connected": false, "reason": st.ExitReason, "next": clientOutdatedNext}
	}
	result := map[string]any{
		"linked":    false,
		"connected": false,
		"next":      "run: whatsapp connect --source <vesta-cloud|doubletick|self-managed>",
	}
	if st.ExitReason != "" {
		result["reason"] = st.ExitReason
	}
	return result
}
