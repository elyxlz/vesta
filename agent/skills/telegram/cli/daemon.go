package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const (
	DaemonStartTimeout = 30 * time.Second
	DaemonStopTimeout  = 15 * time.Second
	DaemonPollInterval = time.Second
	SocketDialTimeout  = 2 * time.Second

	daemonInfoFile  = "daemon-info.json"
	watchdogSession = "telegram-watchdog"
)

type daemonInfo struct {
	Args      []string  `json:"args"`
	PID       int       `json:"pid"`
	StartedAt time.Time `json:"started_at"`
}

func defaultNotificationsDir() string {
	return filepath.Join(os.Getenv("HOME"), "agent", "notifications")
}

func stopRequestedPath(dataDir string) string {
	return filepath.Join(dataDir, "stop-requested")
}

func sessionName() string {
	if instance := extractInstance(); instance != "" {
		return "telegram-" + instance
	}
	return "telegram"
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
// and `telegram` must not match `telegram-watchdog`).
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

func writeDaemonInfo(dataDir string, serveArgs []string) {
	info := daemonInfo{Args: serveArgs, PID: os.Getpid(), StartedAt: time.Now().UTC()}
	data, err := json.Marshal(info)
	if err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to marshal daemon info: %v\n", err)
		return
	}
	if err := os.WriteFile(filepath.Join(dataDir, daemonInfoFile), data, 0644); err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to write daemon info: %v\n", err)
	}
}

func readDaemonInfo(dataDir string) (daemonInfo, error) {
	var info daemonInfo
	data, err := os.ReadFile(filepath.Join(dataDir, daemonInfoFile))
	if err != nil {
		return info, err
	}
	if err := json.Unmarshal(data, &info); err != nil {
		return info, err
	}
	return info, nil
}

func runDaemon() {
	if len(os.Args) < 2 {
		printJSON(map[string]interface{}{"error": "usage: telegram daemon <start|stop|restart|status> [serve flags]"})
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
		printJSON(map[string]interface{}{"error": fmt.Sprintf("unknown daemon subcommand %q (use start|stop|restart|status)", sub)})
		os.Exit(1)
	}
}

// startDaemonProcess launches `telegram serve` under screen and waits for the
// socket. Idempotent: an already-answering daemon is a no-op.
func startDaemonProcess(serveArgs []string) error {
	sockPath := getSocketPath()
	if daemonAlive(sockPath) {
		return nil
	}
	binary, err := exec.LookPath("telegram")
	if err != nil {
		return fmt.Errorf("telegram binary not on PATH; build it per SETUP.md first")
	}
	screenArgs := append([]string{"-dmS", sessionName(), binary, "serve"}, serveArgs...)
	if err := exec.Command("screen", screenArgs...).Run(); err != nil {
		return fmt.Errorf("failed to launch screen session: %v", err)
	}
	deadline := time.Now().Add(DaemonStartTimeout)
	for time.Now().Before(deadline) {
		if daemonAlive(sockPath) {
			return nil
		}
		if !screenSessionLive(sessionName()) {
			return fmt.Errorf("daemon exited during startup; run 'telegram serve' in the foreground to see the error")
		}
		time.Sleep(DaemonPollInterval)
	}
	return fmt.Errorf("daemon did not answer on %s within %s", sockPath, DaemonStartTimeout)
}

func daemonStart(serveArgs []string) {
	if daemonAlive(getSocketPath()) {
		printJSON(map[string]interface{}{"status": "already_running", "session": sessionName()})
		return
	}
	if err := startDaemonProcess(serveArgs); err != nil {
		printJSON(map[string]interface{}{"error": err.Error()})
		os.Exit(1)
	}
	printJSON(map[string]interface{}{"status": "started", "session": sessionName()})
}

// stopWatchdogIfLive quits the watchdog screen session first so it cannot race
// the stop and respawn a second daemon (the documented two-daemons footgun).
// Returns whether the watchdog was running, so restart can bring it back.
func stopWatchdogIfLive() bool {
	if !screenSessionLive(watchdogSession) {
		return false
	}
	if err := exec.Command("screen", "-S", watchdogSession, "-X", "quit").Run(); err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to quit watchdog session: %v\n", err)
	}
	return true
}

func startWatchdog() {
	script := filepath.Join(os.Getenv("HOME"), "agent", "skills", "telegram", "telegram-watchdog.sh")
	if _, err := os.Stat(script); err != nil {
		return
	}
	if screenSessionLive(watchdogSession) {
		return
	}
	if err := exec.Command("screen", "-dmS", watchdogSession, "bash", script).Run(); err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to start watchdog session: %v\n", err)
	}
}

func stopDaemonProcess() error {
	dataDir, _ := parseStateDir()
	// Mark the stop intentional so serve's shutdown skips the daemon_died
	// notification the agent would otherwise investigate.
	if err := os.WriteFile(stopRequestedPath(dataDir), []byte{}, 0644); err != nil {
		fmt.Fprintf(os.Stderr, "warning: could not mark stop as intentional: %v\n", err)
	}
	if err := exec.Command("screen", "-S", sessionName(), "-X", "quit").Run(); err != nil {
		return fmt.Errorf("screen quit failed: %v", err)
	}
	deadline := time.Now().Add(DaemonStopTimeout)
	for time.Now().Before(deadline) {
		if !daemonAlive(getSocketPath()) {
			return nil
		}
		time.Sleep(DaemonPollInterval)
	}
	return fmt.Errorf("daemon still answering after screen quit; inspect with 'screen -r %s'", sessionName())
}

func daemonStop() {
	if !daemonAlive(getSocketPath()) {
		stopWatchdogIfLive()
		printJSON(map[string]interface{}{"status": "already_stopped", "session": sessionName()})
		return
	}
	watchdogWasLive := stopWatchdogIfLive()
	if err := stopDaemonProcess(); err != nil {
		printJSON(map[string]interface{}{"error": err.Error()})
		os.Exit(1)
	}
	printJSON(map[string]interface{}{"status": "stopped", "session": sessionName(), "watchdog_stopped": watchdogWasLive})
}

func daemonRestart() {
	dataDir, _ := parseStateDir()
	serveArgs := []string{}
	if info, err := readDaemonInfo(dataDir); err == nil {
		serveArgs = info.Args
	}
	watchdogWasLive := stopWatchdogIfLive()
	if daemonAlive(getSocketPath()) {
		if err := stopDaemonProcess(); err != nil {
			printJSON(map[string]interface{}{"error": err.Error()})
			os.Exit(1)
		}
	}
	if err := startDaemonProcess(serveArgs); err != nil {
		printJSON(map[string]interface{}{"error": err.Error()})
		os.Exit(1)
	}
	if watchdogWasLive {
		startWatchdog()
	}
	printJSON(map[string]interface{}{"status": "restarted", "session": sessionName(), "watchdog_restarted": watchdogWasLive, "serve_args": serveArgs})
}

func daemonStatus() {
	dataDir, _ := parseStateDir()
	result := map[string]interface{}{
		"running":          daemonAlive(getSocketPath()),
		"session":          sessionName(),
		"watchdog_running": screenSessionLive(watchdogSession),
		"auth":             readAuthStatus(dataDir),
	}
	if info, err := readDaemonInfo(dataDir); err == nil {
		result["started_at"] = info.StartedAt
		result["serve_args"] = info.Args
	}
	printJSON(result)
}
