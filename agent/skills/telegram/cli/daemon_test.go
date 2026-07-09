package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestUsageListsLifecycleCommands(t *testing.T) {
	var buf bytes.Buffer
	printUsage(&buf)
	out := buf.String()
	for _, want := range []string{"daemon", "serve", "authenticate", "send-message"} {
		if !strings.Contains(out, want) {
			t.Errorf("usage output missing %q", want)
		}
	}
}

func TestIsHelpArg(t *testing.T) {
	cases := map[string]bool{"--help": true, "-h": true, "help": true, "send": false, "serve": false}
	for arg, want := range cases {
		if got := isHelpArg(arg); got != want {
			t.Errorf("isHelpArg(%q) = %v, want %v", arg, got, want)
		}
	}
}

func TestScreenOutputHasLiveSession(t *testing.T) {
	live := "There are screens on:\n\t12345.telegram\t(Detached)\n\t99.telegram-watchdog\t(Detached)\n2 Sockets in /run/screen/S-root.\n"
	dead := "There are screens on:\n\t12345.telegram\t(Dead ???)\nRemove dead screens with 'screen -wipe'.\n"
	cases := []struct {
		session string
		output  string
		want    bool
	}{
		{"telegram", live, true},
		{"telegram-watchdog", live, true},
		{"telegram", dead, false},
		{"telegram", "No Sockets found in /run/screen/S-root.\n", false},
		{"telegram-other", live, false},
	}
	for _, testCase := range cases {
		if got := screenOutputHasLiveSession(testCase.output, testCase.session); got != testCase.want {
			t.Errorf("screenOutputHasLiveSession(session=%q) = %v, want %v", testCase.session, got, testCase.want)
		}
	}
}

func TestDaemonInfoRoundTrip(t *testing.T) {
	dir := t.TempDir()
	writeDaemonInfo(dir, []string{"--notifications-dir", "/tmp/n"})
	info, err := readDaemonInfo(dir)
	if err != nil {
		t.Fatalf("readDaemonInfo: %v", err)
	}
	if len(info.Args) != 2 || info.Args[0] != "--notifications-dir" {
		t.Errorf("args round-trip failed: %v", info.Args)
	}
	if info.PID != os.Getpid() {
		t.Errorf("pid = %d, want %d", info.PID, os.Getpid())
	}
	if time.Since(info.StartedAt) > time.Minute {
		t.Errorf("started_at not recent: %v", info.StartedAt)
	}
}

func TestDefaultNotificationsDir(t *testing.T) {
	want := filepath.Join(os.Getenv("HOME"), "agent", "notifications")
	if got := defaultNotificationsDir(); got != want {
		t.Errorf("defaultNotificationsDir() = %q, want %q", got, want)
	}
}
