package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

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
