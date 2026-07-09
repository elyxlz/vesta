package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"time"
)

const (
	// A cold-cache daemon start compiles the CLI and pulls whatsmeow first,
	// which can take minutes; a warm start answers on the socket in seconds.
	DaemonStartTimeout = 5 * time.Minute
	DaemonStopTimeout  = 15 * time.Second
	DaemonPollInterval = time.Second
)

func sessionName() string {
	if instance := extractInstance(); instance != "" {
		return "whatsapp-" + instance
	}
	return "whatsapp"
}

func daemonAlive(sockPath string) bool {
	conn, err := net.DialTimeout("unix", sockPath, SocketDialTimeout)
	if err != nil {
		return false
	}
	conn.Close()
	return true
}

// screenOutputHasLiveSession reports whether `screen -ls` output contains a
// LIVE session with exactly this name (a "(Dead ???)" corpse does not count,
// and `whatsapp` must not match `whatsapp-personal`).
func screenOutputHasLiveSession(screenLs, name string) bool {
	sessionPattern := regexp.MustCompile(`[0-9]+\.` + regexp.QuoteMeta(name) + `\s`)
	for _, line := range strings.Split(screenLs, "\n") {
		if sessionPattern.MatchString(line) && !strings.Contains(line, "Dead") {
			return true
		}
	}
	return false
}

func screenSessionLive(name string) bool {
	// screen -ls exits nonzero when no sessions exist; only the output matters.
	output, _ := exec.Command("screen", "-ls").CombinedOutput()
	return screenOutputHasLiveSession(string(output), name)
}

// stopRefusal returns a non-empty refusal message when stopping now would
// break the fragile post-link sync window.
func stopRefusal(remaining time.Duration, force bool) string {
	if remaining <= 0 || force {
		return ""
	}
	return fmt.Sprintf(
		"refusing to stop the daemon: history sync is still settling after linking (%s left). Restarting in this window logs the device out and forces a re-pair. Wait it out, or pass --force only if the user explicitly accepts a re-pair",
		remaining.Round(time.Second))
}

func hasBareFlag(name string) bool {
	for _, arg := range os.Args {
		if arg == "--"+name {
			return true
		}
	}
	return false
}

func runDaemon() {
	if len(os.Args) < 2 {
		printJSON(map[string]any{"error": "usage: whatsapp daemon <start|stop|restart|status> [--force] [serve flags]"})
		os.Exit(1)
	}
	sub := os.Args[1]
	os.Args = append(os.Args[:1], os.Args[2:]...)
	switch sub {
	case "start":
		daemonStart(os.Args[1:])
	case "stop":
		daemonStop()
	case "restart":
		daemonRestart()
	case "status":
		daemonStatus()
	default:
		printJSON(map[string]any{"error": fmt.Sprintf("unknown daemon subcommand %q (use start|stop|restart|status)", sub)})
		os.Exit(1)
	}
}

// startDaemonProcess launches `whatsapp serve` under screen (via the launcher
// on PATH so the on-invocation compile and whatsmeow float still apply) and
// waits for the socket. Idempotent: an already-answering daemon is a no-op.
func startDaemonProcess(serveArgs []string) error {
	sockPath := getSocketPath()
	if daemonAlive(sockPath) {
		return nil
	}
	launcher, err := exec.LookPath("whatsapp")
	if err != nil {
		return fmt.Errorf("whatsapp launcher not on PATH; run ~/agent/skills/whatsapp/setup.sh first")
	}
	screenArgs := append([]string{"-dmS", sessionName(), launcher, "serve"}, serveArgs...)
	if err := exec.Command("screen", screenArgs...).Run(); err != nil {
		return fmt.Errorf("failed to launch screen session: %v", err)
	}
	deadline := time.Now().Add(DaemonStartTimeout)
	for time.Now().Before(deadline) {
		if daemonAlive(sockPath) {
			return nil
		}
		if !screenSessionLive(sessionName()) {
			return fmt.Errorf("daemon exited during startup; run 'whatsapp serve' in the foreground to see the error")
		}
		time.Sleep(DaemonPollInterval)
	}
	return fmt.Errorf("daemon did not answer on %s within %s", sockPath, DaemonStartTimeout)
}

func daemonStart(serveArgs []string) {
	if daemonAlive(getSocketPath()) {
		printJSON(map[string]any{"status": "already_running", "session": sessionName()})
		return
	}
	if err := startDaemonProcess(serveArgs); err != nil {
		printJSON(map[string]any{"error": err.Error()})
		os.Exit(1)
	}
	printJSON(map[string]any{"status": "started", "session": sessionName()})
}

func daemonStop() {
	dataDir := stateDataDir()
	if !daemonAlive(getSocketPath()) {
		printJSON(map[string]any{"status": "already_stopped", "session": sessionName()})
		return
	}
	if msg := stopRefusal(syncWindowRemaining(dataDir, time.Now()), hasBareFlag("force")); msg != "" {
		printJSON(map[string]any{"error": msg})
		os.Exit(1)
	}
	// Mark the stop intentional so serve's shutdown skips the daemon_died
	// notification the agent would otherwise investigate.
	if err := os.WriteFile(stopRequestedPath(dataDir), []byte{}, 0644); err != nil {
		fmt.Fprintf(os.Stderr, "warning: could not mark stop as intentional: %v\n", err)
	}
	if err := exec.Command("screen", "-S", sessionName(), "-X", "quit").Run(); err != nil {
		// The daemon never got the quit, so remove the marker: leaving it behind
		// would suppress the death notification of a later genuine crash.
		os.Remove(stopRequestedPath(dataDir))
		printJSON(map[string]any{"error": fmt.Sprintf("screen quit failed: %v", err)})
		os.Exit(1)
	}
	deadline := time.Now().Add(DaemonStopTimeout)
	for time.Now().Before(deadline) {
		if !daemonAlive(getSocketPath()) {
			printJSON(map[string]any{"status": "stopped", "session": sessionName()})
			return
		}
		time.Sleep(DaemonPollInterval)
	}
	// The daemon never consumed the marker (it's still answering), so remove
	// it: leaving it behind would suppress the death notification of a later
	// genuine crash.
	os.Remove(stopRequestedPath(dataDir))
	printJSON(map[string]any{"error": "daemon still answering after screen quit; do NOT send signals — inspect with 'screen -r " + sessionName() + "'"})
	os.Exit(1)
}

func daemonRestart() {
	dataDir := stateDataDir()
	info, err := readDaemonInfo(dataDir)
	running := daemonAlive(getSocketPath())
	if err != nil && running {
		// LEGACY(remove-when: fleet daemons have all restarted once under the lifecycle commands): pre-lifecycle daemons have no daemon-info.json, so a faithful restart is impossible.
		printJSON(map[string]any{"error": "running daemon has no daemon-info.json (started before the lifecycle commands): stop it and start it explicitly with the right flags: whatsapp daemon stop, then whatsapp daemon start [flags]"})
		os.Exit(1)
	}
	if !running {
		serveArgs := linkServeArgs()
		if err := startDaemonProcess(serveArgs); err != nil {
			printJSON(map[string]any{"error": err.Error()})
			os.Exit(1)
		}
		printJSON(map[string]any{"status": "restarted", "session": sessionName(), "serve_args": serveArgs, "note": "daemon was not running; started fresh with instance args only"})
		return
	}
	serveArgs := info.Args
	daemonStop()
	if err := startDaemonProcess(serveArgs); err != nil {
		printJSON(map[string]any{"error": err.Error()})
		os.Exit(1)
	}
	printJSON(map[string]any{"status": "restarted", "session": sessionName(), "serve_args": serveArgs})
}

func daemonStatus() {
	dataDir := stateDataDir()
	now := time.Now()
	result := map[string]any{
		"running":                  daemonAlive(getSocketPath()),
		"session":                  sessionName(),
		"auth":                     readAuthStatus(dataDir),
		"sync_window_seconds_left": int(syncWindowRemaining(dataDir, now).Seconds()),
		"pair_attempts_last_hour":  pairAttemptsInWindow(dataDir, now),
	}
	if output, exitCode, connected := trySocketCommand(getSocketPath(), "daemon-status", nil); connected && exitCode == 0 {
		var connState any
		if err := json.Unmarshal(output, &connState); err == nil {
			result["connection"] = connState
		}
	}
	printJSON(result)
}
