package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

// testModeEnv re-runs the test binary as something other than the suite, which is how these
// tests get real processes: modeServe is the daemon a start spawns, modeMute a daemon that
// comes up and never answers, and modeVerb one `whatsapp daemon <verb>` invocation.
const (
	testModeEnv = "WHATSAPP_TEST_MODE"
	modeServe   = "serve"
	modeMute    = "mute"
	modeVerb    = "verb"
	// serveDelayEnv holds the fake daemon between taking the device-store lock and opening its
	// socket, which is the window a real daemon spends connecting and the one the race below
	// needs: a second start landing inside it finds no socket and spawns a child that the lock
	// then kills.
	serveDelayEnv = "WHATSAPP_TEST_SERVE_DELAY_MS"
	raceStarts    = 2
	raceRounds    = 3
	RaceServeWait = 1500 * time.Millisecond
	RaceStagger   = 500 * time.Millisecond
)

func TestMain(m *testing.M) {
	switch os.Getenv(testModeEnv) {
	case "":
		os.Exit(m.Run())
	case modeMute:
		select {}
	case modeVerb:
		// The daemon this verb starts is the fake serve, not another verb.
		os.Setenv(testModeEnv, modeServe)
		runDaemon()
		os.Exit(0)
	default:
		runFakeServe()
	}
}

// runFakeServe stands in for the whatsmeow half of `whatsapp serve` and for nothing else: it
// takes the same device-store lock (so a second daemon on one instance exits exactly as the
// real one does), serves the same socket, and ends through the real death-notification
// decision, so what these tests exercise there is the shipping code.
func runFakeServe() {
	dataDir := stateDataDir()
	if err := os.MkdirAll(dataDir, daemonDirPerms); err != nil {
		os.Exit(1)
	}
	lock, ok, err := acquireDaemonLock(dataDir)
	if err != nil || !ok {
		os.Exit(0)
	}
	serveDaemonLock = lock
	if delay, err := strconv.Atoi(os.Getenv(serveDelayEnv)); err == nil {
		time.Sleep(time.Duration(delay) * time.Millisecond)
	}
	listener, err := net.Listen("unix", getSocketPath())
	if err != nil {
		os.Exit(1)
	}
	go answerSocketCommands(listener)
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT, syscall.SIGHUP)
	sig := <-signals
	if deathIsNews(sig) {
		writeDeathNotification(defaultNotificationsDir(), sig.String())
	}
	listener.Close()
	os.Remove(getSocketPath())
}

// answerSocketCommands keeps the fake daemon answering, so a caller that asks it something
// (status does) gets a reply instead of waiting out its socket deadline.
func answerSocketCommands(listener net.Listener) {
	for {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		json.NewEncoder(conn).Encode(SocketResponse{Result: map[string]any{}})
		conn.Close()
	}
}

// daemonVerb runs one lifecycle verb the way a caller does, in its own process, and returns
// its envelope and exit code.
func daemonVerb(t *testing.T, args ...string) (map[string]any, int) {
	t.Helper()
	output, code := runVerbProcess(t, args...)
	var envelope map[string]any
	if err := json.Unmarshal(output, &envelope); err != nil {
		t.Fatalf("whatsapp daemon %v printed unparseable output %q: %v", args, output, err)
	}
	return envelope, code
}

func runVerbProcess(t *testing.T, args ...string) ([]byte, int) {
	t.Helper()
	binary, err := os.Executable()
	if err != nil {
		t.Fatalf("failed to locate the test binary: %v", err)
	}
	verb := exec.Command(binary, args...)
	verb.Env = append(os.Environ(), testModeEnv+"="+modeVerb)
	output, err := verb.Output()
	var exitErr *exec.ExitError
	if err != nil && !errors.As(err, &exitErr) {
		t.Fatalf("whatsapp daemon %v could not run: %v", args, err)
	}
	return output, verb.ProcessState.ExitCode()
}

func wantEnvelope(t *testing.T, got map[string]any, code int, status string) {
	t.Helper()
	if code != 0 {
		t.Errorf("the verb exited %d, want 0 (envelope %v)", code, got)
	}
	if !reflect.DeepEqual(got, map[string]any{"status": status}) {
		t.Errorf("envelope = %v, want exactly {status: %s}", got, status)
	}
}

func deathNotices(t *testing.T, home string) []string {
	t.Helper()
	notices, err := filepath.Glob(filepath.Join(home, "agent/notifications/*daemon_died*"))
	if err != nil {
		t.Fatalf("failed to list the notifications directory: %v", err)
	}
	return notices
}

func waitForDaemon(t *testing.T, want bool) {
	t.Helper()
	deadline := time.Now().Add(DaemonStopTimeout)
	for time.Now().Before(deadline) {
		if daemonAlive(getSocketPath()) == want {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("the socket at %s never became %v", getSocketPath(), want)
}

// hermeticHome points every daemon record, log, and data dir at a temporary home and installs
// the fake serve there under the launcher path a start spawns.
func hermeticHome(t *testing.T, mode string, serveArgs ...string) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv(testModeEnv, mode)
	if err := os.MkdirAll(filepath.Join(home, "agent/notifications"), daemonDirPerms); err != nil {
		t.Fatalf("failed to create the notifications directory: %v", err)
	}
	launcher := filepath.Join(home, whatsappLauncherInHome)
	if err := os.MkdirAll(filepath.Dir(launcher), daemonDirPerms); err != nil {
		t.Fatalf("failed to create the launcher directory: %v", err)
	}
	binary, err := os.Executable()
	if err != nil {
		t.Fatalf("failed to locate the test binary: %v", err)
	}
	if err := os.WriteFile(launcher, []byte("#!/bin/sh\nexec "+binary+" \"$@\"\n"), 0755); err != nil {
		t.Fatalf("failed to write the fake launcher: %v", err)
	}
	withArgs(t, serveArgs...)
	return home
}

func withArgs(t *testing.T, args ...string) {
	t.Helper()
	saved := os.Args
	os.Args = append([]string{"whatsapp"}, args...)
	t.Cleanup(func() { os.Args = saved })
}

func recordedPid(t *testing.T) int {
	t.Helper()
	record, err := os.ReadFile(daemonPidfile())
	if err != nil {
		t.Fatalf("start recorded no pid at %s: %v", daemonPidfile(), err)
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(record)))
	if err != nil {
		t.Fatalf("pid record %q is not a pid: %v", record, err)
	}
	return pid
}

func TestDaemonRecordsAreScopedToTheInstance(t *testing.T) {
	for _, tc := range []struct {
		name     string
		args     []string
		wantName string
	}{
		{"default instance", nil, "whatsapp"},
		{"named instance", []string{"--instance", "personal"}, "whatsapp-personal"},
		{"named instance as one argument", []string{"--instance=work"}, "whatsapp-work"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("HOME", "/home/agent")
			withArgs(t, tc.args...)
			if got := daemonName(); got != tc.wantName {
				t.Errorf("daemonName() = %q, want %q", got, tc.wantName)
			}
			if got := daemonPidfile(); got != "/home/agent/agent/data/daemons/"+tc.wantName+".pid" {
				t.Errorf("daemonPidfile() = %q, want the %s record", got, tc.wantName)
			}
			if got := daemonLifecycleLog(); got != "/home/agent/agent/logs/"+tc.wantName+".log" {
				t.Errorf("daemonLifecycleLog() = %q, want the %s log", got, tc.wantName)
			}
		})
	}
}

func TestLivePidIsOnlyAProcessThatIsStillThere(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	withArgs(t)
	if err := os.MkdirAll(filepath.Dir(daemonPidfile()), daemonDirPerms); err != nil {
		t.Fatalf("failed to create the record directory: %v", err)
	}
	if _, alive := livePid(); alive {
		t.Error("no record at all must not read as running")
	}
	if err := os.WriteFile(daemonPidfile(), []byte("not a pid\n"), daemonRecordPerms); err != nil {
		t.Fatalf("failed to write the record: %v", err)
	}
	if _, alive := livePid(); alive {
		t.Error("an unreadable record must not read as running")
	}
	gone := exec.Command("/bin/sh", "-c", "exit 0")
	if err := gone.Run(); err != nil {
		t.Fatalf("failed to run the short-lived process: %v", err)
	}
	if err := os.WriteFile(daemonPidfile(), []byte(strconv.Itoa(gone.Process.Pid)), daemonRecordPerms); err != nil {
		t.Fatalf("failed to write the record: %v", err)
	}
	if _, alive := livePid(); alive {
		t.Error("a record pointing at an exited process must not read as running")
	}
	if err := os.WriteFile(daemonPidfile(), []byte(strconv.Itoa(os.Getpid())), daemonRecordPerms); err != nil {
		t.Fatalf("failed to write the record: %v", err)
	}
	pid, alive := livePid()
	if !alive || pid != os.Getpid() {
		t.Errorf("livePid() = (%d, %v), want this process", pid, alive)
	}
}

func TestStartRecordsTheDaemonAndStopEndsIt(t *testing.T) {
	hermeticHome(t, modeServe)
	if err := startDaemonProcess(nil); err != nil {
		t.Fatalf("start failed: %v", err)
	}
	pid := recordedPid(t)
	if !daemonAlive(getSocketPath()) {
		t.Fatal("start returned before the daemon answered on its socket")
	}
	if err := startDaemonProcess(nil); err != nil {
		t.Fatalf("a second start must be a no-op, got %v", err)
	}
	if again := recordedPid(t); again != pid {
		t.Errorf("a second start stacked a daemon: pid %d became %d", pid, again)
	}
	status, err := stopDaemon()
	if err != nil {
		t.Fatalf("stop failed: %v", err)
	}
	if status != "stopped" {
		t.Errorf("stop reported %q, want stopped", status)
	}
	if syscall.Kill(pid, 0) == nil {
		t.Errorf("the daemon (pid %d) survived the stop", pid)
	}
	if _, err := os.Stat(daemonPidfile()); !os.IsNotExist(err) {
		t.Errorf("a stopped daemon must leave no pid record, got %v", err)
	}
	if status, err := stopDaemon(); err != nil || status != "already_stopped" {
		t.Errorf("a second stop = (%q, %v), want already_stopped", status, err)
	}
}

// Two instances are two daemons: they must never share a record, or stopping one would
// signal the other and every start after the first would read as a no-op.
func TestAnInstanceKeepsItsOwnRecord(t *testing.T) {
	home := hermeticHome(t, modeServe, "--instance", "personal")
	if err := startDaemonProcess([]string{"--instance", "personal"}); err != nil {
		t.Fatalf("start failed: %v", err)
	}
	if filepath.Base(daemonPidfile()) != "whatsapp-personal.pid" {
		t.Fatalf("the instance recorded its pid at %s", daemonPidfile())
	}
	if _, err := os.Stat(filepath.Join(home, "agent/data/daemons/whatsapp.pid")); !os.IsNotExist(err) {
		t.Errorf("the instance must not touch the default record, got %v", err)
	}
	if _, err := os.Stat(filepath.Join(home, ".whatsapp/personal/whatsapp.sock")); err != nil {
		t.Errorf("the instance daemon must serve the instance socket: %v", err)
	}
	if status, err := stopDaemon(); err != nil || status != "stopped" {
		t.Fatalf("stop = (%q, %v), want stopped", status, err)
	}
}

func TestAStartThatNeverGetsAnAnswerLeavesNothingBehind(t *testing.T) {
	hermeticHome(t, modeMute)
	t.Setenv(DaemonReadyTimeoutEnv, "1")
	pids := make(chan int, 1)
	go func() {
		deadline := time.Now().Add(DaemonStopTimeout)
		for time.Now().Before(deadline) {
			if pid, alive := livePid(); alive {
				pids <- pid
				return
			}
			time.Sleep(10 * time.Millisecond)
		}
		pids <- 0
	}()
	if err := startDaemonProcess(nil); err == nil {
		t.Fatal("a start whose daemon never answers must fail")
	}
	spawned := <-pids
	if spawned == 0 {
		t.Fatal("start never recorded the pid it was waiting on")
	}
	if syscall.Kill(spawned, 0) == nil {
		t.Errorf("the abandoned daemon (pid %d) is still running", spawned)
	}
	if _, err := os.Stat(daemonPidfile()); !os.IsNotExist(err) {
		t.Errorf("a start that gave up must leave no pid record, got %v", err)
	}
}

// startPair launches two `daemon start` processes a hair apart, so the second lands inside the
// first's startup window, and returns what each one answered.
func startPair(t *testing.T) []map[string]any {
	t.Helper()
	binary, err := os.Executable()
	if err != nil {
		t.Fatalf("failed to locate the test binary: %v", err)
	}
	starts := make([]*exec.Cmd, raceStarts)
	answers := make([]bytes.Buffer, raceStarts)
	for i := range starts {
		start := exec.Command(binary, "start")
		start.Env = append(os.Environ(), testModeEnv+"="+modeVerb)
		start.Stdout = &answers[i]
		if err := start.Start(); err != nil {
			t.Fatalf("failed to launch start %d: %v", i, err)
		}
		starts[i] = start
		time.Sleep(RaceStagger)
	}
	envelopes := make([]map[string]any, raceStarts)
	for i, start := range starts {
		start.Wait()
		if err := json.Unmarshal(answers[i].Bytes(), &envelopes[i]); err != nil {
			t.Fatalf("start %d printed unparseable output %q: %v", i, answers[i].String(), err)
		}
	}
	return envelopes
}

// Two starts landing at once leave one daemon and one record that points at it. The failure
// this guards is the second start recording the child that lost the device-store lock: the
// socket answers (the winner holds it), the record names a corpse, and from there stop reads
// already_stopped while status reads running, which no verb recovers from.
func TestTwoStartsRacingLeaveOneDaemonAndOneLiveRecord(t *testing.T) {
	hermeticHome(t, modeServe)
	t.Setenv(serveDelayEnv, strconv.Itoa(int(RaceServeWait.Milliseconds())))
	for round := 1; round <= raceRounds; round++ {
		brought := 0
		answered := startPair(t)
		t.Logf("round %d: the two starts answered %v", round, answered)
		for _, envelope := range answered {
			if reflect.DeepEqual(envelope, map[string]any{"status": "started"}) {
				brought++
				continue
			}
			if reflect.DeepEqual(envelope, map[string]any{"status": "already_running"}) {
				continue
			}
			if _, reported := envelope["error"]; !reported {
				t.Fatalf("round %d: a start answered %v, want started, already_running, or a failure", round, envelope)
			}
		}
		if brought != 1 {
			t.Fatalf("round %d: %d of two starts claim to have brought the daemon up, want exactly one", round, brought)
		}
		pid, alive := livePid()
		if !alive {
			t.Fatalf("round %d: the record names no live process", round)
		}
		if !daemonAlive(getSocketPath()) {
			t.Fatalf("round %d: no daemon is answering", round)
		}
		// The record names the daemon that owns the socket, so the stop verb ends it. A corpse
		// in the record would leave the socket answering right through this.
		if status, err := stopDaemon(); err != nil || status != "stopped" {
			t.Fatalf("round %d: stop = (%q, %v), want stopped", round, status, err)
		}
		waitForDaemon(t, false)
		if syscall.Kill(pid, 0) == nil {
			t.Fatalf("round %d: the recorded daemon (pid %d) survived the stop", round, pid)
		}
	}
}

// A daemon this lifecycle did not start still owns the instance: it holds the device-store lock,
// so the child a start spawns dies on it. Reporting success there would hand back a record no
// process stands behind, so restart says so instead.
func TestRestartOntoADaemonItDoesNotOwnFailsLoudly(t *testing.T) {
	hermeticHome(t, modeServe)
	binary, err := os.Executable()
	if err != nil {
		t.Fatalf("failed to locate the test binary: %v", err)
	}
	foreign := exec.Command(binary, "serve")
	foreign.Env = append(os.Environ(), testModeEnv+"="+modeServe)
	if err := foreign.Start(); err != nil {
		t.Fatalf("failed to launch the foreign daemon: %v", err)
	}
	t.Cleanup(func() {
		foreign.Process.Signal(syscall.SIGTERM)
		foreign.Wait()
	})
	waitForDaemon(t, true)
	if _, err := os.Stat(daemonPidfile()); !os.IsNotExist(err) {
		t.Fatalf("the foreign daemon must leave no record, got %v", err)
	}
	envelope, code := daemonVerb(t, "restart")
	if code == 0 {
		t.Errorf("restart onto a daemon it does not own exited 0 with %v", envelope)
	}
	if _, reported := envelope["error"]; !reported {
		t.Errorf("restart answered %v, want an error envelope", envelope)
	}
	if _, err := os.Stat(daemonPidfile()); !os.IsNotExist(err) {
		t.Errorf("a restart that failed must leave no pid record, got %v", err)
	}
	if !daemonAlive(getSocketPath()) {
		t.Error("the foreign daemon must still be serving")
	}
}

func TestTheDaemonVerbsAnswerTheContract(t *testing.T) {
	hermeticHome(t, modeServe)
	envelope, code := daemonVerb(t, "start")
	wantEnvelope(t, envelope, code, "started")
	first := recordedPid(t)
	envelope, code = daemonVerb(t, "start")
	wantEnvelope(t, envelope, code, "already_running")
	running, code := daemonVerb(t, "status")
	if code != 0 || running["running"] != true || running["port"] != nil {
		t.Errorf("status = %v (exit %d), want running true and no port", running, code)
	}
	envelope, code = daemonVerb(t, "restart")
	wantEnvelope(t, envelope, code, "started")
	second := recordedPid(t)
	if second == first {
		t.Errorf("restart kept pid %d, want a new daemon", first)
	}
	if syscall.Kill(first, 0) == nil {
		t.Errorf("restart left the old daemon (pid %d) running", first)
	}
	envelope, code = daemonVerb(t, "stop")
	wantEnvelope(t, envelope, code, "stopped")
	stopped, code := daemonVerb(t, "status")
	if code != 0 || stopped["running"] != false {
		t.Errorf("status after a stop = %v (exit %d), want running false", stopped, code)
	}
	envelope, code = daemonVerb(t, "stop")
	wantEnvelope(t, envelope, code, "already_stopped")
}

func TestUsageAnswersZeroAndAnUnknownVerbDoesNot(t *testing.T) {
	hermeticHome(t, modeServe)
	for _, args := range [][]string{{}, {"-h"}, {"--help"}, {"help"}} {
		output, code := runVerbProcess(t, args...)
		if code != 0 {
			t.Errorf("whatsapp daemon %v exited %d, want 0", args, code)
		}
		if !strings.Contains(strings.ToLower(string(output)), "usage") {
			t.Errorf("whatsapp daemon %v printed %q, want its usage", args, output)
		}
	}
	if _, code := runVerbProcess(t, "bogus"); code == 0 {
		t.Error("an unknown daemon verb exited 0, want nonzero")
	}
}

func TestOnlyADeathNobodyAskedForIsReported(t *testing.T) {
	home := hermeticHome(t, modeServe)
	envelope, code := daemonVerb(t, "start")
	wantEnvelope(t, envelope, code, "started")
	envelope, code = daemonVerb(t, "stop")
	wantEnvelope(t, envelope, code, "stopped")
	if notices := deathNotices(t, home); len(notices) != 0 {
		t.Errorf("a deliberate stop reported a death: %v", notices)
	}
	envelope, code = daemonVerb(t, "start")
	wantEnvelope(t, envelope, code, "started")
	pid := recordedPid(t)
	if err := syscall.Kill(pid, syscall.SIGINT); err != nil {
		t.Fatalf("failed to interrupt the daemon: %v", err)
	}
	deadline := time.Now().Add(DaemonStopTimeout)
	for time.Now().Before(deadline) && len(deathNotices(t, home)) == 0 {
		time.Sleep(10 * time.Millisecond)
	}
	if notices := deathNotices(t, home); len(notices) != 1 {
		t.Errorf("an exit nobody asked for produced %v, want one daemon_died notification", notices)
	}
	daemonVerb(t, "stop")
}

func TestDeathIsNewsUnlessTheAgentAskedForIt(t *testing.T) {
	for _, tc := range []struct {
		sig  os.Signal
		want bool
	}{
		{syscall.SIGTERM, false},
		{syscall.SIGINT, true},
		{syscall.SIGHUP, true},
	} {
		if got := deathIsNews(tc.sig); got != tc.want {
			t.Errorf("deathIsNews(%v) = %v, want %v", tc.sig, got, tc.want)
		}
	}
}

func TestDaemonBudgetsComeFromTheEnvironment(t *testing.T) {
	if got := daemonBudget(DaemonStopTimeoutEnv, DaemonStopTimeout); got != DaemonStopTimeout {
		t.Errorf("an unset budget = %s, want the default %s", got, DaemonStopTimeout)
	}
	t.Setenv(DaemonStopTimeoutEnv, "3")
	if got := daemonBudget(DaemonStopTimeoutEnv, DaemonStopTimeout); got != 3*time.Second {
		t.Errorf("budget = %s, want 3s", got)
	}
	t.Setenv(DaemonStopTimeoutEnv, "not a number")
	if got := daemonBudget(DaemonStopTimeoutEnv, DaemonStopTimeout); got != DaemonStopTimeout {
		t.Errorf("an unreadable budget = %s, want the default %s", got, DaemonStopTimeout)
	}
}

func TestStopRefusalDuringSyncWindow(t *testing.T) {
	if msg := stopRefusal(3*time.Minute, false); msg == "" {
		t.Fatal("stop during the sync window without --force must be refused")
	} else if !strings.Contains(msg, "logs the device out") {
		t.Errorf("refusal must explain the consequence, got %q", msg)
	}
	if msg := stopRefusal(3*time.Minute, true); msg != "" {
		t.Errorf("--force must override, got %q", msg)
	}
	if msg := stopRefusal(0, false); msg != "" {
		t.Errorf("no window means no refusal, got %q", msg)
	}
}

func TestRestartReusesRecordedServeFlags(t *testing.T) {
	recorded := []string{"--instance", "personal", "--read-only", "--no-notifications"}
	serveArgs := restartServeArgs(daemonState{Args: recorded, StartedAt: time.Now()})
	if !reflect.DeepEqual(serveArgs, recorded) {
		t.Errorf("restart must reuse the recorded serve flags, got %v", serveArgs)
	}
}

func TestRestartWithoutARecordedRunFallsBackToInstanceArgs(t *testing.T) {
	t.Run("named instance", func(t *testing.T) {
		withArgs(t, "--instance", "personal")
		if serveArgs := restartServeArgs(daemonState{}); !reflect.DeepEqual(serveArgs, []string{"--instance", "personal"}) {
			t.Errorf("without a recorded run the fallback is instance args only, got %v", serveArgs)
		}
	})
	t.Run("default instance", func(t *testing.T) {
		withArgs(t)
		if serveArgs := restartServeArgs(daemonState{}); len(serveArgs) != 0 {
			t.Errorf("the default instance has no flags to fall back to, got %v", serveArgs)
		}
	})
}
