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
	// them. Readiness is minutes because a cold cache compiles the CLI on this very path
	// before the socket can open, and past that come the whatsmeow update warning (20s), the
	// store open, and a first connect that retries for ConnectRetryAttempts seconds.
	DaemonReadyTimeoutEnv = "DAEMON_READY_TIMEOUT_SECS"
	DaemonStopTimeoutEnv  = "DAEMON_STOP_TIMEOUT_SECS"
	DaemonReadyTimeout    = 5 * time.Minute
	DaemonStopTimeout     = 15 * time.Second
	// How long a start that lost the record claim waits for the rival start to resolve.
	DaemonClaimWait        = 3 * time.Second
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
	fields := strings.Fields(string(record))
	if len(fields) == 0 {
		return 0, false
	}
	pid, err := strconv.Atoi(fields[0])
	if err != nil || pid <= 0 {
		return 0, false
	}
	if err := syscall.Kill(pid, 0); err != nil {
		return 0, false
	}
	// LEGACY(remove-when: no daemon record predating the release that ships this check remains, i.e.
	// every box has restarted its daemons at least once on this version): a record written by the old
	// code is a bare pid. Trust it rather than reading the absence of a starttime as a mismatch,
	// because an upgrade must not declare a live daemon dead and let a second stack beside it.
	if len(fields) > 1 && isDigits(fields[1]) {
		if current := starttimeOf(pid); current != "" && current != fields[1] {
			return 0, false
		}
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

// failDaemon ends a verb with its error envelope as the one compact line the
// daemon contract pins; emitAndExit routes it to stderr.
func failDaemon(format string, args ...any) {
	envelope, _ := json.Marshal(map[string]string{"error": fmt.Sprintf(format, args...)})
	emitAndExit(envelope, 1)
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
		// A verb that does not exist is the caller's typo, not a daemon failure, so it answers
		// with usage rather than the error envelope a caller retries on.
		fmt.Fprintln(os.Stderr, daemonUsage)
		os.Exit(1)
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

// claimStart takes the pid record exclusively for this start, so a start that loses the claim
// answers already_running instead of stacking a daemon beside the winner's. Losing the claim is
// not a failure: the rival either brings a daemon up (nothing left to do, claimed
// false) or leaves a record no process stands behind, which this start takes over once.
func claimStart() (claimed bool, err error) {
	switch err := writePidRecord(os.Getpid(), os.O_EXCL); {
	case err == nil:
		return true, nil
	case !errors.Is(err, os.ErrExist):
		return false, fmt.Errorf("could not claim %s: %v", daemonPidfile(), err)
	}
	deadline := time.Now().Add(DaemonClaimWait)
	for time.Now().Before(deadline) {
		if _, alive := livePid(); alive {
			return false, nil
		}
		// The rival dropped its own claim, so there is nothing to remove: the exclusive create
		// alone is the takeover, which is the narrowest window in which two starts can both get one.
		if _, err := os.Stat(daemonPidfile()); errors.Is(err, os.ErrNotExist) {
			return takeOverRecord()
		}
		time.Sleep(DaemonPollInterval)
	}
	os.Remove(daemonPidfile())
	return takeOverRecord()
}

// takeOverRecord claims a record no live process stands behind, which is the one path on which
// two starts can both spawn, and the duplicate loses on the device-store lock.
func takeOverRecord() (bool, error) {
	if err := writePidRecord(os.Getpid(), os.O_EXCL); err != nil {
		return false, fmt.Errorf("another whatsapp start holds %s: %v", daemonPidfile(), err)
	}
	return true, nil
}

func writePidRecord(pid int, flags int) error {
	file, err := os.OpenFile(daemonPidfile(), os.O_CREATE|os.O_WRONLY|os.O_TRUNC|flags, daemonRecordPerms)
	if err != nil {
		return err
	}
	defer file.Close()
	_, err = file.WriteString(pidRecordFor(pid))
	return err
}

// Field 22 of /proc/<pid>/stat is the process start time in clock ticks since boot. A recycled pid
// cannot share the original's starttime, because the process that took the pid necessarily started
// later, so (pid, starttime) is a stable identity. Empty where /proc cannot answer, which drops the
// caller back to a bare pid-existence check.
func starttimeOf(pid int) string {
	data, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		return ""
	}
	// comm is a bracketed field that may itself contain spaces and parentheses, so the numbered
	// fields resume after the LAST ')'.
	end := strings.LastIndex(string(data), ")")
	if end < 0 {
		return ""
	}
	fields := strings.Fields(string(data)[end+1:])
	if len(fields) < 20 {
		return ""
	}
	return fields[19]
}

// A starttime is only worth comparing when it is a plain run of digits. Any other second field,
// from a writer this contract does not own, would compare a real starttime against a non-number and
// declare a live daemon dead, letting a second stack beside it.
func isDigits(value string) bool {
	if value == "" {
		return false
	}
	for _, r := range value {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

// The record is "<pid> <starttime>", or a bare pid where the starttime is unavailable: a bare pid is
// the honest form of "identity unknown", and the readers take it the legacy way rather than as a
// mismatch.
func pidRecordFor(pid int) string {
	if started := starttimeOf(pid); started != "" {
		return strconv.Itoa(pid) + " " + started
	}
	return strconv.Itoa(pid)
}

// ensureDaemon is the self-bootstrap every agent-facing command runs: a socket that answers is
// all those commands need, whoever brought it up.
func ensureDaemon(serveArgs []string) error {
	if daemonAlive(getSocketPath()) {
		return nil
	}
	_, err := startDaemonProcess(serveArgs)
	return err
}

// startDaemonProcess launches `whatsapp serve` detached in its own session, records its pid,
// and waits for that recorded process to answer on the socket. The record is the mutual
// exclusion: a start claims it before spawning and drops it on every failure, so what the
// record names is a daemon that was serving. The answer
// is whether this start is the one that brought the daemon up: a start that lost the claim to a
// rival did not, and says so rather than taking credit for the daemon now running.
func startDaemonProcess(serveArgs []string) (broughtUp bool, err error) {
	sockPath := getSocketPath()
	if _, alive := livePid(); alive {
		return false, nil
	}
	if daemonAlive(sockPath) {
		return false, fmt.Errorf("%s", foreignDaemonMessage(sockPath))
	}
	if err := os.MkdirAll(filepath.Dir(daemonPidfile()), daemonDirPerms); err != nil {
		return false, fmt.Errorf("could not create the daemon record directory: %v", err)
	}
	if err := os.MkdirAll(filepath.Dir(daemonLifecycleLog()), daemonDirPerms); err != nil {
		return false, fmt.Errorf("could not create the daemon log directory: %v", err)
	}
	logFile, err := os.OpenFile(daemonLifecycleLog(), os.O_CREATE|os.O_WRONLY|os.O_APPEND, daemonRecordPerms)
	if err != nil {
		return false, fmt.Errorf("could not open %s: %v", daemonLifecycleLog(), err)
	}
	defer logFile.Close()
	claimed, err := claimStart()
	if err != nil {
		return false, err
	}
	if !claimed {
		return false, nil
	}
	child := exec.Command(whatsappLauncher(), append([]string{"serve"}, serveArgs...)...)
	child.Stdout, child.Stderr = logFile, logFile
	child.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := child.Start(); err != nil {
		os.Remove(daemonPidfile())
		return false, fmt.Errorf("could not launch %s: %v", whatsappLauncher(), err)
	}
	exited := make(chan struct{})
	go func() {
		child.Wait()
		close(exited)
	}()
	if err := writePidRecord(child.Process.Pid, 0); err != nil {
		return false, abandon(child, exited, fmt.Sprintf("could not record the daemon pid: %v", err))
	}
	return true, awaitDaemon(child, exited, sockPath)
}

// foreignDaemonMessage names the one situation this lifecycle cannot manage: a daemon serving
// this instance that it did not start, so it holds the device-store lock and no pid it records
// would stand for the process actually serving.
func foreignDaemonMessage(sockPath string) string {
	return fmt.Sprintf(
		"a whatsapp daemon this lifecycle did not start already answers on %s; end that process before starting this instance (see %s)",
		sockPath, daemonLifecycleLog())
}

// awaitDaemon holds the start open until the daemon it spawned answers. A socket that answers
// while that child is gone belongs to another daemon (only one can hold the device-store lock),
// so this start reports the conflict instead of leaving a corpse in the record.
func awaitDaemon(child *exec.Cmd, exited <-chan struct{}, sockPath string) error {
	deadline := time.Now().Add(daemonBudget(DaemonReadyTimeoutEnv, DaemonReadyTimeout))
	for time.Now().Before(deadline) {
		answering := daemonAlive(sockPath)
		select {
		case <-exited:
			if answering || daemonAlive(sockPath) {
				return abandon(child, exited, foreignDaemonMessage(sockPath))
			}
			return abandon(child, exited, fmt.Sprintf("the daemon exited during startup; see %s", daemonLifecycleLog()))
		default:
			if answering {
				return nil
			}
		}
		time.Sleep(DaemonPollInterval)
	}
	return abandon(child, exited, fmt.Sprintf("the daemon never answered on %s; see %s", sockPath, daemonLifecycleLog()))
}

func daemonStart(serveArgs []string) {
	if _, alive := livePid(); alive {
		printJSON(map[string]string{"status": "already_running"})
		return
	}
	broughtUp, err := startDaemonProcess(serveArgs)
	if err != nil {
		failDaemon("%s", err.Error())
	}
	status := "started"
	if !broughtUp {
		status = "already_running"
	}
	printJSON(map[string]string{"status": status})
}

// stopDaemon does the stop work and returns the resulting status ("already_stopped"
// or "stopped") or an error. It prints NOTHING, so callers compose it without
// emitting stray JSON: the stop verb prints one object, restart stays silent and
// prints only its own.
//
// SIGTERM is never escalated to SIGKILL here, alone among the skills: killing this daemon
// mid-history-sync can invalidate the multi-device session and force the user to re-pair the
// phone, so a daemon that will not go is reported instead of taken by force.
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
		failDaemon("%s", err.Error())
	}
	printJSON(map[string]string{"status": status})
}

func daemonRestart() {
	serveArgs := restartServeArgs(loadStateFromDisk(stateDataDir()))
	if _, err := stopDaemon(); err != nil {
		failDaemon("%s", err.Error())
	}
	if _, err := startDaemonProcess(serveArgs); err != nil {
		failDaemon("%s", err.Error())
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
