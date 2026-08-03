package main

import (
	"fmt"
	"os"
)

// runProvision is the managed-WhatsApp arm of `whatsapp connect` for a hosted
// (vesta.run) box (runConnect dispatches here when the box can reach a pool). It
// mirrors runLink: cold-start the daemon (ensureDaemon waits for the socket
// through the first-boot recompile), then dispatch the synchronous `provision`
// command, which runs the whole claim -> pair -> link handshake in the daemon and
// returns a terminal {status:"linked", number, next} (or {status:"provisioning"} /
// {status:"blocked"}). No daemon management, no readiness polling, no code
// shuttling. Idempotent, so re-running is always safe.
func runProvision(source, opener, directURL, directKey string) {
	if err := ensureDaemon(linkServeArgs()); err != nil {
		failJSON("%s", err.Error())
	}
	args := []string{}
	// Thread the resolved source so the daemon pins its pairing auth to the agent's
	// explicit choice, not its boot-time env: `cloud` forces the server-identity
	// token even on a warm daemon that also carries direct pool creds.
	if source != "" {
		args = append(args, "--source", source)
	}
	// A daemon may already be warm from boot before Double Tick credentials are
	// configured. Carry the direct pair over its private Unix socket so this one
	// connect call can switch the daemon to the requested source without a restart.
	// These become fields in an in-process SocketRequest, not operating-system argv.
	if directURL != "" && directKey != "" {
		args = append(args, "--direct-url", directURL, "--direct-key", directKey)
	}
	if opener != "" {
		args = append(args, "--opener", opener)
	}
	output, exitCode, connected := trySocketCommand(getSocketPath(), "provision", args)
	if !connected {
		failJSON("daemon not answering after start; check 'whatsapp daemon status'")
	}
	fmt.Println(string(output))
	os.Exit(exitCode)
}
