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
	SocketDialTimeout  = 2 * time.Second
	// Both budgets are whole seconds in the environment, so a caller in a hurry can shorten
	// them. Readiness is minutes because a start compiles the CLI on this very path before the
	// daemon it spawns can open its socket.
	DaemonReadyTimeoutEnv = "DAEMON_READY_TIMEOUT_SECS"
	DaemonStopTimeoutEnv  = "DAEMON_STOP_TIMEOUT_SECS"
	DaemonReadyTimeout    = 5 * time.Minute
	DaemonStopTimeout     = 15 * time.Second
	// How long a start that lost the record claim waits for the rival start to resolve.
	DaemonClaimWait   = 3 * time.Second
	daemonRecordPerms = 0644
	daemonDirPerms    = 0755
	daemonInfoFile    = "daemon-info.json"
	daemonUsage       = "usage: telegram daemon <start|stop|restart|status> [serve flags]"
	// The watchdog guards the default daemon alone: it is the channel the user depends on, and
	// a second watchdog would fight the first over one bot token.
	watchdogRecord         = "telegram-watchdog"
	telegramLauncherInHome = "agent/skills/telegram/telegram"
	watchdogScriptInHome   = "agent/skills/telegram/telegram-watchdog.sh"
)

type daemonInfo struct {
	Args      []string  `json:"args"`
	PID       int       `json:"pid"`
	StartedAt time.Time `json:"started_at"`
}

func defaultNotificationsDir() string {
	return filepath.Join(os.Getenv("HOME"), "agent", "notifications")
}

// daemonName is this instance's name in every record: the bare skill name for the default
// instance, suffixed per named instance so two instances never share a pid record or a log.
func daemonName() string {
	if instance := extractInstance(); instance != "" {
		return "telegram-" + instance
	}
	return "telegram"
}

func pidfileFor(name string) string {
	return filepath.Join(os.Getenv("HOME"), "agent", "data", "daemons", name+".pid")
}

func logFor(name string) string {
	return filepath.Join(os.Getenv("HOME"), "agent", "logs", name+".log")
}

func daemonPidfile() string      { return pidfileFor(daemonName()) }
func daemonLifecycleLog() string { return logFor(daemonName()) }

// telegramLauncher is the skill's own launcher: a box's HOME is the checkout, and the launcher
// (never a cached binary) is what keeps a source change from serving stale code.
func telegramLauncher() string {
	return filepath.Join(os.Getenv("HOME"), telegramLauncherInHome)
}

func watchdogScript() string {
	return filepath.Join(os.Getenv("HOME"), watchdogScriptInHome)
}

// daemonBudget reads a lifecycle budget in whole seconds from the environment.
func daemonBudget(name string, fallback time.Duration) time.Duration {
	secs, err := strconv.Atoi(os.Getenv(name))
	if err != nil || secs <= 0 {
		return fallback
	}
	return time.Duration(secs) * time.Second
}

// livePidIn is the pid a record names, when that process is still there.
func livePidIn(record string) (int, bool) {
	data, err := os.ReadFile(record)
	if err != nil {
		return 0, false
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil || pid <= 0 {
		return 0, false
	}
	if err := syscall.Kill(pid, 0); err != nil {
		return 0, false
	}
	return pid, true
}

func livePid() (int, bool) { return livePidIn(daemonPidfile()) }

func daemonAlive(sockPath string) bool {
	conn, err := net.DialTimeout("unix", sockPath, SocketDialTimeout)
	if err != nil {
		return false
	}
	conn.Close()
	return true
}

// deathIsNews reports whether an exiting daemon owes the agent a notification. SIGTERM is what
// `telegram daemon stop` sends, so it is the one exit the agent asked for; every other way out
// is news.
func deathIsNews(sig os.Signal) bool {
	return sig != syscall.SIGTERM
}

func writeDaemonInfo(dataDir string, serveArgs []string) {
	info := daemonInfo{Args: serveArgs, PID: os.Getpid(), StartedAt: time.Now().UTC()}
	data, err := json.Marshal(info)
	if err != nil {
		fmt.Fprintf(os.Stderr, "warning: failed to marshal daemon info: %v\n", err)
		return
	}
	if err := os.WriteFile(filepath.Join(dataDir, daemonInfoFile), data, daemonRecordPerms); err != nil {
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

// failDaemon ends a verb with its error envelope on stderr, which is where the contract puts a
// failure: stdout carries the one status object a verb answers with and nothing else.
func failDaemon(format string, args ...any) {
	envelope, err := json.Marshal(map[string]string{"error": fmt.Sprintf(format, args...)})
	if err != nil {
		fmt.Fprintf(os.Stderr, "JSON encoding error: %v\n", err)
		os.Exit(1)
	}
	fmt.Fprintln(os.Stderr, string(envelope))
	os.Exit(1)
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
		failDaemon("unknown daemon subcommand %q (use start|stop|restart|status)", sub)
	}
}

func makeRecordDirs() error {
	if err := os.MkdirAll(filepath.Dir(daemonPidfile()), daemonDirPerms); err != nil {
		return fmt.Errorf("could not create the daemon record directory: %v", err)
	}
	if err := os.MkdirAll(filepath.Dir(daemonLifecycleLog()), daemonDirPerms); err != nil {
		return fmt.Errorf("could not create the daemon log directory: %v", err)
	}
	return nil
}

func writePidRecord(record string, pid int, flags int) error {
	file, err := os.OpenFile(record, os.O_CREATE|os.O_WRONLY|os.O_TRUNC|flags, daemonRecordPerms)
	if err != nil {
		return err
	}
	defer file.Close()
	_, err = file.WriteString(strconv.Itoa(pid))
	return err
}

// claimRecord takes a pid record exclusively for this start, so two starts racing on one name
// cannot both spawn a process and leave the loser's corpse in the record. Losing the claim is
// not a failure: the rival either brings its process up (nothing left to do, claimed false) or
// leaves a record no process stands behind, which this start takes over once.
func claimRecord(record string) (claimed bool, err error) {
	switch err := writePidRecord(record, os.Getpid(), os.O_EXCL); {
	case err == nil:
		return true, nil
	case !errors.Is(err, os.ErrExist):
		return false, fmt.Errorf("could not claim %s: %v", record, err)
	}
	deadline := time.Now().Add(DaemonClaimWait)
	for time.Now().Before(deadline) {
		if _, alive := livePidIn(record); alive {
			return false, nil
		}
		if _, err := os.Stat(record); errors.Is(err, os.ErrNotExist) {
			break
		}
		time.Sleep(DaemonPollInterval)
	}
	os.Remove(record)
	if err := writePidRecord(record, os.Getpid(), os.O_EXCL); err != nil {
		return false, fmt.Errorf("another telegram start holds %s: %v", record, err)
	}
	return true, nil
}

// signalRecorded ends a recorded process and everything it launched. Every process this
// lifecycle spawns leads its own group, so the signal goes to the group: a watchdog signalled
// alone leaves the `telegram daemon start` it is running mid-restart, which then brings back
// what the stop just ended. A pid that leads no group (a start still holding its claim) is
// signalled by itself.
func signalRecorded(pid int, sig syscall.Signal) error {
	if pgid, err := syscall.Getpgid(pid); err == nil && pgid == pid {
		return syscall.Kill(-pid, sig)
	}
	return syscall.Kill(pid, sig)
}

// abandon ends a start that gave up, taking the child and its pid record with it: a process
// nothing can reach, with a record that says it is up, reads as running and turns every later
// start into a no-op.
func abandon(name string, child *exec.Cmd, exited <-chan struct{}, message string) error {
	signalRecorded(child.Process.Pid, syscall.SIGTERM)
	select {
	case <-exited:
	case <-time.After(daemonBudget(DaemonStopTimeoutEnv, DaemonStopTimeout)):
		signalRecorded(child.Process.Pid, syscall.SIGKILL)
		<-exited
	}
	os.Remove(pidfileFor(name))
	return errors.New(message)
}

// spawnRecorded launches argv detached in its own session, appends its output to the named log,
// and puts the child's pid in the record this caller already claimed. On any error nothing is
// left running and the record is gone, so a claim never outlives the start that took it.
func spawnRecorded(name string, argv []string) (*exec.Cmd, <-chan struct{}, error) {
	logFile, err := os.OpenFile(logFor(name), os.O_CREATE|os.O_WRONLY|os.O_APPEND, daemonRecordPerms)
	if err != nil {
		os.Remove(pidfileFor(name))
		return nil, nil, fmt.Errorf("could not open %s: %v", logFor(name), err)
	}
	defer logFile.Close()
	child := exec.Command(argv[0], argv[1:]...)
	child.Stdout, child.Stderr = logFile, logFile
	child.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := child.Start(); err != nil {
		os.Remove(pidfileFor(name))
		return nil, nil, fmt.Errorf("could not launch %s: %v", argv[0], err)
	}
	exited := make(chan struct{})
	go func() {
		child.Wait()
		close(exited)
	}()
	if err := writePidRecord(pidfileFor(name), child.Process.Pid, 0); err != nil {
		return nil, nil, abandon(name, child, exited, fmt.Sprintf("could not record the pid of %s: %v", name, err))
	}
	return child, exited, nil
}

// startDaemonProcess launches `telegram serve` detached and waits for that process to answer on
// the socket. The record is the mutual exclusion: a start claims it before spawning and drops it
// on every failure, so what the record names is always a daemon that was serving.
func startDaemonProcess(serveArgs []string) error {
	sockPath := getSocketPath()
	if _, alive := livePid(); alive {
		return nil
	}
	if daemonAlive(sockPath) {
		return errors.New(foreignDaemonMessage(sockPath))
	}
	if err := makeRecordDirs(); err != nil {
		return err
	}
	claimed, err := claimRecord(daemonPidfile())
	if err != nil {
		return err
	}
	if !claimed {
		return nil
	}
	child, exited, err := spawnRecorded(daemonName(), append([]string{telegramLauncher(), "serve"}, serveArgs...))
	if err != nil {
		return err
	}
	return awaitDaemon(child, exited, sockPath)
}

// foreignDaemonMessage names the one situation this lifecycle cannot manage: a daemon serving
// this instance that it did not start, so no pid it records would stand for the process actually
// polling Telegram (and two pollers on one bot token get 409 Conflict).
func foreignDaemonMessage(sockPath string) string {
	return fmt.Sprintf(
		"a telegram daemon this lifecycle did not start already answers on %s; end that process before starting this instance (see %s)",
		sockPath, daemonLifecycleLog())
}

// awaitDaemon holds the start open until the daemon it spawned answers. A socket that answers
// while that child is gone belongs to another daemon, so this start reports the conflict instead
// of leaving a corpse in the record.
func awaitDaemon(child *exec.Cmd, exited <-chan struct{}, sockPath string) error {
	deadline := time.Now().Add(daemonBudget(DaemonReadyTimeoutEnv, DaemonReadyTimeout))
	for time.Now().Before(deadline) {
		answering := daemonAlive(sockPath)
		select {
		case <-exited:
			if answering || daemonAlive(sockPath) {
				return abandon(daemonName(), child, exited, foreignDaemonMessage(sockPath))
			}
			return abandon(daemonName(), child, exited, fmt.Sprintf("the daemon exited during startup; see %s", daemonLifecycleLog()))
		default:
			if answering {
				return nil
			}
		}
		time.Sleep(DaemonPollInterval)
	}
	return abandon(daemonName(), child, exited, fmt.Sprintf("the daemon never answered on %s; see %s", sockPath, daemonLifecycleLog()))
}

// ensureWatchdog brings the watchdog up whenever its own record names no live process, so a
// start converges on both processes however it was called. A watchdog that will not start is a
// warning and never a failed start: it is the daemon's safety net, not the daemon.
func ensureWatchdog() {
	if extractInstance() != "" {
		return
	}
	if _, alive := livePidIn(pidfileFor(watchdogRecord)); alive {
		return
	}
	if err := makeRecordDirs(); err != nil {
		fmt.Fprintf(os.Stderr, "warning: the watchdog did not start: %v\n", err)
		return
	}
	claimed, err := claimRecord(pidfileFor(watchdogRecord))
	if err != nil {
		fmt.Fprintf(os.Stderr, "warning: the watchdog did not start: %v\n", err)
		return
	}
	if !claimed {
		return
	}
	if _, _, err := spawnRecorded(watchdogRecord, []string{"bash", watchdogScript()}); err != nil {
		fmt.Fprintf(os.Stderr, "warning: the watchdog did not start: %v\n", err)
	}
}

// endRecorded signals the process a record names and waits for it to go, taking the record with
// it. Reports whether there was one to end.
func endRecorded(name string) (bool, error) {
	record := pidfileFor(name)
	pid, alive := livePidIn(record)
	if !alive {
		os.Remove(record)
		return false, nil
	}
	if err := signalRecorded(pid, syscall.SIGTERM); err != nil {
		return false, fmt.Errorf("could not signal %s (pid %d): %v", name, pid, err)
	}
	budget := daemonBudget(DaemonStopTimeoutEnv, DaemonStopTimeout)
	deadline := time.Now().Add(budget)
	for time.Now().Before(deadline) {
		if _, alive := livePidIn(record); !alive {
			os.Remove(record)
			return true, nil
		}
		time.Sleep(DaemonPollInterval)
	}
	return false, fmt.Errorf("%s is still running %s after SIGTERM (pid %d); see %s", name, budget, pid, logFor(name))
}

func daemonStart(serveArgs []string) {
	if _, alive := livePid(); alive {
		ensureWatchdog()
		printJSON(map[string]string{"status": "already_running"})
		return
	}
	if err := startDaemonProcess(serveArgs); err != nil {
		failDaemon("%s", err.Error())
	}
	ensureWatchdog()
	printJSON(map[string]string{"status": "started"})
}

// stopDaemon does the stop work and returns the resulting status ("already_stopped" or
// "stopped") or an error. It prints NOTHING, so callers compose it without emitting stray JSON.
// The watchdog goes first: it exists to restart a daemon that went away, so a stop that left it
// running would race itself into a second daemon.
func stopDaemon() (string, error) {
	if extractInstance() == "" {
		if _, err := endRecorded(watchdogRecord); err != nil {
			return "", err
		}
	}
	ended, err := endRecorded(daemonName())
	if err != nil {
		return "", err
	}
	if !ended {
		return "already_stopped", nil
	}
	return "stopped", nil
}

func daemonStop() {
	status, err := stopDaemon()
	if err != nil {
		failDaemon("%s", err.Error())
	}
	printJSON(map[string]string{"status": status})
}

func daemonRestart() {
	dataDir, _ := parseStateDir()
	serveArgs := restartServeArgs(dataDir)
	if _, err := stopDaemon(); err != nil {
		failDaemon("%s", err.Error())
	}
	if err := startDaemonProcess(serveArgs); err != nil {
		failDaemon("%s", err.Error())
	}
	ensureWatchdog()
	printJSON(map[string]string{"status": "started"})
}

// restartServeArgs picks the flags a restart brings the daemon back with: the last run's flags
// as the daemon itself recorded them, falling back to the instance flag alone when no run was
// ever recorded (without it the daemon would come back on the default instance's socket).
func restartServeArgs(dataDir string) []string {
	if info, err := readDaemonInfo(dataDir); err == nil {
		return info.Args
	}
	if instance := extractInstance(); instance != "" {
		return []string{"--instance", instance}
	}
	return nil
}

// daemonStatus answers from the pid records alone, so it stays instant and truthful with vestad
// down. There is no port: telegram polls Telegram and serves its own commands over a socket.
func daemonStatus() {
	dataDir, _ := parseStateDir()
	_, running := livePid()
	_, watchdog := livePidIn(pidfileFor(watchdogRecord))
	printJSON(map[string]any{
		"running":          running,
		"port":             nil,
		"watchdog_running": watchdog,
		"auth":             readAuthStatus(dataDir),
	})
}
