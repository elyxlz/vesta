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
	// A cold-cache daemon start compiles the CLI first, which can take minutes;
	// a warm start reuses the cached binary and answers on the socket in seconds.
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

func runDaemon() {
	if len(os.Args) < 2 {
		failJSON("usage: whatsapp daemon <start|stop|restart|status> [--force] [serve flags]")
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
		failJSON("unknown daemon subcommand %q (use start|stop|restart|status)", sub)
	}
}

// startDaemonProcess launches `whatsapp serve` under screen (via the launcher
// on PATH so the cached-build check still applies) and waits for the socket.
// Idempotent: an already-answering daemon is a no-op.
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
		failJSON("%s", err.Error())
	}
	printJSON(map[string]any{"status": "started", "session": sessionName()})
}

func daemonStop() {
	dataDir := stateDataDir()
	if !daemonAlive(getSocketPath()) {
		printJSON(map[string]any{"status": "already_stopped", "session": sessionName()})
		return
	}
	if msg := stopRefusal(syncWindowRemaining(loadStateFromDisk(dataDir).LinkedAt, time.Now()), hasBareFlag("force")); msg != "" {
		failJSON("%s", msg)
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
		failJSON("screen quit failed: %v", err)
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
	failJSON("daemon still answering after screen quit; do NOT send signals. Inspect with 'screen -r %s'", sessionName())
}

func daemonRestart() {
	dataDir := stateDataDir()
	st := loadStateFromDisk(dataDir)
	recorded := !st.StartedAt.IsZero()
	running := daemonAlive(getSocketPath())
	if !recorded && running {
		// LEGACY(remove-when: fleet daemons have all restarted once under the lifecycle commands): pre-lifecycle daemons recorded no serve args, so a faithful restart is impossible.
		failJSON("running daemon recorded no serve args (started before the lifecycle commands): stop it and start it explicitly with the right flags: whatsapp daemon stop, then whatsapp daemon start [flags]")
	}
	serveArgs, note := restartServeArgs(st.Args, recorded)
	if running {
		daemonStop()
	}
	if err := startDaemonProcess(serveArgs); err != nil {
		failJSON("%s", err.Error())
	}
	result := map[string]any{"status": "restarted", "session": sessionName(), "serve_args": serveArgs}
	if note != "" {
		result["note"] = note
	}
	printJSON(result)
}

// restartServeArgs picks the flags a restart brings the daemon back with: the
// last run's flags recorded in state.json (which survives stops and crashes, so
// e.g. --read-only is never silently dropped), falling back to the instance flag
// alone when no run was ever recorded.
func restartServeArgs(recordedArgs []string, recorded bool) (serveArgs []string, note string) {
	if !recorded {
		return linkServeArgs(), "daemon was not running and recorded no serve args; started fresh with instance args only"
	}
	return recordedArgs, ""
}

func daemonStatus() {
	dataDir := stateDataDir()
	now := time.Now()
	st := loadStateFromDisk(dataDir)
	result := map[string]any{
		"running":                  daemonAlive(getSocketPath()),
		"session":                  sessionName(),
		"auth":                     authStatusMap(st, dataDir),
		"sync_window_seconds_left": int(syncWindowRemaining(st.LinkedAt, now).Seconds()),
		"pair_attempts_last_hour":  pairAttemptsInWindow(st.PairAttempts, now),
		"pair_attempts_last_day":   len(attemptsWithin(st.PairAttempts, now, PairDayWindow)),
		"pair_attempts_last_7d":    len(attemptsWithin(st.PairAttempts, now, PairWeekWindow)),
	}
	if output, exitCode, connected := trySocketCommand(getSocketPath(), "daemon-status", nil); connected && exitCode == 0 {
		var connState any
		if err := json.Unmarshal(output, &connState); err == nil {
			result["connection"] = connState
		}
	}
	printJSON(result)
}
