package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const (
	DaemonPollInterval = 500 * time.Millisecond
	// Both budgets are whole seconds in the environment, so a caller in a hurry can shorten
	// them. Readiness is generous because the socket only opens past the launcher's build
	// check, the whatsmeow update warning (20s), the store open, and a first connect that
	// retries for ConnectRetryAttempts seconds.
	DaemonReadyTimeoutEnv  = "DAEMON_READY_TIMEOUT_SECS"
	DaemonStopTimeoutEnv   = "DAEMON_STOP_TIMEOUT_SECS"
	DaemonReadyTimeout     = 120 * time.Second
	DaemonStopTimeout      = 15 * time.Second
	daemonRecordPerms      = 0644
	daemonDirPerms         = 0755
	daemonUsage            = "usage: whatsapp daemon <start|stop|restart|status> [--force] [serve flags]"
	whatsappLauncherInHome = "agent/skills/whatsapp/whatsapp"
)

// daemonName is this instance's name in every record: the bare skill name for the default
// instance, suffixed per named instance so two instances never share a pid record or a log.
func daemonName() string {
	if instance := extractInstance(); instance != "" {
		return "whatsapp-" + instance
	}
	return "whatsapp"
}

func daemonPidfile() string {
	return filepath.Join(os.Getenv("HOME"), "agent", "data", "daemons", daemonName()+".pid")
}

func daemonLifecycleLog() string {
	return filepath.Join(os.Getenv("HOME"), "agent", "logs", daemonName()+".log")
}

// whatsappLauncher is the skill's own launcher: a box's HOME is the checkout, and the
// launcher (never the cached binary) is what keeps a source change from serving stale code.
func whatsappLauncher() string {
	return filepath.Join(os.Getenv("HOME"), whatsappLauncherInHome)
}

// daemonBudget reads a lifecycle budget in whole seconds from the environment.
func daemonBudget(name string, fallback time.Duration) time.Duration {
	secs, err := strconv.Atoi(os.Getenv(name))
	if err != nil || secs <= 0 {
		return fallback
	}
	return time.Duration(secs) * time.Second
}

// livePid is the pid the last start recorded, when that process is still there.
func livePid() (int, bool) {
	record, err := os.ReadFile(daemonPidfile())
	if err != nil {
		return 0, false
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(record)))
	if err != nil || pid <= 0 {
		return 0, false
	}
	if err := syscall.Kill(pid, 0); err != nil {
		return 0, false
	}
	return pid, true
}

func daemonAlive(sockPath string) bool {
	conn, err := net.DialTimeout("unix", sockPath, SocketDialTimeout)
	if err != nil {
		return false
	}
	conn.Close()
	return true
}

// deathIsNews reports whether an exiting daemon owes the agent a notification. SIGTERM is
// what `whatsapp daemon stop` sends, so it is the one exit the agent asked for; every other
// way out is news.
func deathIsNews(sig os.Signal) bool {
	return sig != syscall.SIGTERM
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
	if len(os.Args) < 2 || isHelpArg(os.Args[1]) {
		fmt.Println(daemonUsage)
		return
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

// abandon ends a start that gave up, taking the child and its pid record with it: a daemon
// nothing can reach, with a record that says it is up, reads as running and turns every
// later start into a no-op.
func abandon(child *exec.Cmd, exited <-chan struct{}, message string) error {
	child.Process.Signal(syscall.SIGTERM)
	select {
	case <-exited:
	case <-time.After(daemonBudget(DaemonStopTimeoutEnv, DaemonStopTimeout)):
		child.Process.Kill()
		<-exited
	}
	os.Remove(daemonPidfile())
	return errors.New(message)
}

// startDaemonProcess launches `whatsapp serve` detached in its own session, records its pid,
// and waits for it to answer on the socket. Idempotent: an already-answering daemon is a no-op.
func startDaemonProcess(serveArgs []string) error {
	sockPath := getSocketPath()
	if daemonAlive(sockPath) {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(daemonPidfile()), daemonDirPerms); err != nil {
		return fmt.Errorf("could not create the daemon record directory: %v", err)
	}
	if err := os.MkdirAll(filepath.Dir(daemonLifecycleLog()), daemonDirPerms); err != nil {
		return fmt.Errorf("could not create the daemon log directory: %v", err)
	}
	logFile, err := os.OpenFile(daemonLifecycleLog(), os.O_CREATE|os.O_WRONLY|os.O_APPEND, daemonRecordPerms)
	if err != nil {
		return fmt.Errorf("could not open %s: %v", daemonLifecycleLog(), err)
	}
	defer logFile.Close()
	child := exec.Command(whatsappLauncher(), append([]string{"serve"}, serveArgs...)...)
	child.Stdout, child.Stderr = logFile, logFile
	child.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := child.Start(); err != nil {
		return fmt.Errorf("could not launch %s: %v", whatsappLauncher(), err)
	}
	exited := make(chan struct{})
	go func() {
		child.Wait()
		close(exited)
	}()
	if err := os.WriteFile(daemonPidfile(), []byte(strconv.Itoa(child.Process.Pid)), daemonRecordPerms); err != nil {
		return abandon(child, exited, fmt.Sprintf("could not record the daemon pid: %v", err))
	}
	deadline := time.Now().Add(daemonBudget(DaemonReadyTimeoutEnv, DaemonReadyTimeout))
	for time.Now().Before(deadline) {
		if daemonAlive(sockPath) {
			return nil
		}
		select {
		case <-exited:
			return abandon(child, exited, fmt.Sprintf("the daemon exited during startup; see %s", daemonLifecycleLog()))
		default:
		}
		time.Sleep(DaemonPollInterval)
	}
	return abandon(child, exited, fmt.Sprintf("the daemon never answered on %s; see %s", sockPath, daemonLifecycleLog()))
}

func daemonStart(serveArgs []string) {
	if daemonAlive(getSocketPath()) {
		printJSON(map[string]string{"status": "already_running"})
		return
	}
	if err := startDaemonProcess(serveArgs); err != nil {
		failJSON("%s", err.Error())
	}
	printJSON(map[string]string{"status": "started"})
}

// stopDaemon does the stop work and returns the resulting status ("already_stopped"
// or "stopped") or an error. It prints NOTHING, so callers compose it without
// emitting stray JSON: the stop verb prints one object, restart stays silent and
// prints only its own.
func stopDaemon() (string, error) {
	pid, running := livePid()
	if !running {
		os.Remove(daemonPidfile())
		return "already_stopped", nil
	}
	if msg := stopRefusal(syncWindowRemaining(loadStateFromDisk(stateDataDir()).LinkedAt, time.Now()), hasBareFlag("force")); msg != "" {
		return "", errors.New(msg)
	}
	if err := syscall.Kill(pid, syscall.SIGTERM); err != nil {
		return "", fmt.Errorf("could not signal the daemon (pid %d): %v", pid, err)
	}
	budget := daemonBudget(DaemonStopTimeoutEnv, DaemonStopTimeout)
	deadline := time.Now().Add(budget)
	for time.Now().Before(deadline) {
		if _, alive := livePid(); !alive {
			os.Remove(daemonPidfile())
			return "stopped", nil
		}
		time.Sleep(DaemonPollInterval)
	}
	return "", fmt.Errorf("the daemon is still running %s after SIGTERM (pid %d); see %s", budget, pid, daemonLifecycleLog())
}

func daemonStop() {
	status, err := stopDaemon()
	if err != nil {
		failJSON("%s", err.Error())
	}
	printJSON(map[string]string{"status": status})
}

func daemonRestart() {
	serveArgs := restartServeArgs(loadStateFromDisk(stateDataDir()))
	if _, err := stopDaemon(); err != nil {
		failJSON("%s", err.Error())
	}
	if err := startDaemonProcess(serveArgs); err != nil {
		failJSON("%s", err.Error())
	}
	printJSON(map[string]string{"status": "started"})
}

// restartServeArgs picks the flags a restart brings the daemon back with: the last run's
// flags recorded in state.json (which survives stops and crashes, so e.g. --read-only is
// never silently dropped), falling back to the instance flag alone when no run was ever
// recorded.
func restartServeArgs(st daemonState) []string {
	if st.StartedAt.IsZero() {
		return linkServeArgs()
	}
	return st.Args
}

// daemonStatus answers from the pid record and one local socket dial, so it stays instant and
// truthful with vestad down. Running means the daemon answers: whatsapp serves no port of its
// own (its link page registers its own service only while a link is open).
func daemonStatus() {
	dataDir := stateDataDir()
	now := time.Now()
	st := loadStateFromDisk(dataDir)
	result := map[string]any{
		"running":                  daemonAlive(getSocketPath()),
		"port":                     nil,
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
