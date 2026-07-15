package main

import (
	"fmt"
	"os"
)

// runProvision is the one-command managed-WhatsApp setup for a hosted (vesta.run)
// box. It mirrors runLink: cold-start the daemon (startDaemonProcess waits for the
// socket through the first-boot recompile), then dispatch the synchronous
// `provision` command, which runs the whole claim -> pair -> link handshake in the
// daemon and returns a terminal {status:"linked", msisdn} or a clear error. The
// agent runs `whatsapp provision` and nothing else: no daemon management, no
// readiness polling, no code shuttling. Idempotent, so re-running is always safe.
func runProvision() {
	if err := startDaemonProcess(linkServeArgs()); err != nil {
		failJSON("%s", err.Error())
	}
	output, exitCode, connected := trySocketCommand(getSocketPath(), "provision", nil)
	if !connected {
		failJSON("daemon not answering after start; check 'whatsapp daemon status'")
	}
	fmt.Println(string(output))
	os.Exit(exitCode)
}
