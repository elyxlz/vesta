package main

import (
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

// fakeServeEnv turns the test binary into the daemon a start spawns: "socket" opens the
// instance's socket and waits for a signal, "mute" comes up and never answers. The lifecycle
// tests need a real detached child, and the test binary is the one executable they can be
// sure exists.
const fakeServeEnv = "WHATSAPP_TEST_FAKE_SERVE"

func TestMain(m *testing.M) {
	switch os.Getenv(fakeServeEnv) {
	case "":
		os.Exit(m.Run())
	case "mute":
		select {}
	default:
		runFakeServe()
	}
}

func runFakeServe() {
	if err := os.MkdirAll(stateDataDir(), daemonDirPerms); err != nil {
		os.Exit(1)
	}
	listener, err := net.Listen("unix", getSocketPath())
	if err != nil {
		os.Exit(1)
	}
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT)
	<-signals
	listener.Close()
	os.Remove(getSocketPath())
}

// hermeticHome points every daemon record, log, and data dir at a temporary home and installs
// the fake serve there under the launcher path a start spawns.
func hermeticHome(t *testing.T, mode string, serveArgs ...string) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv(fakeServeEnv, mode)
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
	hermeticHome(t, "socket")
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
	home := hermeticHome(t, "socket", "--instance", "personal")
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
	hermeticHome(t, "mute")
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
	withArgs(t, "--instance", "personal")
	if serveArgs := restartServeArgs(daemonState{}); !reflect.DeepEqual(serveArgs, []string{"--instance", "personal"}) {
		t.Errorf("without a recorded run the fallback is instance args only, got %v", serveArgs)
	}
}
